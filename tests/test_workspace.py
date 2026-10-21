"""The workspace commands' pieces (lib/odoo_nix_cli/workspace) that
tests/module.sh reaches only indirectly or not at all, without Odoo, a
database or a remote: the configuration schema, remove's command line, which
modules and repositories a removal takes, and the in-use check against
databases, with odoo.sql_db and odooenv stood in.

Run: python3 -I tests/test_workspace.py <dir holding odoo_nix_cli> <data dir>
     (checks.odoo-module-unit)
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.abspath(sys.argv.pop(1)))
DATA = Path(sys.argv.pop(1)).resolve()

from odoo_nix_cli.workspace import config, remove
from odoo_nix_cli.workspace.add import Stop
from odoo_nix_cli.workspace.common import read_modules, write_modules

GOOD = {
    "series": "18.0",
    "ocaDataset": str(DATA / "oca-modules.json"),
    "ocaBundles": str(DATA / "oca-bundles.json"),
    "layout": {"coreSrc": "odoo", "externalDir": "modules", "customDir": "custom"},
    "sources": "odoo-nix-sources",
    "regenerate": shutil.which("true") or "/bin/true",
}


def git(*argv):
    subprocess.run(["git", *argv], check=True, capture_output=True)


class ConfigTest(unittest.TestCase):
    def test_good(self):
        c = config.parse(GOOD)
        self.assertEqual((c.series, c.layout.external_dir), ("18.0", "modules"))

    def test_refuses(self):
        for data, message in (
            ({**GOOD, "x": 1}, "unknown key(s): x"),
            (
                {k: v for k, v in GOOD.items() if k != "sources"},
                "missing key(s): sources",
            ),
            ({**GOOD, "layout": {"coreSrc": "odoo"}}, "config.layout: missing key(s)"),
            ({**GOOD, "series": ""}, "config.series"),
            (
                {**GOOD, "layout": {**GOOD["layout"], "customDir": 1}},
                "config.layout.custom_dir",
            ),
        ):
            with self.assertRaises(config.ConfigError) as ctx:
                config.parse(data)
            self.assertIn(message, str(ctx.exception))

    def test_load_needs_the_variable(self):
        with (
            unittest.mock.patch.dict(os.environ, {}, clear=True),
            self.assertRaises(config.ConfigError) as ctx,
        ):
            config.load()
        self.assertIn("workspace dev shell", str(ctx.exception))


class ArgsTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(
            remove.parse_args(["a", "--force", "b"]), (["a", "b"], True, False)
        )
        self.assertEqual(remove.parse_args(["--keep-repos", "a"]), (["a"], False, True))
        self.assertIsNone(remove.parse_args(["a", "--help"]))
        for argv in ([], ["--force"], ["--nope", "a"]):
            with self.assertRaises(remove.UsageError):
                remove.parse_args(argv)


class Workspace(unittest.TestCase):
    """A workspace in a fresh directory: submodules registered in .gitmodules
    (paths only, nothing cloned), modules on disk where a test puts them."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, cwd)
        self.cfg = config.parse(GOOD)

    def sub(self, path, *modules, depends=None):
        git("config", "-f", ".gitmodules", f"submodule.{path}.path", path)
        for m in modules:
            Path(path, m).mkdir(parents=True)
            Path(path, m, "__manifest__.py").write_text(
                repr({"depends": (depends or {}).get(m, [])})
            )

    def custom(self, name, depends=()):
        Path("custom", name).mkdir(parents=True)
        Path("custom", name, "__manifest__.py").write_text(
            repr({"depends": list(depends)})
        )

    def plan(self, names, keep=False):
        return remove.plan(self.cfg, names, keep)


class PlanTest(Workspace):
    def test_catalog_closure_when_nothing_is_on_disk(self):
        # account_tax_balance → account-financial-reporting, date_range → server-ux.
        self.sub("modules/account-financial-reporting")
        self.sub("modules/server-ux")
        write_modules(["account_tax_balance", "date_range"])
        p = self.plan(["account_tax_balance"])
        self.assertEqual(
            (p.modules, p.repos, p.code),
            (["account_tax_balance"], ["modules/account-financial-reporting"], []),
        )
        p = self.plan(["account_tax_balance", "date_range"])
        self.assertEqual(
            p.repos, ["modules/account-financial-reporting", "modules/server-ux"]
        )

    def test_disk_depends_keep_a_repo(self):
        self.sub("modules/lib", "base_lib")
        self.sub("modules/app", "app_one", "app_two", depends={"app_one": ["base_lib"]})
        self.custom("ours", depends=["base_lib"])
        write_modules(["app_one", "ours"])
        # ours (custom/) still needs base_lib: modules/lib stays.
        p = self.plan(["app_one"])
        self.assertEqual((p.repos, p.code), (["modules/app"], ["app_one", "app_two"]))
        write_modules(["app_one"])
        p = self.plan(["app_one"])
        self.assertEqual(p.repos, ["modules/app", "modules/lib"])
        self.assertEqual(p.code, ["app_one", "app_two", "base_lib"])

    def test_a_sibling_still_listed_keeps_the_repo(self):
        self.sub("modules/multi", "one", "two")
        write_modules(["one", "two"])
        p = self.plan(["one"])
        self.assertEqual((p.modules, p.repos, p.code), (["one"], [], []))

    def test_repo_by_name_or_path_takes_its_listed_modules(self):
        self.sub("modules/multi", "one", "two")
        self.sub("modules/other", "three")
        write_modules(["one", "three", "two"])
        for name in ("multi", "modules/multi", "modules/multi/"):
            p = self.plan([name])
            self.assertEqual(
                (p.modules, p.repos), (["one", "two"], ["modules/multi"]), name
            )

    def test_repo_still_needed_is_refused(self):
        self.sub("modules/lib", "base_lib")
        self.sub("modules/app", "app_one", depends={"app_one": ["base_lib"]})
        write_modules(["app_one"])
        with self.assertRaises(Stop) as ctx:
            self.plan(["lib"])
        self.assertIn("modules/lib is still needed by app_one", str(ctx.exception))

    def test_unknown(self):
        with self.assertRaises(Stop) as ctx:
            self.plan(["nope"])
        self.assertEqual(ctx.exception.code, 1)

    def test_keep_repos(self):
        self.sub("modules/multi", "one")
        write_modules(["one"])
        p = self.plan(["one"], keep=True)
        self.assertEqual((p.modules, p.repos, p.code), (["one"], [], []))

    def test_modules_txt(self):
        Path("modules.txt").write_text("b\n\n a\nb")
        self.assertEqual(read_modules(), ["b", "a", "b"])
        write_modules(read_modules())
        self.assertEqual(Path("modules.txt").read_text(), "a\nb\n")


class FakeOdoo:
    """odoo.sql_db with databases DBS ({name: installed modules, or an
    exception to raise}), and odooenv answering with their names."""

    def __init__(self, dbs, listing_error=None):
        fake = self
        self.dbs = dbs

        class Cursor:
            def __init__(self, db):
                self.db = db

            def __enter__(self):
                value = fake.dbs[self.db]
                if isinstance(value, Exception):
                    raise value
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, query, params):
                self.wanted = params[0]

            def fetchall(self):
                return [(m,) for m in sorted(fake.dbs[self.db]) if m in self.wanted]

        sql_db = types.ModuleType("odoo.sql_db")
        sql_db.db_connect = lambda db: types.SimpleNamespace(cursor=lambda: Cursor(db))
        odoo = types.ModuleType("odoo")
        odoo.sql_db = sql_db
        self.modules = {"odoo": odoo, "odoo.sql_db": sql_db}

        def targets(explicit, all_flag, conf):
            if listing_error:
                raise listing_error
            return list(dbs)

        self.patches = [
            unittest.mock.patch.dict(sys.modules, self.modules),
            unittest.mock.patch("odoo_nix_cli.odooenv.load_config", lambda *a: {}),
            unittest.mock.patch("odoo_nix_cli.odooenv.list_target_databases", targets),
        ]

    def __enter__(self):
        for p in self.patches:
            p.__enter__()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.__exit__(*exc)


@unittest.skipUnless(
    __import__("importlib").util.find_spec("click"),
    "odoo_nix_cli.odooenv needs click (the CLI's interpreter)",
)
class InUseTest(Workspace):
    def check(self, p):
        try:
            remove.refuse_if_in_use(p, {})
        except Stop as e:
            return str(e)
        return None

    def test_installed_is_refused_with_each_database(self):
        p = remove.Plan(modules=["a"], repos=[], code=["a", "b"])
        with FakeOdoo({"prod": ["a", "x"], "test": ["b"], "clean": []}):
            message = self.check(p)
        self.assertIn("still installed", message)
        self.assertIn("    prod: a", message)
        self.assertIn("    test: b", message)
        self.assertNotIn("clean", message)

    def test_none_installed_passes(self):
        with FakeOdoo({"prod": ["x"]}):
            self.assertIsNone(self.check(remove.Plan(code=["a"])))

    def test_unreadable_is_refused(self):
        with FakeOdoo({"prod": RuntimeError("connection refused")}):
            message = self.check(remove.Plan(code=["a"]))
        self.assertIn("could not read the installed modules", message)
        self.assertIn("prod: RuntimeError: connection refused", message)
        with FakeOdoo({}, listing_error=OSError("no odoo.conf")):
            self.assertIn("no odoo.conf", self.check(remove.Plan(code=["a"])))

    def test_no_code_no_database(self):
        with FakeOdoo({}, listing_error=AssertionError("must not be asked")):
            self.assertIsNone(self.check(remove.Plan(modules=["a"])))


class RemoveTest(Workspace):
    def test_usage(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(remove.remove(self.cfg, []), 1)
        self.assertIn("Usage: odoo module remove", err.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(remove.remove(self.cfg, ["--help"]), 0)
        self.assertIn("--keep-repos", out.getvalue())

    def test_modules_txt_only(self):
        git("init", "-q", ".")
        write_modules(["a", "b"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(remove.remove(self.cfg, ["a"]), 0)
        self.assertEqual(read_modules(), ["b"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
