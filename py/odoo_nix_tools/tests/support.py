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
from dataclasses import fields
from pathlib import Path

from odoo_nix_tools import cli
from odoo_nix_tools.product import PRODUCT
from standards_core.product import Hooks
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


def run_cli(*argv: str, cwd: Path | None = None) -> tuple[int, str, str]:
    """``odoo-nix <argv>`` in-process: (exit code, stdout, stderr)."""
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
