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
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, os.path.abspath(sys.argv.pop(1)))
DATA = Path(sys.argv.pop(1)).resolve()

from odoo_nix_cli.workspace import config, lock, relock, remove, update
from odoo_nix_cli.workspace.add import Stop
from odoo_nix_cli.workspace.common import read_modules, write_modules

GOOD = {
    "series": "18.0",
    "ocaDataset": str(DATA / "oca-modules.json"),
    "ocaBundles": str(DATA / "oca-bundles.json"),
    "layout": {"coreSrc": "odoo", "externalDir": "modules", "customDir": "custom"},
    "sources": "odoo-nix-sources",
    "python": sys.executable,
    "ocaSources": "oca_sources.py",
    "uv": "uv",
    "buildDeps": "odoo-nix-build-deps",
    "coreSource": None,
    "node": None,
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


def stub(path, name, rc_var):
    """An executable at PATH that logs ``NAME argv…`` to $STUB_LOG and exits
    with $RC_VAR (0 when unset)."""
    Path(path).write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "with open(os.environ['STUB_LOG'], 'a') as f:\n"
        f"    f.write(' '.join([{name!r}, *sys.argv[1:]]) + '\\n')\n"
        f"sys.exit(int(os.environ.get({rc_var!r}, '0')))\n"
    )
    os.chmod(path, 0o755)


class Workspace(unittest.TestCase):
    """A workspace in a fresh directory: submodules registered in .gitmodules
    (paths only, nothing cloned), modules on disk where a test puts them. The
    re-lock's tools (oca_sources.py, uv, odoo-nix-build-deps) are stubs that log
    to $STUB_LOG and exit with $RC_SOURCES, $RC_UV and $RC_BUILD_DEPS."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, cwd)
        tools = Path(tmp.name, ".tools")
        tools.mkdir()
        stub(tools / "oca_sources.py", "oca_sources", "RC_SOURCES")
        stub(tools / "uv", "uv", "RC_UV")
        stub(tools / "build-deps", "build-deps", "RC_BUILD_DEPS")
        self.cfg = config.parse(
            {
                **GOOD,
                "ocaSources": str(tools / "oca_sources.py"),
                "uv": str(tools / "uv"),
                "buildDeps": str(tools / "build-deps"),
            }
        )
        self.log = tools / "log"
        self.log.touch()
        env = unittest.mock.patch.dict(os.environ, {"STUB_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)

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


class RelockTest(Workspace):
    """odoo_nix_cli.workspace.update's relock and regenerate, with oca_sources.py,
    uv and odoo-nix-build-deps stood in."""

    def calls(self):
        return self.log.read_text().splitlines()

    @contextlib.contextmanager
    def quiet(self, **rcs):
        """The stubs' statuses set to RCS, and the output caught: yields (out, err)."""
        out, err = io.StringIO(), io.StringIO()
        with (
            unittest.mock.patch.dict(os.environ, rcs),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            yield out, err

    def relock(self, *uv_args, **rcs):
        with self.quiet(**rcs) as (out, err):
            r = update.relock(self.cfg, uv_args)
        return r, out.getvalue(), err.getvalue()

    def test_sequence(self):
        r, out, err = self.relock("--upgrade-package", "lxml")
        self.assertEqual((r.status, err), (0, ""))
        self.assertEqual(
            self.calls(),
            [
                "oca_sources update pyproject.toml modules.txt modules custom odoo",
                "uv lock --upgrade-package lxml",
                "build-deps update pyproject.toml uv.lock",
                "uv lock",
            ],
        )
        self.assertIn("==> Regenerating uv path-sources…", out)
        self.assertIn("==> Re-locking Python environment (uv lock)…", out)

    def test_failed_path_sources_stop_it(self):
        r, _, _ = self.relock(RC_SOURCES="3")
        self.assertEqual((r.sources, r.status), (3, 3))
        self.assertEqual(len(self.calls()), 1)
        with self.quiet(RC_SOURCES="3"):
            self.assertEqual(update.regenerate(self.cfg), 3)

    def test_failed_lock_is_said_and_nothing_follows(self):
        r, _, err = self.relock(RC_UV="2")
        self.assertEqual((r.sources, r.lock, r.status), (0, 2, 2))
        self.assertIn(update.LOCK_FAILED, err)
        self.assertEqual(self.calls()[-1], "uv lock")
        self.assertEqual(len(self.calls()), 2)
        # module add|remove and project update carry on past it, as before.
        with self.quiet(RC_UV="2"):
            self.assertEqual(update.regenerate(self.cfg), 0)

    def test_failed_build_deps_still_relocks(self):
        r, _, _ = self.relock(RC_BUILD_DEPS="4")
        self.assertEqual((r.lock, r.after, r.status), (0, 4, 4))
        self.assertEqual(self.calls()[-1], "uv lock")

    def test_fixtures_main(self):
        tools = ["--uv", self.cfg.uv, "--build-deps", self.cfg.build_deps]
        with self.quiet():
            self.assertEqual(lock.main([*tools, "--", "-U"]), 0)
        self.assertEqual(self.calls()[0], "uv lock -U")
        # Unlike a project's relock, any failed step fails it.
        with self.quiet(RC_BUILD_DEPS="1"):
            self.assertEqual(lock.main(tools), 1)
        with self.quiet():
            self.assertEqual(lock.main(tools[:2]), 2)


class RelockAppTest(Workspace):
    """odoo_nix_cli.workspace.relock: ``run``, which ``odoo project relock``
    and ``nix run .#relock`` share, and ``main``, the flake app's."""

    calls = RelockTest.calls
    quiet = RelockTest.quiet

    def setUp(self):
        super().setUp()
        Path("pyproject.toml").touch()
        baked = Path(".tools", "workspace.json")
        stub(Path(".tools", "sources"), "sources", "RC_ENTER")
        data = {
            **GOOD,
            "sources": str(Path(".tools", "sources").resolve()),
            "ocaSources": self.cfg.oca_sources,
            "uv": self.cfg.uv,
            "buildDeps": self.cfg.build_deps,
        }
        baked.write_text(json.dumps(data))
        env = unittest.mock.patch.dict(os.environ, {config.ENV: str(baked.resolve())})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("REPO_ROOT", None)

    def main(self, *argv, **rcs):
        with self.quiet(**rcs) as (out, err):
            rc = relock.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_run_says_how_it_ended(self):
        with self.quiet() as (out, _):
            self.assertEqual(relock.run(self.cfg, ["-U"]), 0)
        self.assertIn(relock.DONE, out.getvalue())
        self.assertEqual(self.calls()[1], "uv lock -U")
        with self.quiet(RC_BUILD_DEPS="4") as (out, err):
            self.assertEqual(relock.run(self.cfg), 4)
        self.assertIn(relock.AFTER_FAILED, err.getvalue())
        self.assertNotIn(relock.DONE, out.getvalue())

    def test_main_relocks_the_project_root(self):
        root = Path.cwd()
        Path("sub").mkdir()
        os.chdir("sub")
        rc, _, err = self.main("--upgrade-package", "lxml")
        self.assertEqual(rc, 1)
        self.assertIn("no pyproject.toml in", err)
        self.assertEqual(self.calls(), [])
        with unittest.mock.patch.dict(os.environ, {"REPO_ROOT": str(root)}):
            rc, out, _ = self.main("--upgrade-package", "lxml")
        self.assertEqual((rc, Path.cwd()), (0, root))
        self.assertEqual(self.calls()[2], "uv lock --upgrade-package lxml")
        self.assertIn(relock.DONE, out)

    def test_main_checks_out_what_shell_entry_would(self):
        # First the submodules a clone whose shell never started has never
        # had, as shell entry checks them out, so the install set has their
        # modules. odoo-nix-sources always exits 0; the relock goes on anyway.
        rc, _, _ = self.main()
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.calls()[:2],
            [
                f"sources enter --treeless odoo {Path.cwd()}",
                "oca_sources update pyproject.toml modules.txt modules custom odoo",
            ],
        )
        self.assertEqual(self.main(RC_ENTER="1")[0], 0)

    def test_main_statuses(self):
        self.assertEqual(self.main(RC_UV="2")[0], 2)
        self.assertEqual(self.main(RC_SOURCES="3")[0], 3)
        before = self.calls()
        rc, out, _ = self.main("--upgrade", "--help")
        self.assertEqual((rc, self.calls()), (0, before))
        self.assertIn("Usage: nix run .#relock", out)
        del os.environ[config.ENV]
        rc, _, err = self.main()
        self.assertEqual(rc, 1)
        self.assertIn(f"{relock.NAME}: ${config.ENV} is not set", err)


class CoreShadowTest(unittest.TestCase):
    """The lock-time shadow of a store-resident OCB (coreSource)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = root / "store"
        for d in ("odoo", "addons", "setup"):
            (self.store / d).mkdir(parents=True)
        (self.store / "setup" / "odoo").write_text("backend\n")
        (self.store / "setup.py").write_text("setup()\n")
        (self.store / ".hidden").write_text("x\n")
        for p in sorted(self.store.rglob("*"), reverse=True):
            p.chmod(0o555 if p.is_dir() else 0o444)
        self.store.chmod(0o555)
        self.addCleanup(
            lambda: [p.chmod(0o755) for p in [self.store, *self.store.rglob("*")]]
        )
        self.link = root / "odoo"
        self.link.symlink_to(self.store)

    def test_shadow_while_locking(self):
        with lock.core_shadow(str(self.link), str(self.store)) as shadow:
            self.assertEqual(os.readlink(self.link), shadow)
            for big in ("odoo", "addons"):
                self.assertEqual(os.readlink(Path(shadow, big)), str(self.store / big))
            self.assertFalse(Path(shadow, "setup.py").is_symlink())
            self.assertEqual(Path(shadow, "setup", "odoo").read_text(), "backend\n")
            self.assertTrue(Path(shadow, ".hidden").exists())
            # setuptools' egg_info writes at the root: it can.
            Path(shadow, "odoo.egg-info").mkdir()
        self.assertEqual(os.readlink(self.link), str(self.store))
        self.assertFalse(os.path.exists(shadow))

    def test_restored_on_failure(self):
        with (
            self.assertRaises(RuntimeError),
            lock.core_shadow(str(self.link), str(self.store)) as shadow,
        ):
            raise RuntimeError
        self.assertEqual(os.readlink(self.link), str(self.store))
        self.assertFalse(os.path.exists(shadow))

    def test_a_missing_link_is_made(self):
        self.link.unlink()
        with lock.core_shadow(str(self.link), str(self.store)) as shadow:
            self.assertEqual(os.readlink(self.link), shadow)
        self.assertEqual(os.readlink(self.link), str(self.store))

    def test_a_checkout_or_no_core_source_is_left_alone(self):
        with lock.core_shadow(str(self.link), None) as shadow:
            self.assertIsNone(shadow)
            self.assertEqual(os.readlink(self.link), str(self.store))
        checkout = self.link.parent / "checkout"
        checkout.mkdir()
        with lock.core_shadow(str(checkout), str(self.store)) as shadow:
            self.assertIsNone(shadow)


class FetchDepthTest(Workspace):
    """How much of a submodule's pinned branch `project update` fetches."""

    def test_by_how_it_was_cloned(self):
        git("init", "-q", "-b", "main", "full")
        git(
            "-C",
            "full",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "1",
        )
        git(
            "-C",
            "full",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "2",
        )
        self.assertEqual(update.fetch_depth("full", "odoo"), [])
        url = Path("full").resolve().as_uri()
        git("clone", "-q", "--depth", "1", url, "shallow")
        self.assertEqual(update.fetch_depth("shallow", "odoo"), ["--depth=1"])
        for path in ("partial", "odoo"):
            git("clone", "-q", url, path)
            git("-C", path, "config", "remote.origin.promisor", "true")
        self.assertEqual(update.fetch_depth("partial", "odoo"), ["--filter=blob:none"])
        self.assertEqual(update.fetch_depth("odoo", "odoo"), [])

    def test_pinned_branch(self):
        git("init", "-q", "-b", "17.0", "sub")
        self.assertEqual(update.pinned_branch("sub"), "17.0")
        git("config", "-f", ".gitmodules", "submodule.sub.branch", "18.0")
        self.assertEqual(update.pinned_branch("sub"), "18.0")


class CoreSourceConfigTest(unittest.TestCase):
    def test_nullable(self):
        self.assertIsNone(config.parse(GOOD).core_source)
        c = config.parse({**GOOD, "coreSource": "/nix/store/x-ocb"})
        self.assertEqual(c.core_source, "/nix/store/x-ocb")
        for bad in ("", 1):
            with self.assertRaises(config.ConfigError):
                config.parse({**GOOD, "coreSource": bad})
        with self.assertRaises(config.ConfigError):
            config.parse({**GOOD, "python": None})


class BuildTest(unittest.TestCase):
    """`odoo module build`: names resolved against odoo-nix-node's targets."""

    KEYS: ClassVar[list[str]] = [
        "custom/acme_ui",
        "modules/frontends",
        "modules/frontends/acme_pos_ui",
        "modules/x/acme_ui",
    ]

    def test_a_key_or_a_unique_last_segment(self):
        from odoo_nix_cli.workspace.build import resolve

        self.assertEqual(
            resolve(self.KEYS, ["custom/acme_ui", "acme_pos_ui", "modules/frontends/"]),
            ["custom/acme_ui", "modules/frontends/acme_pos_ui", "modules/frontends"],
        )

    def test_an_ambiguous_or_unknown_name_stops(self):
        from odoo_nix_cli.workspace.add import Stop
        from odoo_nix_cli.workspace.build import resolve

        with self.assertRaises(Stop) as cm:
            resolve(self.KEYS, ["acme_ui"])
        self.assertIn("custom/acme_ui and modules/x/acme_ui", str(cm.exception))
        with self.assertRaises(Stop) as cm:
            resolve(self.KEYS, ["nope"])
        self.assertEqual(cm.exception.code, 2)

    def test_runs_the_node_command_with_the_keys(self):
        from odoo_nix_cli.workspace.build import build

        with tempfile.TemporaryDirectory() as d:
            log = Path(d, "log")
            node = Path(d, "node")
            node.write_text(
                "#!/bin/sh\n"
                f'echo "$*" >> {log}\n'
                'if [ "$1" = list ]; then echo \'{"custom/acme_ui": {}}\'; fi\n'
            )
            node.chmod(0o755)
            cfg = config.parse({**GOOD, "node": str(node)})
            self.assertEqual(build(cfg, ["acme_ui"]), 0)
            self.assertEqual(
                log.read_text().splitlines(), ["list --json", "build custom/acme_ui"]
            )

    def test_no_node_targets_is_nothing_to_do(self):
        from odoo_nix_cli.workspace.add import Stop
        from odoo_nix_cli.workspace.build import build

        with self.assertRaises(Stop) as cm:
            build(config.parse(GOOD), [])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
