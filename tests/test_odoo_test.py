"""`odoo test` without Odoo: which addons it tests, the odoo-bin command line it
runs (-u on a database, or -i into a fresh one with the series' demo flag),
its log, its coverage variables and its exit code
(lib/odoo_nix_cli/commands/__init__.py, lib/odoo_nix_cli/testrun.py).

$ODOO_NIX_RAW_ODOO is a stand-in that records how it was run, and a stand-in
`odoo` package answers the configuration, the series and the database calls.
odoo-test-ci-18 runs the real Odoo, with coverage and checklog-odoo.

Run: python3 -I tests/test_odoo_test.py <dir holding odoo_nix_cli>   (checks.odoo-test-unit)
with an interpreter that has click and rich (the `odoo` CLI's).
"""

import configparser
import json
import os
import signal
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(sys.argv.pop(1)))

from click.testing import CliRunner
from odoo_nix_cli import testrun
from odoo_nix_cli.commands import cli

# Records its argv and the variables `odoo test` sets, "creates" the database
# an `-i` run names (a line in $FAKE_ODOO_DATABASES, which the stand-in `odoo`
# reads), prints a line to each stream, writes coverage data when asked, and
# exits as told -- or is killed by the signal it is told.
RAW = """#!{python}
import json, os, signal, sys
keys = ("ODOO_NIX_COVERAGE_RCFILE", "COVERAGE_FILE")
with open(os.environ["FAKE_ODOO_RECORD"], "w") as f:
    json.dump({{"argv": sys.argv[1:], "env": {{k: os.environ.get(k) for k in keys}}}}, f)
if "-i" in sys.argv:
    with open(os.environ["FAKE_ODOO_DATABASES"], "a") as f:
        f.write(sys.argv[sys.argv.index("-d") + 1] + "\\n")
clash = os.environ.get("FAKE_ODOO_CLASH")
if clash:
    # Dies binding its port, before any module loads: the first `FAKE_ODOO_CLASH_TIMES` runs.
    count = int(open(clash).read() or 0) if os.path.exists(clash) else 0
    if count < int(os.environ.get("FAKE_ODOO_CLASH_TIMES", "1")):
        with open(clash, "w") as f:
            f.write(str(count + 1))
        with open(os.environ["FAKE_ODOO_RECORD"] + ".%d" % count, "w") as f:
            json.dump(sys.argv[1:], f)
        print("OSError: [Errno 98] Address already in use", file=sys.stderr, flush=True)
        sys.exit(1)
print("2026-11-03 10:00:00,000 1 INFO db odoo.modules.loading: out", flush=True)
print("2026-11-03 10:00:00,001 1 WARNING db odoo.tests: err", file=sys.stderr, flush=True)
if os.environ.get("FAKE_ODOO_COVERAGE") and os.environ.get("ODOO_NIX_COVERAGE_RCFILE"):
    open(os.environ["COVERAGE_FILE"] + ".host.pid1.X1", "w").close()
if os.environ.get("FAKE_ODOO_SIGNAL"):
    os.kill(os.getpid(), int(os.environ["FAKE_ODOO_SIGNAL"]))
sys.exit(int(os.environ.get("FAKE_ODOO_EXIT", "0")))
"""

MANIFEST = '{{"name": "{name}", "version": "18.0.1.0.0", "installable": {installable}}}'


class Odoo:
    """A stand-in `odoo` in sys.modules: the configuration `load_config`
    parses (odoo.conf's `db_name` included), `release.version_info`, and
    18.0's database management (`odoo.service.db`), whose drops land in
    `calls`. Its databases are `existing` and the ones the raw odoo-bin
    created; `list_dbs` and `exp_drop` gate on a pinned `db_name` as 18.0's
    do."""

    def __init__(self, *, created, major=18, existing=()):
        self.calls = []
        self.existing = set(existing)
        self.created = created
        self.modules = {}

        def package(name, **attrs):
            mod = types.ModuleType(name)
            mod.__path__ = []
            mod.__dict__.update(attrs)
            self.modules[name] = mod

        class Config(dict):
            def parse_config(self, args, setup_logging=True):
                parser = configparser.ConfigParser()
                parser.read(args[args.index("-c") + 1])
                self.update(
                    db_name=parser.get("options", "db_name", fallback=False),
                    dbfilter=parser.get("options", "dbfilter", fallback=""),
                )

        self.config = Config()

        package("odoo")
        package("odoo.tools", config=self.config)
        package("odoo.release", version_info=(major, 0, 0, "final", 0, ""))
        package("odoo.modules")
        package("odoo.modules.db", is_initialized=lambda cr: True)
        package(
            "odoo.service.db",
            exp_db_exist=lambda name: name in self.databases(),
            exp_drop=self.drop,
            list_dbs=self.list_dbs,
        )
        package("odoo.service")
        for name, mod in self.modules.items():
            if "." in name:
                parent, _, child = name.rpartition(".")
                setattr(self.modules[parent], child, mod)

    def databases(self):
        made = self.created.read_text().split() if self.created.exists() else []
        return self.existing | set(made)

    def list_dbs(self, force=False):
        pinned = self.config["db_name"]
        if pinned and not self.config["dbfilter"]:
            return sorted(n.strip() for n in pinned.split(","))
        return sorted(self.databases())

    def drop(self, name):
        self.calls.append(("drop", name))
        if name not in self.list_dbs(True):
            return False
        self.existing.discard(name)
        if self.created.exists():
            made = self.created.read_text().split()
            self.created.write_text("".join(f"{n}\n" for n in made if n != name))
        return True

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
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.conf = self.root / "odoo.conf"
        self.conf.write_text("[options]\n")
        self.record = self.tmp / "record.json"
        self.raw = self.tmp / "odoo-bin"
        self.raw.write_text(RAW.format(python=sys.executable))
        self.raw.chmod(0o755)
        self.env = {
            "REPO_ROOT": str(self.root),
            "ODOO_NIX_RAW_ODOO": str(self.raw),
            "ODOO_NIX_TEST_ALLOW_SKIP": "1",
            "FAKE_ODOO_RECORD": str(self.record),
            "FAKE_ODOO_DATABASES": str(self.tmp / "databases"),
            "ODOO_NIX_LOCAL_ADDONS": None,
            "ODOO_NIX_WORKSPACE_CONFIG": None,
            "ODOO_NIX_DB": None,
            "COVERAGE_FILE": None,
            "ODOO_RC": None,
        }
        self.odoo = self.stand_in()

    def stand_in(self, **kwargs):
        if getattr(self, "odoo", None) is not None:
            self.odoo.uninstall()
        odoo = Odoo(created=self.tmp / "databases", **kwargs)
        odoo.install()
        self.addCleanup(odoo.uninstall)
        self.odoo = odoo
        return odoo

    def addon(self, path, name, *, installable=True):
        d = self.root / path / name
        d.mkdir(parents=True)
        (d / "__manifest__.py").write_text(
            MANIFEST.format(name=name, installable=installable)
        )

    def invoke(self, *argv, env=None, **kwargs):
        result = CliRunner().invoke(
            cli,
            ["-c", str(self.conf), *argv],
            env={**self.env, **(env or {})},
            **kwargs,
        )
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result

    def ran(self):
        return json.loads(self.record.read_text())

    def ports(self, argv=None):
        """The `--http-port N --gevent-port M` flags of a run's command line (the
        last run's unless `argv`), checked: two different ports, not odoo.conf's."""
        argv = self.ran()["argv"] if argv is None else argv
        at = argv.index("--http-port")
        flags = argv[at : at + 4]
        self.assertEqual(flags[0::2], ["--http-port", "--gevent-port"], argv)
        http, gevent = int(flags[1]), int(flags[3])
        self.assertNotEqual(http, gevent)
        self.assertNotIn(10428, (http, gevent))
        return flags


class UpdateTest(Case):
    """MODULES DATABASE: -u on an existing database, as before."""

    def test_argv(self):
        result = self.invoke("test", "a,b", "mydb")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            self.ran()["argv"],
            [
                "-c",
                str(self.conf),
                "-d",
                "mydb",
                "-u",
                "a,b",
                "--test-enable",
                "--test-tags",
                "/a,/b",
                "--stop-after-init",
                "--logfile=",
                *self.ports(),
            ],
        )
        self.assertEqual(self.ran()["env"]["ODOO_NIX_COVERAGE_RCFILE"], None)

    def test_exit_code_is_odoos(self):
        result = self.invoke("test", "a", "mydb", env={"FAKE_ODOO_EXIT": "3"})
        self.assertEqual(result.exit_code, 3)
        self.assertIn("Odoo exited 3", result.output)

    def test_killed_by_a_signal(self):
        # Popen's -15 is reported as the shell would: 128 + 15.
        result = self.invoke(
            "test", "a", "mydb", env={"FAKE_ODOO_SIGNAL": str(int(signal.SIGTERM))}
        )
        self.assertEqual(result.exit_code, 128 + signal.SIGTERM)
        self.assertIn(f"killed by signal {int(signal.SIGTERM)}", result.output)

    def test_connection_flags(self):
        result = self.invoke("--db-host", "/run/pg", "test", "a", "mydb")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.ran()["argv"][-2:], ["--db_host", "/run/pg"])
        # ...after the run's own ports.
        self.assertEqual(self.ran()["argv"][-6:-2], self.ports())

    def test_configured_database(self):
        result = self.invoke("test", "a", env={"ODOO_NIX_DB": "envdb"})
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.ran()["argv"][3], "envdb")

    def test_no_database(self):
        result = self.invoke("test", "a")
        self.assertEqual(result.exit_code, 2)
        self.assertIn("no database given", result.output)
        self.assertFalse(self.record.exists())

    def test_tours_refused(self):
        # Neither websocket-client nor a browser here: refused unless allowed.
        result = self.invoke(
            "test", "a", "mydb", env={"ODOO_NIX_TEST_ALLOW_SKIP": None, "PATH": ""}
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Browser tours cannot run here", result.output)
        self.assertFalse(self.record.exists())


class PortsTest(Case):
    """A test run binds ports of its own, never odoo.conf's (the dev server's, or
    a CI runner's other job's)."""

    def test_odoo_conf_ports_are_overridden(self):
        self.conf.write_text("[options]\nhttp_port = 10428\ngevent_port = 11428\n")
        result = self.invoke("test", "a", "mydb")
        self.assertEqual(result.exit_code, 0, result.output)
        flags = self.ports()
        self.assertIn(f"HTTP on port {flags[1]}, gevent on {flags[3]}", result.output)

    def test_ports_are_free_and_distinct(self):
        import socket

        for interface in ("127.0.0.1", "", "::1", "localhost"):
            with self.subTest(interface=interface):
                ports = testrun.free_ports(interface, 4)
                self.assertEqual(len(set(ports)), 4, ports)
                host = interface or "0.0.0.0"
                # werkzeug's rule (select_address_family): IPv6 only for a literal
                # with a colon; "localhost" is IPv4 to Odoo whatever getaddrinfo lists first.
                family = socket.AF_INET6 if ":" in host else socket.AF_INET
                for port in ports:
                    with socket.socket(family, socket.SOCK_STREAM) as s:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        s.bind((host, port))

    def test_never_a_port_that_is_taken(self):
        import socket

        # A dev server on the port: a pick never lands on one held open.
        with socket.socket() as held:
            held.bind(("127.0.0.1", 0))
            held.listen()
            taken = held.getsockname()[1]
            for _ in range(200):
                self.assertNotIn(taken, testrun.free_ports("127.0.0.1", 2))

    def test_http_interface_of_odoo_conf_is_probed(self):
        seen = []
        original = testrun.free_ports
        testrun.free_ports = lambda interface, count=2: (
            seen.append(interface) or original(interface, count)
        )
        self.addCleanup(setattr, testrun, "free_ports", original)
        self.odoo.config["http_interface"] = "127.0.0.1"
        result = self.invoke("test", "a", "mydb")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(seen, ["127.0.0.1"])

    def test_fresh_runs_pick_their_own(self):
        # Two runs side by side (a runner's concurrent jobs) do not share a port.
        first = set(testrun.free_ports("127.0.0.1", 2))
        second = set(testrun.free_ports("127.0.0.1", 2))
        self.assertTrue(first and second)

    def test_bind_clash(self):
        early = b"queue_job.post_load: x\nOSError: [Errno 98] Address already in use\n"
        self.assertTrue(testrun.bind_clash(early))
        # After modules loaded it is a test's own business, not Odoo's start.
        late = b"odoo.modules.loading: loading 1 modules\n" + early
        self.assertFalse(testrun.bind_clash(late))
        self.assertFalse(testrun.bind_clash(b"odoo.modules.loading: ok\n"))

    def test_retried_on_another_port_when_taken_meanwhile(self):
        log = self.root / "odoo.log"
        clash = self.tmp / "clash"
        result = self.invoke(
            "test",
            "a",
            "--fresh-db",
            "--log",
            str(log),
            env={"FAKE_ODOO_CLASH": str(clash)},
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("trying other ports", result.output)
        first = json.loads(Path(f"{self.record}.0").read_text())
        self.assertNotEqual(self.ports(first), self.ports())
        # The failed attempt's database is dropped before the next one, then the last.
        self.assertEqual(self.odoo.calls, [("drop", self.name())] * 2)
        # The log is the last run's: checklog-odoo must not see the failed one.
        self.assertNotIn("Address already in use", log.read_text())

    def test_gives_up_after_the_attempts(self):
        log = self.root / "odoo.log"
        result = self.invoke(
            "test",
            "a",
            "mydb",
            "--log",
            str(log),
            env={
                "FAKE_ODOO_CLASH": str(self.tmp / "clash"),
                "FAKE_ODOO_CLASH_TIMES": "99",
            },
        )
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            result.output.count("trying other ports"), testrun.PORT_ATTEMPTS - 1
        )
        self.assertIn("Odoo exited 1", result.output)

    def test_other_failures_are_not_retried(self):
        result = self.invoke(
            "test",
            "a",
            "mydb",
            "--log",
            str(self.tmp / "l"),
            env={"FAKE_ODOO_EXIT": "1"},
        )
        self.assertEqual(result.exit_code, 1)
        self.assertNotIn("trying other ports", result.output)

    def name(self):
        return f"odoo_nix_test_{os.getpid()}"


class UsageTest(Case):
    def test_refusals(self):
        for argv, text in (
            (["test"], "give MODULES"),
            (["test", "--all", "a", "db"], "at most DATABASE"),
            (["test", "a", "db", "--keep-db"], "--keep-db keeps"),
            (["test", "a", "db", "--fresh-db"], "makes its own database"),
        ):
            with self.subTest(argv=argv):
                result = self.invoke(*argv)
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn(text, result.output)
        self.assertFalse(self.record.exists())

    def test_help(self):
        result = self.invoke("test", "--help")
        for flag in ("--all", "--fresh-db", "--keep-db", "--coverage", "--log"):
            self.assertIn(flag, result.output)


class AllTest(Case):
    """--all: the repository's installable addons, minus the untested ones."""

    def project(self):
        self.addon("custom", "x")
        self.addon("custom", "w")
        self.addon("custom", "legacy", installable=False)
        self.addon("custom", "demo_data")
        (self.root / "pyproject.toml").write_text(
            textwrap.dedent(
                """\
                [project]
                name = "p"

                [tool.odoo-nix]
                schema = 1

                [[tool.odoo-nix.untested]]
                addon = "demo_data"
                reason = "data only, no code to test"
                """
            )
        )

    def test_project(self):
        self.project()
        result = self.invoke("test", "--all", "mydb")
        self.assertEqual(result.exit_code, 0, result.output)
        argv = self.ran()["argv"]
        self.assertEqual(argv[3], "mydb")
        self.assertEqual(argv[4:6], ["-u", "w,x"])
        self.assertEqual(argv[7:9], ["--test-tags", "/w,/x"])

    def test_addons_mode(self):
        self.addon(".", "a")
        self.addon(".", "b")
        (self.root / "nix").mkdir()
        (self.root / "nix" / "pyproject.toml").write_text(
            '[tool.odoo-nix]\nuntested = [{addon = "b", reason = "a theme, no code"}]\n'
        )
        result = self.invoke(
            "test", "--all", "mydb", env={"ODOO_NIX_LOCAL_ADDONS": "."}
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.ran()["argv"][4:6], ["-u", "a"])

    def test_workspace_custom_dir(self):
        self.addon("addons", "q")
        config = self.tmp / "workspace.json"
        config.write_text(json.dumps({"layout": {"customDir": "addons"}}))
        result = self.invoke(
            "test",
            "--all",
            "mydb",
            env={"ODOO_NIX_WORKSPACE_CONFIG": str(config)},
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.ran()["argv"][4:6], ["-u", "q"])

    def test_nothing_to_test(self):
        self.addon("custom", "demo_data")
        (self.root / "pyproject.toml").write_text(
            '[tool.odoo-nix]\nuntested = [{addon = "demo_data", reason = "data only here"}]\n'
        )
        result = self.invoke("test", "--all", "mydb")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("no addon to test in custom/", result.output)

    def test_not_opted_in(self):
        self.addon("custom", "x")
        (self.root / "pyproject.toml").write_text('[project]\nname = "p"\n')
        result = self.invoke("test", "--all", "mydb")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.ran()["argv"][4:6], ["-u", "x"])


class FreshDbTest(Case):
    """--fresh-db: -i into odoo_nix_test_<pid>, dropped unless --keep-db."""

    def name(self):
        return f"odoo_nix_test_{os.getpid()}"

    def test_18(self):
        result = self.invoke("test", "a,b", "--fresh-db")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            self.ran()["argv"],
            [
                "-c",
                str(self.conf),
                "-d",
                self.name(),
                "-i",
                "a,b",
                "--without-demo=",
                "--test-enable",
                "--test-tags",
                "/a,/b",
                "--stop-after-init",
                "--logfile=",
                "--workers=0",
                *self.ports(),
            ],
        )
        self.assertEqual(self.odoo.calls, [("drop", self.name())])
        self.assertIn(f"dropped the test database '{self.name()}'", result.output)

    def test_dropped_when_odoo_conf_pins_db_name(self):
        # The dev shell writes `db_name = <dbName>` and no dbfilter; 18.0's
        # exp_drop would then see only that database and drop nothing.
        self.conf.write_text("[options]\ndb_name = odoo_dev\n")
        result = self.invoke("test", "a", "--fresh-db")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.ran()["argv"][3], self.name())
        self.assertIn(f"dropped the test database '{self.name()}'", result.output)

    def test_drop_refused_is_reported(self):
        # A database Odoo does not list is not dropped, and says so.
        self.conf.write_text("[options]\ndb_name = odoo_dev\n")
        result = self.invoke(
            "test",
            "a",
            "--fresh-db",
            env={"FAKE_ODOO_DATABASES": str(self.tmp / "elsewhere")},
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(f"did not drop the test database '{self.name()}'", result.output)

    def test_19_and_later(self):
        for major in (19, 20):
            with self.subTest(major=major):
                self.stand_in(major=major)
                result = self.invoke("test", "a", "--fresh-db")
                self.assertEqual(result.exit_code, 0, result.output)
                argv = self.ran()["argv"]
                self.assertIn("--with-demo", argv)
                self.assertNotIn("--without-demo=", argv)

    def test_keep_db(self):
        result = self.invoke("test", "a", "--fresh-db", "--keep-db")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.odoo.calls, [])
        self.assertIn(f"kept the test database '{self.name()}'", result.output)

    def test_dropped_after_a_failure(self):
        result = self.invoke("test", "a", "--fresh-db", env={"FAKE_ODOO_EXIT": "1"})
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(self.odoo.calls, [("drop", self.name())])

    def test_existing_database_refused(self):
        self.stand_in(existing=[self.name()])
        result = self.invoke("test", "a", "--fresh-db")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("already exists", result.output)
        self.assertFalse(self.record.exists())
        self.assertEqual(self.odoo.calls, [])

    def test_all(self):
        self.addon("custom", "x")
        result = self.invoke("test", "--all", "--fresh-db")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.ran()["argv"][4:6], ["-i", "x"])


class LogTest(Case):
    def test_both_streams_in_order(self):
        log = self.root / ".odoo-nix" / "test" / "odoo.log"
        result = self.invoke("test", "a", "mydb", "--log", str(log))
        self.assertEqual(result.exit_code, 0, result.output)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].endswith("odoo.modules.loading: out"))
        self.assertTrue(lines[1].endswith("odoo.tests: err"))
        # ...and on the terminal as well.
        self.assertIn("odoo.tests: err", result.output)

    def test_written_when_the_run_fails(self):
        log = self.tmp / "odoo.log"
        result = self.invoke(
            "test", "a", "mydb", "--log", str(log), env={"FAKE_ODOO_EXIT": "1"}
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("odoo.tests: err", log.read_text())


class CoverageTest(Case):
    def rcfile(self):
        rc = self.root / "tools" / "pyproject.toml"
        rc.parent.mkdir()
        rc.write_text("[tool.coverage.run]\nsource = ['custom']\n")
        return rc

    def test_variables(self):
        rc = self.rcfile()
        data = self.root / ".odoo-nix" / "coverage" / ".coverage"
        data.parent.mkdir(parents=True)
        stale = data.with_name(".coverage.old.pid9.X9")
        stale.write_text("")
        unrelated = data.with_name("coverage.xml")
        unrelated.write_text("")
        result = self.invoke(
            "test",
            "a",
            "mydb",
            "--coverage",
            str(rc),
            env={"FAKE_ODOO_COVERAGE": "1"},
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            self.ran()["env"],
            {"ODOO_NIX_COVERAGE_RCFILE": str(rc.resolve()), "COVERAGE_FILE": str(data)},
        )
        # A former run's data is gone; this run's is there; other files stay.
        self.assertFalse(stale.exists())
        self.assertEqual(
            [p.name for p in testrun.coverage_files(data)], [".coverage.host.pid1.X1"]
        )
        self.assertTrue(unrelated.exists())

    def test_exported_coverage_file_kept(self):
        rc = self.rcfile()
        data = self.tmp / "elsewhere" / ".coverage"
        result = self.invoke(
            "test",
            "a",
            "mydb",
            "--coverage",
            str(rc),
            env={"FAKE_ODOO_COVERAGE": "1", "COVERAGE_FILE": str(data)},
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.ran()["env"]["COVERAGE_FILE"], str(data))
        self.assertTrue(data.parent.is_dir())

    def test_relative_coverage_file(self):
        # Relative to the repository root, where the raw odoo-bin runs,
        # not to wherever `odoo test` was started.
        rc = self.rcfile()
        result = self.invoke(
            "test",
            "a",
            "mydb",
            "--coverage",
            str(rc),
            env={"FAKE_ODOO_COVERAGE": "1", "COVERAGE_FILE": "cov/.coverage"},
        )
        self.assertEqual(result.exit_code, 0, result.output)
        data = self.root / "cov" / ".coverage"
        self.assertEqual(self.ran()["env"]["COVERAGE_FILE"], str(data))
        self.assertEqual(
            [p.name for p in testrun.coverage_files(data)], [".coverage.host.pid1.X1"]
        )

    def test_no_hook(self):
        # An Odoo without lib/raw-odoo.nix's coverage hook writes no data.
        rc = self.rcfile()
        result = self.invoke("test", "a", "mydb", "--coverage", str(rc))
        self.assertEqual(result.exit_code, 1)
        self.assertIn("no coverage hook", result.output)

    def test_missing_rcfile(self):
        result = self.invoke("test", "a", "mydb", "--coverage", "nope.toml")
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(self.record.exists())


class PiecesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_demo_args(self):
        self.assertEqual(testrun.demo_args(18), ["--without-demo="])
        self.assertEqual(testrun.demo_args(19), ["--with-demo"])

    def test_root_table_first(self):
        (self.root / "nix").mkdir()
        (self.root / "pyproject.toml").write_text(
            '[tool.odoo-nix]\nuntested = [{addon = "r", reason = "the root one"}]\n'
        )
        (self.root / "nix" / "pyproject.toml").write_text(
            '[tool.odoo-nix]\nuntested = [{addon = "n", reason = "the nix one"}]\n'
        )
        self.assertEqual(testrun.untested(self.root), {"r"})

    def test_untested_shape(self):
        for text in (
            "[tool.odoo-nix]\nuntested = 'x'\n",
            "[tool.odoo-nix]\nuntested = [{reason = 'no addon key here'}]\n",
            "[tool.odoo-nix\n",
        ):
            with self.subTest(text=text):
                (self.root / "pyproject.toml").write_text(text)
                with self.assertRaises(testrun.OdooTestError):
                    testrun.untested(self.root)

    def test_unreadable_manifest_skipped(self):
        bad = self.root / "bad"
        bad.mkdir()
        (bad / "__manifest__.py").write_text("{'name': compute()}")
        good = self.root / "good"
        good.mkdir()
        (good / "__manifest__.py").write_text("{'name': 'good'}")
        self.assertEqual(testrun.installable_addons(self.root), ["good"])


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], "-v"])
