"""Discovery: the config file, shape, series and addon facts (DESIGN.md §2.3, §7.2)."""

from __future__ import annotations

import argparse
import unittest
from collections.abc import Mapping
from pathlib import Path

from odoo_nix_tools import discover
from odoo_nix_tools.pngsize import png_size
from standards_core.common.report import ConfigError
from standards_core.scaffold.context import Checkout
from support import SHAPES, TempRepos, git, run_cli

TABLE = '[tool.odoo-nix]\nschema = 1\nprofile = "recommended"\n'
ADDONS_FLAKE = """{
  inputs.odoo-nix.url = "github:Avunu/odoo-nix";
  outputs = { odoo-nix, ... }: {
    # addons.enable = false;
    odoo-nix = {
      addons.enable = true;
      odooSeries = lib.fileContents ./.odoo-series;
    };
  };
}
"""
PROJECT_FLAKE = """{
  inputs = {
    self.submodules = true;
    odoo-nix.url = "github:Avunu/odoo-nix";
  };
  outputs = { ... }: {
    odoo-nix.odooSeries = "18.0";
  };
}
"""


def manifest(version: str = "18.0.1.0.0", **extra: object) -> str:
    body = {"name": "X", "version": version, "license": "LGPL-3", **extra}
    return repr(body) + "\n"


def shape_text(name: str) -> str:
    return (SHAPES / "manifests" / name / "__manifest__.py").read_text()


class Discovery(TempRepos):
    def checkout(self, files: Mapping[str, str | bytes]) -> Checkout:
        return discover.load_checkout(self.make_tree(files))

    def facts(self, files: Mapping[str, str | bytes], cfg: dict | None = None) -> dict:
        return discover.facts(self.checkout(files), cfg or {}, {})


class ConfigFile(Discovery):
    def test_root_pyproject_with_the_table(self) -> None:
        root = self.make_tree({"pyproject.toml": TABLE, "modules.txt": ""})
        self.assertEqual(discover.config_file(root), "pyproject.toml")

    def test_nix_pyproject_with_the_table(self) -> None:
        root = self.make_tree({"nix/pyproject.toml": TABLE, "flake.nix": ADDONS_FLAKE})
        self.assertEqual(discover.config_file(root), "nix/pyproject.toml")

    def test_both_answers_the_default_and_the_checkout_is_exit_2(self) -> None:
        # The core asks the hook about every directory while it finds the root, so the
        # hook answers; loading the checkout at that root refuses (core §14 Stage 10).
        root = self.make_tree({"pyproject.toml": TABLE, "nix/pyproject.toml": TABLE})
        self.assertEqual(discover.config_file(root), "pyproject.toml")
        with self.assertRaisesRegex(
            ConfigError, "both pyproject.toml and nix/pyproject.toml"
        ):
            discover.load_checkout(root)
        code, out, err = run_cli("sync", "--check", cwd=root)
        self.assertEqual(code, 2, out + err)
        self.assertIn("both pyproject.toml and nix/pyproject.toml", out + err)

    def test_outside_git(self) -> None:
        # No tracked files to read: the default file, and nothing raised.
        plain = self.tmp / "plain"
        (plain / "nix").mkdir(parents=True)
        (plain / "flake.nix").write_text(ADDONS_FLAKE)
        (plain / "nix/pyproject.toml").write_text("[project]\n")
        self.assertEqual(discover.config_file(plain), "pyproject.toml")
        (plain / "nix/pyproject.toml").write_text(TABLE)
        self.assertEqual(discover.config_file(plain), "nix/pyproject.toml")

    def test_an_addon_directory_is_asked_too(self) -> None:
        # From inside an addon with its own pyproject.toml the core walks up to the
        # checkout whose nix/pyproject.toml opens the table.
        root = self.make_tree(
            {
                "nix/pyproject.toml": TABLE,
                "flake.nix": ADDONS_FLAKE,
                "x/pyproject.toml": "[project]\nname = 'x'\n",
                "x/__manifest__.py": manifest(),
            }
        )
        self.assertEqual(discover.config_file(root / "x"), "pyproject.toml")
        self.assertEqual(discover.config_file(root / "nix"), "pyproject.toml")

    def test_neither_follows_the_shape(self) -> None:
        addons = self.make_tree(
            {"nix/pyproject.toml": "[project]\n", "flake.nix": ADDONS_FLAKE}, name="a"
        )
        project = self.make_tree(
            {"pyproject.toml": "[project]\n", "modules.txt": ""}, name="p"
        )
        self.assertEqual(discover.config_file(addons), "nix/pyproject.toml")
        self.assertEqual(discover.config_file(project), "pyproject.toml")

    def test_a_commented_table_is_not_an_opt_in(self) -> None:
        root = self.make_tree(
            {"pyproject.toml": "# [tool.odoo-nix]\n", "nix/pyproject.toml": TABLE}
        )
        self.assertEqual(discover.config_file(root), "nix/pyproject.toml")


class Shape(Discovery):
    def test_explicit(self) -> None:
        facts = self.facts(
            {
                "pyproject.toml": TABLE + 'shape = "project"\nseries = "18.0"\n',
                "flake.nix": ADDONS_FLAKE,
            }
        )
        self.assertEqual(facts["shape"], "project")
        self.assertEqual(facts["addons_root"], "custom")

    def test_flake_addons_enable(self) -> None:
        facts = self.facts({"flake.nix": ADDONS_FLAKE, ".odoo-series": "18.0\n"})
        self.assertEqual(facts["shape"], "addons")
        self.assertEqual(facts["addons_root"], ".")
        self.assertEqual(facts["lock_dir"], "nix")
        self.assertEqual(facts["config_file"], "nix/pyproject.toml")
        self.assertTrue(facts["flake"]["addons_mode"])

    def test_flake_addons_attrset(self) -> None:
        flake = "{ odoo-nix = { addons = { enable = true; }; }; }\n"
        facts = self.facts({"flake.nix": flake, ".odoo-series": "18.0\n"})
        self.assertEqual(facts["shape"], "addons")

    def test_a_commented_addons_enable_is_no_signal(self) -> None:
        flake = "{\n  # addons.enable = true;\n}\n"
        with self.assertRaisesRegex(ConfigError, "cannot tell this repository's shape"):
            self.facts({"flake.nix": flake, ".odoo-series": "18.0\n"})

    def test_root_manifest(self) -> None:
        facts = self.facts({"x/__manifest__.py": manifest(), "x/__init__.py": ""})
        self.assertEqual(facts["shape"], "addons")
        self.assertEqual(facts["series"], "18.0")

    def test_odoo_gitlink(self) -> None:
        root = self.make_tree({"flake.nix": PROJECT_FLAKE}, commit=False)
        git(root, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},odoo")
        git(root, "commit", "-q", "-m", "init")
        facts = discover.facts(discover.load_checkout(root), {}, {})
        self.assertEqual(facts["shape"], "project")
        self.assertEqual(facts["shape_signals"]["project"], ["odoo is a submodule"])

    def test_modules_txt(self) -> None:
        facts = self.facts({"modules.txt": "queue_job\n", "flake.nix": PROJECT_FLAKE})
        self.assertEqual(facts["shape"], "project")
        self.assertIsNone(facts["shape_notice"])

    def test_none_is_exit_2(self) -> None:
        with self.assertRaisesRegex(ConfigError, "set \\[tool.odoo-nix\\] shape"):
            self.facts({"README.md": "x\n"})

    def test_both_kinds_choose_addons_with_a_notice(self) -> None:
        facts = self.facts(
            {"modules.txt": "", "flake.nix": ADDONS_FLAKE, ".odoo-series": "18.0\n"}
        )
        self.assertEqual(facts["shape"], "addons")
        self.assertIn("both addons-mode and project signals", facts["shape_notice"])

    def test_custom_dir_literal(self) -> None:
        flake = PROJECT_FLAKE.replace(
            "odoo-nix.odooSeries",
            'odoo-nix.layout.customDir = "addons";\n    odoo-nix.odooSeries',
        )
        facts = self.facts(
            {
                "modules.txt": "",
                "flake.nix": flake,
                "addons/y/__manifest__.py": manifest(),
            }
        )
        self.assertEqual(facts["addons_root"], "addons")
        self.assertEqual(facts["installable"], ["y"])


class Series(Discovery):
    def test_odoo_series_file_first(self) -> None:
        facts = self.facts(
            {
                ".odoo-series": "19.0\n",
                "flake.nix": ADDONS_FLAKE,
                "x/__manifest__.py": manifest("18.0.1.0.0"),
            }
        )
        self.assertEqual(facts["series"], "19.0")
        self.assertEqual(facts["series_sources"]["manifests"], {"18.0": ["x"]})

    def test_flake_literal(self) -> None:
        facts = self.facts({"modules.txt": "", "flake.nix": PROJECT_FLAKE})
        self.assertEqual(facts["series"], "18.0")
        self.assertEqual(facts["series_sources"]["flake"], "18.0")

    def test_manifests_must_agree(self) -> None:
        files = {
            "a/__manifest__.py": manifest("18.0.1.0.0"),
            "b/__manifest__.py": manifest("19.0.1.0.0"),
        }
        with self.assertRaisesRegex(ConfigError, "18.0: a; 19.0: b"):
            self.facts(files)

    def test_not_installable_addons_do_not_vote(self) -> None:
        facts = self.facts(
            {
                "a/__manifest__.py": manifest("20.0.1.0.0"),
                "b/__manifest__.py": manifest("19.0.1.0.0", installable=False),
            }
        )
        self.assertEqual(facts["series"], "20.0")
        self.assertEqual(facts["not_installable"], ["b"])

    def test_integration_branch(self) -> None:
        facts = self.facts({"flake.nix": ADDONS_FLAKE}, {"integration-branch": "19.0"})
        self.assertEqual(facts["series"], "19.0")

    def test_explicit_series_wins(self) -> None:
        facts = self.facts(
            {".odoo-series": "18.0\n", "flake.nix": ADDONS_FLAKE}, {"series": "20.0"}
        )
        self.assertEqual(facts["series"], "20.0")

    def test_none_is_exit_2(self) -> None:
        with self.assertRaisesRegex(
            ConfigError, "cannot tell the Odoo series: add .odoo-series"
        ):
            self.facts({"flake.nix": ADDONS_FLAKE})

    def test_a_series_without_data_is_exit_2(self) -> None:
        with self.assertRaisesRegex(ConfigError, "knows series 18.0, 19.0, 20.0"):
            self.facts({".odoo-series": "17.0\n", "flake.nix": ADDONS_FLAKE})

    def test_a_malformed_series_file_is_exit_2(self) -> None:
        with self.assertRaisesRegex(ConfigError, "not a series"):
            self.facts({".odoo-series": "eighteen\n", "flake.nix": ADDONS_FLAKE})

    def test_ocb_lock_is_a_source_not_the_series(self) -> None:
        lock = (
            '{"nodes": {"root": {"inputs": {"ocb": "ocb"}}, "ocb": {"original":'
            ' {"type": "github", "owner": "OCA", "repo": "OCB", "ref": "19.0"}}},'
            ' "root": "root", "version": 7}'
        )
        facts = self.facts(
            {".odoo-series": "18.0\n", "flake.nix": ADDONS_FLAKE, "flake.lock": lock}
        )
        self.assertEqual(facts["series"], "18.0")
        self.assertEqual(facts["series_sources"]["ocb-lock"], "19.0")


class AddonFacts(Discovery):
    def test_real_manifests(self) -> None:
        files: dict[str, str | bytes] = {
            ".odoo-series": "18.0\n",
            "flake.nix": ADDONS_FLAKE,
            "web_theme_carbon/package.json": (
                SHAPES / "manifests/web_theme_carbon/package.json"
            ).read_text(),
            "web_theme_carbon/node_modules/x/package.json": "{}\n",
            "web_theme_carbon/static/src/js/a.js": "",
            "edi_import_router/tests/__init__.py": "",
            "edi_import_router/models/router.py": "",
            "edi_import_router/README.md": "# x\n",
            "edi_import_router/pyproject.toml": (
                '[build-system]\nrequires = ["whool"]\nbuild-backend = "whool.buildapi"\n'
            ),
            "shopfloor_mobile_camera_scan/templates/assets.xml": "<odoo/>\n",
            "shopfloor_mobile_camera_scan/README.rst": "x\n",
        }
        for name in (
            "edi_import_router",
            "shopfloor_mobile_camera_scan",
            "web_theme_carbon",
        ):
            files[f"{name}/__manifest__.py"] = shape_text(name)
        facts = self.facts(files)
        addons = {a["name"]: a for a in facts["addons"]}
        self.assertEqual(
            list(addons),
            ["edi_import_router", "shopfloor_mobile_camera_scan", "web_theme_carbon"],
        )
        edi = addons["edi_import_router"]
        self.assertEqual(edi["license"], "AGPL-3")
        self.assertEqual(edi["author"], "Avunu LLC")
        self.assertEqual(edi["website"], "https://avu.nu")
        self.assertEqual(edi["depends"], ["mail", "queue_job", "import_from_email"])
        self.assertTrue(
            edi["has_tests"] and edi["has_py"] and edi["packaged"] and edi["whool"]
        )
        self.assertEqual(edi["readme"], "README.md")
        self.assertFalse(edi["icon"]["present"])
        scan = addons["shopfloor_mobile_camera_scan"]
        self.assertEqual(scan["license"], "LGPL-3")
        self.assertEqual(scan["readme"], "README.rst")
        self.assertTrue(scan["has_xml"])
        self.assertFalse(scan["has_py"] or scan["packaged"])
        carbon = addons["web_theme_carbon"]
        self.assertTrue(carbon["package_json"] and carbon["has_js"])
        self.assertEqual(facts["addon_package_json"], ["web_theme_carbon"])
        self.assertFalse(facts["root_package_json"])
        self.assertTrue(facts["has_js"])

    def test_ruckus_manifest_without_website(self) -> None:
        facts = self.facts(
            {
                "modules.txt": "",
                "flake.nix": PROJECT_FLAKE,
                "custom/sale_component_check/__manifest__.py": shape_text(
                    "sale_component_check"
                ),
            }
        )
        (addon,) = facts["addons"]
        self.assertEqual(addon["path"], "custom/sale_component_check")
        self.assertIsNone(addon["website"])
        self.assertEqual(addon["author"], "Walnook LLC")
        self.assertEqual(addon["version"], "18.0.1.0.0")

    def test_an_unreadable_manifest_is_exit_2(self) -> None:
        with self.assertRaisesRegex(ConfigError, "x/__manifest__.py"):
            self.facts({"x/__manifest__.py": "{'name': open('x')}\n"})

    def test_icon_size(self) -> None:
        root = self.fixture("standards-addons")
        facts = discover.facts(discover.load_checkout(root), {}, {})
        icon = facts["addons"][0]["icon"]
        self.assertEqual(
            (icon["present"], icon["width"], icon["height"]), (True, 128, 128)
        )
        data = (root / "fixture_a/static/description/icon.png").read_bytes()
        self.assertEqual(png_size(data), (128, 128))
        self.assertEqual(icon["bytes"], len(data))


class ProjectFixture(Discovery):
    def test_facts(self) -> None:
        facts = discover.facts(
            discover.load_checkout(self.fixture("standards-project")), {}, {}
        )
        self.assertEqual(facts["shape"], "project")
        self.assertEqual(facts["series"], "18.0")
        self.assertEqual(facts["installable"], ["fixture_sale"])
        self.assertEqual(facts["not_installable"], ["fixture_legacy"])
        self.assertTrue(facts["dev_group_ruff"])
        self.assertEqual(facts["vscode"], {"settings": True, "extensions": True})
        self.assertEqual(
            facts["submodules"],
            [
                {
                    "path": "modules/server-tools",
                    "url": "https://github.com/OCA/server-tools.git",
                    "branch": "18.0",
                    "shallow": False,
                    "gitlink": False,
                },
                {
                    "path": "odoo",
                    "url": "https://github.com/OCA/OCB.git",
                    "branch": "18.0",
                    "shallow": True,
                    "gitlink": False,
                },
            ],
        )
        flake = facts["flake"]
        self.assertTrue(flake["self_submodules"])
        self.assertEqual(flake["inputs"]["odoo-nix"], "github:avunu/odoo-nix/release-2")
        self.assertEqual(flake["inputs"]["nixpkgs"], "follows:odoo-nix/nixpkgs")
        self.assertTrue(facts["has_py"] and facts["has_js"] and facts["has_xml"])
        self.assertTrue(facts["has_nix"])
        self.assertFalse(facts["has_sh"])

    def test_addons_fixture_facts(self) -> None:
        facts = discover.facts(
            discover.load_checkout(self.fixture("standards-addons")), {}, {}
        )
        self.assertEqual(facts["shape"], "addons")
        self.assertEqual(facts["config_file"], "nix/pyproject.toml")
        self.assertEqual(facts["installable"], ["fixture_a", "fixture_b"])
        self.assertTrue(facts["flake"]["external_sources"])
        self.assertEqual(facts["series_sources"]["ocb-lock"], "18.0")
        self.assertTrue(facts["dev_group_ruff"])


class Derive(Discovery):
    def test_project_integration_branch_is_main(self) -> None:
        checkout = self.checkout(
            {"pyproject.toml": TABLE, "modules.txt": "", "flake.nix": PROJECT_FLAKE}
        )
        cfg = {"integration-branch": "develop", "dependabot": {"target-branches": []}}
        discover.derive(cfg, checkout)
        self.assertEqual(cfg["shape"], "project")
        self.assertEqual(cfg["series"], "18.0")
        self.assertEqual(cfg["integration-branch"], "main")
        self.assertEqual(cfg["dependabot"]["target-branches"], ["main"])

    def test_project_table_branch_kept(self) -> None:
        checkout = self.checkout(
            {
                "pyproject.toml": TABLE + 'integration-branch = "master"\n',
                "modules.txt": "",
                "flake.nix": PROJECT_FLAKE,
            }
        )
        cfg = {"integration-branch": "master"}
        discover.derive(cfg, checkout)
        self.assertEqual(cfg["integration-branch"], "master")

    def test_licenses_follow_the_org(self) -> None:
        cfg = {
            "integration-branch": "develop",
            "org": {"license": "AGPL-3"},
            "addon-manifest": {"licenses-allowed": []},
            "dependabot": {"target-branches": ["develop", "17.0"]},
        }
        discover.derive(cfg, None)
        self.assertEqual(cfg["addon-manifest"]["licenses-allowed"], ["AGPL-3"])
        self.assertEqual(cfg["dependabot"]["target-branches"], ["develop", "17.0"])
        empty = {
            "integration-branch": "main",
            "org": {"license": ""},
            "addon-manifest": {"licenses-allowed": []},
        }
        discover.derive(empty, None)
        self.assertEqual(empty["addon-manifest"]["licenses-allowed"], [])

    def test_addons_fixture_through_the_core(self) -> None:
        checkout = discover.load_checkout(self.fixture("standards-addons"))
        cfg = {"integration-branch": "develop", "dependabot": {"target-branches": []}}
        discover.derive(cfg, checkout)
        self.assertEqual(cfg["shape"], "addons")
        self.assertEqual(cfg["dependabot"]["target-branches"], ["develop"])


class NewTargetTable(TempRepos):
    def target_table(self, root: Path, profile: str) -> dict:
        checkout = discover.load_checkout(root)
        return discover.new_target_table(root, checkout, argparse.Namespace(), profile)

    def test_upstream_only(self) -> None:
        root = self.make_tree({"modules.txt": ""})
        git(root, "remote", "add", "upstream", "git@github.com:Avunu/millrun.git")
        self.assertEqual(
            self.target_table(root, "recommended"),
            {"repo": "Avunu/millrun"},
        )

    def test_origin_or_several(self) -> None:
        root = self.make_tree({"modules.txt": ""})
        self.assertEqual(self.target_table(root, "x"), {})
        git(
            root,
            "remote",
            "add",
            "origin",
            "https://github.com/Walnook-LLC/odoo-ruckus.git",
        )
        self.assertEqual(self.target_table(root, "x"), {})
        git(root, "remote", "remove", "origin")
        git(root, "remote", "add", "a", "https://github.com/a/b.git")
        git(root, "remote", "add", "c", "https://github.com/c/d.git")
        self.assertEqual(self.target_table(root, "x"), {})


if __name__ == "__main__":
    unittest.main()
