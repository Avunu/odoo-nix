"""The `odoo` CLI's own command tree: db / module / project / shell.

Everything else is passthrough, handled in __main__.py before this module is
even imported (see there for why).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import click

from .. import odoo_db, odooenv, testrun
from .db import db_group
from .module import module_group
from .project import project_group

_TEST_BROWSERS = (
    "google-chrome",
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
)


@click.group()
@click.option(
    "-c",
    "--config",
    "config_path",
    default=None,
    help="Path to odoo.conf (default: $ODOO_RC, then ./odoo.conf).",
)
@click.option(
    "-d",
    "--database",
    "database",
    default=None,
    help="Default database name for subcommands that take one.",
)
@click.option(
    "--db-host",
    "db_host",
    default=None,
    help="Override odoo.conf's db_host for this run.",
)
@click.option(
    "--db-port",
    "db_port",
    default=None,
    help="Override odoo.conf's db_port for this run.",
)
@click.option(
    "--db-user",
    "db_user",
    default=None,
    help="Override odoo.conf's db_user for this run.",
)
@click.option(
    "--db-password",
    "db_password",
    default=None,
    help="Override odoo.conf's db_password for this run.",
)
@click.pass_context
def cli(ctx, config_path, database, db_host, db_port, db_user, db_password):
    """odoo-nix's site-maintenance CLI: database lifecycle, module/OCA
    management, and workspace updates -- everything else (server, shell,
    scaffold, …) passes straight through to odoo-bin."""
    ctx.obj = {
        "config": config_path,
        "database": database,
        "db_host": db_host,
        "db_port": db_port,
        "db_user": db_user,
        "db_password": db_password,
    }


cli.add_command(db_group)
cli.add_command(module_group)
cli.add_command(project_group)


@cli.command(
    "ui", context_settings={"ignore_unknown_options": True, "help_option_names": []}
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def ui_cmd(args):
    """The interactive menu: the stack, every command, and the OCA store. A
    bare `odoo` at a terminal in the dev shell opens it too."""
    from ..__main__ import tui

    tui(list(args))


@cli.command("shell")
@click.argument("database", required=False)
@click.pass_context
def shell_cmd(ctx, database):
    """Odoo's Python REPL against a database (replaces the old odoo-shell)."""
    conf_path = odooenv.resolve_config_path(ctx.obj.get("config"))
    db_args = odooenv.db_connection_args(ctx.obj)
    odoo_config = odooenv.load_config(conf_path, db_args)
    target = odooenv.resolve_database(database or ctx.obj.get("database"), odoo_config)
    if not target:
        raise click.UsageError(
            "no database given, and none configured (db_name / $ODOO_NIX_DB)."
        )
    raw = odooenv.require_env("ODOO_NIX_RAW_ODOO")
    # A REPL serves nothing: no workers and no HTTP. Under a server conf with
    # workers > 0, `odoo-bin shell` otherwise starts the prefork server, which
    # binds http_port -- taken by the running service, so the shell dies with
    # "Address already in use".
    os.execv(
        raw,
        [
            raw,
            "shell",
            "-c",
            str(conf_path),
            "-d",
            target,
            "--workers=0",
            "--no-http",
            *db_args,
        ],
    )


@cli.command("test")
@click.argument("modules", required=False)
@click.argument("database", required=False)
@click.option(
    "--all",
    "all_",
    is_flag=True,
    help="Test every installable addon of this repository (custom/, or the addons "
    "directory in addons mode) but the [[tool.odoo-nix.untested]] ones. A lone "
    "argument is then DATABASE.",
)
@click.option(
    "--fresh-db",
    is_flag=True,
    help="Install the addons (-i) into a new database, odoo_nix_test_<pid>, dropped "
    "afterwards; without it the addons are updated (-u) on DATABASE.",
)
@click.option(
    "--keep-db",
    is_flag=True,
    help="With --fresh-db: keep the database after the run.",
)
@click.option(
    "--coverage",
    "rcfile",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Measure the run with coverage.py and this rcfile (tools/pyproject.toml), "
    "into $COVERAGE_FILE (default: .odoo-nix/coverage/.coverage).",
)
@click.option(
    "--log",
    "log_path",
    type=click.Path(dir_okay=False),
    default=None,
    help="Also write Odoo's output to this file.",
)
@click.pass_context
def test_cmd(ctx, modules, database, all_, fresh_db, keep_db, rcfile, log_path):
    """Run MODULES' Odoo tests (comma-separated) -- and refuse to call a
    skipped browser tour a pass (replaces the old odoo-test script).

    MODULES are updated (-u) on DATABASE (default: the configured one), or with
    --fresh-db installed into a new database; --all tests every installable
    addon of this repository instead. The exit code is Odoo's.

    Odoo degrades quietly when tour prerequisites are missing: no
    `websocket` module, or no Chrome on PATH, and every HttpCase is
    *skipped*. The summary line reports skips and passes identically, so a
    broken environment reads as a green run -- this checks the
    prerequisites up front and refuses to run rather than let that happen.
    """
    root = odooenv.repo_root()
    if all_:
        if modules and database:
            raise click.UsageError(
                "--all tests every addon: give at most DATABASE, not MODULES."
            )
        database = database or modules
        try:
            names = testrun.all_modules(root, os.environ)
        except testrun.OdooTestError as exc:
            raise click.ClickException(str(exc)) from exc
    elif modules:
        names = [m.strip() for m in modules.split(",") if m.strip()]
    else:
        raise click.UsageError("give MODULES (comma-separated), or --all.")
    if keep_db and not fresh_db:
        raise click.UsageError("--keep-db keeps the database --fresh-db makes.")
    if fresh_db and database:
        raise click.UsageError(
            f"--fresh-db makes its own database: drop {database!r}, or drop --fresh-db."
        )

    conf_path = odooenv.resolve_config_path(ctx.obj.get("config"))
    db_args = odooenv.db_connection_args(ctx.obj)
    odoo_config = odooenv.load_config(conf_path, db_args)
    if fresh_db:
        target = f"odoo_nix_test_{os.getpid()}"
        # The run has its own database, so a db_name odoo.conf pins (the dev
        # shell's dbName) names nothing here -- and through 19.0 it would stop
        # the drop afterwards: exp_drop refuses any name outside list_dbs(),
        # which a pinned db_name (and no dbfilter) narrows to that one name.
        odooenv.clear_db_name(odoo_config)
        if odoo_db.exists(target):
            raise click.ClickException(
                f"database {target!r} already exists (a test database kept with --keep-db?): drop it first."
            )
    else:
        target = odooenv.resolve_database(
            database or ctx.obj.get("database"), odoo_config
        )
        if not target:
            raise click.UsageError(
                "no database given, and none configured (db_name / $ODOO_NIX_DB)."
            )

    _check_tour_prerequisites()

    env = dict(os.environ)
    data_file = None
    if rcfile:
        env.update(testrun.coverage_env(root, Path(rcfile), os.environ))
        data_file = Path(env["COVERAGE_FILE"])
        data_file.parent.mkdir(parents=True, exist_ok=True)
        # A fresh measurement: data a former run left would be combined in.
        for stale in testrun.coverage_files(data_file):
            stale.unlink()

    raw = odooenv.require_env("ODOO_NIX_RAW_ODOO")
    argv = testrun.odoo_argv(
        raw,
        conf_path,
        target,
        names,
        fresh=fresh_db,
        major=_odoo_major(),
        db_args=db_args,
    )
    how = "installing into a new database" if fresh_db else "updating"
    click.echo(
        f"==> Testing {','.join(names)} on '{target}' ({how}; tags: {testrun.tags_for(names)})…"
    )
    try:
        code = testrun.run(argv, env, Path(log_path) if log_path else None)
    finally:
        if fresh_db and not keep_db:
            _drop_test_database(target)
    if fresh_db and keep_db:
        click.echo(f"==> kept the test database '{target}'")
    if code == 0 and data_file is not None and not testrun.coverage_files(data_file):
        raise click.ClickException(
            f"no coverage data was written to {data_file}: this Odoo has no coverage hook "
            "(lib/raw-odoo.nix, the dev shell's)."
        )
    if code < 0:
        # Popen's -N for a signal; the shell's 128+N is what callers recognise.
        click.echo(f"✗ odoo test: Odoo was killed by signal {-code}", err=True)
        sys.exit(128 - code)
    if code:
        click.echo(f"✗ odoo test: Odoo exited {code}", err=True)
    sys.exit(code)


def _check_tour_prerequisites() -> None:
    missing = []
    if importlib.util.find_spec("websocket") is None:
        missing.append(
            "the 'websocket-client' package (add it to [dependency-groups].dev, then re-lock)"
        )
    browser = next((b for b in _TEST_BROWSERS if shutil.which(b)), None)
    if browser is None:
        missing.append(
            "a headless browser (set odoo-nix's testBrowser, or put one on PATH)"
        )

    if missing:
        click.echo(
            "✗ Browser tours cannot run here, and Odoo would skip them silently:",
            err=True,
        )
        for m in missing:
            click.echo(f"  - {m}", err=True)
        click.echo(
            "\n  Refusing to run, because a skipped tour is reported exactly like a passing one. "
            "Set ODOO_NIX_TEST_ALLOW_SKIP=1 to run anyway.",
            err=True,
        )
        if os.environ.get("ODOO_NIX_TEST_ALLOW_SKIP") != "1":
            sys.exit(1)
    else:
        click.echo(f"==> tours enabled (browser: {browser})")


def _odoo_major() -> int:
    import odoo.release

    return int(odoo.release.version_info[0])


def _drop_test_database(name: str) -> None:
    try:
        dropped = odoo_db.drop(name)
    except Exception as exc:  # noqa: BLE001 -- reported; the run's exit code stands
        click.echo(f"✗ could not drop the test database '{name}': {exc}", err=True)
        return
    if dropped:
        click.echo(f"==> dropped the test database '{name}'")
    else:
        click.echo(
            f"✗ did not drop the test database '{name}': Odoo does not list it "
            "(`odoo db list`; drop it with `odoo db drop` if it is there)",
            err=True,
        )
