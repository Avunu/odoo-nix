"""Resolve the workspace + odoo.conf, and load Odoo's own config in-process.

odoo-nix always runs odoo-bin (and now `odoo`) from the workspace root, so
paths here follow the same REPO_ROOT / -c / $ODOO_RC precedence odoo-bin
itself already uses. Nothing here duplicates odoo.tools.config's own
data_dir/db_name resolution -- it just gets a config path INTO that resolver,
then reads the result back.

Every `odoo` import below is deferred into the function that needs it: `odoo
module` and `odoo project` commands are pure git/OCA operations and should not
pay Odoo's own import cost, and even within `odoo db`, `list`/`create` don't
need the same things `migrate` does.
"""
from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path

import click


def repo_root() -> Path:
    return Path(os.environ.get("REPO_ROOT", os.getcwd()))


def require_env(name: str) -> str:
    """A handful of commands (module add/add-bundle, project update, shell)
    delegate to a helper script or the real odoo-bin whose store path this
    CLI's own Nix wrapper injects as an env var. Production builds only wire
    in the ones a store-assembled deployment can actually use (no git repo,
    no modules.txt) -- if one of those is missing, say so plainly instead of
    a bare KeyError."""
    value = os.environ.get(name)
    if not value:
        raise click.ClickException(
            f"{name} is not set -- this command is only available from an odoo-nix workspace dev shell."
        )
    return value


def resolve_config_path(explicit: str | None) -> Path:
    """Explicit -c/--config > $ODOO_RC/$OPENERP_SERVER > ./odoo.conf, exactly
    the precedence odoo.tools.config itself applies."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ODOO_RC") or os.environ.get("OPENERP_SERVER")
    if env:
        return Path(env)
    return repo_root() / "odoo.conf"


#: ctx.obj key -> the odoo-bin flag it overrides, for the Postgres
#: connection options on the root `cli` group (mirrors -c/-d's own
#: precedence: an explicit flag beats whatever's already in odoo.conf).
_DB_CONNECTION_FLAGS = {
    "db_host": "--db_host",
    "db_port": "--db_port",
    "db_user": "--db_user",
    "db_password": "--db_password",
}


def db_connection_args(ctx_obj: dict) -> list[str]:
    args = []
    for key, flag in _DB_CONNECTION_FLAGS.items():
        value = ctx_obj.get(key)
        if value:
            args += [flag, str(value)]
    return args


def load_config(conf_path: Path, extra_args: list[str] | None = None):
    """Parse odoo.conf in-process; returns odoo.tools.config, ready to use
    with odoo.service.db / Registry.new()."""
    import odoo.tools

    if not conf_path.is_file():
        raise click.ClickException(f"no odoo.conf at {conf_path} (pass -c, or run from the workspace root)")
    odoo.tools.config.parse_config(["-c", str(conf_path), *(extra_args or [])], setup_logging=False)

    # odoo.service.db's mutating functions (dump_db, restore_db, exp_drop,
    # exp_create_database, ...) are gated by config['list_db'] via
    # @check_db_management_enabled -- the same flag that controls whether the
    # *web* Database Manager / remote RPC can list/create/drop databases.
    # That gate exists to stop an unauthenticated network client; it says
    # nothing about this process, which is already running locally as
    # whoever has filesystem access to odoo.conf (and therefore to Postgres
    # itself). So it is set here, in-process only -- never written back to
    # odoo.conf -- rather than requiring every production deployment to also
    # flip its web-facing listDb setting just to let this CLI run locally.
    odoo.tools.config["list_db"] = True

    # odoo.tools.config reads $PGDATABASE (mirroring libpq's own env-var
    # convention for db_host/port/user/password too) as an implicit default
    # for db_name whenever the conf file itself does not set one. That
    # silently narrows every db_name-gated odoo.service.db call -- not just
    # list_dbs(), but exp_drop()'s own "does this database exist" check,
    # which uses list_dbs() internally and returns False (not an error) for
    # anything outside that one database, so a drop/backup/restore on a
    # DIFFERENT database quietly no-ops instead of failing loudly. Ambient
    # $PGDATABASE (a shell profile, sandboxed test fixtures, container
    # conventions) has nothing to do with an odoo-nix project's own
    # configuration, so it is cleared here unless the conf file *itself*
    # actually pins db_name -- odoo-nix's own dbName option does exactly
    # that, and that pin is real config, not an env artifact.
    if not _conf_pins_db_name(conf_path):
        odoo.tools.config["db_name"] = False

    return odoo.tools.config


def _conf_pins_db_name(conf_path: Path) -> bool:
    import configparser

    parser = configparser.ConfigParser()
    try:
        parser.read(conf_path)
    except configparser.Error:
        return False
    return parser.has_option("options", "db_name")


def resolve_database(explicit: str | None, odoo_config) -> str | None:
    """Explicit CLI arg > $ODOO_DB env > db_name from the loaded odoo.conf."""
    if explicit:
        return explicit
    env = os.environ.get("ODOO_DB")
    if env:
        return env
    return odoo_config["db_name"] or None


def list_all_databases(odoo_config) -> list[str]:
    """Every database Postgres reports for the connected role -- true
    wildcard, for `db list` and `--all`.

    odoo.tools.config reads $PGDATABASE (among other libpq-style env vars)
    as an implicit default for db_name when no -d/--database was given, and
    odoo.service.db.list_dbs() treats *any* non-empty db_name as "the caller
    restricted the exposed list to this" -- short-circuiting straight past
    its own Postgres catalog query. $PGDATABASE being set is common (a
    shell profile, sandboxed test fixtures, container conventions) and has
    nothing to do with this command's own request for "every database", so
    that ambient default is cleared here, in-process only, before asking.
    """
    from odoo.service import db as odoo_db

    odoo_config["db_name"] = False
    return sorted(odoo_db.list_dbs(force=True))


def list_target_databases(explicit: str | None, all_flag: bool, odoo_config) -> list[str]:
    """Resolve one or more target database names for a multi-db-aware command:
    --all (matching dbfilter when it's a plain regex), an explicit comma list,
    or the single configured default."""
    if all_flag:
        names = list_all_databases(odoo_config)
        db_filter = odoo_config["dbfilter"]
        # %h/%d are per-request host placeholders (odoo/http.py db_filter());
        # there is no "current host" in a CLI invocation, so a filter using
        # them is left unapplied here rather than guessed at.
        if db_filter and "%h" not in db_filter and "%d" not in db_filter:
            try:
                pattern = re.compile(db_filter)
            except re.error:
                pattern = None
            if pattern is not None:
                names = [n for n in names if pattern.match(n)]
        return names
    if explicit:
        return [d.strip() for d in explicit.split(",") if d.strip()]
    single = resolve_database(None, odoo_config)
    if single:
        return [single]
    raise click.UsageError(
        "no database specified -- pass a name, a comma list, --all, or set db_name in odoo.conf / $ODOO_DB"
    )


@contextlib.contextmanager
def _quiet_module_descriptions():
    """ir.module.module._get_desc() renders every updated module's manifest
    `description` as RST via docutils straight to stderr whenever the module
    has no static/description/index.html (true for addons pulled in as raw
    git checkouts, i.e. everything odoo-nix builds from -- even Odoo's own
    `mail`). Those docutils messages never go through Odoo's logger, so
    there's no --log-level/odoo.log knob for them; they're also almost never
    actionable, since MyWriter already strips the corresponding nodes from
    the rendered HTML before it reaches the Apps page. This raises docutils'
    own report threshold above SEVERE for that one call so the routine
    ERROR/WARNING/INFO noise is dropped, while halt_level (unset by Odoo,
    so still its default 4/SEVERE) is untouched -- a truly broken
    description still raises, and lands in ir_module's own `except Exception`
    fallback, which *does* log through _logger with the module name attached."""
    from odoo.addons.base.models import ir_module

    orig_publish_string = ir_module.publish_string

    def quiet_publish_string(*args, **kwargs):
        overrides = dict(kwargs.get("settings_overrides") or {})
        overrides.setdefault("report_level", 5)
        kwargs["settings_overrides"] = overrides
        return orig_publish_string(*args, **kwargs)

    ir_module.publish_string = quiet_publish_string
    try:
        yield
    finally:
        ir_module.publish_string = orig_publish_string


def run_module_update(db_name: str, *, update: list[str] | None = None, install: list[str] | None = None) -> None:
    """Trigger Odoo's own module load/upgrade loop for one database -- the
    same call odoo-bin's own -u/-i/--stop-after-init makes (Registry.new),
    just invoked in-process instead of as a subprocess.

    Two APIs, detected rather than keyed on a version number:

    - 18.0 and older read the lists from odoo.tools.config['init'] /
      ['update']; `update=["all"]` reproduces `--update all` exactly
      (odoo/modules/graph.py expands the literal 'all' sentinel per module as
      the dependency graph is built).
    - 19.0 takes them as Registry.new(install_modules=, upgrade_modules=)
      keywords and no longer reads config for this at all -- setting config
      alone installs and updates *nothing*, silently. Its own `-u all` is
      "upgrade base" (tools/config.py), which button_upgrade cascades to every
      module depending on it, i.e. all of them.
    """
    import inspect

    import odoo.tools
    from odoo.modules.registry import Registry

    install = list(install or [])
    update = list(update or [])
    update_module = bool(update) or bool(install)
    with _quiet_module_descriptions():
        if "upgrade_modules" in inspect.signature(Registry.new).parameters:
            upgrade = {"base"} if "all" in update else set(update)
            Registry.new(db_name, update_module=update_module, install_modules=install, upgrade_modules=upgrade)
        else:
            odoo.tools.config["init"] = dict.fromkeys(install, 1)
            odoo.tools.config["update"] = dict.fromkeys(update, 1)
            Registry.new(db_name, update_module=update_module)
