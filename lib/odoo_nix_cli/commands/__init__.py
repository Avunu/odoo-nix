"""The `odoo` CLI's own command tree: db / module / project / shell.

Everything else is passthrough, handled in __main__.py before this module is
even imported (see there for why).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys

import click

from .. import odooenv
from .db import db_group
from .module import module_group
from .project import project_group

_TEST_BROWSERS = ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable")


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
@click.option("--db-host", "db_host", default=None, help="Override odoo.conf's db_host for this run.")
@click.option("--db-port", "db_port", default=None, help="Override odoo.conf's db_port for this run.")
@click.option("--db-user", "db_user", default=None, help="Override odoo.conf's db_user for this run.")
@click.option("--db-password", "db_password", default=None, help="Override odoo.conf's db_password for this run.")
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
        raise click.UsageError("no database given, and none configured (db_name / $ODOO_DB).")
    raw = odooenv.require_env("ODOO_NIX_RAW_ODOO")
    os.execv(raw, [raw, "shell", "-c", str(conf_path), "-d", target, *db_args])


@cli.command("test")
@click.argument("modules")
@click.argument("database", required=False)
@click.pass_context
def test_cmd(ctx, modules, database):
    """Run MODULES' Odoo tests (comma-separated) -- and refuse to call a
    skipped browser tour a pass (replaces the old odoo-test script).

    Odoo degrades quietly when tour prerequisites are missing: no
    `websocket` module, or no Chrome on PATH, and every HttpCase is
    *skipped*. The summary line reports skips and passes identically, so a
    broken environment reads as a green run -- this checks the
    prerequisites up front and refuses to run rather than let that happen.
    """
    conf_path = odooenv.resolve_config_path(ctx.obj.get("config"))
    db_args = odooenv.db_connection_args(ctx.obj)
    odoo_config = odooenv.load_config(conf_path, db_args)
    target = odooenv.resolve_database(database or ctx.obj.get("database"), odoo_config)
    if not target:
        raise click.UsageError("no database given, and none configured (db_name / $ODOO_DB).")

    missing = []
    if importlib.util.find_spec("websocket") is None:
        missing.append("the 'websocket-client' package (add it to [dependency-groups].dev, then re-lock)")
    browser = next((b for b in _TEST_BROWSERS if shutil.which(b)), None)
    if browser is None:
        missing.append("a headless browser (set odoo-nix's testBrowser, or put one on PATH)")

    if missing:
        click.echo("✗ Browser tours cannot run here, and Odoo would skip them silently:", err=True)
        for m in missing:
            click.echo(f"  - {m}", err=True)
        click.echo(
            "\n  Refusing to run, because a skipped tour is reported exactly like a passing one. "
            "Set ODOO_TEST_ALLOW_SKIP=1 to run anyway.",
            err=True,
        )
        if os.environ.get("ODOO_TEST_ALLOW_SKIP") != "1":
            sys.exit(1)
    else:
        click.echo(f"==> tours enabled (browser: {browser})")

    # "a,b" -> "/a,/b": --test-tags wants a leading slash per module.
    tags = "/" + modules.replace(",", ",/")
    click.echo(f"==> Testing {modules} on '{target}' (tags: {tags})…")
    raw = odooenv.require_env("ODOO_NIX_RAW_ODOO")
    os.execv(
        raw,
        [
            raw,
            "-c",
            str(conf_path),
            "-d",
            target,
            "-u",
            modules,
            "--test-enable",
            "--test-tags",
            tags,
            "--stop-after-init",
            *db_args,
        ],
    )
