"""Odoo's database-management API behind one set of names, for 18.0 through 20.0.

Through 19.0 it is `odoo.service.db`: the RPC-shaped `exp_*` functions
(`exp_create_database`, `exp_drop`, `exp_db_exist`, ...) next to `dump_db` /
`restore_db` / `list_dbs` / `list_db_incompatible`. 20.0 deleted that module and
moved the logic into `odoo.modules.db` under plain names (`create`, `drop`,
`exist`, `dump`, `restore`, ...) with keyword-only options, and dropped
`list_db_incompatible` altogether.

Everything in odoo-nix's CLI that manages databases goes through here, so the
commands read the same on every series. Which implementation to use is
detected from what the installed Odoo has, never from a version number --
the way `odooenv.run_module_update` picks between its two registry APIs.
"""

from __future__ import annotations

import subprocess
import zipfile
from contextlib import closing
from typing import BinaryIO


def _modern():
    """`odoo.modules.db` when it carries the 20.0 management functions, else None.

    `odoo.modules.db` exists in every series (it has `is_initialized` and
    `initialize`), so the module alone proves nothing; `create` is what 20.0
    added there.
    """
    from odoo.modules import db

    return db if hasattr(db, "create") else None


def _legacy():
    from odoo.service import db

    return db


def list_dbs(*, force: bool = False) -> list[str]:
    backend = _modern() or _legacy()
    return list(backend.list_dbs(force=force))


def exists(name: str) -> bool:
    """Whether a connection to `name` can be opened.

    Not whether it is an Odoo database -- see `commands.db._has_odoo_schema`.
    """
    modern = _modern()
    return modern.exist(name) if modern else _legacy().exp_db_exist(name)


def create_empty(name: str) -> None:
    """CREATE DATABASE with Odoo's template, encoding and extensions; no schema.

    Raises when `name` already exists (`DatabaseExists`).
    """
    (_modern() or _legacy())._create_empty_database(name)


def create(name: str, *, demo: bool, lang: str, user_password: str = "admin") -> None:
    modern = _modern()
    if modern:
        modern.create(name, demo=demo, lang=lang, user_password=user_password)
    else:
        _legacy().exp_create_database(name, demo, lang, user_password=user_password)


def duplicate(source: str, dest: str, *, neutralize: bool = False) -> None:
    modern = _modern()
    if modern:
        modern.duplicate(source, dest, neutralize_database=neutralize)
    else:
        _legacy().exp_duplicate_database(source, dest, neutralize_database=neutralize)


def rename(old_name: str, new_name: str) -> None:
    modern = _modern()
    if modern:
        modern.rename(old_name, new_name)
    else:
        _legacy().exp_rename(old_name, new_name)


def drop(name: str) -> bool:
    """Drop `name` and its filestore. False when there was no such database.

    `exp_drop` answered False for a database outside `list_dbs()`; 20.0's `drop`
    returns nothing and lets Postgres raise instead. The 18/19 answer is kept,
    so callers can tell "nothing to drop" from a real failure -- but asked of
    the server (can it be connected to?), not of `list_dbs()`, which a pinned
    `db_name` narrows to that one database.
    """
    modern = _modern()
    if modern is None:
        return bool(_legacy().exp_drop(name))
    if not modern.exist(name):
        return False
    modern.drop(name)
    return True


def dump(name: str, stream: BinaryIO, *, backup_format: str = "zip") -> None:
    modern = _modern()
    if modern:
        modern.dump(name, stream, backup_format=backup_format)
    else:
        _legacy().dump_db(name, stream, backup_format=backup_format)


def restore(name: str, path: str, *, neutralize: bool = False) -> None:
    """Restore the backup at `path` into a new database `name` (which must not exist).

    A zip (dump.sql + filestore/ + manifest.json) or, as `db backup --format
    dump` writes, a plain `pg_dump -Fc` file. 18.0 and 19.0 took both; 20.0's
    restore reads only zips, so the other is restored here the way theirs was.
    """
    modern = _modern()
    if modern is None:
        _legacy().restore_db(name, path, neutralize_database=neutralize)
    elif zipfile.is_zipfile(path):
        modern.restore(name, path, neutralize_database=neutralize)
    else:
        _restore_pg_dump(name, path, neutralize)


def _restore_pg_dump(name: str, path: str, neutralize: bool) -> None:
    """A `pg_dump -Fc` file into a new database: no filestore, as 19.0's restore_db had it."""
    import odoo.modules.neutralize
    import odoo.sql_db
    from odoo.modules.registry import Registry
    from odoo.tools.misc import exec_pg_environ, find_pg_tool

    if exists(name):
        raise ValueError(f"Database {name!r} already exists")
    create_empty(name)
    result = subprocess.run(
        [find_pg_tool("pg_restore"), "--no-owner", "--dbname=" + name, path],
        env=exec_pg_environ(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Couldn't restore database {name!r} from {path}")
    if neutralize:
        # before the registry loads, so the cron workers never see it live
        with odoo.sql_db.db_connect(name).cursor() as cr:
            odoo.modules.neutralize.neutralize_database(cr)
    Registry.new(name)


def list_incompatible(names: list[str]) -> list[str]:
    """The databases among `names` that are not for the running series.

    A database is incompatible when it has no Odoo schema, or its `base` module
    was last installed or upgraded by a different series. This is
    `list_db_incompatible` as 18.0 and 19.0 define it; 20.0 removed it, and
    reimplementing it here is cheaper than keeping two answers to the question.
    """
    import odoo.release
    import odoo.sql_db
    import odoo.tools.sql

    server = ".".join(str(v) for v in odoo.release.version_info[:2])
    incompatible = []
    for name in names:
        with closing(odoo.sql_db.db_connect(name).cursor()) as cr:
            if not odoo.tools.sql.table_exists(cr, "ir_module_module"):
                incompatible.append(name)
                continue
            cr.execute(
                "SELECT latest_version FROM ir_module_module WHERE name = %s", ("base",)
            )
            row = cr.fetchone()
            if not row or not row[0] or ".".join(row[0].split(".")[:2]) != server:
                incompatible.append(name)
    # release the connections of the ones that will not be used, as Odoo's own did
    for name in incompatible:
        odoo.sql_db.close_db(name)
    return incompatible
