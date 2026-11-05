"""The ``flake.nix`` inputs block (DESIGN.md §3.1 dev-shell, core §5.6.4) on
representative flakes (``tests/shapes/flakes``): two project-shape checkouts, project-b
(``self.submodules`` and the ``''${ODOO_NIX_HTTP_PORT:-8069}`` indented string) and
project-a, and two addon repositories' own: edi-addons (``ocb`` and ``oca-*`` inputs,
unclaimed) and vertical-auto-repair-addons (25 inputs).

Each hand-writes ``odoo-nix.url`` with another URL than the block renders, so the first
sync is exit 2 with the replacement's diff; ``--force`` moves the input into the block and
leaves every other byte; a second run changes nothing; the flake's inputs read the same
inside and outside the block, so a lock of the synced flake has no stale input.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from standards_core.scaffold import engine
from standards_core.testing import fakes
from support import ORG_PROFILES, SHAPES, SyncCase, need_root

PROJECT = "standards-project"
ADDONS = "standards-addons"
RENDERED = "github:Avunu/odoo-nix/release-2"
BEGIN = "# >>> odoo-nix: inputs (managed) >>>"
END = "# <<< odoo-nix: inputs (managed) <<<"
# shape → (fixture it goes into, the odoo-nix URL it writes by hand)
CASES = {
    "project-b": (PROJECT, "github:Avunu/odoo-nix"),
    "project-a": (PROJECT, "github:Avunu/odoo-nix"),
    "edi-addons": (ADDONS, "github:Avunu/odoo-nix/feat/addons-mode"),
    "vertical-auto-repair-addons": (ADDONS, "github:Avunu/odoo-nix/feat/addons-mode"),
}


def hand_line(url: str) -> str:
    return f'    odoo-nix.url = "{url}";\n'


def block_lines(text: str) -> list[str]:
    """The lines between the inputs block's markers (markers excluded)."""
    lines = text.splitlines(keepends=True)
    begin = next(i for i, line in enumerate(lines) if line.strip() == BEGIN)
    end = next(i for i, line in enumerate(lines) if line.strip() == END)
    return lines[begin + 1 : end]


def outside_block(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    begin = next(i for i, line in enumerate(lines) if line.strip() == BEGIN)
    end = next(i for i, line in enumerate(lines) if line.strip() == END)
    return lines[:begin] + lines[end + 1 :]


class FlakeShapes(SyncCase):
    def adopt(self, shape: str) -> tuple[Path, str]:
        """A fixture copy under ``recommended`` whose flake is ``shape``'s, locked as it
        is in its repository (from the URL written by hand)."""
        fixture, _ = CASES[shape]
        text = (SHAPES / "flakes" / f"{shape}.nix").read_text()
        lock = json.dumps(fakes.flake_lock(text), indent=2) + "\n"
        root = self.profile_fixture(
            fixture, "recommended", {"flake.nix": text, "flake.lock": lock}
        )
        return root, text

    def test_first_opt_in_force_and_idempotence(self) -> None:
        need_root(self)
        for shape, (_, url) in CASES.items():
            with self.subTest(shape=shape):
                root, before = self.adopt(shape)
                flake = root / "flake.nix"
                self.assertIn(hand_line(url), before)

                # The first run shows the replacement and writes nothing.
                code, text = self.write(root, ok=False)
                self.assertEqual(code, 2, text)
                self.assertIn(
                    "flake.nix defines odoo-nix otherwise than the managed inputs block",
                    text,
                )
                self.assertIn("-" + hand_line(url).rstrip("\n"), text)
                self.assertIn(f'+    odoo-nix.url = "{RENDERED}";', text)
                self.assertEqual(flake.read_text(), before)

                # --force moves the input into the block; every other byte stays.
                self.sync(root, "--write", "--offline", "--force")
                after = flake.read_text()
                self.assertEqual(
                    block_lines(after), [f'    odoo-nix.url = "{RENDERED}";\n']
                )
                kept = before.splitlines(keepends=True)
                kept.remove(hand_line(url))
                self.assertEqual(outside_block(after), kept)
                self.assertEqual(after.count("odoo-nix.url"), 1)

                # The inputs read the same in and out of the block; self is none.
                specs_before = engine.flake_input_specs(before)
                specs_after = engine.flake_input_specs(after)
                self.assertNotIn("self", specs_after)
                self.assertEqual(
                    {k: v for k, v in specs_after.items() if k != "odoo-nix"},
                    {k: v for k, v in specs_before.items() if k != "odoo-nix"},
                )
                self.assertEqual(
                    specs_after["odoo-nix"], "github:avunu/odoo-nix/release-2"
                )
                # The repository's lock is stale for odoo-nix alone (phase A's
                # `nix flake lock` moves it); a lock of the synced flake is clean.
                self.assertEqual(
                    [
                        s.split(" ")[0]
                        for s in engine.stale_inputs(
                            fakes.flake_lock(before), specs_after
                        )
                    ],
                    ["odoo-nix"],
                )
                self.assertEqual(
                    engine.stale_inputs(fakes.flake_lock(after), specs_after), []
                )

                # Idempotent, and clean once the lock follows the flake.
                (root / "flake.lock").write_text(
                    json.dumps(fakes.flake_lock(after), indent=2) + "\n"
                )
                self.commit(root)
                self.write(root)
                self.assertEqual(flake.read_text(), after)
                self.check(root)

    def test_counts(self) -> None:
        """The shapes are what the design says they are."""
        specs = {
            shape: engine.flake_input_specs(
                (SHAPES / "flakes" / f"{shape}.nix").read_text()
            )
            for shape in CASES
        }
        # 25 inputs besides odoo-nix: nixpkgs, ocb, OCA, Avunu and muk-it sources.
        self.assertEqual(len(specs["vertical-auto-repair-addons"]) - 1, 25)
        self.assertIn("ocb", specs["edi-addons"])
        self.assertTrue(any(k.startswith("oca-") for k in specs["edi-addons"]))
        project = (SHAPES / "flakes" / "project-b.nix").read_text()
        self.assertIn("self.submodules = true;", project)
        self.assertIn("''${ODOO_NIX_HTTP_PORT:-8069}", project)

    def test_indented_string_survives(self) -> None:
        root, before = self.adopt("project-b")
        self.sync(root, "--write", "--offline", "--force")
        after = (root / "flake.nix").read_text()
        port = next(
            line for line in before.splitlines() if "ODOO_NIX_HTTP_PORT" in line
        )
        self.assertIn(port, after.splitlines())

    def test_unclaimed_inputs_stay_where_they_are(self) -> None:
        root, before = self.adopt("edi-addons")
        self.sync(root, "--write", "--offline", "--force")
        after = (root / "flake.nix").read_text()
        for name in ("ocb", "oca-edi", "nixpkgs"):
            with self.subTest(input=name):
                lines = [
                    line
                    for line in before.splitlines()
                    if re.match(rf"\s*{re.escape(name)}[ .=]", line)
                ]
                self.assertTrue(lines)
                for line in lines:
                    self.assertIn(line, after.splitlines())
                    self.assertNotIn(line + "\n", "".join(block_lines(after)))

    def test_hand_definition_after_opt_in(self) -> None:
        root, _ = self.adopt("project-a")
        self.sync(root, "--write", "--offline", "--force")
        flake = root / "flake.nix"
        (root / "flake.lock").write_text(
            json.dumps(fakes.flake_lock(flake.read_text()), indent=2) + "\n"
        )
        self.commit(root)
        flake.write_text(
            flake.read_text().replace(
                "    nixpkgs.follows",
                '    odoo-nix.url = "github:Avunu/odoo-nix/main";\n    nixpkgs.follows',
                1,
            )
        )
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 2, text)
        self.assertIn("defines odoo-nix outside the managed inputs block", text)

    def test_equal_definition_moves_silently(self) -> None:
        """A flake odoo-init scaffolds with the release URL opts in without --force."""
        root, before = self.adopt("project-a")
        flake = root / "flake.nix"
        flake.write_text(before.replace('"github:Avunu/odoo-nix"', f'"{RENDERED}"'))
        self.commit(root)
        self.write(root)
        self.assertEqual(
            block_lines(flake.read_text()), [f'    odoo-nix.url = "{RENDERED}";\n']
        )

    def test_profile_input(self) -> None:
        """An org profile from GitHub is a flake input of its own, in the block."""
        repo = need_root(self)
        root = self.profile_fixture(PROJECT, "recommended")
        config = root / "pyproject.toml"
        url = "github:example-org/odoo-standards-profile/v1"
        config.write_text(
            config.read_text().replace('profile = "recommended"', f'profile = "{url}"')
        )
        self.commit(root)
        self.sync(
            root,
            "--write",
            "--offline",
            "--profile-path",
            str(repo / ORG_PROFILES / "example-org"),
        )
        self.assertEqual(
            "".join(block_lines((root / "flake.nix").read_text())),
            f'    odoo-nix.url = "{RENDERED}";\n'
            "    standards-profile = {\n"
            f'      url = "{url}";\n'
            "      flake = false;\n"
            "    };\n",
        )
