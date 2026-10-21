"""lib/odoo_nix_cli/odoo_db.py without Odoo: one set of names over Odoo's two
database-management APIs -- `odoo.service.db` (18.0, 19.0) and `odoo.modules.db`
(20.0) -- told apart by what the installed Odoo has, not by its version.

Each test installs a stand-in `odoo` package shaped like one series and asserts
which of its functions a call reached, and with what: 20.0's keyword-only
options, `drop` that returns nothing where `exp_drop` said False, a restore of
a `pg_dump -Fc` file (which 20.0's `restore` no longer reads), and
`list_db_incompatible`, which 20.0 removed.

Run: python3 -I tests/test_odoo_db.py <dir holding odoo_nix_cli>   (checks.odoo-db-compat)
"""

import io
import os
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
import zipfile
from typing import ClassVar

sys.path.insert(0, os.path.abspath(sys.argv.pop(1)))

from odoo_nix_cli import odoo_db

MODERN = (
    "create",
    "duplicate",
    "rename",
    "drop",
    "dump",
    "restore",
    "list_dbs",
    "exist",
    "_create_empty_database",
)
LEGACY = (
    "exp_create_database",
    "exp_duplicate_database",
    "exp_rename",
    "exp_drop",
    "dump_db",
    "restore_db",
    "list_dbs",
    "exp_db_exist",
    "_create_empty_database",
)


class Odoo:
    """A stand-in `odoo` in sys.modules, shaped like one series.

    `calls` logs every management-API call as (name, args, kwargs); `returns`
    says what a function answers. `databases` is what the SQL layer holds, as
    {name: latest_version of base, None for a database with no version, False
    for one with no Odoo schema}; `closed` logs the connections given back.
    `steps` logs the side effects a restore of a plain dump goes through.
    """

    def __init__(self, *, modern, returns=None, databases=None, series=(20, 0)):
        self.calls, self.steps, self.closed = [], [], []
        self.returns = returns or {}
        self.databases = databases or {}
        self.modules = {}

        def package(name, **attrs):
            mod = types.ModuleType(name)
            mod.__path__ = []
            mod.__dict__.update(attrs)
            self.modules[name] = mod
            return mod

        package("odoo")
        package("odoo.modules")
        package("odoo.service")
        package("odoo.tools")
        # present in every series; `create` is what 20.0 added
        package("odoo.modules.db", is_initialized=lambda cr: True)
        package("odoo.service.db")
        management = self.modules["odoo.modules.db" if modern else "odoo.service.db"]
        for name in MODERN if modern else LEGACY:
            setattr(management, name, self.fn(name))
        package("odoo.release", version_info=(*series, 0, "final", 0, ""))
        package("odoo.sql_db", db_connect=self.connect, close_db=self.closed.append)
        package(
            "odoo.tools.sql", table_exists=lambda cr, table: cr.version is not False
        )
        package(
            "odoo.tools.misc",
            find_pg_tool=lambda name: f"/pg/{name}",
            exec_pg_environ=lambda: {"PGHOST": "h"},
        )
        package(
            "odoo.modules.neutralize",
            neutralize_database=lambda cr: self.steps.append("neutralize"),
        )
        package(
            "odoo.modules.registry",
            Registry=types.SimpleNamespace(
                new=lambda name: self.steps.append(("registry", name))
            ),
        )
        # A real import binds a submodule on its parent; sys.modules alone does not.
        for name, mod in self.modules.items():
            if "." in name:
                setattr(
                    self.modules[name.rsplit(".", 1)[0]], name.rsplit(".", 1)[1], mod
                )

    def fn(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.returns.get(name)

        return call

    def connect(self, name):
        version = self.databases[name]

        class Cursor:
            def __init__(self):
                self.version = version

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, query, params=None):
                pass

            def fetchone(self):
                return None if version is None else (version,)

            def close(self):
                pass

        return types.SimpleNamespace(cursor=Cursor)

    def install(self):
        self.saved = {name: sys.modules.get(name) for name in self.modules}
        sys.modules.update(self.modules)

    def uninstall(self):
        for name, mod in self.saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


class Case(unittest.TestCase):
    def odoo(self, **kwargs):
        stand_in = Odoo(**kwargs)
        stand_in.install()
        self.addCleanup(stand_in.uninstall)
        return stand_in

    def backup_files(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        zipped = os.path.join(tmp.name, "b.dump.zip")
        with zipfile.ZipFile(zipped, "w") as z:
            z.writestr("dump.sql", "")
        raw = os.path.join(tmp.name, "b.dump")
        with open(raw, "wb") as f:
            f.write(b"PGDMP\x01\x0e")
        return zipped, raw


class ModernTest(Case):
    """20.0: odoo.modules.db."""

    def test_create_is_keyword_only_and_carries_the_admin_password(self):
        odoo = self.odoo(modern=True)
        odoo_db.create("d", demo=True, lang="de_DE")
        self.assertEqual(
            odoo.calls,
            [
                (
                    "create",
                    ("d",),
                    {"demo": True, "lang": "de_DE", "user_password": "admin"},
                )
            ],
        )

    def test_create_empty(self):
        odoo = self.odoo(modern=True)
        odoo_db.create_empty("d")
        self.assertEqual(odoo.calls, [("_create_empty_database", ("d",), {})])

    def test_exists_is_exist(self):
        odoo = self.odoo(modern=True, returns={"exist": True})
        self.assertIs(odoo_db.exists("d"), True)
        self.assertEqual(odoo.calls, [("exist", ("d",), {})])

    def test_duplicate_rename_dump_restore(self):
        odoo = self.odoo(modern=True)
        zipped, _raw = self.backup_files()
        stream = io.BytesIO()
        odoo_db.duplicate("a", "b", neutralize=True)
        odoo_db.rename("a", "c")
        odoo_db.dump("a", stream, backup_format="dump")
        odoo_db.restore("a", zipped, neutralize=True)
        self.assertEqual(
            odoo.calls,
            [
                ("duplicate", ("a", "b"), {"neutralize_database": True}),
                ("rename", ("a", "c"), {}),
                ("dump", ("a", stream), {"backup_format": "dump"}),
                ("restore", ("a", zipped), {"neutralize_database": True}),
            ],
        )

    def test_drop_keeps_the_legacy_contract(self):
        # exp_drop answered False for a database it could not see; 20.0's drop
        # returns nothing and lets Postgres raise.
        odoo = self.odoo(modern=True, returns={"exist": False})
        self.assertIs(odoo_db.drop("gone"), False)
        self.assertNotIn("drop", [c[0] for c in odoo.calls])
        odoo = self.odoo(modern=True, returns={"exist": True})
        self.assertIs(odoo_db.drop("here"), True)
        self.assertEqual(odoo.calls[-1], ("drop", ("here",), {}))

    def test_drop_does_not_ask_list_dbs(self):
        # list_dbs() is narrowed to a pinned db_name; whether a database exists is not.
        odoo = self.odoo(
            modern=True, returns={"exist": True, "list_dbs": ["only_this_one"]}
        )
        self.assertIs(odoo_db.drop("another"), True)
        self.assertNotIn("list_dbs", [c[0] for c in odoo.calls])

    def test_list_dbs_forwards_force(self):
        odoo = self.odoo(modern=True, returns={"list_dbs": ["b", "a"]})
        self.assertEqual(odoo_db.list_dbs(force=True), ["b", "a"])
        self.assertEqual(odoo.calls, [("list_dbs", (), {"force": True})])


class PgDumpRestoreTest(Case):
    """20.0's restore reads only zips; `db backup --format dump` writes `pg_dump -Fc`,
    which 18.0 and 19.0 restored and so must this."""

    def restore(self, odoo, path, **kwargs):
        ran = []

        def run(cmd, **kw):
            ran.append((cmd, kw))
            odoo.steps.append("pg_restore")
            return subprocess.CompletedProcess(cmd, odoo.returns.get("pg_restore", 0))

        with unittest.mock.patch.object(odoo_db.subprocess, "run", run):
            odoo_db.restore("d", path, **kwargs)
        return ran

    def test_creates_restores_neutralizes_then_loads(self):
        odoo = self.odoo(
            modern=True, returns={"exist": False}, databases={"d": "20.0.1.3"}
        )
        _zipped, raw = self.backup_files()
        ran = self.restore(odoo, raw, neutralize=True)
        self.assertEqual(
            [c[0] for c in odoo.calls], ["exist", "_create_empty_database"]
        )
        self.assertEqual(ran[0][0], ["/pg/pg_restore", "--no-owner", "--dbname=d", raw])
        self.assertEqual(ran[0][1]["env"], {"PGHOST": "h"})
        # never live before it is neutralized: the registry loads last
        self.assertEqual(odoo.steps, ["pg_restore", "neutralize", ("registry", "d")])

    def test_neutralizes_only_when_asked(self):
        odoo = self.odoo(modern=True, returns={"exist": False})
        _zipped, raw = self.backup_files()
        self.restore(odoo, raw)
        self.assertEqual(odoo.steps, ["pg_restore", ("registry", "d")])

    def test_refuses_an_existing_database(self):
        odoo = self.odoo(modern=True, returns={"exist": True})
        _zipped, raw = self.backup_files()
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.restore(odoo, raw)
        self.assertEqual(odoo.steps, [])

    def test_a_failing_pg_restore_raises_before_the_registry_loads(self):
        odoo = self.odoo(modern=True, returns={"exist": False, "pg_restore": 1})
        _zipped, raw = self.backup_files()
        with self.assertRaisesRegex(RuntimeError, "Couldn't restore"):
            self.restore(odoo, raw)
        self.assertEqual(odoo.steps, ["pg_restore"])

    def test_a_zip_is_left_to_odoo(self):
        odoo = self.odoo(modern=True)
        zipped, _raw = self.backup_files()
        self.restore(odoo, zipped)
        self.assertEqual([c[0] for c in odoo.calls], ["restore"])
        self.assertEqual(odoo.steps, [])


class LegacyTest(Case):
    """18.0 and 19.0: odoo.service.db. odoo.modules.db exists there too, without `create`."""

    def test_create(self):
        odoo = self.odoo(modern=False)
        odoo_db.create("d", demo=False, lang="en_US")
        self.assertEqual(
            odoo.calls,
            [
                (
                    "exp_create_database",
                    ("d", False, "en_US"),
                    {"user_password": "admin"},
                )
            ],
        )

    def test_create_empty_and_exists(self):
        odoo = self.odoo(modern=False, returns={"exp_db_exist": True})
        odoo_db.create_empty("d")
        self.assertIs(odoo_db.exists("d"), True)
        self.assertEqual(
            odoo.calls,
            [("_create_empty_database", ("d",), {}), ("exp_db_exist", ("d",), {})],
        )

    def test_duplicate_rename_dump_restore(self):
        odoo = self.odoo(modern=False)
        stream = io.BytesIO()
        odoo_db.duplicate("a", "b", neutralize=False)
        odoo_db.rename("a", "c")
        odoo_db.dump("a", stream)
        # whatever the format: restore_db tells a zip from a pg_dump itself
        odoo_db.restore("a", "/x.dump")
        self.assertEqual(
            odoo.calls,
            [
                ("exp_duplicate_database", ("a", "b"), {"neutralize_database": False}),
                ("exp_rename", ("a", "c"), {}),
                ("dump_db", ("a", stream), {"backup_format": "zip"}),
                ("restore_db", ("a", "/x.dump"), {"neutralize_database": False}),
            ],
        )

    def test_drop_passes_exp_drop_through(self):
        odoo = self.odoo(modern=False, returns={"exp_drop": False})
        self.assertIs(odoo_db.drop("gone"), False)
        self.assertEqual(odoo.calls, [("exp_drop", ("gone",), {})])


class IncompatibleTest(Case):
    """list_incompatible is the same on every series: it needs no management API."""

    DATABASES: ClassVar[dict] = {
        "fresh": "20.0.1.3",
        "old": "19.0.1.3",
        "never_installed": None,
        "empty_version": "",
        "no_schema": False,
    }

    def test_schema_less_and_other_series_databases_are_incompatible(self):
        odoo = self.odoo(modern=True, databases=self.DATABASES)
        incompatible = ["old", "never_installed", "empty_version", "no_schema"]
        self.assertEqual(odoo_db.list_incompatible(list(self.DATABASES)), incompatible)
        # the ones that will not be used give their connection back; the usable one keeps it
        self.assertEqual(odoo.closed, incompatible)

    def test_the_series_is_the_running_ones(self):
        self.odoo(modern=False, databases={"d": "19.0.1.3"}, series=(19, 0))
        self.assertEqual(odoo_db.list_incompatible(["d"]), [])


if __name__ == "__main__":
    unittest.main()
