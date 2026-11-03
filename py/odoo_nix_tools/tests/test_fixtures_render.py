"""Both fixtures under every profile, through ``sync --write --offline`` and ``--check``
(DESIGN.md §7.2 test_fixtures_render), and the fixtures the package ships.

The addons fixture runs through ``support.ADDONS_PRODUCT``, the stand-in for core CR1
(its table is in ``nix/pyproject.toml``).
"""

from __future__ import annotations

import importlib.util
import json
import os
import unittest
from pathlib import Path

import yaml
from odoo_nix_tools.product import PRODUCT
from standards_core.testing import conformance
from support import PACKAGE, SyncCase, need_root, product_for, run_cli

FIXTURES = ("standards-project", "standards-addons")
PROFILES = ("minimal", "recommended", "example-org")
# What sync writes under an org profile that turns every module on, per fixture.
WHOLE = {
    ".editorconfig",
    ".ruff.toml",
    ".pylintrc",
    ".pylintrc-mandatory",
    "prettier.config.cjs",
    "eslint.config.cjs",
    ".pre-commit-config.yaml",
    "committed.toml",
    ".github/dependabot.yml",
    ".github/zizmor.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/pr-policy.yml",
    ".github/workflows/deps.yml",
}
MERGED = {"tools/pyproject.toml", "package.json"}
LOCKS = {"tools/uv.lock", "package-lock.json"}
SEEDS = {"checklog-odoo.cfg", ".git-blame-ignore-revs"}
# The sentinel blocks: (path, begin marker). dev-shell's are in every profile.
DEV_SHELL_BLOCKS = (
    ("flake.nix", "# >>> odoo-nix: inputs (managed) >>>"),
    (".gitignore", "# >>> odoo-nix: dev-shell (managed) >>>"),
)
README_BLOCK = ("README.md", "<!-- odoo-nix:begin addons-table -->")
IDE_LEAF = '"python.languageServer": "None"'
IDE_EXTENSION = "charliermarsh.ruff"
# A leaf the dev shell seeds (data/ide/vscode.json), which the project fixture has.
SEED_LEAF = '"python.defaultInterpreterPath"'


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


class Matrix(SyncCase):
    def synced(self, name: str, profile: str) -> Path:
        root = self.profile_fixture(name, profile)
        self.write(root, product=product_for(name))
        self.commit(root)
        return root

    def test_write_check_and_idempotence(self) -> None:
        for name in FIXTURES:
            for profile in PROFILES:
                with self.subTest(fixture=name, profile=profile):
                    product = product_for(name)
                    root = self.synced(name, profile)
                    before = snapshot(root)
                    self.write(root, product=product)
                    self.assertEqual(snapshot(root), before)
                    self.check(root, product=product)
                    files = set(before)
                    for path, marker in DEV_SHELL_BLOCKS:
                        self.assertIn(marker, before[path].decode(), path)
                    has_readme_block = README_BLOCK[1] in before["README.md"].decode()
                    self.assertEqual(has_readme_block, profile == "example-org")
                    has_ide = (
                        IDE_LEAF in before.get(".vscode/settings.json", b"").decode()
                    )
                    self.assertEqual(has_ide, profile == "example-org")
                    if has_ide and name == "standards-project":
                        # The fixture's Odoo.serverConfigPath is forbidden (bd59032).
                        self.assertNotIn(
                            b"Odoo.serverConfigPath", before[".vscode/settings.json"]
                        )
                    if profile == "minimal":
                        self.assertFalse((WHOLE | MERGED | LOCKS) & files)
                    else:
                        self.assertLessEqual(MERGED | LOCKS | SEEDS, files)
                    if profile == "example-org":
                        self.assertLessEqual(WHOLE, files)
                        self.assertIn("SECURITY.md", files)
                        # The profile retires the addon repositories' mirror workflow.
                        self.assertNotIn(".github/workflows/mirror.yml", files)
                        release = ".github/workflows/release.yml"
                        self.assertEqual(release in files, name == "standards-addons")

    def test_workflow_names(self) -> None:
        root = self.synced("standards-addons", "example-org")
        for path, name in (
            ("ci.yml", "ci"),
            ("pr-policy.yml", "pr-policy"),
            ("release.yml", "release"),
            ("deps.yml", "deps"),
        ):
            with self.subTest(workflow=path):
                doc = yaml.safe_load((root / ".github/workflows" / path).read_text())
                self.assertEqual(doc["name"], name)
                for job in doc["jobs"].values():
                    self.assertRegex(
                        job["uses"],
                        r"^[a-z]+/odoo-nix/\.github/workflows/odoo-[a-z-]+\.yml@[0-9a-f]{40}$",
                    )
        ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
        # `on:` reads as True in YAML 1.1.
        self.assertEqual(ci[True]["push"]["branches"], ["develop"])
        self.assertEqual({j["name"] for j in ci["jobs"].values()}, {"ci"})
        release = yaml.safe_load((root / ".github/workflows/release.yml").read_text())
        self.assertEqual(release["jobs"]["release"]["with"]["release-branch"], "18.0")
        self.assertEqual(
            release["jobs"]["release"]["with"]["client-id"],
            "${{ vars.EXAMPLE_CI_APP_ID }}",
        )

    def test_project_update_schedule(self) -> None:
        root = self.synced("standards-project", "recommended")
        deps = yaml.safe_load((root / ".github/workflows/deps.yml").read_text())
        self.assertEqual(deps[True]["schedule"], [{"cron": "0 6 * * 1"}])
        self.assertEqual(deps["jobs"]["deps"]["with"]["shape"], "project")
        self.assertNotIn("client-id", deps["jobs"]["deps"]["with"])
        ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
        self.assertEqual(ci[True]["push"]["branches"], ["main"])

    def test_dependabot_branches_and_local_region(self) -> None:
        product = product_for("standards-addons")
        root = self.synced("standards-addons", "recommended")
        path = root / ".github/dependabot.yml"
        doc = yaml.safe_load(path.read_text())
        self.assertEqual(
            [(u["package-ecosystem"], u["target-branch"]) for u in doc["updates"]],
            [
                ("github-actions", "develop"),
                ("nix", "develop"),
                ("github-actions", "17.0"),
                ("nix", "17.0"),
            ],
        )
        entry = (
            "  - package-ecosystem: npm\n"
            "    directory: /fixture_b/static\n"
            '    target-branch: "17.0"\n'
            "    schedule:\n"
            "      interval: weekly\n"
        )
        path.write_text(
            path.read_text().replace(
                "  # odoo-nix:local-begin updates\n",
                "  # odoo-nix:local-begin updates\n" + entry,
            )
        )
        self.write(root, product=product)
        self.assertIn(entry, path.read_text())
        self.check(root, product=product)
        # A region entry with a managed entry's key is exit 2.
        path.write_text(
            path.read_text().replace("npm", "nix").replace("/fixture_b/static", "/")
        )
        code, text = self.check(root, product=product, ok=False)
        self.assertEqual(code, 2, text)

    def test_minimal_after_recommended_retracts(self) -> None:
        for name in FIXTURES:
            with self.subTest(fixture=name):
                product = product_for(name)
                root = self.synced(name, "example-org")
                config = root / (
                    "pyproject.toml"
                    if name == "standards-project"
                    else "nix/pyproject.toml"
                )
                config.write_text(
                    config.read_text().replace('"./.standards-profile"', '"minimal"')
                )
                self.write(root, product=product)
                files = snapshot(root)
                left = set(files)
                self.assertFalse(
                    left & (WHOLE | MERGED | LOCKS), left & (WHOLE | MERGED | LOCKS)
                )
                # The README block and the editor leaves go; dev-shell's blocks and
                # the leaves the dev shell seeds stay.
                self.assertEqual(
                    files["README.md"],
                    (
                        need_root(self) / "tests/fixtures" / name / "README.md"
                    ).read_bytes(),
                )
                for path, marker in DEV_SHELL_BLOCKS:
                    self.assertIn(marker, files[path].decode(), path)
                if name == "standards-project":
                    settings = files[".vscode/settings.json"].decode()
                    self.assertNotIn(IDE_LEAF, settings)
                    self.assertIn(SEED_LEAF, settings)
                    extensions = files[".vscode/extensions.json"].decode()
                    self.assertNotIn(IDE_EXTENSION, extensions)
                    self.assertIn("Odoo.odoo", extensions)
                else:
                    # The editor files sync made for ide hold nothing of sync's now.
                    for path in (".vscode/settings.json", ".vscode/extensions.json"):
                        if path in files:
                            self.assertNotIn(IDE_EXTENSION, files[path].decode())
                            self.assertNotIn(IDE_LEAF, files[path].decode())
                self.assertNotIn(".github/workflows/release.yml", left)
                # The org profile's [[extra-files]] leave with it: switching to minimal
                # leaves SECURITY.md, which no profile names any more.
                # The seeds are the checkout's.
                self.assertLessEqual(SEEDS, left)
                self.assertIn(".envrc", left)
                self.commit(root)
                self.check(root, product=product)


class Defects(SyncCase):
    def test_missing_readme(self) -> None:
        product = product_for("standards-addons")
        root = self.profile_fixture(
            "standards-addons", "example-org", {"fixture_b/README.md": None}
        )
        code, text = self.write(root, product=product, ok=False)
        self.assertEqual(code, 1, text)
        self.commit(root)
        code, text = self.check(root, product=product, ok=False)
        self.assertEqual(code, 1, text)
        self.assertIn("fixture_b has no README.md", text)

    def test_hand_edited_tools_project(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        self.commit(root)
        path = root / "tools/pyproject.toml"
        path.write_text(path.read_text().replace('"prek==0.5.7"', '"prek==0.6.0"'))
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 1, text)
        self.assertIn("tools/uv.lock predates tools/pyproject.toml", text)

    def test_exit_codes(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        config = root / "pyproject.toml"
        config.write_text(
            config.read_text() + '\n[tool.odoo-nix.python-lint]\nextra-select = "B"\n'
        )
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 2, text)
        outside = self.tmp / "not-a-checkout"
        outside.mkdir()
        code, out, err = run_cli("sync", "--check", cwd=outside)
        self.assertEqual(code, 3, out + err)


class ShippedFixtures(unittest.TestCase):
    def test_generated_from_the_tree(self) -> None:
        repo = need_root(self)
        script = PACKAGE / "scripts" / "gen_fixture_data.py"
        if not script.is_file():
            self.skipTest("scripts/ is not in the package build")
        spec = importlib.util.spec_from_file_location("gen_fixture_data", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in module.FIXTURES:
            with self.subTest(fixture=name):
                shipped = json.loads(
                    (Path(PRODUCT.data_root) / "fixtures" / f"{name}.json").read_text()
                )
                self.assertEqual(shipped, module.build(repo, name))

    def test_product_fixtures(self) -> None:
        self.assertEqual(list(PRODUCT.fixtures), ["project"])
        files = PRODUCT.fixtures["project"].files
        self.assertNotIn("[tool.odoo-nix]", files["pyproject.toml"])
        for path in ("flake.nix", "flake.lock", "tools/uv.lock", "package-lock.json"):
            self.assertIn(path, files)

    def test_conformance_render_part(self) -> None:
        saved = dict(os.environ)
        try:
            self.assertEqual(conformance.check(PRODUCT), [])
        finally:
            os.environ.clear()
            os.environ.update(saved)


if __name__ == "__main__":
    unittest.main()
