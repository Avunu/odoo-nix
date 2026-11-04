"""What odoo-nix's own commands share: the checkout they read and how they report."""

from __future__ import annotations

import argparse
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from standards_core.common import pyproject, repoconfig
from standards_core.common.report import CLEAN, DRIFT, EnvError, Finding, annotation

if TYPE_CHECKING:
    from standards_core.common.repoconfig import RepoConfig
    from standards_core.product import Product

FORMATS = ("text", "github")
# The checkout's locked Python tools (tools/uv.lock, linked by the dev shell).
TOOLS_BIN = "tools/.venv/bin"


@dataclass(frozen=True)
class Problem:
    path: str
    text: str


def load(product: Product, start: Path | None = None) -> RepoConfig:
    """The checkout at or above ``start`` (the current directory): its resolved
    configuration, facts and gates, as sync computes them. Not opted in is exit 2."""
    return repoconfig.load(product, pyproject.checkout_root(product, start))


def default_format() -> str:
    return "github" if os.environ.get("GITHUB_ACTIONS") == "true" else "text"


def add_format(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--format",
        choices=FORMATS,
        default=None,
        help="text, or github (::error annotations); default: github under GitHub"
        " Actions, else text",
    )


def report(problems: Sequence[Problem], fmt: str | None, what: str) -> int:
    """One line per problem (``github``: an ``::error`` annotation on its file); exit 1
    when there is any."""
    fmt = fmt or default_format()
    for p in problems:
        if fmt == "github":
            print(annotation(Finding(p.path, "check", p.text)))
        else:
            print(f"{p.path}: {p.text}")
    if not problems:
        print(f"{what}: ok")
    return DRIFT if problems else CLEAN


def tool(root: Path, name: str) -> str:
    """``tools/.venv/bin/<name>``; exit 3 when the dev shell has not linked it."""
    path = root / TOOLS_BIN / name
    if not (path.is_file() and os.access(path, os.X_OK)):
        raise EnvError(
            f"{TOOLS_BIN}/{name} is missing: enter the dev shell (`nix develop`) or the"
            " lint shell, which link tools/.venv from tools/uv.lock"
        )
    return str(path)


def which(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise EnvError(f"{name} is not on PATH")
    return found
