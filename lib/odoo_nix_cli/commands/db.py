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

import contextlib
import datetime as dt
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .. import migrate_plan, odooenv, remote
from ..progress import MigrationProgress

console = Console()


def say(*objects, **kwargs) -> None:
    """console.print without wrapping. Off a terminal (journald, CI) rich
    wraps at 80 columns, which splits one log line -- a migration plan, a
    snapshot path -- into several."""
    console.print(*objects, soft_wrap=True, **kwargs)


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

    if odoo_db.exp_db_exist(target) and _has_odoo_schema(target):
        console.print(f"==> '{target}' already exists — migrating instead of installing.")
        _migrate_one(target, MigrateOptions(snapshot="none" if no_backup else "zip"))
        return
    _provision_one(target, Path(modules_file))


def _provision_one(target: str, modules_file: Path) -> None:
    from odoo.service import db as odoo_db

    exists = odoo_db.exp_db_exist(target)
    modules = _read_modules_file(modules_file)
    say(f"==> Provisioning '{target}' with: base,{','.join(modules)}" if modules else f"==> Provisioning '{target}' with: base")
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
    # A fresh install is the checksum baseline: without it, the first
    # migrate after provisioning would update every module all over again.
    _record_success(target)
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
@click.option(
    "--full",
    is_flag=True,
    help="Update every installed module (-u all) instead of only the ones whose code or version changed.",
)
@click.option(
    "--if-needed",
    is_flag=True,
    help="Do nothing when this build ($ODOO_NIX_BUILD) already migrated the database.",
)
@click.option("--also", default="", help="Comma-separated modules to update even when unchanged.")
@click.option(
    "--snapshot",
    type=click.Choice(["zip", "dump", "none"]),
    default="zip",
    show_default=True,
    help="Pre-migrate snapshot: zip = schema + filestore; dump = pg_dump custom format, schema only; none = no snapshot.",
)
@click.option("--no-backup", is_flag=True, help="Same as --snapshot none.")
@click.option(
    "--keep",
    type=int,
    default=0,
    show_default=True,
    help="Keep only the N newest pre-migrate snapshots of each database (0 = keep all).",
)
@click.option(
    "--rollback",
    is_flag=True,
    help="If the update fails, restore the database from the pre-migrate snapshot before exiting non-zero.",
)
@click.option(
    "--provision-if-empty",
    is_flag=True,
    help="Install base (+ --modules-file) when the database has no Odoo schema, instead of skipping it.",
)
@click.option("--modules-file", default="modules.txt", show_default=True, type=click.Path())
@click.pass_context
def db_migrate(
    ctx,
    database,
    all_dbs,
    full,
    if_needed,
    also,
    snapshot,
    no_backup,
    keep,
    rollback,
    provision_if_empty,
    modules_file,
):
    """Update the modules whose code or version changed, with a snapshot first.

    Change detection compares each module's content checksum with the one
    stored when this database was last migrated (OCA module_auto_update's
    algorithm and parameter, so the three tools agree), and its recorded
    version with its manifest. A database that has never recorded checksums
    is updated in full once, as a baseline.
    """
    odoo_config = _load(ctx)
    if rollback and (no_backup or snapshot == "none"):
        raise click.UsageError("--rollback needs a snapshot to roll back to (drop --no-backup / --snapshot none).")
    options = MigrateOptions(
        full=full,
        if_needed=if_needed,
        also=[m.strip() for m in also.split(",") if m.strip()],
        snapshot="none" if no_backup else snapshot,
        keep=keep,
        rollback=rollback,
        provision_if_empty=provision_if_empty,
        modules_file=Path(modules_file),
    )
    targets = odooenv.list_target_databases(database, all_dbs, odoo_config)
    _run_multi(targets, lambda name: _migrate_one(name, options))


@dataclass
class MigrateOptions:
    full: bool = False
    if_needed: bool = False
    also: list[str] = field(default_factory=list)
    snapshot: str = "zip"
    keep: int = 0
    rollback: bool = False
    provision_if_empty: bool = False
    modules_file: Path = Path("modules.txt")


def _current_build() -> str | None:
    """The store path of the build doing the migration -- the value
    migrate_plan records as odoo_nix.migrated_build. lib/cli.nix sets it only
    for store-assembled (production) builds: a dev shell runs editable code
    whose store path does not change when the code does, so it gets no fast
    path and always runs change detection."""
    return os.environ.get("ODOO_NIX_BUILD") or None


def _migrate_one(db_name: str, options: MigrateOptions | None = None) -> None:
    options = options or MigrateOptions()
    from odoo.service import db as odoo_db

    if not (odoo_db.exp_db_exist(db_name) and _has_odoo_schema(db_name)):
        if options.provision_if_empty:
            _provision_one(db_name, options.modules_file)
            return
        # Installing or restoring a database is an operator's decision, not a
        # deploy's: say what is missing and succeed, so one uninitialised
        # database does not fail every start of the service around it.
        say(
            f"==> '{db_name}' has no Odoo schema — not initialised; skipping migrate. Provision or restore it, then restart."
        )
        return

    build = _current_build()
    with _migration_lock(db_name):
        import odoo.sql_db

        with odoo.sql_db.db_connect(db_name).cursor() as cr:
            if options.if_needed and build and migrate_plan.get_param(cr, migrate_plan.PARAM_MIGRATED_BUILD) == build:
                say(f"[green]✓[/] {db_name}: already migrated by this build — up to date")
                return
            plan = migrate_plan.build_plan(cr, full=options.full, also=options.also)

        say(f"==> {db_name}: {plan.describe()}")
        if plan.missing:
            say(
                f"    [yellow]installed but not on the addons path (left alone):[/] {', '.join(plan.missing)}"
            )
        if plan.empty:
            _record_success(db_name)
            say(f"[green]✓[/] {db_name}: up to date")
            return

        snap = None
        if options.snapshot != "none":
            say(f"==> snapshotting '{db_name}' before migrating…")
            snap = _snapshot(db_name, options.snapshot)

        try:
            with MigrationProgress(db_name, console):
                odooenv.run_module_update(db_name, update=plan.update)
        except Exception:
            if options.rollback and snap is not None:
                _rollback(db_name, snap)
            raise

        _record_success(db_name)
        if snap is not None and options.keep:
            _prune_snapshots(snap.parent, options.keep)


def _record_success(db_name: str) -> None:
    import odoo.sql_db

    with odoo.sql_db.db_connect(db_name).cursor() as cr:
        migrate_plan.record_success(cr, _current_build())
        cr.commit()


# ── safety net: lock, snapshot, rollback ─────────────────────────────────────


def _raw_connect(db_name: str):
    """A plain psycopg2 connection with Odoo's own connection settings --
    for the operations Odoo's pooled Cursor is the wrong tool for: holding a
    session-level lock for the whole run, and dropping/creating a database."""
    import psycopg2
    import odoo.sql_db

    _name, info = odoo.sql_db.connection_info_for(db_name)
    conn = psycopg2.connect(**info)
    conn.autocommit = True
    return conn


@contextlib.contextmanager
def _migration_lock(db_name: str):
    """A session advisory lock, so a manual `odoo db migrate` and a deploy
    cannot update the same database at once. Taken in the `postgres`
    database, not the target: advisory locks are per-database, and holding a
    session open in the target would stop a rollback from dropping it."""
    try:
        conn = _raw_connect("postgres")
    except Exception as exc:  # noqa: BLE001 -- the lock is a guard, not a precondition
        say(f"[yellow]warning:[/] could not take the migration lock ({exc}); continuing without it")
        yield
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (f"odoo_nix.migrate:{db_name}",))
            if not cur.fetchone()[0]:
                raise click.ClickException(f"another migration of '{db_name}' is already running")
        yield
    finally:
        conn.close()


def _snapshot(db_name: str, fmt: str) -> Path:
    """A pre-migrate snapshot in its own folder next to the regular backups,
    so count-based pruning (--keep) never touches a backup somebody took on
    purpose. Verified before anything relies on it: dump_db() streams the
    custom format straight from a pg_dump pipe and never checks its exit
    status, so a failed dump would otherwise leave a truncated safety net."""
    import odoo.tools

    directory = Path(odoo.tools.config["data_dir"]) / "backups" / db_name / "premigrate"
    snap = _backup_one(db_name, str(directory), fmt)
    if fmt == "dump":
        from odoo.tools.misc import exec_pg_environ, find_pg_tool

        check = subprocess.run(
            [find_pg_tool("pg_restore"), "--list", str(snap)],
            env=exec_pg_environ(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if check.returncode != 0 or snap.stat().st_size == 0:
            snap.unlink(missing_ok=True)
            raise click.ClickException(f"pre-migrate snapshot of '{db_name}' is unreadable: {check.stderr.strip()}")
    return snap


def _prune_snapshots(directory: Path, keep: int) -> None:
    snaps = sorted(p for p in directory.iterdir() if p.is_file())
    for stale in snaps[:-keep]:
        stale.unlink()
        say(f"  [dim]pruned {stale.name}[/]")


def _rollback(db_name: str, snap: Path) -> None:
    """Put the database back exactly as the snapshot has it.

    Not odoo.service.db.exp_drop + restore_db: exp_drop also deletes the
    filestore, which a schema-only snapshot cannot bring back (and the
    filestore needs no rollback -- attachments are content-addressed and
    only ever added), and restore_db loads a registry of the NEW code against
    the restored OLD schema before returning, which is the very mismatch a
    failed migration leaves behind. So: drop the database only, recreate it
    with the same encoding and collation, load the snapshot, and stop there.
    """
    from psycopg2 import sql

    import odoo.sql_db
    from odoo.modules.registry import Registry
    from odoo.tools.misc import exec_pg_environ, find_pg_tool

    say(f"[bold red]==> rolling '{db_name}' back to {snap}[/]")
    Registry.delete(db_name)
    odoo.sql_db.close_db(db_name)

    conn = _raw_connect("postgres")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_encoding_to_char(encoding), datcollate, datctype FROM pg_database WHERE datname = %s",
                (db_name,),
            )
            encoding, collate, ctype = cur.fetchone()
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                (db_name,),
            )
            cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(db_name)))
            cur.execute(
                sql.SQL("CREATE DATABASE {} ENCODING {} LC_COLLATE {} LC_CTYPE {} TEMPLATE template0").format(
                    sql.Identifier(db_name), sql.Literal(encoding), sql.Literal(collate), sql.Literal(ctype)
                )
            )
    finally:
        conn.close()

    env = exec_pg_environ()
    with tempfile.TemporaryDirectory() as tmp:
        if zipfile.is_zipfile(snap):
            with zipfile.ZipFile(snap) as zf:
                zf.extract("dump.sql", tmp)
            cmd = [find_pg_tool("psql"), "-q", "-v", "ON_ERROR_STOP=1", f"--dbname={db_name}", "-f", os.path.join(tmp, "dump.sql")]
        else:
            cmd = [find_pg_tool("pg_restore"), "--no-owner", "--exit-on-error", f"--dbname={db_name}", str(snap)]
        result = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        say(
            f"[bold red]✗ rollback of '{db_name}' FAILED — the database may be incomplete. "
            f"Snapshot preserved at {snap}.[/]\n{result.stderr.strip()}"
        )
        return
    say(f"[bold red]✗ {db_name}: migration failed; database restored from {snap}[/]")


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
#: in the OCA server-tools auto_backup source): a zip-format dump
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
    say(f"[green]✓[/] {db_name} → {dest}  ({_human_size(dest.stat().st_size)}, {elapsed:.1f}s)")
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


def _dev_shell() -> bool:
    """True inside an odoo-nix dev shell (the only place Nix sets
    $ODOO_NIX_DEVGUARD, to 1/0 for devguard.enable), False on a server."""
    return os.environ.get("ODOO_NIX_DEVGUARD") is not None


def _require_devguard() -> None:
    """Refuse to put a production database on a machine where nothing stops it
    reaching production, unless explicitly told otherwise.

    Nix-time, not $ODOO_DEVGUARD_ENABLED: `devguard.enable = false` is a
    persistent property of the project, so every later `devenv up` is unguarded
    too. A per-command disable is scoped to that command and is nobody's
    problem.
    """
    if os.environ.get("ODOO_NIX_DEVGUARD") == "0" and os.environ.get("ODOO_NIX_RESTORE_ALLOW_UNGUARDED") != "1":
        raise click.ClickException(
            "refusing to restore: odoo-nix.devguard.enable is false in this project, so nothing stops the "
            "restored database from mailing customers, writing to production storage or running its crons. "
            "Enable the devguard, or set ODOO_NIX_RESTORE_ALLOW_UNGUARDED=1 to restore anyway."
        )


def _attachments_root() -> Path:
    return Path(
        os.environ.get("ODOO_NIX_ATTACHMENTS_DIR")
        or odooenv.repo_root() / ".devenv" / "state" / "odoo-nix" / "attachments"
    )


def _restore_one(db_name: str, backup_path: str, force: bool, neutralize: bool, localize: bool = True) -> None:
    from odoo.service import db as odoo_db

    _require_devguard()
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
    if localize and _dev_shell():
        # Whatever the dump's storage records say, a development copy never
        # keeps a remote store (devguard's objectstore guard would refuse to
        # open it anyway). The remote restore does this itself, after mirroring.
        _localize_storages(db_name, _remote_storages(db_name), _attachments_root())


#: Storages the localize step must leave alone: already local, or the backup
#: destination itself (its options are $VAR references, never secrets).
_KEEP_STORAGE_PROTOCOLS = ("file", "odoofs", "memory")
_KEEP_STORAGE_CODES = ("odoo_backup",)


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def _reexec_with_secrets() -> None:
    """Credentials are decrypted per command, never held in the shell: when
    they are not in the environment, re-run this very command under the
    dev-shell wrapper that decrypts the backup-access secret first."""
    wrapper = os.environ.get("ODOO_NIX_WITH_SECRETS")
    if remote.has_credentials() or not wrapper or os.environ.get("ODOO_NIX_SECRETS_LOADED"):
        return
    console.print("[dim]decrypting backup-access secret...[/]")
    os.execv(wrapper, [wrapper, "odoo", *sys.argv[1:]])  # noqa: S606


def _restore_cache_dir() -> Path:
    state = os.environ.get("DEVENV_STATE")
    base = Path(state) if state else odooenv.repo_root() / ".devenv" / "state"
    return base / "odoo-nix" / "restore"


def _remote_storages(db_name: str) -> list[dict]:
    """fs.storage rows of the restored database that point off-machine."""
    from odoo.sql_db import db_connect

    with db_connect(db_name).cursor() as cr:
        cr.execute("SELECT to_regclass('fs_storage') IS NOT NULL")
        if not cr.fetchone()[0]:
            return []
        cr.execute("SELECT id, code, protocol, directory_path FROM fs_storage ORDER BY id")
        return [
            {"id": i, "code": c, "protocol": p, "directory_path": d}
            for i, c, p, d in cr.fetchall()
            if p not in _KEEP_STORAGE_PROTOCOLS and c not in _KEEP_STORAGE_CODES
        ]


def _localize_storages(db_name: str, storages: list[dict], root: Path) -> None:
    """Point every remote fs.storage at a local directory.

    A restored copy carries production's object-store settings -- credentials
    included -- and would otherwise write new attachments into the production
    bucket. `store_fname` is `<code>://<path>`, so files mirrored under the new
    directory resolve unchanged.
    """
    from odoo.sql_db import db_connect

    with db_connect(db_name).cursor() as cr:
        for st in storages:
            target = root / st["code"]
            target.mkdir(parents=True, exist_ok=True)
            cr.execute(
                "UPDATE fs_storage SET protocol = 'file', options = '{}', "
                "eval_options_from_env = false, directory_path = %s, base_url = '' WHERE id = %s",
                (str(target), st["id"]),
            )
            console.print(f"  [dim]storage '{st['code']}' ({st['protocol']}) → {target}[/]")


def _restore_remote(db_name, source_db, at, force, neutralize, use_cache, attachments, list_only) -> None:
    _reexec_with_secrets()
    prefix = os.environ.get("ODOO_NIX_RESTORE_PREFIX")
    if prefix and not os.environ.get("BACKUPS_PREFIX"):
        os.environ["BACKUPS_PREFIX"] = prefix
    try:
        with remote.store() as base:
            if list_only:
                for name, size in remote.list_backups(base, source_db):
                    say(f"{name}  {_human_size(size)}")
                return
            console.print(f"[cyan]fetching[/] newest backup of '{source_db}'" if not at else f"[cyan]fetching[/] '{source_db}' @ {at}")
            path = remote.fetch(base, source_db, _restore_cache_dir(), at, use_cache)
            _restore_one(db_name, str(path), force, neutralize, localize=False)

            storages = _remote_storages(db_name)
            root = _attachments_root()
            for st in storages:
                src = (st["directory_path"] or "").format(db_name=source_db)
                if attachments == "mirror" and src and "$" not in src and not remote.is_local():
                    console.print(f"[cyan]mirroring[/] attachments '{st['code']}' from {src}")
                    remote.mirror(src, root / st["code"])
                elif attachments == "mirror":
                    console.print(f"[yellow]![/] not mirroring '{st['code']}' ({src or 'no directory path'})")
            _localize_storages(db_name, storages, root)
    except remote.RemoteError as exc:
        raise click.ClickException(str(exc)) from exc


@db_group.command("restore")
@click.argument("db_name")
@click.argument("backup_path", type=click.Path(exists=True), required=False)
@click.option("--force", is_flag=True, help="Overwrite DB_NAME if it already exists.")
@click.option(
    "--neutralize/--no-neutralize",
    default=None,
    help="Disable outgoing mail/cron on the restored copy. Default: on in the dev shell (restore.neutralize), off on a server.",
)
@click.option("--from", "source_db", default=None, help="Remote restore: source database folder (default: DB_NAME).")
@click.option("--at", default=None, help="Remote restore: newest backup at or before this timestamp prefix (YYYY_MM_DD_HH_MM_SS).")
@click.option("--list", "list_only", is_flag=True, help="Remote restore: list available backups and exit.")
@click.option("--no-cache", is_flag=True, help="Remote restore: download again even if cached.")
@click.option(
    "--attachments/--no-attachments",
    default=None,
    help="Remote restore: mirror object-store attachments locally (default: per odoo-nix.restore.attachments).",
)
@click.pass_context
def db_restore(ctx, db_name, backup_path, force, neutralize, source_db, at, list_only, no_cache, attachments):
    """Restore BACKUP_PATH into DB_NAME -- or, with no path, the newest backup
    from the remote store (S3 credentials from the backup-access secret)."""
    if backup_path:
        _load(ctx)
        if neutralize is None:
            # Off on a server (the variable is only set in the dev shell), on
            # in the dev shell: a dump you were handed is as live as one you fetched.
            neutralize = _env_flag("ODOO_NIX_RESTORE_NEUTRALIZE", False)
        _restore_one(db_name, backup_path, force, neutralize)
        return
    source_db = source_db or os.environ.get("ODOO_NIX_RESTORE_SOURCE_DB") or db_name
    if neutralize is None:
        neutralize = _env_flag("ODOO_NIX_RESTORE_NEUTRALIZE", True)
    if attachments is None:
        mode = os.environ.get("ODOO_NIX_RESTORE_ATTACHMENTS", "none")
    else:
        mode = "mirror" if attachments else "none"
    if not list_only:
        _load(ctx)
    _restore_remote(db_name, source_db, at, force, neutralize, not no_cache, mode, list_only)
