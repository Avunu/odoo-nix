"""odoo-nix's part of ``odoo-nix policy`` (core DESIGN.md §6.2; DESIGN.md §2.1, §3.1).

``committed_argv``: the checkout's own ``committed``, ``tools/.bin/committed`` (the dev
shell links ``tools/.bin`` to the engine's Nix tools, DESIGN.md §5.2), else the one on
``PATH`` (CI's pr-policy installs it from the locked engine).

``pr_checks``: under a ``post-merge-bump`` branching (``develop+series``) the CI App
bumps each addon's version after the merge (``ci bump``), so a pull request to the
integration branch that moves a version by hand would be bumped twice (or skipped, with a
notice): it is refused, naming the manifest.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from standards_core.common import repo
from standards_core.common.report import EnvError

from odoo_nix_tools import manifests

if TYPE_CHECKING:
    from standards_core.commands.policy import PrContext

COMMITTED_LINK = "tools/.bin/committed"
MANIFEST = "__manifest__.py"


def committed_argv(root: Path) -> list[str]:
    """``committed`` from ``tools/.bin`` when the dev shell linked it, else ``PATH``'s."""
    linked = Path(root) / COMMITTED_LINK
    if linked.is_file() and os.access(linked, os.X_OK):
        return [str(linked)]
    return ["committed"]


def _version(text: str | None, path: str) -> str | None:
    if text is None:
        return None
    try:
        version = manifests.literal(text, path).get("version")
    except ValueError:
        return None
    return version if isinstance(version, str) else None


def _merge_base(pr: PrContext) -> str | None:
    for ref in (f"origin/{pr.base_ref}", pr.base_ref):
        try:
            return repo.git(pr.root, "merge-base", ref, pr.head_sha).strip()
        except EnvError:
            continue
    return None


def _post_merge_bump(pr: PrContext) -> bool:
    from odoo_nix_tools.release import BRANCHING

    rules = pr.rules
    if rules.scheme is None:  # releases off
        return False
    name = (rules.cfg.get("releases") or {}).get("branching", "")
    branching = BRANCHING.get(name)
    return branching is not None and branching.flow == "post-merge-bump"


def pr_checks(pr: PrContext) -> list[str]:
    """A version moved by hand in a pull request to the integration branch, under a
    ``post-merge-bump`` branching."""
    if not _post_merge_bump(pr) or pr.base_ref != pr.rules.integration:
        return []
    manifests_changed = [
        p for p in pr.changed() if p == MANIFEST or p.endswith("/" + MANIFEST)
    ]
    if not manifests_changed:
        return []
    base = _merge_base(pr)
    if base is None:
        return [f"the base branch {pr.base_ref!r} is not fetched (fetch-depth: 0)"]
    out = []
    for path in manifests_changed:
        old = _version(pr.show(base, path), path)
        new = _version(pr.show(pr.head_sha, path), path)
        if old is not None and new is not None and old != new:
            out.append(
                f"{path}: version moved by hand ({old} → {new}): under"
                f" {pr.rules.cfg['releases']['branching']} the release bumps it after"
                " the merge, from the conventional commits that touch the addon; keep"
                f" {old}"
            )
    return out
