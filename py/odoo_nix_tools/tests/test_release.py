"""The release flow's odoo parts (DESIGN.md §2.2, §7.2 test_release): the ``odoo-series``
scheme's arithmetic and refusals, the manifest release tool writing a version with every
other byte kept (on real manifest shapes), the exempt paths, and ``odoo-nix ci bump`` on
the addons fixture through the core."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from odoo_nix_tools import manifests, release
from odoo_nix_tools.product import PRODUCT
from standards_core.common import schema
from standards_core.common.report import ConfigError
from standards_core.product import ReleaseUnit
from support import ADDONS_PRODUCT, SHAPES, SyncCase, git, run_cli

SCHEME = release.OdooSeries()
TOOL = release.ManifestTool()
FACTS = {"series": "18.0"}
UNIT = ReleaseUnit("fixture_a", "fixture_a/", "fixture_a/__manifest__.py")


class Scheme(unittest.TestCase):
    def test_registered(self) -> None:
        self.assertIs(type(PRODUCT.version_schemes["odoo-series"]), release.OdooSeries)
        self.assertEqual(SCHEME.name, "odoo-series")

    def test_schema_names_every_scheme(self) -> None:
        # The product spells releases.version-scheme out (DESIGN.md §14, O3-2): it must
        # equal the core's "semver" plus the registered schemes.
        doc = schema.raw(PRODUCT, "modules.schema.json")
        node = doc["$defs"]["modules"]["releases"]["properties"]["version-scheme"]
        self.assertEqual(node["enum"], ["semver", *PRODUCT.version_schemes])
        self.assertEqual(node["default"], "odoo-series")

    def test_bump(self) -> None:
        cases = {
            "major": "18.0.2.0.0",
            "minor": "18.0.1.3.0",
            "patch": "18.0.1.2.4",
        }
        for level, want in cases.items():
            with self.subTest(level=level):
                self.assertEqual(SCHEME.bump("18.0.1.2.3", level, {}, FACTS), want)
        self.assertEqual(SCHEME.bump("19.0.0.0.9", "patch", {}, FACTS), "19.0.0.0.10")

    def test_bump_refuses_another_shape(self) -> None:
        for version in ("1.0.0", "18.0.1.0", "18.0.1.0.0.0", ""):
            with self.subTest(version=version), self.assertRaises(ConfigError):
                SCHEME.bump(version, "patch", {}, FACTS)

    def test_valid(self) -> None:
        self.assertIsNone(SCHEME.valid("18.0.1.0.0", {}, FACTS))
        self.assertEqual(
            SCHEME.valid("17.0.1.0.0", {}, FACTS),
            "version 17.0.1.0.0 is not 18.0.x.y.z",
        )
        self.assertEqual(
            SCHEME.valid("1.0.0", {}, FACTS), "version 1.0.0 is not 18.0.x.y.z"
        )
        # The series from cfg when the facts have none.
        self.assertIsNone(SCHEME.valid("19.0.1.0.0", {"series": "19.0"}, {}))

    def test_message_problems(self) -> None:
        self.assertEqual(SCHEME.message_problems("feat: x", {}, FACTS), [])
        self.assertEqual(
            SCHEME.message_problems("feat!: x\n\nBREAKING CHANGE: y", {}, FACTS), []
        )
        found = SCHEME.message_problems("fix: x\n\nRelease-As: 18.0.2.0.0", {}, FACTS)
        self.assertEqual(len(found), 1)
        self.assertIn("Release-As has no meaning here", found[0])

    def test_tag_problem(self) -> None:
        self.assertIsNone(SCHEME.tag_problem("", {}, FACTS))
        self.assertEqual(
            SCHEME.tag_problem("v18.0.1.0.0", {}, FACTS),
            "odoo-series releases make no tags",
        )


class WriteVersion(unittest.TestCase):
    def check(self, text: str, version: str = "18.0.1.1.0") -> str:
        out = TOOL.write_version(text, UNIT, version)
        self.assertEqual(TOOL.read_version(out, UNIT), version)
        # Every other byte kept: the one difference is the literal's inside.
        old = TOOL.read_version(text, UNIT)
        self.assertEqual(out, text.replace(old, version, 1))
        return out

    def test_real_shapes(self) -> None:
        shapes = sorted((SHAPES / "manifests").glob("*/__manifest__.py"))
        self.assertEqual(len(shapes), 4)
        for path in shapes:
            with self.subTest(addon=path.parent.name):
                self.check(path.read_text())

    def test_single_quotes_trailing_comma_and_comments(self) -> None:
        text = (
            "# a comment with 'version': '1.0'\n"
            "{\n"
            "    'name': 'X',  # \"version\" in a comment\n"
            "    'version':   '18.0.1.0.0' ,  # the version\n"
            "    'depends': ['base'],\n"
            "}\n"
        )
        out = self.check(text)
        self.assertIn("    'version':   '18.0.1.1.0' ,  # the version\n", out)

    def test_non_ascii_before_the_version_on_its_line(self) -> None:
        text = '{"summary": "Café ✓", "version": "18.0.1.0.0"}\n'
        self.assertEqual(
            self.check(text), '{"summary": "Café ✓", "version": "18.0.1.1.0"}\n'
        )

    def test_crlf_and_no_final_newline(self) -> None:
        text = '{\r\n    "name": "X",\r\n    "version": "18.0.1.0.0",\r\n}'
        self.assertEqual(
            self.check(text),
            '{\r\n    "name": "X",\r\n    "version": "18.0.1.1.0",\r\n}',
        )

    def test_the_top_level_key_only(self) -> None:
        text = '{\n    "x": {"version": "1"},\n    "version": "18.0.1.0.0",\n}\n'
        self.assertIn('"x": {"version": "1"}', self.check(text))

    def test_refusals(self) -> None:
        cases = {
            "no key": '{"name": "X"}\n',
            "a name": '{"version": VERSION}\n',
            "an f-string": '{"version": f"18.0.{1}.0.0"}\n',
            "a concatenation": '{"version": "18.0." "1.0.0"}\n',
            "not a dict": '["version"]\n',
            "two statements": 'x = 1\n{"version": "18.0.1.0.0"}\n',
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(ValueError) as cm:
                TOOL.write_version(text, UNIT, "18.0.1.1.0")
            self.assertIn("fixture_a/__manifest__.py", str(cm.exception))

    def test_read_version(self) -> None:
        self.assertEqual(
            TOOL.read_version('{"version": "18.0.1.0.0"}', UNIT), "18.0.1.0.0"
        )
        self.assertIsNone(TOOL.read_version('{"name": "X"}', UNIT))
        self.assertIsNone(TOOL.read_version("not python (", UNIT))
        self.assertIsNone(TOOL.read_version('{"version": 18}', UNIT))

    def test_version_problem(self) -> None:
        self.assertIsNone(manifests.version_problem("18.0.1.0.0", "18.0"))
        self.assertEqual(
            manifests.version_problem(None, "18.0"), "no version: it must be 18.0.x.y.z"
        )
        self.assertEqual(
            manifests.version_problem("18.0.1.0", "18.0"),
            "version 18.0.1.0 is not 18.0.x.y.z",
        )


class Units(unittest.TestCase):
    def test_installable_addons_sorted(self) -> None:
        ctx = {
            "discover": {
                "addons": [
                    {"name": "b", "path": "custom/b", "installable": True},
                    {"name": "legacy", "path": "custom/legacy", "installable": False},
                    {"name": "a", "path": "custom/a", "installable": True},
                ]
            }
        }
        self.assertEqual(
            TOOL.units(Path("."), ctx),
            [
                ReleaseUnit("a", "custom/a/", "custom/a/__manifest__.py"),
                ReleaseUnit("b", "custom/b/", "custom/b/__manifest__.py"),
            ],
        )
        self.assertEqual(
            TOOL.commit_subject.format(units="a, b"), "chore(release): bump a, b"
        )

    def test_exempt(self) -> None:
        unit = ReleaseUnit("a", "custom/a/", "custom/a/__manifest__.py")
        exempt = (
            "custom/a/tests/test_a.py",
            "custom/a/tests/data/x.xml",
            "custom/a/README.md",
            "custom/a/README.rst",
            "custom/a/readme/DESCRIPTION.md",
            "custom/a/i18n/fr.po",
            "custom/a/i18n_extra/fr.po",
            "custom/a/static/description/icon.png",
            "custom/a/static/description/index.html",
        )
        counted = (
            "custom/a/__manifest__.py",
            "custom/a/models/a.py",
            "custom/a/static/src/js/a.js",
            "custom/a/views/README.md",
            "custom/a/data/tests/x.xml",
        )
        for path in exempt:
            with self.subTest(path=path):
                self.assertTrue(TOOL.exempt(unit, path))
        for path in counted:
            with self.subTest(path=path):
                self.assertFalse(TOOL.exempt(unit, path))


class Bump(SyncCase):
    """``odoo-nix ci bump`` (core DESIGN.md §8.2) on the addons fixture under example-org
    (releases on, develop+series)."""

    def setUp(self) -> None:
        super().setUp()
        root = self.profile_fixture("standards-addons", "example-org")
        git(root, "branch", "-m", "develop")
        git(root, "branch", "18.0")
        self.root = root

    def change(self, path: str, text: str, message: str) -> None:
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)

    def manifest(self, addon: str) -> str:
        return (self.root / addon / "__manifest__.py").read_text()

    def bump(self, *argv: str) -> tuple[int, str]:
        output = self.tmp / "github-output"
        output.write_text("")
        os.environ["GITHUB_OUTPUT"] = str(output)
        code, out, err = run_cli(
            "ci", "bump", "--base", "18.0", *argv, cwd=self.root, product=ADDONS_PRODUCT
        )
        return code, out + err + output.read_text()

    def test_levels_per_addon_and_exempt_paths(self) -> None:
        before_a, before_b = self.manifest("fixture_a"), self.manifest("fixture_b")
        self.change("fixture_a/models/extra.py", "X = 1\n", "feat(fixture_a): a field")
        self.change("fixture_a/models/more.py", "Y = 1\n", "fix(fixture_a): a fix")
        self.change("fixture_b/README.md", "# B\n\nMore.\n", "docs(fixture_b): explain")
        self.change("fixture_b/tests/__init__.py", "", "fix(fixture_b): a test only")
        code, out = self.bump()
        self.assertEqual(code, 0, out)
        self.assertIn("bumped=fixture_a", out)
        self.assertEqual(
            git(self.root, "log", "-1", "--format=%s").strip(),
            "chore(release): bump fixture_a",
        )
        self.assertEqual(
            self.manifest("fixture_a"), before_a.replace("18.0.1.0.0", "18.0.1.1.0")
        )
        self.assertEqual(self.manifest("fixture_b"), before_b)
        self.assertEqual(
            git(self.root, "show", "--name-only", "--format=", "HEAD").split(),
            ["fixture_a/__manifest__.py"],
        )

    def test_breaking_change_raises_x(self) -> None:
        self.change(
            "fixture_b/static/src/js/fixture_b.js",
            "// new\n",
            "feat(fixture_b)!: drop the old widget",
        )
        code, out = self.bump()
        self.assertEqual(code, 0, out)
        self.assertIn('"version": "18.0.2.0.0"', self.manifest("fixture_b"))

    def test_a_hand_edit_is_not_bumped_again(self) -> None:
        text = self.manifest("fixture_a").replace("18.0.1.0.0", "18.0.1.5.0")
        self.change("fixture_a/__manifest__.py", text, "feat(fixture_a): by hand")
        code, out = self.bump()
        self.assertEqual(code, 0, out)
        self.assertIn("version edited by hand", out)
        self.assertIn('"version": "18.0.1.5.0"', self.manifest("fixture_a"))

    def test_dry_run_writes_nothing(self) -> None:
        self.change("fixture_a/models/extra.py", "X = 1\n", "fix(fixture_a): a fix")
        head = git(self.root, "rev-parse", "HEAD")
        code, out = self.bump("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("18.0.1.0.1", out)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), head)


if __name__ == "__main__":
    unittest.main()
