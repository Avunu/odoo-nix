"""odoo-nix's part of ``odoo-nix policy`` (core DESIGN.md §6.2; DESIGN.md §2.1, §3.1).

``committed_argv``: the checkout's own ``committed``, ``tools/.bin/committed`` (the dev
shell links ``tools/.bin`` to the engine's Nix tools, DESIGN.md §5.2), else the one on
``PATH`` (CI's pr-policy installs it from the locked engine).

``pr_checks``: under a ``post-merge-bump`` branching (``develop+series``) the CI App
bumps each addon's version after the merge (``ci bump``), so a pull request to the
integration branch that moves a version by hand would be bumped twice (or skipped, with a
notice): it is refused, naming the manifest. Under ``series`` versions move in
release-please's release PR only (its head is ``release-please--branches--<series>``,
where ``odoo-nix release sync`` writes them), so the same hand edit is refused in every
other pull request: release-please would release from the old version and overwrite it.
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


def _branching(pr: PrContext) -> str:
    if pr.rules.scheme is None:  # releases off
        return ""
    return str((pr.rules.cfg.get("releases") or {}).get("branching", ""))


def _post_merge_bump(pr: PrContext) -> bool:
    from odoo_nix_tools.release import BRANCHING

    branching = BRANCHING.get(_branching(pr))
    return branching is not None and branching.flow == "post-merge-bump"


def _release_please_pr(pr: PrContext) -> bool | None:
    """``None`` outside the ``series`` branching, else whether ``pr`` is release-please's
    release PR on its series."""
    from odoo_nix_tools import release

    if _branching(pr) != release.SERIES:
        return None
    series = str(pr.rules.facts.get("series") or pr.rules.cfg.get("series") or "")
    return pr.head_ref == release.rp_branch(series)


def pr_checks(pr: PrContext) -> list[str]:
    """A version moved by hand in a pull request to the integration branch, under a
    ``post-merge-bump`` branching, or outside release-please's release PR under
    ``series``."""
    release_pr = _release_please_pr(pr)
    if release_pr is not None:
        return [] if release_pr else _hand_moved(pr, _SERIES_WHY)
    if not _post_merge_bump(pr) or pr.base_ref != pr.rules.integration:
        return []
    return _hand_moved(pr, _BUMP_WHY.format(branching=_branching(pr)))


_BUMP_WHY = (
    "under {branching} the release bumps it after the merge, from the conventional"
    " commits that touch the addon"
)
_SERIES_WHY = (
    "under series release-please's release PR moves it, from the conventional commits"
    " that touch the addon (use a `Release-As: x.y.z` footer to choose the version)"
)


def _hand_moved(pr: PrContext, why: str) -> list[str]:
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
                f"{path}: version moved by hand ({old} → {new}): {why}; keep {old}"
            )
    return out
