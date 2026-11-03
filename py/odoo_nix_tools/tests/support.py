"""Helpers the suites share: the CLI in-process, throwaway git repositories, and the
odoo-nix files outside the package (the fixtures, version.txt, lib/odoo-presets.json).

Those files are found through ``$ODOO_NIX_TOOLS_REPO`` (the package build points it at a
copy of them, lib/standards/package.nix), else in the working tree this package sits in.
A suite that needs them skips when neither has them.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from collections.abc import Mapping
from dataclasses import fields, replace
from pathlib import Path

from odoo_nix_tools import cli, discover
from odoo_nix_tools.product import PRODUCT
from standards_core.product import Hooks, Product
from standards_core.testing import fakes

PACKAGE = Path(__file__).resolve().parent.parent
SHAPES = Path(__file__).resolve().parent / "shapes"

# Core change request CR1 (DESIGN.md §10): without it the core reads [tool.odoo-nix]
# from the root pyproject.toml only, so an addon repository's nix/pyproject.toml table
# is not seen.
HAS_CR1 = "config_file" in {f.name for f in fields(Hooks)}
NEEDS_CR1 = (
    "needs core CR1 (DESIGN.md §10): the core reads [tool.odoo-nix] from the root"
    " pyproject.toml only, and an addon repository's table is in nix/pyproject.toml"
)


def _addons_product() -> Product:
    """``PRODUCT`` as core CR1 would serve an addon repository: ``[tool.odoo-nix]`` in
    ``nix/pyproject.toml``. The engine resolves with the checkout's root (core stage 2),
    so a product whose config file is that path syncs the addons fixture; only the
    per-checkout choice (``hooks.config_file``) is missing. Once the core has CR1 this
    is ``PRODUCT`` itself."""
    if HAS_CR1:
        return PRODUCT
    made: dict[str, Product] = {}
    hooks = replace(
        PRODUCT.hooks,
        load_checkout=lambda root: discover.load_checkout(root, made["p"]),
    )
    identity = replace(PRODUCT.identity, config_file=discover.ADDONS_CONFIG)
    made["p"] = replace(PRODUCT, identity=identity, hooks=hooks)
    return made["p"]


ADDONS_PRODUCT = _addons_product()


def product_for(fixture: str) -> Product:
    """The product that syncs ``tests/fixtures/<fixture>``."""
    return ADDONS_PRODUCT if fixture == "standards-addons" else PRODUCT


def odoo_nix_root() -> Path | None:
    """The odoo-nix tree holding tests/fixtures and version.txt, when there is one."""
    env = os.environ.get("ODOO_NIX_TOOLS_REPO")
    candidates = [Path(env)] if env else []
    candidates.append(PACKAGE.parent.parent)
    for root in candidates:
        if (root / "version.txt").is_file() and (root / "tests/fixtures").is_dir():
            return root
    return None


def need_root(case: unittest.TestCase) -> Path:
    root = odoo_nix_root()
    if root is None:
        case.skipTest(
            "the odoo-nix tree (tests/fixtures, version.txt) is not available"
        )
    return root


# The fixtures, their config files, and where each profile's locks are kept
# (DESIGN.md §7.1).
CONFIG_FILES = {
    "standards-project": "pyproject.toml",
    "standards-addons": "nix/pyproject.toml",
}
BUILTIN_PROFILES = ("minimal", "recommended", "recommended@2.3")
ORG_PROFILES = "tests/fixtures/standards-profiles"
LOCKS = "tests/fixtures/standards-locks"
IN_REPO_PROFILE = ".standards-profile"


def _tree(source: Path) -> dict[str, bytes]:
    return {
        p.relative_to(source).as_posix(): p.read_bytes()
        for p in sorted(source.rglob("*"))
        if p.is_file()
    }


def fixture_files(
    repo: Path, name: str, profile: str, *, locks: bool = True
) -> dict[str, bytes]:
    """``tests/fixtures/<name>`` under ``profile``: a built-in named in the table, or an
    org profile of ``tests/fixtures/standards-profiles`` copied in as the in-repo
    profile ``./.standards-profile``; with ``locks``, that profile's locks of
    ``tests/fixtures/standards-locks/<name>/<profile>/``."""
    files = _tree(repo / "tests/fixtures" / name)
    config = CONFIG_FILES[name]
    text = files[config].decode()
    ref = profile if profile in BUILTIN_PROFILES else f"./{IN_REPO_PROFILE}"
    if 'profile = "recommended"' not in text:
        raise AssertionError(f"{name}/{config} names no profile to replace")
    files[config] = text.replace(
        'profile = "recommended"', f'profile = "{ref}"', 1
    ).encode()
    if profile not in BUILTIN_PROFILES:
        for rel, body in _tree(repo / ORG_PROFILES / profile).items():
            files[f"{IN_REPO_PROFILE}/{rel}"] = body
    lock_dir = repo / LOCKS / name / profile
    if locks and lock_dir.is_dir():
        files.update(_tree(lock_dir))
    return files


def run_cli(
    *argv: str, cwd: Path | None = None, product: Product = PRODUCT
) -> tuple[int, str, str]:
    """``odoo-nix <argv>`` in-process: (exit code, stdout, stderr). ``product`` other
    than ``PRODUCT`` (the CR1 stand-in) runs the core's CLI with it."""
    if product is not PRODUCT:
        return fakes.run_cli(product, *argv, cwd=cwd)
    return fakes.run_cli(PRODUCT, *argv, cwd=cwd, main=cli.main)


def git(root: Path, *args: str) -> str:
    return fakes.git(root, *args)


class TempRepos(unittest.TestCase):
    """A test case with a temporary directory and git without user configuration."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="odoo-nix-tools-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

    def make_tree(
        self, files: Mapping[str, str | bytes], name: str = "repo", commit: bool = True
    ) -> Path:
        """A git repository holding ``files`` (path → text or bytes), all tracked."""
        root = self.tmp / name
        root.mkdir(parents=True)
        for rel, body in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(body, bytes):
                path.write_bytes(body)
            else:
                path.write_text(body)
        git(root, "init", "-q", "-b", "main")
        git(root, "add", "-A")
        if commit:
            git(root, "commit", "-q", "-m", "init", "--allow-empty")
        return root

    def fixture(self, name: str, edit: Mapping[str, str | bytes | None] = {}) -> Path:
        """A git copy of ``tests/fixtures/<name>``, with ``edit`` applied (None deletes)."""
        source = need_root(self) / "tests/fixtures" / name
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
        return self.make_tree(files, name=name)

    def profile_fixture(
        self,
        name: str,
        profile: str,
        edit: Mapping[str, str | bytes | None] = {},
        *,
        locks: bool = True,
    ) -> Path:
        """A git copy of ``tests/fixtures/<name>`` under ``profile`` (``fixture_files``),
        with ``edit`` applied (None deletes)."""
        files: dict[str, str | bytes] = dict(
            fixture_files(need_root(self), name, profile, locks=locks)
        )
        for rel, body in edit.items():
            if body is None:
                files.pop(rel, None)
            else:
                files[rel] = body
        self._count = getattr(self, "_count", 0) + 1
        return self.make_tree(files, name=f"{name}-{profile}-{self._count}")


class SyncCase(TempRepos):
    """Fixture syncs: ``ODOO_NIX_ALLOW_SKEW=1`` (no caller SHA or core rev can match a
    fixture lock's fake rev, DESIGN.md §7.1) and git identities for commits."""

    def setUp(self) -> None:
        super().setUp()
        os.environ["ODOO_NIX_ALLOW_SKEW"] = "1"
        for key, value in (
            ("GIT_AUTHOR_NAME", "odoo-nix-tools"),
            ("GIT_AUTHOR_EMAIL", "tests@example.org"),
            ("GIT_COMMITTER_NAME", "odoo-nix-tools"),
            ("GIT_COMMITTER_EMAIL", "tests@example.org"),
        ):
            os.environ[key] = value

    def sync(
        self, root: Path, *argv: str, product: Product = PRODUCT, ok: bool = True
    ) -> tuple[int, str]:
        """``odoo-nix sync <argv>`` in ``root``; with ``ok``, assert it exits 0."""
        code, out, err = run_cli("sync", *argv, cwd=root, product=product)
        if ok:
            self.assertEqual(code, 0, f"sync {' '.join(argv)}: {out}{err}")
        return code, out + err

    def write(
        self, root: Path, product: Product = PRODUCT, ok: bool = True
    ) -> tuple[int, str]:
        return self.sync(root, "--write", "--offline", product=product, ok=ok)

    def check(
        self, root: Path, product: Product = PRODUCT, ok: bool = True
    ) -> tuple[int, str]:
        return self.sync(root, "--check", product=product, ok=ok)

    def commit(self, root: Path, message: str = "sync") -> None:
        git(root, "add", "-A")
        git(root, "commit", "-q", "--allow-empty", "-m", message)
