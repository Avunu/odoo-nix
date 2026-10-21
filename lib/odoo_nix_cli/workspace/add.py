"""`odoo module add` and `odoo module add-bundle`. Was lib/cli-scripts.nix's
moduleAdd, moduleAddBundle, addModules and addGitSubmodule.

`odoo module add [module …]` adds OCA modules: the repositories their
dependency closure needs, as shallow submodules on the series' branch, and
the modules in modules.txt. `odoo module add <git-url | owner/repo> [branch]
[path]` adds any git repository instead, and records the modules in it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from odoo_nix_cli import oca
from odoo_nix_cli.init import ui
from odoo_nix_cli.init.proc import attempt, git, probe, run
from odoo_nix_cli.init.select import pick_bundles, pick_modules
from odoo_nix_cli.workspace.common import (
    add_modules_txt,
    register,
    submodules,
)
from odoo_nix_cli.workspace.config import WorkspaceConfig
from odoo_nix_cli.workspace.update import regenerate

#: odoo-nix-sources' status for a remote without the branch asked for.
NO_BRANCH = 3

NEXT_STEPS = """\
   1. Reload so the Nix engine re-derives addons_path + rebuilds the env:
        direnv reload
   2. Install:  odoo db provision    (installs everything in modules.txt)"""


class Stop(Exception):
    """Stop with CODE, after MESSAGE (if any) on stderr."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(message)
        self.code = code


def _err(text: str) -> None:
    sys.stdout.flush()
    print(text, file=sys.stderr, flush=True)


def clone(cfg: WorkspaceConfig, url: str, branch: str, path: str) -> int:
    """A partial clone of the one branch, as shell entry makes them
    (odoo-nix-sources): every commit and folder, the files of the checkout."""
    return attempt(
        [cfg.sources, "clone", "--branch", branch, "--require-branch", url, path]
    )


def add_oca_modules(cfg: WorkspaceConfig, selected: list[str]) -> int:
    """SELECTED's dependency closure as submodules, SELECTED in modules.txt, re-locked."""
    if not selected:
        ui.out("Nothing to add.")
        return 0
    ui.out(f"==> Resolving dependency closure for {len(selected)} module(s)…")
    catalog = oca.load_catalog(cfg.oca_dataset)
    repos = oca.resolve_repos(catalog, cfg.series, selected)
    ext = Path(cfg.layout.external_dir)
    ext.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in ext.iterdir()}
    new = [r for r in repos if r not in existing]
    if new:
        ui.out(f"==> Adding {len(new)} new repo submodule(s): {' '.join(new)}")
        added: list[str] = []
        for repo in new:
            url, path = oca.repo_url(repo), f"{cfg.layout.external_dir}/{repo}"
            rc = clone(cfg, url, cfg.series, path)
            if rc == NO_BRANCH:
                continue  # the tool has said why
            if rc != 0:
                raise Stop(rc)
            register(url, cfg.series, path)
            added.append(path)
            ui.out(f"   + {path}")
        # Only what was added here: an unscoped update would also reset every
        # other submodule to the commit the index records, discarding an
        # uncommitted `odoo project update` move.
        if added:
            run(git("submodule", "update", "--init", "--recursive", "--", *added))
    else:
        ui.out("==> All required repos already present.")

    # Every seed is recorded; `odoo db provision` reports anything missing.
    add_modules_txt(selected)
    rc = regenerate(cfg)
    if rc != 0:
        raise Stop(rc)
    ui.out(f"\n✅ Added {len(selected)} module(s) to modules.txt.\n{NEXT_STEPS}")
    return 0


def _has_branch(url: str, branch: str) -> bool:
    return bool(probe(git("ls-remote", "--heads", url, branch)))


def default_branch(url: str) -> str:
    """The remote's HEAD branch, or "" when it cannot be read."""
    for line in (probe(git("ls-remote", "--symref", url, "HEAD")) or "").splitlines():
        if line.startswith("ref:"):
            return line.split()[1].removeprefix("refs/heads/")
    return ""


def add_git_repo(cfg: WorkspaceConfig, argv: list[str]) -> int:
    src, branch_arg, path_arg = (argv + ["", "", ""])[:3]
    tty = ui.has_tty()
    if not src:
        if not tty:
            raise Stop(
                1, "usage: odoo module add <git-url-or-owner/repo> [branch] [path]"
            )
        src = ui.ask(
            "Git URL or owner/repo (https://example.com/owner/repo.git or owner/repo)",
            "",
        ).strip()
        if not src:
            ui.out("Nothing entered.")
            return 0
    try:
        url = oca.resolve_git_url(src)
    except ValueError as e:
        raise Stop(1, str(e)) from None
    slug = oca.repo_slug(url)
    if path_arg:
        slug = path_arg
    elif tty:
        slug = ui.ask(
            f"Submodule path (under {cfg.layout.external_dir}/)", slug
        ).strip()
        if not slug:
            ui.out("Nothing entered.")
            return 0
    path = f"{cfg.layout.external_dir}/{slug}"
    if os.path.lexists(path) or path in submodules():
        raise Stop(
            1,
            f"✗ '{path}' already exists (directory or registered submodule) — pass a different path as the third argument.",
        )

    series = cfg.series
    if branch_arg:
        branch = branch_arg
        if not _has_branch(url, branch):
            raise Stop(1, f"✗ branch '{branch}' not found on {url}")
    elif _has_branch(url, series):
        branch = series
    else:
        detected = default_branch(url)
        if not detected:
            raise Stop(
                1,
                f"✗ no '{series}' branch, and could not detect a default branch on {url} — pass [branch] explicitly.",
            )
        if tty:
            branch = (
                ui.ask(
                    f"No '{series}' branch on {url} — confirm the branch to use",
                    detected,
                ).strip()
                or detected
            )
        else:
            branch = detected
            _err(
                f"==> no '{series}' branch — using detected default branch '{branch}'."
            )

    ui.out(f"==> Cloning {url} ({branch}) → {path}…")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    rc = clone(cfg, url, branch, path)
    if rc != 0:
        raise Stop(rc)

    found = oca.scan_modules(path)
    if not found:
        _err(
            f"⚠  no __manifest__.py found in {url} — adding the submodule without registering any module."
        )
        chosen: list[str] = []
    elif len(found) == 1:
        chosen = found
    elif tty:
        chosen = ui.choose_many(
            "Select module(s) to record in modules.txt:", [(m, m) for m in found]
        )
    else:
        chosen = found
        _err(f"==> non-interactive: recording all {len(chosen)} discovered module(s).")

    ui.out(f"==> Registering {path} as a submodule ({branch})…")
    register(url, branch, path)
    run(git("submodule", "update", "--init", "--recursive", "--", path))
    if not chosen:
        ui.out(
            f"\n✅ Added {path} as a submodule (no modules recorded in modules.txt).\n"
            "   Reload so the Nix engine picks up the new addons_path:\n"
            "     direnv reload"
        )
        return 0
    add_modules_txt(chosen)
    rc = regenerate(cfg)
    if rc != 0:
        raise Stop(rc)
    ui.out(
        f"\n✅ Added {path} as a submodule and recorded {len(chosen)} module(s) in modules.txt.\n{NEXT_STEPS}"
    )
    return 0


def add(cfg: WorkspaceConfig, argv: list[str]) -> int:
    """`odoo module add [module …]` | `odoo module add <git-url-or-owner/repo> [branch] [path]`."""
    tty = ui.has_tty()
    mode = "oca"
    if argv and oca.url_shaped(argv[0]):
        mode = "git"
    elif not argv and tty:
        mode = ui.choose(
            "odoo module add: what do you want to add?",
            [("oca", "Browse OCA catalog"), ("git", "Add from a Git URL")],
        )
    if mode == "git":
        return add_git_repo(cfg, argv)
    if argv:
        selected = list(argv)
    elif tty:
        selected = pick_modules(oca.load_catalog(cfg.oca_dataset), cfg.series)
    else:
        selected = []
    if not selected:
        ui.out("Nothing selected.")
        return 0
    return add_oca_modules(cfg, selected)


def add_bundle(cfg: WorkspaceConfig, argv: list[str]) -> int:
    """`odoo module add-bundle <name …>`: a curated set (data/oca-bundles.json)."""
    bundles = oca.load_bundles(cfg.oca_bundles)
    if argv:
        names = list(argv)
    elif ui.has_tty():
        names = pick_bundles(bundles)
    else:
        raise Stop(
            1,
            f"usage: odoo module add-bundle <name …>   (available: {' '.join(oca.bundle_names(bundles))})",
        )
    if not names:
        ui.out("No bundle selected.")
        return 0
    catalog = oca.load_catalog(cfg.oca_dataset)
    modules = oca.expand_bundles(bundles, catalog, cfg.series, names, ui.warn_line)
    if not modules:
        ui.out("No modules in the selected bundle(s).")
        return 0
    ui.out(f"==> Bundle(s): {' '.join(names)}  →  {len(modules)} module(s)")
    return add_oca_modules(cfg, modules)
