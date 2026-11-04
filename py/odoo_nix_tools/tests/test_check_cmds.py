"""``odoo-nix check manifests|icons|submodules`` (DESIGN.md §6.2, §7.2 test_check_cmds),
and ``pngsize`` on the three icon shapes."""

from __future__ import annotations

import os
import unittest

from odoo_nix_tools.pngsize import png_size
from support import ADDONS_PRODUCT, ICONS, SyncCase, git, png, run_cli

ICON = "static/description/icon.png"


class PngSize(unittest.TestCase):
    def test_shapes(self) -> None:
        sizes = {name: png_size(make()) for name, make in ICONS.items()}
        self.assertEqual(
            sizes,
            {
                "ok-128": (128, 128),
                "wide-200x100": (200, 100),
                "heavy-150k": (224, 224),
            },
        )
        self.assertGreater(len(ICONS["heavy-150k"]()), 150_000)
        self.assertLess(len(ICONS["ok-128"]()), 2_000)

    def test_not_a_png(self) -> None:
        for data in (b"", b"GIF89a" + bytes(30), png(1, 1)[:20]):
            with self.subTest(data=data[:8]), self.assertRaises(ValueError):
                png_size(data)


class Case(SyncCase):
    def addons(self, edit: dict | None = None, profile: str = "example-org"):
        return self.profile_fixture("standards-addons", profile, edit or {})

    def check(self, root, *argv: str) -> tuple[int, str]:
        os.environ.pop("GITHUB_ACTIONS", None)
        code, out, err = run_cli("check", *argv, cwd=root, product=ADDONS_PRODUCT)
        return code, out + err


class Manifests(Case):
    WEBSITE = "https://github.com/example-org/fixture-addons"

    def with_website(self, text: str) -> str:
        return text.replace("https://github.com/fixture/fixture-addons", self.WEBSITE)

    def fixed(self, edit: dict | None = None) -> dict:
        """The fixture's manifests with example-org's rendered website."""
        root = self.addons()
        files = {
            f"{a}/__manifest__.py": self.with_website(
                (root / a / "__manifest__.py").read_text()
            )
            for a in ("fixture_a", "fixture_b")
        }
        return {**files, **(edit or {})}

    def test_clean(self) -> None:
        code, out = self.check(self.addons(self.fixed()), "manifests")
        self.assertEqual(code, 0, out)
        self.assertIn("odoo-nix check manifests: ok", out)

    def test_website(self) -> None:
        code, out = self.check(self.addons(), "manifests")
        self.assertEqual(code, 1, out)
        self.assertEqual(
            out.splitlines(),
            [
                f"fixture_a/__manifest__.py: website is https://github.com/fixture/fixture-addons, not {self.WEBSITE}",
                f"fixture_b/__manifest__.py: website is https://github.com/fixture/fixture-addons, not {self.WEBSITE}",
            ],
        )

    def test_no_website_rule_without_the_template(self) -> None:
        # recommended sets no addon-manifest.website.
        code, out = self.check(self.addons(profile="recommended"), "manifests")
        self.assertEqual(code, 0, out)

    def test_series_version(self) -> None:
        files = self.fixed()
        files["fixture_b/__manifest__.py"] = files["fixture_b/__manifest__.py"].replace(
            "18.0.1.0.0", "1.0.0"
        )
        code, out = self.check(self.addons(files), "manifests")
        self.assertEqual(code, 1, out)
        self.assertEqual(
            out.strip(), "fixture_b/__manifest__.py: version 1.0.0 is not 18.0.x.y.z"
        )

    def test_odoo_series_and_integration_branch(self) -> None:
        root = self.addons(self.fixed({".odoo-series": "17.0\n"}))
        config = root / "nix/pyproject.toml"
        config.write_text(
            config.read_text().replace(
                "[tool.odoo-nix]\n",
                '[tool.odoo-nix]\nseries = "18.0"\nintegration-branch = "17.0"\n',
                1,
            )
        )
        git(root, "commit", "-q", "-am", "series")
        code, out = self.check(root, "manifests")
        self.assertEqual(code, 1, out)
        self.assertEqual(
            out.splitlines(),
            [
                (
                    "nix/pyproject.toml: the integration branch 17.0 is a series"
                    " branch, and the series is 18.0"
                ),
                ".odoo-series: names 17.0, and the series is 18.0",
            ],
        )

    def test_github_format(self) -> None:
        code, out = self.check(self.addons(), "manifests", "--format", "github")
        self.assertEqual(code, 1, out)
        self.assertTrue(
            out.startswith("::error file=fixture_a/__manifest__.py::website is https"),
            out,
        )


class Icons(Case):
    def test_clean(self) -> None:
        code, out = self.check(self.addons(), "icons")
        self.assertEqual(code, 0, out)

    def test_shapes(self) -> None:
        cases = {
            "wide-200x100": "static/description/icon.png is 200×100, not square and"
            " is smaller than 128×128",
            "heavy-150k": "static/description/icon.png has 150555 bytes, more than 102400",
        }
        for name, want in cases.items():
            with self.subTest(icon=name):
                data = ICONS[name]()
                root = self.addons({f"fixture_a/{ICON}": data})
                code, out = self.check(root, "icons")
                self.assertEqual(code, 1, out)
                self.assertEqual(
                    out.strip(),
                    "fixture_a/__manifest__.py: "
                    + want.replace("150555", str(len(data))),
                )

    def test_small_and_missing(self) -> None:
        root = self.addons(
            {f"fixture_a/{ICON}": png(64, 64), f"fixture_b/{ICON}": None}
        )
        code, out = self.check(root, "icons")
        self.assertEqual(code, 1, out)
        self.assertEqual(
            out.splitlines(),
            [
                (
                    "fixture_a/__manifest__.py: static/description/icon.png is smaller"
                    " than 128×128"
                ),
                "fixture_b/__manifest__.py: no static/description/icon.png",
            ],
        )

    def test_github_format(self) -> None:
        # An annotation needs a file: the addon's manifest, not its directory.
        root = self.addons({f"fixture_b/{ICON}": None})
        code, out = self.check(root, "icons", "--format", "github")
        self.assertEqual(code, 1, out)
        self.assertTrue(
            out.startswith(
                "::error file=fixture_b/__manifest__.py::no static/description/icon.png"
            ),
            out,
        )

    def fake_tool(self, root) -> None:
        """oca-gen-addon-icon's behaviour: the src icon into each --addon-dir that has
        none."""
        bin_dir = root / "tools/.venv/bin"
        bin_dir.mkdir(parents=True)
        tool = bin_dir / "oca-gen-addon-icon"
        tool.write_text(
            "#!/bin/sh\n"
            'echo "$@" > "$(dirname "$0")/argv"\n'
            "src=\n"
            'for a in "$@"; do case "$a" in --src-icon=*) src="${a#--src-icon=}";; esac; done\n'
            'for a in "$@"; do case "$a" in --addon-dir=*)\n'
            '  d="${a#--addon-dir=}/static/description"\n'
            '  [ -e "$d/icon.png" ] || { mkdir -p "$d"; cp "$src" "$d/icon.png"; };;\n'
            "esac; done\n"
        )
        tool.chmod(0o755)

    def test_fix_adds_the_profile_icon(self) -> None:
        root = self.addons({f"fixture_b/{ICON}": None})
        self.fake_tool(root)
        code, out = self.check(root, "icons", "--fix")
        self.assertEqual(code, 0, out)
        argv = (root / "tools/.venv/bin/argv").read_text().split()
        self.assertEqual(
            argv,
            [
                "--no-commit",
                f"--src-icon={root / '.standards-profile/assets/addon-icon.png'}",
                "--addon-dir=fixture_b",
            ],
        )
        self.assertEqual(
            (root / "fixture_b" / ICON).read_bytes(),
            (root / ".standards-profile/assets/addon-icon.png").read_bytes(),
        )
        self.assertEqual(
            git(root, "diff", "--cached", "--name-only").split(), [f"fixture_b/{ICON}"]
        )

    def test_fix_keeps_a_wrong_icon_reported(self) -> None:
        root = self.addons({f"fixture_a/{ICON}": ICONS["wide-200x100"]()})
        self.fake_tool(root)
        code, out = self.check(root, "icons", "--fix")
        self.assertEqual(code, 1, out)
        self.assertIn("200×100, not square", out)
        self.assertFalse((root / "tools/.venv/bin/argv").exists())

    def test_fix_needs_an_org_icon(self) -> None:
        root = self.addons({f"fixture_b/{ICON}": None}, profile="recommended")
        config = root / "nix/pyproject.toml"
        config.write_text(
            config.read_text().replace(
                "[tool.odoo-nix]\n", "[tool.odoo-nix]\nicons.enable = true\n", 1
            )
        )
        git(root, "commit", "-q", "-am", "icons")
        self.fake_tool(root)
        code, out = self.check(root, "icons", "--fix")
        self.assertEqual(code, 2, out)
        self.assertIn("has no icon to copy", out)

    def test_fix_needs_the_linked_tool(self) -> None:
        root = self.addons({f"fixture_b/{ICON}": None})
        code, out = self.check(root, "icons", "--fix")
        self.assertEqual(code, 3, out)
        self.assertIn("tools/.venv/bin/oca-gen-addon-icon is missing", out)

    def test_fix_is_for_icons_only(self) -> None:
        code, out = self.check(self.addons(), "manifests", "--fix")
        self.assertEqual(code, 2, out)


class Submodules(Case):
    def project(self, gitmodules: str | None = None):
        edit = {".gitmodules": gitmodules} if gitmodules is not None else {}
        return self.profile_fixture("standards-project", "recommended", edit)

    def check_project(self, root) -> tuple[int, str]:
        code, out, err = run_cli("check", "submodules", cwd=root)
        return code, out + err

    def test_clean(self) -> None:
        code, out = self.check_project(self.project())
        self.assertEqual(code, 0, out)

    def test_another_branch_or_none(self) -> None:
        root = self.project()
        text = (root / ".gitmodules").read_text()
        text = text.replace(
            "\tbranch = 18.0\n\tshallow = true\n", "\tshallow = true\n", 1
        )
        text = text.replace("branch = 18.0", "branch = 17.0")
        root = self.project(text)
        code, out = self.check_project(root)
        self.assertEqual(code, 1, out)
        self.assertEqual(
            out.splitlines(),
            [
                ".gitmodules: submodule modules/server-tools has branch = 17.0, not branch = 18.0",
                ".gitmodules: submodule odoo has no branch, not branch = 18.0",
            ],
        )


if __name__ == "__main__":
    unittest.main()
