"""Preflight, notices, whole-repo checks, the lock checks, first opt-in and the retire
rules (DESIGN.md §2.6, §3.2, §3.4; §7.2 test_checks, test_lock_checks)."""

from __future__ import annotations

import json
import unittest

from odoo_nix_tools import checks
from support import SyncCase, git, need_root

ADDONS = "standards-addons"
PROJECT = "standards-project"
LOCK = "standards-locks"


class LockChecks(unittest.TestCase):
    def setUp(self) -> None:
        root = need_root(self)
        self.lock = (
            root / "tests/fixtures" / LOCK / PROJECT / "recommended/tools/uv.lock"
        ).read_text()
        self.superset = (
            root / "tests/fixtures" / LOCK / PROJECT / "example-org/tools/uv.lock"
        ).read_text()
        self.deps = [
            "prek==0.5.7",
            "ruff==0.6.8",
            "pylint-odoo==9.1.3",
            "oca-odoo-pre-commit-hooks==0.0.33",
            "pre-commit-hooks==4.6.0",
            "manifestoo==1.2",
            "coverage==7.16.2",
            "checklog-odoo==1.0",
        ]

    def pyproject(self, deps: list[str]) -> str:
        return f"[project]\nname = 'x'\ndependencies = {json.dumps(deps)}\n"

    def test_equal(self) -> None:
        self.assertEqual(
            checks.tools_lock_problem(
                self.pyproject(self.deps), self.lock, subset=False
            ),
            "",
        )

    def test_stale(self) -> None:
        raised = [d.replace("ruff==0.6.8", "ruff==0.7.0") for d in self.deps]
        problem = checks.tools_lock_problem(
            self.pyproject(raised), self.lock, subset=False
        )
        self.assertIn("tools/uv.lock predates tools/pyproject.toml", problem)
        self.assertIn("ruff", problem)
        self.assertIn("uv lock --project tools", problem)

    def test_subset_only_in_a_throwaway(self) -> None:
        text = self.pyproject(self.deps)
        self.assertEqual(
            checks.tools_lock_problem(text, self.superset, subset=True), ""
        )
        self.assertIn(
            "locked but not declared",
            checks.tools_lock_problem(text, self.superset, subset=False),
        )

    def test_git_source(self) -> None:
        url = (
            "oca-maintainers-tools @ git+https://github.com/oca/maintainer-tools"
            "@31bdbd8e4cb94be6534f0e82b1cafb84a455f671"
        )
        declared = checks.declared_deps(self.pyproject([url]))
        locked = checks.locked_deps(self.superset)
        self.assertTrue(declared and locked and declared <= locked)
        other = checks.declared_deps(self.pyproject([url.replace("31bd", "41bd")]))
        self.assertFalse(other and locked and other <= locked)

    def test_no_root_package(self) -> None:
        problem = checks.tools_lock_problem(
            self.pyproject(self.deps), "version = 1\n", subset=False
        )
        self.assertIn("no root package", problem)

    def test_npm(self) -> None:
        lock = (
            need_root(self)
            / "tests/fixtures"
            / LOCK
            / PROJECT
            / "recommended/package-lock.json"
        ).read_text()
        dev = json.loads(lock)["packages"][""]["devDependencies"]
        self.assertEqual(
            checks.node_lock_problem(json.dumps({"devDependencies": dev}), lock), ""
        )
        raised = {**dev, "prettier": "3.4.0"}
        self.assertIn(
            "package-lock.json predates package.json",
            checks.node_lock_problem(json.dumps({"devDependencies": raised}), lock),
        )


class Preflight(SyncCase):
    def refused(self, root, needle: str) -> None:
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 2, text)
        self.assertIn(needle, text)

    def test_releases_need_conventional_commits(self) -> None:
        config = (
            need_root(self) / "tests/fixtures" / ADDONS / "nix/pyproject.toml"
        ).read_text()
        root = self.profile_fixture(
            ADDONS,
            "example-org",
            {
                "nix/pyproject.toml": config.replace(
                    'profile = "recommended"', 'profile = "./.standards-profile"'
                )
                + '\n[tool.odoo-nix.commits]\nconvention = "odoo"\n'
            },
        )
        self.refused(root, "releases needs conventional commits")

    def test_config_file_of_the_other_shape(self) -> None:
        root = self.profile_fixture(ADDONS, "recommended")
        config = root / "nix/pyproject.toml"
        config.write_text(
            config.read_text().replace(
                'profile = "recommended"', 'profile = "recommended"\nshape = "project"'
            )
        )
        self.refused(root, "move the table to pyproject.toml")

    def test_untested_names_an_addon(self) -> None:
        root = self.profile_fixture(ADDONS, "recommended")
        config = root / "nix/pyproject.toml"
        config.write_text(
            config.read_text()
            + '\n[[tool.odoo-nix.untested]]\naddon = "nope"\nreason = "a stand-in addon"\n'
        )
        self.refused(root, "'nope', which is no addon")

    def test_addons_mode_files(self) -> None:
        root = self.profile_fixture(ADDONS, "recommended", {"flake.nix": None})
        self.refused(root, "run `odoo-init --addons` first")
        config = (
            need_root(self) / "tests/fixtures" / ADDONS / "nix/pyproject.toml"
        ).read_text()
        bare = config.replace("# >>> odoo-nix: install set", "# install set")
        root = self.profile_fixture(ADDONS, "recommended", {"nix/pyproject.toml": bare})
        self.refused(root, "run `odoo-init --addons` first")

    def test_lock_dir(self) -> None:
        flake = (need_root(self) / "tests/fixtures" / ADDONS / "flake.nix").read_text()
        moved = flake.replace(
            "addons.enable = true;",
            'addons.enable = true;\n              addons.lockDir = "deps";',
        )
        root = self.profile_fixture(ADDONS, "recommended", {"flake.nix": moved})
        self.refused(root, 'keep addons.lockDir = "nix"')

    def test_series_integration_branch_under_develop_series(self) -> None:
        root = self.profile_fixture(ADDONS, "example-org")
        config = root / "nix/pyproject.toml"
        config.write_text(
            config.read_text().replace(
                "[tool.odoo-nix.dependabot]",
                'integration-branch = "18.0"\n\n[tool.odoo-nix.dependabot]',
            )
        )
        self.refused(root, "create develop and make it the default branch")

    def test_project_without_flake(self) -> None:
        root = self.profile_fixture(
            PROJECT, "recommended", {"flake.nix": None, "flake.lock": None}
        )
        self.refused(root, "has no flake.nix")


class Notices(SyncCase):
    def test_project_under_an_org_profile(self) -> None:
        root = self.profile_fixture(PROJECT, "example-org")
        _, text = self.write(root)
        self.assertIn("releases applies to addon repositories", text)
        self.assertIn("packaging applies to addon repositories", text)
        self.assertIn("[dependency-groups].dev lists ruff", text)
        self.assertIn(".vscode/settings.json sets python-envs.*", text)

    def test_both_shape_signals(self) -> None:
        root = self.profile_fixture(
            ADDONS, "recommended", {"modules.txt": "queue_job\n"}
        )
        _, text = self.write(root)
        self.assertIn("both addons-mode and project signals; using addons", text)


class Checks(SyncCase):
    def drift(self, root, needle: str) -> None:
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 1, text)
        self.assertIn(needle, text)

    def synced(self, name: str, profile: str, edit: dict | None = None):
        root = self.profile_fixture(name, profile, edit or {})
        self.write(root, ok=False)
        self.commit(root)
        return root

    def test_readme(self) -> None:
        root = self.synced(ADDONS, "example-org", {"fixture_b/README.md": None})
        self.drift(root, "addon fixture_b has no README.md")

    def test_submodule_branch(self) -> None:
        root = self.synced(PROJECT, "recommended")
        modules = root / ".gitmodules"
        modules.write_text(
            modules.read_text().replace("branch = 18.0", "branch = 17.0", 1)
        )
        self.drift(root, "submodule odoo follows 17.0, not branch = 18.0")

    def test_packaging(self) -> None:
        root = self.synced(ADDONS, "example-org", {"fixture_b/pyproject.toml": None})
        self.drift(root, "addon fixture_b has no whool pyproject.toml")
        config = root / "nix/pyproject.toml"
        config.write_text(
            config.read_text().replace(
                '"odoo-addon-fixture_a" = { path', '"x" = { path'
            )
        )
        git(root, "add", "-A")
        self.drift(root, "nix/uv.lock predates fixture_a/pyproject.toml")

    def test_ruff_table_in_the_config_file(self) -> None:
        root = self.synced(PROJECT, "recommended")
        config = root / "pyproject.toml"
        config.write_text(
            config.read_text().replace(
                "[tool.odoo-nix]", "[tool.ruff]\nline-length = 100\n\n[tool.odoo-nix]"
            )
        )
        self.drift(root, "[tool.ruff] is ignored")

    def test_series_disagreement(self) -> None:
        root = self.synced(ADDONS, "recommended")
        lock = root / "flake.lock"
        doc = json.loads(lock.read_text())
        ocb = doc["nodes"][doc["nodes"]["root"]["inputs"]["ocb"]]
        ocb["original"]["ref"] = "19.0"
        lock.write_text(json.dumps(doc, indent=2) + "\n")
        flake = root / "flake.nix"
        flake.write_text(
            flake.read_text().replace("github:OCA/OCB/18.0", "github:OCA/OCB/19.0")
        )
        self.drift(root, "series 18.0, but flake.lock's ocb names 19.0")

    def test_stale_tools_lock(self) -> None:
        root = self.synced(PROJECT, "recommended")
        path = root / "tools/pyproject.toml"
        path.write_text(path.read_text().replace('"ruff==0.6.8"', '"ruff==0.7.0"'))
        self.drift(root, "tools/uv.lock predates tools/pyproject.toml")
        # --write --offline names the command and leaves the lock to it.
        code, text = self.write(root, ok=False)
        self.assertEqual(code, 0, text)
        self.assertIn("(offline: run `uv lock --project tools`)", text)

    def test_stale_npm_lock(self) -> None:
        root = self.synced(PROJECT, "recommended")
        path = root / "package.json"
        doc = json.loads(path.read_text())
        doc["devDependencies"]["prettier"] = "3.4.0"
        path.write_text(json.dumps(doc, indent=2) + "\n")
        self.drift(root, "package-lock.json predates package.json")


class FirstOptIn(SyncCase):
    def test_own_pre_commit_config_needs_force(self) -> None:
        own = "repos:\n  - repo: local\n    hooks: []\n"
        root = self.profile_fixture(
            PROJECT, "recommended", {".pre-commit-config.yaml": own}
        )
        code, text = self.write(root, ok=False)
        self.assertEqual(code, 2, text)
        self.assertIn("`# odoo-nix:local-begin hooks` region", text)
        self.assertIn("then pass --force", text)
        self.assertEqual((root / ".pre-commit-config.yaml").read_text(), own)
        self.sync(root, "--write", "--offline", "--force")
        self.assertIn(
            "odoo-nix:managed", (root / ".pre-commit-config.yaml").read_text()
        )

    def test_legacy_envrc_replaced_silently_own_refused(self) -> None:
        for text in checks.LEGACY_ENVRC:
            with self.subTest(envrc=text[:30]):
                root = self.profile_fixture(PROJECT, "minimal", {".envrc": text})
                self.write(root)
                self.assertIn("odoo-nix:managed", (root / ".envrc").read_text())
                (root / ".envrc").unlink()
        root = self.profile_fixture(
            PROJECT, "minimal", {".envrc": "dotenv\nuse flake\n"}
        )
        code, text = self.write(root, ok=False)
        self.assertEqual(code, 2, text)
        self.assertIn("`# odoo-nix:local-begin envrc` region", text)


class Retire(SyncCase):
    def test_old_tool_configs(self) -> None:
        root = self.profile_fixture(
            PROJECT,
            "recommended",
            {
                ".flake8": "[flake8]\nmax-line-length = 88\n",
                "setup.cfg": "[flake8]\nx = 1\n[isort]\ny = 2\n",
                ".prettierrc.yml": "printWidth: 88\n",
                ".github/workflows/test.yml": "jobs:\n  t:\n    container: ghcr.io/oca/oca-ci/py3.10-odoo18.0:latest\n",
                ".github/workflows/other.yml": "jobs: {}\n",
            },
        )
        self.write(root)
        for path in (
            ".flake8",
            "setup.cfg",
            ".prettierrc.yml",
            ".github/workflows/test.yml",
        ):
            self.assertFalse((root / path).exists(), path)
        self.assertTrue((root / ".github/workflows/other.yml").exists())

    def test_mixed_setup_cfg_stays(self) -> None:
        root = self.profile_fixture(
            PROJECT,
            "recommended",
            {"setup.cfg": "[flake8]\nx = 1\n[metadata]\nname = x\n"},
        )
        self.write(root)
        self.assertTrue((root / "setup.cfg").exists())


if __name__ == "__main__":
    unittest.main()
