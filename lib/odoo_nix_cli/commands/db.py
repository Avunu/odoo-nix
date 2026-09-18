"""`odoo db ...` -- database lifecycle: list/create/provision/upgrade/migrate/
duplicate/rename/drop/backup/restore.

Every mutating command here is a thin wrapper around odoo.service.db (the
same functions odoo-bin's own `db` command and the /web/database/* Database
Manager use) or odoo.modules.registry.Registry.new (the same call odoo-bin's
own -u/-i/--stop-after-init makes) -- nothing here reimplements Odoo's module
loading or database management, it only adds progress feedback and CLI
ergonomics around them.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from collections.abc import Callable
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .. import odooenv
from ..progress import MigrationProgress

console = Console()


def _load(ctx):
    conf_path = odooenv.resolve_config_path(ctx.obj.get("config"))
    return odooenv.load_config(conf_path, odooenv.db_connection_args(ctx.obj))


@click.group("db")
def db_group():
    """Database lifecycle: list, create, provision, upgrade, migrate, backup, restore…"""


@db_group.command("list")
@click.pass_context
def db_list(ctx):
    """List databases visible to this server, with version compatibility."""
    odoo_config = _load(ctx)
    from odoo.service import db as odoo_db

    names = odooenv.list_all_databases(odoo_config)
    incompatible = set(odoo_db.list_db_incompatible(names))
    table = Table()
    table.add_column("Database")
    table.add_column("Status")
    for name in names:
        table.add_row(name, "[red]incompatible[/]" if name in incompatible else "[green]ok[/]")
    console.print(table)


@db_group.command("create")
@click.argument("db_name")
@click.option("--demo/--no-demo", default=False, help="Load demo data.")
@click.option("--lang", default="en_US", show_default=True)
@click.pass_context
def db_create(ctx, db_name, demo, lang):
    """Create an empty database (base not installed -- see `provision`)."""
    _load(ctx)
    from odoo.service import db as odoo_db

    odoo_db.exp_create_database(db_name, demo, lang)
    console.print(f"[green]✓[/] created database '{db_name}'")


def _read_modules_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


@db_group.command("provision")
@click.argument("db_name", required=False)
@click.option("--modules-file", default="modules.txt", show_default=True, type=click.Path())
@click.option("--no-backup", is_flag=True, help="Skip the automatic pre-migrate backup when the database already exists.")
@click.pass_context
def db_provision(ctx, db_name, modules_file, no_backup):
    """Create + install modules.txt (new database), or migrate it (existing).

    Idempotent: the first run creates the database and installs every module
    listed in modules.txt; every run after that upgrades it instead of
    reinstalling -- the same distinction `bench new-site`/`migrate` draw.
    """
    odoo_config = _load(ctx)
    target = odooenv.resolve_database(db_name, odoo_config)
    if not target:
        raise click.UsageError("no database name given, and none configured (db_name / $ODOO_DB).")

    from odoo.service import db as odoo_db

    exists = odoo_db.exp_db_exist(target)
    if exists and _has_odoo_schema(target):
        console.print(f"==> '{target}' already exists — migrating instead of installing.")
        _migrate_one(target, no_backup)
        return

    modules = _read_modules_file(Path(modules_file))
    console.print(f"==> Provisioning '{target}' with: base,{','.join(modules)}" if modules else f"==> Provisioning '{target}' with: base")
    if not exists:
        # Registry.new() (what run_module_update calls) opens a cursor
        # against an existing database -- it does not create one. odoo-bin's
        # own server startup auto-creates a missing -d target before ever
        # reaching load_modules() (odoo/cli/server.py); do the same here.
        # A database that already exists but has no Odoo schema yet (e.g. a
        # bare `CREATE DATABASE`, or Postgres's own pre-created default
        # database) skips straight to run_module_update below instead --
        # _create_empty_database() raises DatabaseExists if called on it.
        odoo_db._create_empty_database(target)
    with MigrationProgress(target, console):
        odooenv.run_module_update(target, install=["base"] + modules)
    console.print(f"[green]✓[/] provisioned '{target}'")


def _has_odoo_schema(db_name: str) -> bool:
    """A database can exist in Postgres without ever having been Odoo-
    initialized (a bare CREATE DATABASE, or the default database Postgres
    itself pre-creates) -- exp_db_exist only confirms a connection succeeds,
    not that -i base has ever run. Same check load_modules() itself makes
    (odoo.modules.db.is_initialized) before deciding whether it can proceed
    without -i/-u."""
    import odoo.sql_db
    import odoo.tools.sql

    with odoo.sql_db.db_connect(db_name).cursor() as cr:
        return odoo.tools.sql.table_exists(cr, "ir_module_module")


@db_group.command("upgrade")
@click.argument("modules")
@click.argument("database", required=False)
@click.option("--all", "all_dbs", is_flag=True, help="Upgrade on every database matching dbfilter.")
@click.pass_context
def db_upgrade(ctx, modules, database, all_dbs):
    """Upgrade MODULES (comma-separated) on one, several, or --all databases."""
    odoo_config = _load(ctx)
    targets = odooenv.list_target_databases(database, all_dbs, odoo_config)
    module_list = [m.strip() for m in modules.split(",") if m.strip()]
    _run_multi(targets, lambda name: _upgrade_one(name, module_list))


def _upgrade_one(db_name: str, modules: list[str]) -> None:
    with MigrationProgress(db_name, console):
        odooenv.run_module_update(db_name, update=modules)


@db_group.command("migrate")
@click.argument("database", required=False)
@click.option("--all", "all_dbs", is_flag=True, help="Migrate every database matching dbfilter.")
@click.option("--no-backup", is_flag=True, help="Skip the automatic pre-migrate backup.")
@click.pass_context
def db_migrate(ctx, database, all_dbs, no_backup):
    """Upgrade every installed module (-u all), with an automatic backup first."""
    odoo_config = _load(ctx)
    targets = odooenv.list_target_databases(database, all_dbs, odoo_config)
    _run_multi(targets, lambda name: _migrate_one(name, no_backup))


def _migrate_one(db_name: str, no_backup: bool) -> None:
    if not no_backup:
        console.print(f"==> backing up '{db_name}' before migrating…")
        _backup_one(db_name, None)
    with MigrationProgress(db_name, console):
        odooenv.run_module_update(db_name, update=["all"])


def _run_multi(
    items: list,
    run_one: Callable[..., None],
    label: Callable = str,
) -> None:
    """Run `run_one(item)` for each item, collecting (not aborting on) a
    failure unless there's only one item -- matches `bench`'s
    backup-all-sites posture: one bad database shouldn't stop the rest of
    the batch. `label` renders an item for the summary (a plain db-name
    string by default; project_restore passes a (db, path) pair through and
    labels it by the db name alone)."""
    if not items:
        raise click.UsageError("no matching databases.")
    failures = []
    fail_fast = len(items) == 1
    for item in items:
        try:
            run_one(item)
        except Exception as exc:
            failures.append((label(item), exc))
            if fail_fast:
                raise
    if failures:
        console.print(f"[bold red]{len(failures)}/{len(items)} database(s) failed:[/]")
        for name, exc in failures:
            console.print(f"  [red]✗[/] {name}: {exc}")
        sys.exit(1)


@db_group.command("duplicate")
@click.argument("source")
@click.argument("dest")
@click.option("--neutralize", is_flag=True, help="Disable outgoing mail/cron on the copy.")
@click.pass_context
def db_duplicate(ctx, source, dest, neutralize):
    """Duplicate SOURCE to DEST (schema + filestore)."""
    _load(ctx)
    from odoo.service import db as odoo_db

    odoo_db.exp_duplicate_database(source, dest, neutralize_database=neutralize)
    console.print(f"[green]✓[/] duplicated '{source}' → '{dest}'")


@db_group.command("rename")
@click.argument("old_name")
@click.argument("new_name")
@click.pass_context
def db_rename(ctx, old_name, new_name):
    """Rename a database (and its filestore)."""
    _load(ctx)
    from odoo.service import db as odoo_db

    odoo_db.exp_rename(old_name, new_name)
    console.print(f"[green]✓[/] renamed '{old_name}' → '{new_name}'")


@db_group.command("drop")
@click.argument("db_name")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def db_drop(ctx, db_name, yes):
    """Drop a database and its filestore."""
    _load(ctx)
    if not yes:
        click.confirm(f"Drop '{db_name}' and its filestore? This cannot be undone.", abort=True)
    from odoo.service import db as odoo_db

    if not odoo_db.exp_drop(db_name):
        raise click.ClickException(f"'{db_name}' does not exist -- nothing to drop.")
    console.print(f"[green]✓[/] dropped '{db_name}'")


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TiB"


#: OCA auto_backup's own extension convention (models/db_backup.py:261-271
#: in the millrun/modules/server-tools/auto_backup source): a zip-format dump
#: (dump.sql + filestore/ + manifest.json -- the same odoo.service.db.dump_db
#: output either producer writes) is named "*.dump.zip"; the plain
#: `pg_dump -Fc` custom format (no filestore) is named "*.dump". Adopted
#: verbatim, including dropping the db name from the filename (the per-db
#: folder already provides that, matching auto_backup's own default folder
#: too), so backups from this CLI and from an installed auto_backup module
#: are interchangeable in the same folder under one naming scheme.
def _backup_extension(fmt: str) -> str:
    return "dump.zip" if fmt == "zip" else "dump"


def _backup_path(db_name: str, out_dir: str | None, fmt: str) -> Path:
    import odoo.tools

    base = Path(out_dir) if out_dir else Path(odoo.tools.config["data_dir"]) / "backups" / db_name
    base.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")  # noqa: DTZ005 -- a local-time filename stamp, not a stored timestamp
    return base / f"{stamp}.{_backup_extension(fmt)}"


def _prune_backups_by_age(directory: Path, fmt: str, keep_days: int) -> None:
    """auto_backup's own retention algorithm (cleanup(), models/db_backup.py:
    216-239): the zero-padded timestamp filename sorts lexicographically the
    same as chronologically, so a threshold *filename string* -- "now minus
    keep_days" formatted the same way -- can be compared directly against
    each backup's name with no stat() calls."""
    if keep_days <= 0:
        return
    ext = _backup_extension(fmt)
    threshold = (dt.datetime.now() - dt.timedelta(days=keep_days)).strftime("%Y_%m_%d_%H_%M_%S") + "." + ext  # noqa: DTZ005
    for stale in sorted(directory.glob(f"*.{ext}")):
        if stale.name < threshold:
            stale.unlink()
            console.print(f"  [dim]pruned {stale.name}[/]")


def _backup_one(db_name: str, out_dir: str | None, fmt: str = "zip", keep_days: int = 0) -> Path:
    from odoo.service import db as odoo_db

    dest = _backup_path(db_name, out_dir, fmt)
    start = time.monotonic()
    with open(dest, "wb") as stream:
        odoo_db.dump_db(db_name, stream, backup_format=fmt)
    elapsed = time.monotonic() - start
    console.print(f"[green]✓[/] {db_name} → {dest}  ({_human_size(dest.stat().st_size)}, {elapsed:.1f}s)")
    if keep_days:
        _prune_backups_by_age(dest.parent, fmt, keep_days)
    return dest


@db_group.command("backup")
@click.argument("database", required=False)
@click.option("--all", "all_dbs", is_flag=True)
@click.option(
    "--path",
    "out_dir",
    type=click.Path(),
    default=None,
    help="Directory for the backup (default: <data_dir>/backups/<db>/).",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["zip", "dump"]),
    default="zip",
    show_default=True,
    help="zip = schema + filestore (Odoo's own Database Manager format); dump = pg_dump custom format, no filestore.",
)
@click.option(
    "--keep-days",
    "keep_days",
    type=int,
    default=0,
    show_default=True,
    help="Prune backups older than this many days for this database (0 = keep forever).",
)
@click.pass_context
def db_backup(ctx, database, all_dbs, out_dir, fmt, keep_days):
    """Dump one, several, or --all databases."""
    odoo_config = _load(ctx)
    targets = odooenv.list_target_databases(database, all_dbs, odoo_config)
    for name in targets:
        _backup_one(name, out_dir, fmt, keep_days)


def _restore_one(db_name: str, backup_path: str, force: bool, neutralize: bool) -> None:
    from odoo.service import db as odoo_db

    path = Path(backup_path)
    console.print("[cyan][1/3][/] located backup file")
    console.print(f"      {path}  ({_human_size(path.stat().st_size)})")

    if odoo_db.exp_db_exist(db_name):
        if not force:
            raise click.ClickException(f"database '{db_name}' already exists — pass --force to overwrite (drop it first).")
        console.print(f"==> dropping existing '{db_name}' (--force)")
        odoo_db.exp_drop(db_name)

    console.print("[cyan][2/3][/] restoring database + filestore")
    odoo_db.restore_db(db_name, str(path), neutralize_database=neutralize)
    console.print("[cyan][3/3][/] done")
    console.print(f"[green]✓[/] restored '{db_name}' from {path}")


@db_group.command("restore")
@click.argument("db_name")
@click.argument("backup_path", type=click.Path(exists=True))
@click.option("--force", is_flag=True, help="Overwrite DB_NAME if it already exists.")
@click.option("--neutralize", is_flag=True, help="Disable outgoing mail/cron on the restored copy.")
@click.pass_context
def db_restore(ctx, db_name, backup_path, force, neutralize):
    """Restore BACKUP_PATH into DB_NAME."""
    _load(ctx)
    _restore_one(db_name, backup_path, force, neutralize)
