"""The ``ide`` module's jsonc-merge (DESIGN.md §3.1 ide, core §5.5) on editor files
representative of project-shape checkouts (``tests/shapes/vscode``): project-b's 4-space
``settings.json`` (``git.detectSubmodules``, ``python-envs.defaultEnvManager``,
``Odoo.selectedProfile``), project-a's 2-space one (an inline
``python.analysis.extraPaths``, ``git.ignoreLimitWarning``), and both one-line
``extensions.json`` (project-a's keeps ``bierner.lit-html``).

Sync sets the managed leaves and nothing else: ``Odoo.serverConfigPath`` goes, the
``python-envs.*`` keys and ``Odoo.selectedProfile`` stay (a notice names the first), the
file's indentation, inline arrays and final newline (or its absence) are kept, and
turning ``ide`` off takes back exactly what it added: never a leaf the dev shell seeds
(``data/ide/vscode.json``, which ``modules/devenv.nix`` reads too).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from odoo_nix_tools import context
from standards_core.scaffold import jsonc
from support import SHAPES, SyncCase, need_root

PROJECT = "standards-project"
SETTINGS = ".vscode/settings.json"
EXTENSIONS = ".vscode/extensions.json"
TARGETS = ("project-b", "project-a")


def leaves(doc: Mapping[str, Any], path: tuple[str, ...] = ()) -> Iterator[tuple]:
    """Every (key path, value) of ``doc``'s non-object values."""
    for key, value in doc.items():
        if isinstance(value, Mapping):
            yield from leaves(value, (*path, key))
        else:
            yield (*path, key), value


def norm(text: str) -> list[str]:
    return [line.rstrip().removesuffix(",") for line in text.splitlines()]


def subsequence(part: list[str], whole: list[str]) -> bool:
    it = iter(whole)
    return all(any(line == other for other in it) for line in part)


def shape(name: str) -> str:
    return (SHAPES / "vscode" / name).read_text()


class Data(unittest.TestCase):
    def test_seed_and_managed_share_nothing(self) -> None:
        """Retracting ide deletes the ``set`` leaves still equal to the render and the
        ``ensure`` items, so none may be the seed's (review item P3-d)."""
        data = context.ide_data()
        managed = data["managed"]
        seeded = {path for path, _ in leaves(data["seed"])}
        self.assertFalse(seeded & {path for path, _ in leaves(managed["set"])})
        ensure = managed["union"]["recommendations"]["ensure"]
        self.assertFalse(set(data["seed_extensions"]) & set(ensure))
        self.assertIn(["Odoo.serverConfigPath"], managed["forbidden"])

    def test_a_missing_file_gets_the_seed(self) -> None:
        """Sync makes the editor files before the dev shell ever seeds them
        (``odoo-init --standards``), so a file it creates carries the seed too; one
        that exists does not, and its seed leaves stay the checkout's (O9-16)."""
        data = context.ide_data()
        managed = data["managed"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            specs = context.ide_specs(root)
            created = dict(leaves(specs["settings"]["set"]))
            for path, value in [*leaves(data["seed"]), *leaves(managed["set"])]:
                self.assertEqual(created[path], value, path)
            ensure = specs["extensions"]["union"]["recommendations"]["ensure"]
            self.assertEqual(
                ensure,
                [
                    *data["seed_extensions"],
                    *managed["union"]["recommendations"]["ensure"],
                ],
            )
            (root / ".vscode").mkdir()
            (root / SETTINGS).write_text("{}")
            (root / EXTENSIONS).write_text("{}")
            specs = context.ide_specs(root)
            self.assertEqual(specs["settings"]["set"], managed["set"])
            self.assertEqual(specs["extensions"]["union"], managed["union"])

    def test_devenv_reads_the_same_file(self) -> None:
        path = need_root(self) / "modules" / "devenv.nix"
        if not path.is_file():
            self.skipTest("modules/devenv.nix is not in the package build's tree")
        devenv = path.read_text()
        self.assertIn(
            "lib.importJSON ../py/odoo_nix_tools/odoo_nix_tools/data/ide/vscode.json",
            devenv,
        )
        self.assertIn("builtins.toJSON ideData.seed", devenv)
        self.assertIn("recommendations = ideData.seed_extensions;", devenv)


class RealShapes(SyncCase):
    def synced(self, name: str, settings: str | None = None):
        files = {
            SETTINGS: settings
            if settings is not None
            else shape(f"{name}-settings.json"),
            EXTENSIONS: shape(f"{name}-extensions.json"),
        }
        root = self.profile_fixture(PROJECT, "example-org", files)
        _, text = self.write(root)
        return root, text

    def test_managed_leaves_and_kept_layout(self) -> None:
        need_root(self)
        managed = context.ide_data()["managed"]
        for name in TARGETS:
            with self.subTest(target=name):
                before = shape(f"{name}-settings.json")
                root, _ = self.synced(name)
                text = (root / SETTINGS).read_text()
                doc = jsonc.loads(text, SETTINGS)
                for path, value in leaves(managed["set"]):
                    cur: Any = doc
                    for key in path:
                        cur = cur[key]
                    self.assertEqual(cur, value, path)
                # Nothing of the checkout's own is lost or changed.
                for path, value in leaves(json.loads(before)):
                    cur = doc
                    for key in path:
                        cur = cur[key]
                    self.assertEqual(cur, value, path)
                # The original lines are all still there, in their order (a comma
                # added after a former last member aside).
                self.assertTrue(
                    subsequence(norm(before), norm(text)), f"{before}\n---\n{text}"
                )
                self.assertTrue(text.endswith("}\n"))
                # Idempotent; --check clean.
                self.commit(root)
                self.write(root)
                self.assertEqual((root / SETTINGS).read_text(), text)
                self.check(root)

    def test_four_spaces_and_untouched_keys(self) -> None:
        root, notices = self.synced("project-b")
        text = (root / SETTINGS).read_text()
        self.assertIn('\n    "python.languageServer": "None",', text)
        self.assertIn('\n    "[python]": {\n        "editor.defaultFormatter"', text)
        self.assertNotIn('\n  "python.languageServer"', text)
        self.assertIn(
            '    "python-envs.defaultEnvManager": "ms-python.python:system",\n', text
        )
        self.assertIn('    "Odoo.selectedProfile": "default"', text)
        self.assertIn('    "git.detectSubmodules": false,\n', text)
        self.assertIn(".vscode/settings.json sets python-envs.*", notices)

    def test_inline_array_stays_inline(self) -> None:
        root, _ = self.synced("project-a")
        text = (root / SETTINGS).read_text()
        self.assertIn(
            '\n  "python.analysis.extraPaths": [".devenv/state/pythonpath"],\n', text
        )
        self.assertIn('\n  "git.ignoreLimitWarning": true', text)
        self.assertIn('\n  "python.languageServer": "None",', text)

    def test_server_config_path_is_deleted(self) -> None:
        planted = shape("project-a-settings.json").replace(
            '  "git.ignoreLimitWarning": true\n',
            '  "Odoo.serverConfigPath": "${workspaceFolder}/odoo.conf",\n'
            '  "git.ignoreLimitWarning": true\n',
        )
        self.assertIn("Odoo.serverConfigPath", planted)
        root, _ = self.synced("project-a", planted)
        self.assertNotIn("Odoo.serverConfigPath", (root / SETTINGS).read_text())

    def test_extensions_stay_one_line(self) -> None:
        for name in TARGETS:
            with self.subTest(target=name):
                before = shape(f"{name}-extensions.json")
                root, _ = self.synced(name)
                text = (root / EXTENSIONS).read_text()
                self.assertEqual(len(text.rstrip("\n").splitlines()), 1)
                self.assertEqual(text.endswith("\n"), before.endswith("\n"))
                have = json.loads(text)["recommendations"]
                self.assertEqual(
                    have[: len(json.loads(before)["recommendations"])],
                    json.loads(before)["recommendations"],
                )
                for ext in context.ide_data()["managed"]["union"]["recommendations"][
                    "ensure"
                ]:
                    self.assertIn(ext, have)
        # project-b's file has no final newline, and keeps it that way.
        self.assertFalse(shape("project-b-extensions.json").endswith("\n"))

    def test_turning_ide_off_takes_back_what_it_added(self) -> None:
        for name in TARGETS:
            with self.subTest(target=name):
                root, _ = self.synced(name)
                self.commit(root)
                profile = root / ".standards-profile" / "profile.toml"
                profile.write_text(
                    profile.read_text().replace(
                        "[ide]\nenable = true\n", "[ide]\nenable = false\n"
                    )
                )
                self.write(root)
                for path in (SETTINGS, EXTENSIONS):
                    before = shape(f"{name}-{path.rsplit('/', 1)[1]}")
                    # Byte for byte: the edits undo each other.
                    self.assertEqual((root / path).read_text(), before, path)
                self.commit(root)
                self.check(root)


if __name__ == "__main__":
    unittest.main()
