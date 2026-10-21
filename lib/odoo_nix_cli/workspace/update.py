"""``odoo project relock`` and the code half of ``odoo project update``. Was
lib/cli-scripts.nix's regenerateAndLock and projectUpdate (bash).

relock rewrites pyproject.toml's managed blocks from what is on disk
(lib/oca_sources.py: OCB and every local module as uv path sources, the
install set from modules.txt), then re-locks (odoo_nix_cli.workspace.lock).
update first moves every submodule to the tip of the branch .gitmodules pins
it to, then does the same. ``module add``, ``add-bundle`` and ``remove``
re-lock through ``regenerate``, as update does.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.proc import attempt, git, probe, run
from odoo_nix_cli.workspace.config import WorkspaceConfig
from odoo_nix_cli.workspace.lock import core_shadow, lock

LOCK_FAILED = "⚠  uv lock failed — resolve in pyproject.toml and re-run."


def _say(text: str) -> None:
    print(text, flush=True)


def path_sources(cfg: WorkspaceConfig) -> int:
    """pyproject.toml's managed blocks from what is on disk; oca_sources.py's status."""
    _say("==> Regenerating uv path-sources…")
    lay = cfg.layout
    return attempt(
        [
            cfg.python,
            cfg.oca_sources,
            "update",
            "pyproject.toml",
            "modules.txt",
            lay.external_dir,
            lay.custom_dir,
            lay.core_src,
        ]
    )


@dataclass(frozen=True)
class Relocked:
    """What a relock's steps exited with. Nothing runs after a failed step of
    the first two; the build-dependency sync and the second lock both run."""

    sources: int  # lib/oca_sources.py
    lock: int = 0  # the first `uv lock`
    after: int = 0  # odoo-nix-build-deps and the second `uv lock`

    @property
    def status(self) -> int:
        return self.sources or self.lock or self.after


def relock(cfg: WorkspaceConfig, uv_args: Sequence[str] = ()) -> Relocked:
    """The path sources, then the lock, through a writable shadow of a
    store-resident OCB (coreSource). UV_ARGS go to the first ``uv lock``. A
    failed lock is said here."""
    rc = path_sources(cfg)
    if rc != 0:
        return Relocked(rc)
    _say("==> Re-locking Python environment (uv lock)…")
    with core_shadow(cfg.layout.core_src, cfg.core_source):
        first, after = lock(cfg.uv, cfg.build_deps, uv_args)
    if first != 0:
        sys.stdout.flush()
        print(LOCK_FAILED, file=sys.stderr, flush=True)
    return Relocked(0, first, after)


def regenerate(cfg: WorkspaceConfig) -> int:
    """What ``module add|add-bundle|remove`` and ``project update`` re-lock
    with. A failed path-source sync stops them with its status. A failed lock
    is said and they carry on, as the bash did: the user resolves it and runs
    ``odoo project relock``."""
    return relock(cfg).sources


def fetch_depth(path: str, core_src: str) -> list[str]:
    """How much of a submodule's branch to fetch follows how it was cloned. A
    partial clone (odoo-nix-sources) keeps its branch with every commit's
    folders, and OCB (CORE_SRC) with its commits only, so ask for the folders
    except for OCB. ``--depth 1`` would turn it into a shallow clone again, so
    that is only for one still shallow. PATH is the submodule's working tree."""
    if probe(git("config", "remote.origin.promisor", cwd=path)) == "true":
        return [] if path == core_src else ["--filter=blob:none"]
    if probe(git("rev-parse", "--is-shallow-repository", cwd=path)) == "true":
        return ["--depth=1"]
    return []


def pinned_branch(path: str) -> str:
    """The branch .gitmodules pairs PATH with (keyed on the path, as the bash
    did), else the branch the submodule has checked out, else ''."""
    return (
        probe(git("config", "-f", ".gitmodules", "--get", f"submodule.{path}.branch"))
        or probe(git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=path))
        or ""
    )


def checked_out() -> list[str]:
    """The paths of the submodules checked out at the top level: what ``git
    submodule foreach`` visits."""
    listing = probe(git("submodule", "foreach", "--quiet", 'printf "%s\\n" "$sm_path"'))
    return [line for line in (listing or "").splitlines() if line]


def pull(cfg: WorkspaceConfig) -> None:
    """Every submodule at the tip of its pinned branch. A failed checkout of a
    new one stops it (ui.Exit, with the step's status); a failed fetch is
    passed over."""
    core_src = cfg.layout.core_src
    _say("==> Updating git submodules…")
    # A submodule this clone has never had is checked out as shell entry
    # does it -- a partial clone, not the shallow one `update --init` makes.
    run([cfg.sources, "enter", "--treeless", core_src, os.getcwd()])
    run(git("submodule", "update", "--init", "--recursive"))
    # Each submodule to the tip of its .gitmodules-pinned branch, fetched
    # fresh by name. Two things rule out the more obvious approaches:
    # `update --init --recursive` alone leaves submodules in detached HEAD, so
    # `git rev-parse --abbrev-ref HEAD` returns the literal string "HEAD", and
    # pulling "origin HEAD" then follows the remote's *default* branch instead
    # of the pinned one. `git submodule update --remote` avoids that but can
    # still fail if a submodule's local remote-tracking refspec was narrowed
    # to some other branch at clone time. Both surface as "Not possible to
    # fast-forward" whenever a repo's default branch no longer matches what is
    # pinned. Fetching the pinned branch by name every time sidesteps both.
    # Never recursing into nested submodules: in a partial clone that check is
    # a lazy fetch per commit (see python-devops-nix's python/sources.py).
    for path in checked_out():
        branch = pinned_branch(path)
        if not branch:
            continue
        fetch = git(
            "fetch",
            *fetch_depth(path, core_src),
            "--quiet",
            "--no-recurse-submodules",
            "origin",
            branch,
            cwd=path,
        )
        if attempt(fetch) == 0:
            attempt(git("checkout", "--quiet", "FETCH_HEAD", cwd=path))
    if cfg.core_source:
        _say(
            f"    ({core_src} is a flake input, not a submodule: bump it with 'nix flake update')"
        )


def update(cfg: WorkspaceConfig) -> int:
    """``odoo project update``'s code half: pull, then regenerate. Its status;
    a step that stops it has said why."""
    try:
        pull(cfg)
    except ui.Exit as e:
        return e.code
    rc = regenerate(cfg)
    if rc != 0:
        return rc
    _say("✅ Code updated.")
    return 0
