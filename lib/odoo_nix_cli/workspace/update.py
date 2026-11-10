"""``odoo project relock`` and the code half of ``odoo project update``. Was
lib/cli-scripts.nix's regenerateAndLock and projectUpdate (bash).

relock rewrites pyproject.toml's managed blocks from what is on disk
(lib/oca_sources.py: OCB and every local module as uv path sources, the
install set from modules.txt), then re-locks (odoo_nix_cli.workspace.lock).
In a repository of addons (addons mode) pyproject.toml and uv.lock are in the
lock directory (nix/), the install set is every installable local addon, and
the flake inputs the shell links in (externalSources) are linked first, so a
relock works in a clone whose shell has never started.
update first moves every submodule onto the tip of the branch .gitmodules pins
it to (as that branch: python-devops-nix's ``sources pull``), then does the same, and ends with ``odoo-init --sync`` (odoo-nix's
standards: the managed files and the standards' own locks), so everything that
follows from new sources is settled in one command. ``module add``,
``add-bundle`` and ``remove`` re-lock through ``regenerate``, as update does.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.proc import attempt, git, run
from odoo_nix_cli.workspace.config import WorkspaceConfig
from odoo_nix_cli.workspace.lock import core_shadow, lock

LOCK_FAILED = "⚠  uv lock failed — resolve in pyproject.toml and re-run."
PULL_SKIPPED = "⚠  Not every submodule is on its branch's tip — see above."
SYNC_FAILED = "⚠  odoo-init --sync did not finish clean (exit {rc}) — fix what it names and run `odoo-init --sync`."


def _say(text: str) -> None:
    print(text, flush=True)


def _from_lock_dir(cfg: WorkspaceConfig, path: str) -> str:
    """PATH, relative to the root, as seen from the lock directory."""
    return os.path.relpath(path, cfg.lock_dir) if cfg.lock_dir != "." else path


def link_external_sources(cfg: WorkspaceConfig) -> None:
    """<externalDir>/<name> -> its store path for every externalSources entry,
    and no other store link there: what shell entry does (modules/devenv.nix),
    for a relock in a clone whose shell has never started. A real directory
    in the way is left alone (shell entry names it)."""
    ext = cfg.layout.external_dir
    if not cfg.external_sources and not os.path.isdir(ext):
        return
    os.makedirs(ext, exist_ok=True)
    for name in sorted(os.listdir(ext)):
        path = os.path.join(ext, name)
        if (
            name not in cfg.external_sources
            and os.path.islink(path)
            and os.readlink(path).startswith("/nix/store/")
        ):
            os.unlink(path)
    for name, store in cfg.external_sources.items():
        path = os.path.join(ext, name)
        if os.path.lexists(path) and not os.path.islink(path):
            continue
        if not os.path.islink(path) or os.readlink(path) != store:
            tmp = f"{path}.odoo-nix-tmp"
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            os.symlink(store, tmp)
            os.replace(tmp, path)


@contextlib.contextmanager
def _lock_dir(cfg: WorkspaceConfig) -> Iterator[None]:
    """In the lock directory for the duration; it and its pyproject.toml are
    made from the template when missing (addons mode's first lock)."""
    if cfg.lock_dir == ".":
        yield
        return
    os.makedirs(cfg.lock_dir, exist_ok=True)
    target = os.path.join(cfg.lock_dir, "pyproject.toml")
    if cfg.pyproject_template and not os.path.exists(target):
        shutil.copyfile(cfg.pyproject_template, target)
        os.chmod(target, 0o644)
        _say(f"==> Wrote {target} (commit it, with uv.lock)")
    cwd = os.getcwd()
    os.chdir(cfg.lock_dir)
    try:
        yield
    finally:
        os.chdir(cwd)


def path_sources(cfg: WorkspaceConfig) -> int:
    """pyproject.toml's managed blocks from what is on disk; oca_sources.py's
    status. Runs in the lock directory."""
    _say("==> Regenerating uv path-sources…")
    lay = cfg.layout
    rel = lambda p: _from_lock_dir(cfg, p)
    return attempt(
        [
            cfg.python,
            cfg.oca_sources,
            "update",
            *(["--roots=local"] if cfg.addons_mode else []),
            "pyproject.toml",
            rel("modules.txt"),
            rel(lay.external_dir),
            rel(lay.custom_dir),
            rel(lay.core_src),
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
    link_external_sources(cfg)
    core_link = cfg.layout.core_src
    with core_shadow(core_link, cfg.core_source), _lock_dir(cfg):
        rc = path_sources(cfg)
        if rc != 0:
            return Relocked(rc)
        _say("==> Re-locking Python environment (uv lock)…")
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


def pull(cfg: WorkspaceConfig) -> None:
    """Every submodule on the tip of its pinned branch. A failed checkout of a
    new one stops it (ui.Exit, with the step's status); one that cannot be
    moved is left where it was, with the reason said, and the rest go on."""
    core_src = cfg.layout.core_src
    _say("==> Updating git submodules…")
    # A submodule this clone has never had is checked out as shell entry
    # does it -- a partial clone, not the shallow one `update --init` makes.
    run([cfg.sources, "enter", "--treeless", core_src, os.getcwd()])
    run(git("submodule", "update", "--init", "--recursive"))
    # Each submodule onto the tip of its .gitmodules-pinned branch, *as* that
    # branch, not detached at it: python-devops-nix's lib.sources does this
    # (`odoo-nix-sources pull`), as frappe-nix's `bench update` does, so the
    # editor's branch picker shows the branch the submodule follows. Never
    # recursing into nested submodules: in a partial clone that check is a lazy
    # fetch per commit (python/sources.py has the reasoning, and the rest of
    # what it refuses to overwrite). Said there is why one was left alone:
    # local commits the remote branch lacks (ODOO_NIX_UPDATE_FORCE=1
    # overwrites them), a file git names, a branch that cannot be fetched.
    if attempt([cfg.sources, "pull", "--treeless", core_src, "--root", os.getcwd()]):
        print(PULL_SKIPPED, file=sys.stderr, flush=True)
    if cfg.core_source:
        _say(
            f"    ({core_src} is a flake input, not a submodule: bump it with 'nix flake update')"
        )


def sync_standards(cfg: WorkspaceConfig) -> int:
    """``odoo-init --sync`` from the root: odoo-nix's managed files written,
    what a turned-off module left retracted, retired files deleted, and the
    standards' own locks (``tools/uv.lock``, ``package-lock.json``) redone.
    Nothing runs, and 0 is the status, for a project that has not opted in
    (``cfg.standards_init`` is None). Its status otherwise: 1 is drift sync
    cannot fix, 2 a configuration it refuses, 3 the environment."""
    if cfg.standards_init is None:
        _say("==> Standards: not opted in, nothing to sync.")
        return 0
    _say("==> Syncing odoo-nix's standards (odoo-init --sync)…")
    sys.stdout.flush()
    rc = attempt([cfg.standards_init, "--sync"])
    if rc != 0:
        sys.stdout.flush()
        print(SYNC_FAILED.format(rc=rc), file=sys.stderr, flush=True)
    return rc


def update(cfg: WorkspaceConfig, sync: bool = True) -> int:
    """``odoo project update``'s code half: pull, regenerate, then sync the
    standards (unless SYNC is off). Its status; a step that stops it has said
    why. A repository of addons has nothing to pull (its sources are flake
    inputs), so it is refused there."""
    if cfg.addons_mode:
        from odoo_nix_cli.workspace.config import ADDONS_MODE_REFUSAL

        print(ADDONS_MODE_REFUSAL.format(command="project update"), file=sys.stderr)
        return 2
    try:
        pull(cfg)
    except ui.Exit as e:
        return e.code
    rc = regenerate(cfg)
    if rc != 0:
        return rc
    if sync:
        rc = sync_standards(cfg)
        if rc != 0:
            return rc
    _say("✅ Code updated.")
    return 0
