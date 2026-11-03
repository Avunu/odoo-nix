"""The addons-shape preflight (DESIGN.md §3.4, §8.2) on the opt-in path, ``sync --write
--standards <profile>``, where nothing exists yet that a later run could fix:

- an addon repository at ``develop``'s shape (no ``flake.nix``, no ``nix/``; all 10
  ``Avunu/*-addons`` today) is exit 2 with the ``odoo-init --addons`` hint, before the
  table is created: nothing is written;
- a repository whose default branch is its series branch (odoo-studio's ``origin/HEAD``
  is ``18.0``) cannot take ``releases`` under ``develop+series``: exit 2, nothing written;
- until core CR1 (DESIGN.md §10), ``odoo-nix`` (``PRODUCT``) refuses to opt in an addon
  repository at all rather than create ``[tool.odoo-nix]`` in a root ``pyproject.toml``;
  the CR1 stand-in (``ADDONS_PRODUCT``) opts the same tree in, into ``nix/pyproject.toml``.

``odoo-init --addons --standards`` (scaffold, then sync, §5.5) is stage O6's.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from odoo_nix_tools.product import PRODUCT
from support import (
    ADDONS_PRODUCT,
    IN_REPO_PROFILE,
    ORG_PROFILES,
    SyncCase,
    git,
    need_root,
)

ADDONS = "standards-addons"
CONFIG = "nix/pyproject.toml"
HINT = "run `odoo-init --addons` first (or add --addons to this run)"
# What feat/dev-env adds to an addon repository (odoo-init --addons).
ADDONS_MODE = ("flake.nix", "flake.lock", ".odoo-series", CONFIG)


def untabled(text: str) -> str:
    """A config file without its ``[tool.odoo-nix]`` tables (not opted in)."""
    return text[: text.index("\n[tool.odoo-nix]")] + "\n"


class OptIn(SyncCase):
    def tree(self, *, develop: bool, profile: bool = False) -> Path:
        repo = need_root(self)
        config = (repo / "tests/fixtures" / ADDONS / CONFIG).read_text()
        edit: dict[str, str | bytes | None] = {CONFIG: untabled(config)}
        if develop:
            edit.update(dict.fromkeys(ADDONS_MODE))
        if profile:
            for path in sorted((repo / ORG_PROFILES / "example-org").rglob("*")):
                if path.is_file():
                    rel = path.relative_to(repo / ORG_PROFILES / "example-org")
                    edit[f"{IN_REPO_PROFILE}/{rel.as_posix()}"] = path.read_bytes()
        source = repo / "tests/fixtures" / ADDONS
        files: dict[str, str | bytes] = {
            p.relative_to(source).as_posix(): p.read_bytes()
            for p in sorted(source.rglob("*"))
            if p.is_file()
        }
        for rel, body in edit.items():
            if body is None:
                files.pop(rel, None)
            else:
                files[rel] = body
        self._trees = getattr(self, "_trees", 0) + 1
        return self.make_tree(files, name=f"{ADDONS}-{self._trees}")

    def opt_in(self, root: Path, product, profile: str = "recommended"):
        return self.sync(
            root,
            "--write",
            "--offline",
            "--standards",
            profile,
            product=product,
            ok=False,
        )

    def assert_untouched(self, root: Path) -> None:
        self.assertEqual(
            git(root, "status", "--porcelain", "--untracked-files=all"), ""
        )

    def test_develop_shape_is_refused_with_the_hint(self) -> None:
        for product in (PRODUCT, ADDONS_PRODUCT):
            with self.subTest(
                product="cr1" if product is ADDONS_PRODUCT else "odoo-nix"
            ):
                root = self.tree(develop=True)
                for path in ADDONS_MODE:
                    self.assertFalse((root / path).exists(), path)
                code, text = self.opt_in(root, product)
                self.assertEqual(code, 2, text)
                self.assertIn(HINT, text)
                self.assert_untouched(root)
                self.assertFalse((root / "pyproject.toml").exists())

    def test_without_cr1_an_addon_repository_is_refused(self) -> None:
        root = self.tree(develop=False)
        code, text = self.opt_in(root, PRODUCT)
        self.assertEqual(code, 2, text)
        self.assertIn(
            "an addon repository keeps [tool.odoo-nix] in nix/pyproject.toml", text
        )
        self.assert_untouched(root)
        self.assertFalse((root / "pyproject.toml").exists())

    def test_with_cr1_the_table_goes_into_nix_pyproject(self) -> None:
        root = self.tree(develop=False)
        before = (root / CONFIG).read_text()
        code, text = self.opt_in(root, ADDONS_PRODUCT)
        self.assertEqual(code, 0, text)
        after = (root / CONFIG).read_text()
        self.assertTrue(after.startswith(before))
        self.assertIn('[tool.odoo-nix]\nschema = 1\nprofile = "recommended"\n', after)
        self.assertFalse((root / "pyproject.toml").exists())
        self.assertIn(
            "# >>> odoo-nix: inputs (managed) >>>", (root / "flake.nix").read_text()
        )

    def test_series_default_branch_under_develop_series(self) -> None:
        root = self.tree(develop=False, profile=True)
        head = git(root, "rev-parse", "HEAD").strip()
        git(
            root, "remote", "add", "origin", "https://github.com/example-org/studio.git"
        )
        git(root, "update-ref", "refs/remotes/origin/18.0", head)
        git(
            root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/18.0"
        )
        code, text = self.opt_in(root, ADDONS_PRODUCT, f"./{IN_REPO_PROFILE}")
        self.assertEqual(code, 2, text)
        self.assertIn("create develop and make it the default branch", text)
        self.assert_untouched(root)

    @unittest.skip("odoo-init --addons --standards (scaffold, then sync) is stage O6")
    def test_addons_then_standards(self) -> None:  # pragma: no cover
        raise AssertionError


if __name__ == "__main__":
    unittest.main()
