"""``tools/pyproject.toml``'s key groups (DESIGN.md §3.1, §7.2 test_tools_groups)."""

from __future__ import annotations

import tomllib
import unittest

from odoo_nix_tools import groups, series
from odoo_nix_tools.product import PRODUCT
from standards_core.scaffold import engine, tomlmerge
from support import SyncCase

PATH = "tools/pyproject.toml"


def deps(text: str) -> list[str]:
    return tomllib.loads(text)["project"]["dependencies"]


class Reconcile(unittest.TestCase):
    def setUp(self) -> None:
        self.known = groups.known_packages(series.effective("18.0", {}, {}))
        self.rendered = ["prek==0.5.7", "ruff==0.6.8", "coverage==7.16.2"]

    def test_raised_pin_kept_lower_raised(self) -> None:
        have = ["prek==0.5.7", "ruff==0.7.0", "coverage==7.0.0"]
        out = groups.reconcile_deps(self.known, have, self.rendered)
        self.assertEqual(out, ["prek==0.5.7", "ruff==0.7.0", "coverage==7.16.2"])

    def test_unknown_kept_after_the_rendered_ones(self) -> None:
        have = ["mytool>=1", "prek==0.5.7", "ruff==0.6.8"]
        out = groups.reconcile_deps(self.known, have, self.rendered)
        self.assertEqual(out, [*self.rendered, "mytool>=1"])

    def test_known_not_rendered_removed(self) -> None:
        have = [
            "prek==0.5.7",
            "pylint-odoo==9.1.3",
            "Oca_Odoo_Pre_Commit_Hooks==0.0.33",
        ]
        out = groups.reconcile_deps(self.known, have, self.rendered)
        self.assertEqual(out, self.rendered)

    def test_floor_ranges_and_urls(self) -> None:
        self.assertTrue(
            groups.keep_raised("manifestoo-core>=1.17", "manifestoo-core>=1.16.1")
        )
        self.assertTrue(
            groups.keep_raised("manifestoo-core==1.17", "manifestoo-core>=1.16.1")
        )
        self.assertFalse(groups.keep_raised("ruff>=0.7", "ruff==0.6.8"))
        url = "oca-maintainers-tools @ git+https://github.com/oca/maintainer-tools@abc"
        self.assertFalse(groups.keep_raised(url.replace("abc", "def"), url))


class Merged(SyncCase):
    def ctx(self, root):
        return engine.build(PRODUCT, root, options={"throwaway": False}).ctx

    def test_from_nothing(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        merged = tomlmerge.merge(groups.TOOLS, "", self.ctx(root), PATH)
        doc = tomllib.loads(merged.text)
        self.assertEqual(doc["project"]["name"], "fixture-project-tools")
        self.assertEqual(doc["project"]["version"], "0")
        self.assertEqual(doc["project"]["requires-python"], ">=3.11")
        self.assertEqual(doc["tool"]["uv"], {"package": False})
        self.assertEqual(
            [d.split("==")[0] for d in doc["project"]["dependencies"]],
            [
                "prek",
                "ruff",
                "pylint-odoo",
                "oca-odoo-pre-commit-hooks",
                "pre-commit-hooks",
                "manifestoo",
                "coverage",
                "checklog-odoo",
            ],
        )
        run = doc["tool"]["coverage"]["run"]
        self.assertEqual(run["source"], ["custom"])
        self.assertEqual(run["data_file"], ".odoo-nix/coverage/.coverage")
        self.assertIn(".odoo-nix/*", run["omit"])
        self.assertEqual(
            doc["tool"]["coverage"]["report"],
            {"show_missing": True, "skip_covered": True, "fail_under": 0},
        )
        self.assertEqual(
            list(doc),
            ["project", "tool"],
        )

    def test_hand_edits_through_sync(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        path = root / PATH
        text = path.read_text()
        text = text.replace('"ruff==0.6.8"', '"ruff==0.7.0"').replace(
            '"checklog-odoo==1.0"]', '"checklog-odoo==1.0", "mytool>=1"]'
        )
        text = text.replace("fail_under = 0", "fail_under = 42")
        path.write_text(text)
        self.write(root, ok=False)
        doc = tomllib.loads(path.read_text())
        self.assertIn("ruff==0.7.0", doc["project"]["dependencies"])
        self.assertEqual(doc["project"]["dependencies"][-1], "mytool>=1")
        # Seeded once, then the checkout's.
        self.assertEqual(doc["tool"]["coverage"]["report"]["fail_under"], 42)

    def test_pylint_odoo_off_removes_its_tools_by_name(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        self.commit(root)
        config = root / "pyproject.toml"
        config.write_text(
            config.read_text() + "\n[tool.odoo-nix.pylint-odoo]\nenable = false\n"
        )
        self.write(root, ok=False)
        names = [d.split("==")[0] for d in deps((root / PATH).read_text())]
        self.assertNotIn("pylint-odoo", names)
        self.assertNotIn("oca-odoo-pre-commit-hooks", names)
        self.assertIn("ruff", names)
        self.assertFalse((root / ".pylintrc").exists())

    def test_deps_group_owns_the_key_alone(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        owners = [
            group
            for group, keys in groups.TOOLS.groups(self.ctx(root)).items()
            for path, _ in keys
            if path[:2] == ("project", "dependencies")
        ]
        self.assertEqual(owners, ["deps"])

    def test_ruff_table_is_a_problem(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        path = root / PATH
        path.write_text(path.read_text() + "\n[tool.ruff]\nline-length = 100\n")
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 2, text)
        self.assertIn("move it to .ruff.toml", text)

    def test_every_tool_module_off_deletes_the_project(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        self.commit(root)
        config = root / "pyproject.toml"
        config.write_text(config.read_text().replace('"recommended"', '"minimal"'))
        self.write(root)
        for path in (PATH, "tools/uv.lock", "package.json", "package-lock.json"):
            self.assertFalse((root / path).exists(), path)
        self.check(root)


if __name__ == "__main__":
    unittest.main()
