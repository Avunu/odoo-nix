"""Migrate mode: bring an existing Odoo tree in odoo-nix's layout into odoo-nix,
in place, or repair an odoo-nix project.

Runs inside the tree. Nothing here overwrites a file: the template's files are
written only where none is, a .gitignore gains only the patterns it lacks, and
a flake.nix or pyproject.toml that is not odoo-nix's is refused, or with
--force kept, with odoo-nix's written beside it to merge.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.detect import (
    detect_series,
    existing_db,
    existing_name,
    has_foreign_flake,
    has_foreign_pyproject,
    preset_for,
    repo_state,
    submodules,
)
from odoo_nix_cli.init.pipeline import present, run_pipeline
from odoo_nix_cli.init.proc import git, probe
from odoo_nix_cli.init.select import choose_series, select
from odoo_nix_cli.init.state import CORE, MODULES, Run, normalize_db, normalize_name
from odoo_nix_cli.init.template import files, render


def resolve_migration_preset(st: Run) -> None:
    detected = detect_series()
    if st.version:
        if st.version not in st.presets:
            ui.die(
                f"unknown Odoo series '{st.version}' (expected: {st.preset_keys})", 5
            )
        if detected and detected[0] != st.presets[st.version].branch:
            st.warn(
                f"--version {st.version}, but {detected[1]} says {detected[0]} — the python pin and the OCA branches will not match the code"
            )
        st.resolve_preset()
        return
    if detected is None:
        if ui.has_tty():
            st.warn("could not detect the Odoo series")
            st.version = choose_series(st)
        else:
            ui.die(
                f"could not detect the Odoo series; pass --version (one of: {st.preset_keys})",
                5,
            )
    else:
        key = preset_for(detected[0], st.presets)
        if key is None:
            ui.die(
                f"{detected[1]} says Odoo {detected[0]}, which odoo-nix has no preset for (expected: {st.preset_keys}). Re-run with --version to proceed anyway.",
                5,
            )
        st.version = key
        st.detected_from = detected[1]
    st.resolve_preset()


def print_plan(st: Run, written: list[str], aside: list[str]) -> None:
    ui.out(f"Plan for {os.getcwd()}")
    detected = f" (detected from {st.detected_from})" if st.detected_from else ""
    ui.info(f"series   : {st.version}{detected} → python {st.p.pyver}")
    ui.info(f"name     : {st.name}")
    ui.info(f"database : {st.db}")
    subs = submodules()
    if CORE in subs:
        ui.info(
            f"OCB      : {CORE}/ (submodule, {subs[CORE].get('branch') or 'no branch'})"
        )
    elif os.path.lexists(CORE):
        ui.info(f"OCB      : {CORE}/ (not a submodule; left as it is)")
    else:
        ui.info(f"OCB      : add {CORE}/ (OCA/OCB, {st.branch})")
    kept = sorted(p for p in subs if p.startswith(f"{MODULES}/"))
    if kept:
        ui.info(f"repos    : {' '.join(kept)}")
    new = [r for r in st.repos if not present(f"{MODULES}/{r}")]
    if new:
        ui.info(f"add repos: {' '.join(f'{MODULES}/{r}' for r in new)}")
    if st.modules:
        ui.info(f"modules  : {' '.join(st.modules)} (added to modules.txt)")
    if written:
        ui.info(f"files    : {' '.join(written)}")
    for rel in aside:
        ui.info(f"           {rel}.odoo-nix (yours is kept: merge it by hand)")


def cmd_migrate(st: Run) -> None:
    a = st.args
    if repo_state() == "nested":
        top = probe(git("rev-parse", "--show-toplevel")) or ""
        st.warn(
            f"this tree is inside another git repository ({top}); odoo-nix needs the project root to be its own repository"
        )
        if not a.force:
            ui.die("re-run with --force to create a nested repository anyway", 8)

    resolve_migration_preset(st)
    st.name = normalize_name(a.name or existing_name() or os.path.basename(os.getcwd()))
    st.db = normalize_db(a.db or existing_db() or "odoo")
    select(st, prompt=False)

    # What is not odoo-nix's is kept, and odoo-nix's written beside it.
    aside: list[str] = []
    if has_foreign_flake():
        aside.append("flake.nix")
    if has_foreign_pyproject():
        aside.append("pyproject.toml")
    if aside and not a.force:
        ui.die(
            f"{' and '.join(aside)} {'exists and is' if len(aside) == 1 else 'exist and are'} not odoo-nix's. Re-run with --force: odoo-nix's will be written to {' and '.join(f + '.odoo-nix' for f in aside)} for you to merge.",
            4,
        )
    staging = render(st)
    written = [
        f
        for f in files(staging)
        if f not in aside
        and (not os.path.lexists(f) or f == ".gitignore" and not Path(f).is_symlink())
    ]
    print_plan(st, written, aside)

    if a.dry_run:
        shutil.rmtree(staging, ignore_errors=True)
        ui.out("\n--dry-run: nothing was changed.")
        return
    question = (
        "Repair this odoo-nix project?"
        if st.repair
        else "Migrate this tree to odoo-nix?"
    )
    if not a.assume_yes and not ui.confirm(question):
        shutil.rmtree(staging, ignore_errors=True)
        ui.die("aborted. Re-run with --yes (or --dry-run to inspect the plan).", 6)

    for rel in aside:
        shutil.copy(staging / rel, f"{rel}.odoo-nix")
        st.warn(
            f"{rel} is not odoo-nix's; odoo-nix's was written to {rel}.odoo-nix — merge it by hand"
        )
    if "pyproject.toml" in aside:
        st.manage_pyproject = False
    run_pipeline(st, staging, skip=tuple(aside))
