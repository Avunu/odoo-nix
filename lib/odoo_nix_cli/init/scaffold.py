"""Scaffold mode: a new project, from scratch."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.detect import dir_is_empty
from odoo_nix_cli.init.pipeline import run_pipeline
from odoo_nix_cli.init.secret_files import PATH as SECRETS_README
from odoo_nix_cli.init.secret_files import scaffold_secrets_dir
from odoo_nix_cli.init.select import require_version, select
from odoo_nix_cli.init.state import Run, normalize_db, normalize_name
from odoo_nix_cli.init.template import files, render

DEFAULT_TARGET = "odoo-project"


def cmd_init(st: Run) -> None:
    a = st.args
    require_version(st)
    select(st, prompt=True)

    if not st.target:
        if ui.has_tty():
            st.target = ui.ask("Project directory", DEFAULT_TARGET)
        st.target = st.target or DEFAULT_TARGET
        st.cd = st.target
    st.name = normalize_name(a.name or os.path.basename(os.path.abspath(st.target)))
    st.db = normalize_db(a.db or "odoo")

    if not dir_is_empty(st.target) and not a.force:
        ui.die(
            f"target '{st.target}' already exists and is not empty. Use --migrate to bring an existing Odoo tree into odoo-nix, or --init --force to scaffold into it anyway.",
            2,
        )

    what = (
        f"project '{st.name}' (Odoo {st.version} → python {st.p.pyver}) in {st.target}"
    )
    if a.dry_run:
        staging = render(st)
        try:
            seeded = sorted({*files(staging), "modules.txt", str(SECRETS_README)})
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        ui.out("Plan")
        ui.info(f"scaffold {what}")
        print_selection(st)
        ui.info(f"database: {st.db}")
        ui.info(f"files   : {' '.join(seeded)}")
        ui.out("\n--dry-run: nothing was changed.")
        return

    ui.out(f"Creating {what}")
    print_selection(st)
    Path(st.target).mkdir(parents=True, exist_ok=True)
    try:
        os.chdir(st.target)
    except OSError:
        ui.die(f"cannot enter {st.target}")
    staging = render(st)
    # Only on a fresh scaffold: an existing tree that keeps its secrets
    # elsewhere should not grow a directory it never asked for.
    scaffold_secrets_dir()
    run_pipeline(st, staging)


def print_selection(st: Run) -> None:
    if st.bundles:
        ui.info(f"bundles : {' '.join(st.bundles)}")
    if st.modules:
        ui.info(f"modules : {' '.join(st.modules)}")
        ui.info(f"repos   : {' '.join(st.repos)}")
