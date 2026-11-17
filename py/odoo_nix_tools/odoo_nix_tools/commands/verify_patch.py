"""``odoo-nix verify-patch KIND``: the patch a plan job staged in this checkout's index,
checked against ``--base`` (default ``HEAD``) before a job that holds the CI App's key
pushes it (odoo_nix_tools.lockpatch has the rules).

``relock``: odoo-deps.yml's relock-push, a Dependabot nix pull request's
``nix run .#relock`` in a repository of addons (nix/pyproject.toml, nix/uv.lock).
``project-update``: its project-update, ``odoo project update --no-sync`` in a project
(the submodules' gitlinks, pyproject.toml, uv.lock).

It reads only git and the staged files: no configuration, and nothing from the patch
runs. Exit 0 when the patch passes, 1 with each problem as a GitHub error annotation.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from standards_core.commands import Command, help_text
from standards_core.common.report import CLEAN, DRIFT

from odoo_nix_tools import lockpatch

if TYPE_CHECKING:
    from standards_core.product import Product


def run(args: argparse.Namespace) -> int:
    problems = lockpatch.verify(Path(args.root), args.base, lockpatch.KINDS[args.kind])
    for problem in problems:
        print(f"::error title=verify-patch::{problem}")
    if problems:
        return DRIFT
    print(f"verify-patch: the {args.kind} patch passes")
    return CLEAN


def register(sub: argparse._SubParsersAction, product: Product) -> None:
    p = sub.add_parser(
        "verify-patch",
        help="check a plan job's staged patch before a key-holding job pushes it",
        description=help_text(product, "verify-patch", __doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("kind", choices=sorted(lockpatch.KINDS), help="what the plan ran")
    p.add_argument(
        "--base", default="HEAD", help="the revision the patch applies to (HEAD)"
    )
    p.add_argument("--root", default=".", help="the checkout (.)")
    p.set_defaults(func=run)


VERIFY_PATCH = Command("verify-patch", register)
