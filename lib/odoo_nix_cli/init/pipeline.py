"""The steps scaffolding and migration share.

Scaffolding is migration into an empty directory: once the template is
rendered, both install it without overwriting, record modules.txt, add OCB and
the OCA repositories that are missing as submodules, write the uv path sources,
lock, stage, and report. Every step is check-then-act, so an interrupted run is
resumed by running it again.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from odoo_nix_cli import oca
from odoo_nix_cli.init import ui
from odoo_nix_cli.init.detect import flake_text, repo_state, submodules
from odoo_nix_cli.init.proc import attempt, git, probe, run
from odoo_nix_cli.init.secret_files import secrets_declared
from odoo_nix_cli.init.state import CORE, CUSTOM, MODULES, OCB_URL, Run
from odoo_nix_cli.init.template import install

#: odoo-nix-sources' exit status for a remote without the branch asked for.
NO_BRANCH = 3

COMMIT_MESSAGES = {
    "init": "chore: scaffold odoo-nix project",
    "migrate": "chore: migrate project to odoo-nix",
}


def ensure_repo() -> None:
    if repo_state() != "own":
        run(git("init", "-q"))


def write_modules_txt(st: Run) -> None:
    """modules.txt: what it held, and the modules selected, sorted and once each.
    An empty selection is the default, not an error."""
    path = Path("modules.txt")
    have = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    names = sorted({m.strip() for m in [*have, *st.modules] if m.strip()})
    path.write_text("".join(f"{m}\n" for m in names), encoding="utf-8")


def present(path: str) -> bool:
    """PATH is in the tree already: on disk, or registered in .gitmodules."""
    return os.path.lexists(path) or path in submodules()


def add_submodule(st: Run, url: str, path: str, *, treeless: bool = False) -> int:
    """A partial clone of the series' branch, as shell entry makes them
    (odoo-nix-sources, python-devops-nix's lib.sources): every commit and
    folder, the files of the checkout; OCB with its commits alone, its folder
    history being enormous. Then registered as a submodule. The clone's status:
    3 for a remote with no such branch, which the tool has already said."""
    cmd = ["odoo-nix-sources", "clone", "--branch", st.branch, "--require-branch"]
    if treeless:
        cmd.append("--treeless")
    rc = attempt([*cmd, url, path])
    if rc != 0:
        return rc
    ui.info(f"+ {path} ({st.branch})")
    run(git("submodule", "add", "-q", "--force", "-b", st.branch, "--", url, path))
    run(git("config", "-f", ".gitmodules", f"submodule.{path}.shallow", "true"))
    st.added.append(path)
    return 0


def add_sources(st: Run) -> None:
    if not present(CORE):
        ui.out(f"Adding OCB (Odoo {st.version}) at {CORE}/…")
        if add_submodule(st, OCB_URL, CORE, treeless=True) != 0:
            ui.die(f"could not clone OCB ({OCB_URL}, branch {st.branch}) into {CORE}/")
    missing = [r for r in st.repos if not present(f"{MODULES}/{r}")]
    if missing:
        ui.out(f"Adding OCA module-repo submodules under {MODULES}/…")
        for repo in missing:
            url = oca.repo_url(repo)
            rc = add_submodule(st, url, f"{MODULES}/{repo}")
            if rc == NO_BRANCH:
                st.warn(
                    f"{url} has no {st.branch} branch; {MODULES}/{repo} was not added"
                )
            elif rc != 0:
                st.warn(
                    f"{url} could not be cloned (exit {rc}); {MODULES}/{repo} was not added"
                )
    # Only what this run added: an unscoped update would also reset every other
    # submodule to the commit the index records, discarding a move not yet
    # committed.
    if st.added:
        run(git("submodule", "update", "--init", "--recursive", "--", *st.added))


def write_path_sources(st: Run) -> None:
    """OCB and every local module as uv path sources, and the install set from
    modules.txt (lib/oca_sources.py): uv then resolves the whole graph from the
    modules' whool metadata."""
    if not st.manage_pyproject:
        return
    ui.out("Generating uv path-sources in pyproject.toml…")
    rc = attempt(
        [
            sys.executable,
            st.config.oca_sources,
            "update",
            "pyproject.toml",
            "modules.txt",
            MODULES,
            CUSTOM,
            CORE,
        ]
    )
    if rc != 0:
        st.warn(
            f"lib/oca_sources.py failed (exit {rc}); pyproject.toml's managed blocks may be stale"
        )


def lock(st: Run) -> None:
    if st.args.skip_lock:
        ui.info("skipping uv lock (--skip-lock)")
        return
    if not st.manage_pyproject:
        st.warn(
            "pyproject.toml is not odoo-nix's, so nothing was locked; merge pyproject.toml.odoo-nix, then run 'uv lock'"
        )
        return
    ui.out("Resolving Python environment (uv lock)…")
    if attempt(["uv", "lock"]) != 0:
        st.warn(
            "uv lock failed — usually a version conflict. Adjust pyproject.toml [project].dependencies and re-run 'uv lock'."
        )
        return
    # Grant setuptools to sdist-only packages so uv2nix can build them.
    if st.config.build_deps:
        if attempt([st.config.build_deps, "update", "pyproject.toml", "uv.lock"]) != 0:
            st.warn(
                "odoo-nix-build-deps failed; the dev shell's relock derives the build dependencies again"
            )
        if attempt(["uv", "lock"]) != 0:
            st.warn(
                "uv lock failed after the build dependencies were added; re-run 'uv lock'"
            )


def stage_and_commit(st: Run) -> None:
    run(git("add", "-A"))
    if st.args.commit:
        message = st.args.commit_msg or COMMIT_MESSAGES[st.mode]
        run(git("commit", "-q", "-m", message))
        ui.info(f"committed: {message}")


def report(st: Run) -> None:
    here = os.getcwd()
    done = (
        "created" if st.mode == "init" else "migrated" if not st.repair else "repaired"
    )
    ui.out(f"\n✅ Project '{st.name}' {done} in {here}")
    ui.out(f"   series  : {st.version} (python {st.p.pyver})")
    modules = (
        Path("modules.txt").read_text(encoding="utf-8").split()
        if Path("modules.txt").is_file()
        else []
    )
    ui.out(f"   modules : {' '.join(modules) or '<none — Odoo core only>'}")

    if st.warnings:
        ui.out(f"\n{len(st.warnings)} warning(s):")
        for w in st.warnings:
            ui.out(f"  ⚠  {w}")

    declared = secrets_declared(flake_text())
    ui.out("\nNext steps:")
    if st.cd not in ("", "."):
        next_step(f"cd {st.cd}")
    if st.args.commit:
        next_step("git show --stat", "review the commit")
    else:
        next_step("git diff --cached --stat", "review; nothing has been committed")
    next_step("direnv allow", "or: nix develop --no-pure-eval")
    next_step("devenv up", "PostgreSQL, Odoo, Mailpit")
    if declared:
        next_step(
            f"odoo db restore {st.db}",
            f"(in another shell) clone {st.db} from the latest production backup",
        )
    else:
        next_step(
            "odoo db provision",
            f"(in another shell) create {st.db} + install modules.txt",
        )
        ui.out(
            "\nTo restore this project from production backups, declare its secrets —\n"
            'see "Restore a production backup" in the odoo-nix docs, or the commented block in flake.nix.'
        )


def next_step(command: str, comment: str = "") -> None:
    ui.out(f"  {command:<28} # {comment}" if comment else f"  {command}")


def run_pipeline(st: Run, staging: Path, *, skip: tuple[str, ...] = ()) -> None:
    """The steps both modes share, in the project root, with the rendered
    template in STAGING (SKIP: staged files not to install)."""
    try:
        ensure_repo()
        install(staging, skip=skip, verbose=st.mode == "migrate")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    write_modules_txt(st)
    add_sources(st)
    write_path_sources(st)
    lock(st)
    stage_and_commit(st)
    if probe(git("ls-files", "--error-unmatch", "--", "flake.nix")) is None:
        ui.die("flake.nix did not reach the git index")
    report(st)
