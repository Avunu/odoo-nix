"""The built-in profiles, the module schema and their resolution on the fixtures
(DESIGN.md §4, §7.2 test_profiles)."""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
import unittest
from pathlib import Path

from odoo_nix_tools.product import MODULES, PRODUCT
from standards_core.common import config, schema
from standards_core.testing import conformance
from support import TempRepos, need_root, run_cli

PROFILES = Path(PRODUCT.data_root) / "profiles"


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


# The built-in profiles a release has shipped never change (core DESIGN.md §4.4): a
# later minor that changes `recommended` adds recommended@2.<minor>.toml, and only a new
# file gets a new digest here.
FROZEN = {
    "minimal.toml": "81ad8af19e739a34fd1b36ab339a0228c0ff6fbc92adf54c9fc89dd3e053aea7",
    "recommended@2.3.toml": "b59f5a099f84f8be1da72856ee5f0031032c6f563335bcb70e983a8ced4686a1",
}


class Frozen(unittest.TestCase):
    def test_every_builtin_is_frozen(self) -> None:
        self.assertEqual(
            sorted(p.name for p in PROFILES.glob("*.toml")), sorted(FROZEN)
        )

    def test_the_bytes_are_the_frozen_ones(self) -> None:
        for name, digest in FROZEN.items():
            with self.subTest(name):
                data = (PROFILES / name).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)


class Builtins(unittest.TestCase):
    def test_static_conformance(self) -> None:
        self.assertEqual(conformance.check(PRODUCT, render=False), [])

    def test_names(self) -> None:
        self.assertEqual(config.builtin_names(PRODUCT), ["minimal", "recommended@2.3"])
        self.assertEqual(config.builtin_name(PRODUCT, "recommended"), "recommended@2.3")

    def test_module_schema_names_every_module(self) -> None:
        doc = schema.raw(PRODUCT, "modules.schema.json")
        self.assertEqual(doc["$defs"]["module-name"]["enum"], list(MODULES))
        self.assertEqual(list(doc["$defs"]["modules"]), list(MODULES))

    def test_minimal_turns_on_the_dev_shell_only(self) -> None:
        doc = toml(PROFILES / "minimal.toml")
        on = [m for m in MODULES if doc[m]["enable"]]
        self.assertEqual(on, ["dev-shell"])
        self.assertEqual(
            set(doc) - {"schema", "name", "description", "org"}, set(MODULES)
        )

    def test_schema_defaults_equal_recommended(self) -> None:
        # So minimal resolves the same parameter values (DESIGN.md §4.3).
        defaults = schema.defaults(PRODUCT, schema.PROFILE)
        recommended = toml(PROFILES / "recommended@2.3.toml")
        for module in MODULES:
            for key, value in recommended[module].items():
                if key in ("enable", "branching"):
                    continue
                with self.subTest(key=f"{module}.{key}"):
                    self.assertEqual(defaults[module][key], value)

    def test_releases_default_scheme_is_odoo_series(self) -> None:
        defaults = schema.defaults(PRODUCT, schema.PROFILE)
        self.assertEqual(defaults["releases"]["version-scheme"], "odoo-series")
        self.assertEqual(defaults["releases"]["branching"], "develop+series")

    def test_fleet_entry(self) -> None:
        validator = schema.Validator(PRODUCT, schema.FLEET, "fleet")
        good = {
            "schema": 1,
            "repos": [
                {
                    "repo": "Avunu/edi-addons",
                    "shape": "addons",
                    "branches": ["develop", "18.0"],
                    "private": False,
                },
                {
                    "repo": "example-org/project-b",
                    "shape": "project",
                    "branches": ["master"],
                    "integration_branch": "master",
                    "private": True,
                },
            ],
        }
        self.assertEqual(validator.errors(good), [])
        bad = {
            "schema": 1,
            "repos": [{"repo": "Avunu/x", "shape": "bundle", "branches": []}],
        }
        errors = " ".join(validator.errors(bad))
        for word in ("shape", "branches", "private"):
            self.assertIn(word, errors)

    def test_untested_needs_a_reason(self) -> None:
        validator = schema.Validator(PRODUCT, schema.APP, "[tool.odoo-nix]")
        ok = {
            "schema": 1,
            "untested": [{"addon": "fixture_b", "reason": "needs a printer"}],
        }
        self.assertEqual(validator.errors(ok), [])
        short = {"schema": 1, "untested": [{"addon": "fixture_b", "reason": "no"}]}
        self.assertTrue(validator.errors(short))

    def test_project_blank_github_app_is_valid(self) -> None:
        validator = schema.Validator(PRODUCT, schema.APP, "[tool.odoo-nix]")
        table = {"schema": 1, "ci": {"github-app": {"app-id": "", "private-key": ""}}}
        self.assertEqual(validator.errors(table), [])


class Resolution(TempRepos):
    def show(self, root: Path, *extra: str) -> dict:
        code, out, err = run_cli(
            "profile", "show", "--format", "json", *extra, cwd=root
        )
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_list(self) -> None:
        code, out, _ = run_cli("profile", "list")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("minimal "))
        self.assertTrue(lines[1].startswith("recommended@2.3  (recommended)"))

    def test_project_fixture_under_recommended(self) -> None:
        doc = self.show(self.fixture("standards-project"))
        self.assertEqual(doc["profile"]["name"], "recommended@2.3")
        cfg = doc["config"]
        self.assertEqual((cfg["shape"], cfg["series"]), ("project", "18.0"))
        self.assertEqual(cfg["integration-branch"], "main")
        self.assertEqual(cfg["dependabot"]["target-branches"], ["main"])
        self.assertEqual(cfg["addon-manifest"]["licenses-allowed"], [])
        on = [m for m, v in doc["modules"].items() if v]
        self.assertEqual(
            on,
            [
                "dev-shell",
                "editorconfig",
                "python-lint",
                "pylint-odoo",
                "addon-manifest",
                "js-xml",
                "tests",
                "workflow-lint",
                "shell-lint",
                "nix-lint",
                "hygiene",
                "dependabot",
                "ci",
            ],
        )
        # No empty org value is a parameter the defaults filled with a placeholder.
        self.assertNotIn("@@", json.dumps(doc))

    def test_project_fixture_under_minimal(self) -> None:
        root = self.fixture("standards-project")
        text = (root / "pyproject.toml").read_text()
        (root / "pyproject.toml").write_text(text.replace('"recommended"', '"minimal"'))
        doc = self.show(root)
        self.assertEqual([m for m, v in doc["modules"].items() if v], ["dev-shell"])
        self.assertEqual(doc["profile"]["name"], "minimal")
        # The parameters still resolve, to recommended's values (the schema defaults).
        self.assertEqual(doc["config"]["tests"]["goal"], 80)
        self.assertEqual(doc["config"]["ci"]["runs-on"], ["ubuntu-latest"])

    def test_project_fixture_under_example_org(self) -> None:
        root = self.fixture("standards-project")
        shutil.copytree(
            need_root(self) / "tests/fixtures/standards-profiles/example-org",
            root / "standards-profile",
        )
        text = (root / "pyproject.toml").read_text()
        (root / "pyproject.toml").write_text(
            text.replace('"recommended"', '"./standards-profile"')
        )
        doc = self.show(root)
        self.assertEqual(doc["profile"]["name"], "example-org")
        cfg = doc["config"]
        self.assertEqual(cfg["addon-manifest"]["author"], "Example Org")
        self.assertEqual(cfg["addon-manifest"]["licenses-allowed"], ["AGPL-3"])
        self.assertEqual(cfg["repo-policy"]["release-bypass"], "integration:123")
        self.assertTrue(all(doc["modules"].values()), doc["modules"])
        code, out, err = run_cli("config", "commits.convention", cwd=root)
        self.assertEqual((code, out.strip()), (0, "conventional"), err)

    def test_explicit_shape_and_series_in_the_table(self) -> None:
        root = self.fixture("standards-project")
        with (root / "pyproject.toml").open("a") as f:
            f.write('series = "19.0"\nintegration-branch = "master"\n')
        doc = self.show(root)
        self.assertEqual(doc["config"]["series"], "19.0")
        self.assertEqual(doc["config"]["integration-branch"], "master")
        self.assertEqual(doc["config"]["dependabot"]["target-branches"], ["master"])

    def test_a_series_without_data_is_exit_2(self) -> None:
        root = self.fixture("standards-project")
        with (root / "pyproject.toml").open("a") as f:
            f.write('series = "17.0"\n')
        code, _, err = run_cli("config", "series", cwd=root)
        self.assertEqual(code, 2)
        self.assertIn("knows series 18.0, 19.0, 20.0", err)

    def test_addons_fixture(self) -> None:
        root = self.fixture("standards-addons")
        doc = self.show(root)
        cfg = doc["config"]
        self.assertEqual((cfg["shape"], cfg["series"]), ("addons", "18.0"))
        self.assertEqual(cfg["integration-branch"], "develop")
        self.assertEqual(cfg["dependabot"]["target-branches"], ["develop", "17.0"])
        code, out, _ = run_cli("config", "shape", cwd=root / "fixture_a")
        self.assertEqual((code, out.strip()), (0, "addons"))


if __name__ == "__main__":
    unittest.main()
