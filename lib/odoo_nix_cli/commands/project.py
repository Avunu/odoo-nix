"""`odoo project update` -- pull submodules + relock, then (by default) run
the same migrate engine `odoo db migrate --all` uses.

This is the "hook a migrate step into the update flow" the CLI exists to add:
the old odoo-update script only ever touched code, leaving every database to
a separate, manual `odoo-migrate` call.
"""
from __future__ import annotations

import subprocess

import click
from rich.console import Console

from .. import odooenv
from .db import _migrate_one, _run_multi

console = Console()


@click.group("project")
def project_group():
    """Workspace-level maintenance: pull submodules, refresh OCA deps."""


@project_group.command("update")
@click.option(
    "--migrate/--no-migrate",
    default=True,
    help="Also migrate every database matching dbfilter afterward (default: on).",
)
@click.pass_context
def project_update(ctx, migrate):
    """Pull submodules on their pinned branch, refresh OCA deps, uv lock --
    then migrate every database, unless --no-migrate."""
    script = odooenv.require_env("ODOO_NIX_PROJECT_UPDATE")
    subprocess.run([script], check=True)

    if not migrate:
        return

    conf_path = odooenv.resolve_config_path(ctx.obj.get("config"))
    odoo_config = odooenv.load_config(conf_path, odooenv.db_connection_args(ctx.obj))
    targets = odooenv.list_target_databases(None, True, odoo_config)
    if not targets:
        console.print("[yellow]no databases to migrate.[/]")
        return
    console.print(f"==> Migrating {len(targets)} database(s)…")
    _run_multi(targets, lambda name: _migrate_one(name, no_backup=False))
