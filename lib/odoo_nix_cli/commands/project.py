"""`odoo project update` -- pull submodules + relock, then (by default) run
the same migrate engine `odoo db migrate --all` uses.

This is the "hook a migrate step into the update flow" the CLI exists to add:
the old odoo-update script only ever touched code, leaving every database to
a separate, manual `odoo-migrate` call.
"""
from __future__ import annotations

import os
import subprocess

import click
from rich.console import Console

from .. import odooenv
from .db import MigrateOptions, _backup_one, _env_flag, _migrate_one, _restore_one, _restore_remote, _run_multi

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
    _run_multi(targets, lambda name: _migrate_one(name, MigrateOptions()))


@project_group.command("backup")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["zip", "dump"]),
    default="zip",
    show_default=True,
    help="zip = schema + filestore; dump = pg_dump custom format, no filestore.",
)
@click.option(
    "--path",
    "out_dir",
    type=click.Path(),
    default=None,
    help="Parent directory for the backups, one <db> subfolder per database (default: <data_dir>/backups/<db>/).",
)
@click.option(
    "--keep-days",
    "keep_days",
    type=int,
    default=0,
    show_default=True,
    help="Prune backups older than this many days, per database (0 = keep forever).",
)
@click.pass_context
def project_backup(ctx, fmt, out_dir, keep_days):
    """Back up every database matching dbfilter -- the whole project, not
    just one database (see `odoo db backup` for a single/explicit list)."""
    conf_path = odooenv.resolve_config_path(ctx.obj.get("config"))
    odoo_config = odooenv.load_config(conf_path, odooenv.db_connection_args(ctx.obj))
    targets = odooenv.list_all_databases(odoo_config)
    if not targets:
        console.print("[yellow]no databases to back up.[/]")
        return
    console.print(f"==> Backing up {len(targets)} database(s)…")
    # auto_backup's naming has no db name in the filename -- only the folder
    # differentiates -- so passing one flat --path straight through to every
    # database, the way `db backup` does for its own single target, would
    # let two databases backed up in the same second collide. Each database
    # gets its own subfolder under the given parent instead; with no --path
    # at all, _backup_one's own <data_dir>/backups/<db>/ default already
    # does this correctly (None passed straight through, per database).
    _run_multi(
        targets,
        lambda name: _backup_one(name, f"{out_dir}/{name}" if out_dir else None, fmt, keep_days),
    )


@project_group.command("restore")
@click.option(
    "--restore",
    "pairs",
    type=(str, click.Path(exists=True)),
    multiple=True,
    metavar="DB PATH",
    help="A database name and the backup file to restore into it. Repeatable. "
    "Omit to restore the project database from the remote backup store.",
)
@click.option("--force", is_flag=True, help="Overwrite a database if it already exists.")
@click.option("--neutralize", is_flag=True, help="Disable outgoing mail/cron on each restored copy (explicit pairs only).")
@click.option("--at", default=None, help="Remote restore: backup at or before this timestamp prefix.")
@click.option(
    "--attachments/--no-attachments",
    default=None,
    help="Remote restore: mirror object-store attachments locally (default: per odoo-nix.restore.attachments).",
)
@click.pass_context
def project_restore(ctx, pairs, force, neutralize, at, attachments):
    """Restore explicit DB PATH pairs in one batch (see `odoo db restore` for
    a single database) -- or, with no --restore, the project database
    (`odooConf.dbName`) from the remote backup store (pass --force to
    overwrite it)."""
    conf_path = odooenv.resolve_config_path(ctx.obj.get("config"))
    odoo_config = odooenv.load_config(conf_path, odooenv.db_connection_args(ctx.obj))
    if not pairs:
        db_name = odooenv.resolve_database(ctx.obj.get("database"), odoo_config)
        if not db_name:
            raise click.UsageError("no database: pass -d/--database or set odooConf.dbName.")
        mode = os.environ.get("ODOO_NIX_RESTORE_ATTACHMENTS", "none") if attachments is None else ("mirror" if attachments else "none")
        _restore_remote(
            db_name,
            os.environ.get("ODOO_NIX_RESTORE_SOURCE_DB") or db_name,
            at,
            force,
            _env_flag("ODOO_NIX_RESTORE_NEUTRALIZE", True),
            True,
            mode,
            False,
        )
        return
    _run_multi(
        list(pairs),
        lambda pair: _restore_one(pair[0], pair[1], force, neutralize),
        label=lambda pair: pair[0],
    )
