"""`odoo project update` -- pull submodules + relock, then (by default) run
the same migrate engine `odoo db migrate --all` uses; `odoo project relock`
-- the relock alone, odoo-nix's one consumer-facing relock (python-devops-nix
docs/conventions.md, Relock), which `nix run .#relock` runs outside the shell
(odoo_nix_cli.workspace.relock). Their workspace half is
odoo_nix_cli.workspace.update.

This is the "hook a migrate step into the update flow" the CLI exists to add:
the old odoo-update script only ever touched code, leaving every database to
a separate, manual `odoo-migrate` call.
"""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console

from .. import odooenv
from .db import (
    MigrateOptions,
    _backup_one,
    _env_flag,
    _migrate_one,
    _overwrite,
    _restore_one,
    _restore_options,
    _restore_remote,
    _run_multi,
    _with_files,
)

console = Console()


def _in_workspace(fn) -> int:
    """FN(config) from the repository root, with the workspace configuration
    lib/cli-scripts.nix bakes; its status. The working directory is restored
    afterwards (a migrate after it reads ./odoo.conf)."""
    from ..init import ui
    from ..workspace import config

    try:
        cfg = config.load()
    except config.ConfigError as e:
        raise click.ClickException(str(e)) from None
    cwd = os.getcwd()
    os.chdir(odooenv.repo_root())
    try:
        return fn(cfg)
    except ui.Exit as e:
        return e.code
    except KeyboardInterrupt:
        return 130
    finally:
        os.chdir(cwd)


@click.group("project")
def project_group():
    """Workspace-level maintenance: pull submodules, refresh OCA deps, re-lock."""


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
    from ..workspace.update import update

    rc = _in_workspace(update)
    if rc != 0:
        sys.exit(rc)

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


@project_group.command("relock", context_settings={"ignore_unknown_options": True})
@click.argument("uv_args", nargs=-1, type=click.UNPROCESSED)
def project_relock(uv_args):
    """Regenerate what odoo-nix manages in pyproject.toml (OCB and every local
    module as uv path sources, the install set from modules.txt), then
    re-lock uv.lock with the sdist build dependencies in step -- what `project
    update` does after pulling, with no source moved. UV_ARGS go to `uv lock`,
    e.g. --upgrade or --upgrade-package NAME. Outside the shell: nix run .#relock."""
    from ..workspace.relock import run

    sys.exit(_in_workspace(lambda cfg: run(cfg, uv_args)))


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
        lambda name: _backup_one(
            name, f"{out_dir}/{name}" if out_dir else None, fmt, keep_days
        ),
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
@click.option(
    "--neutralize",
    is_flag=True,
    help="Disable outgoing mail/cron on each restored copy (default in the dev shell: restore.neutralize).",
)
@click.option(
    "--at",
    default=None,
    help="Remote restore: the newest backup within this point in time (ISO 8601 or a backup's own name; see `odoo db restore --help`).",
)
@_restore_options
@click.pass_context
def project_restore(
    ctx, pairs, neutralize, at, no_force, force, migrate, files, attachments
):
    """Restore explicit DB PATH pairs in one batch (see `odoo db restore` for
    a single database) -- or, with no --restore, the project database
    (odoo-nix's `dbName`) from the remote backup store. Existing databases are
    overwritten (--no-force refuses) and migrated afterwards (--no-migrate)."""
    overwrite = _overwrite(force, no_force)
    if migrate is None:
        migrate = _env_flag("ODOO_NIX_RESTORE_MIGRATE", True)
    conf_path = odooenv.resolve_config_path(ctx.obj.get("config"))
    odoo_config = odooenv.load_config(conf_path, odooenv.db_connection_args(ctx.obj))
    if not pairs:
        db_name = odooenv.resolve_database(ctx.obj.get("database"), odoo_config)
        if not db_name:
            raise click.UsageError(
                "no database: pass -d/--database or set odoo-nix.dbName."
            )
        _restore_remote(
            db_name,
            os.environ.get("ODOO_NIX_RESTORE_SOURCE_DB") or db_name,
            at,
            overwrite,
            _env_flag("ODOO_NIX_RESTORE_NEUTRALIZE", True),
            True,
            _with_files(files, attachments),
            False,
            migrate=migrate,
        )
        return
    if not neutralize:
        neutralize = _env_flag("ODOO_NIX_RESTORE_NEUTRALIZE", False)
    _run_multi(
        list(pairs),
        lambda pair: _restore_one(
            pair[0], pair[1], overwrite, neutralize, migrate=migrate
        ),
        label=lambda pair: pair[0],
    )
