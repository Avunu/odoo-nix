"""odoo_journald (lib/journald/odoo_journald, as lib/journald.nix grafts it)
without Odoo: the line format (python-devops-nix CONVENTIONS.md, Journald
line format: `<N>{logger} [{db}] msg`, every line of a traceback prefixed,
Odoo's perf_info after the message), and the whole path a production start
takes -- the `odoo` CLI execs "odoo-bin", whose environment's `.pth` graft
patches init_logger as it is imported -- against a stand-in `odoo.netsvc`
shaped like OCB's (DBFormatter on a stderr StreamHandler, the asctime/pid
format).

Run: python3 tests/test_journald.py <graft> <cli package>   (checks.journald-formatter)
  graft        lib/journald.nix's output ($out/odoo_journald)
  cli package  lib/cli-package.nix's output ($out/odoo_nix_cli)
"""

import logging
import os
import subprocess
import sys
import tempfile
import threading
import unittest

CLI = os.path.abspath(sys.argv.pop(2))
GRAFT = os.path.abspath(sys.argv.pop(1))
sys.path.insert(0, GRAFT)

import odoo_journald

# OCB 18.0's netsvc, reduced to what init_logger does with the stderr handler.
FAKE_NETSVC = """
import logging, os, sys, threading

class DBFormatter(logging.Formatter):
    def format(self, record):
        record.pid = os.getpid()
        record.dbname = getattr(threading.current_thread(), 'dbname', '?')
        return logging.Formatter.format(self, record)

def init_logger():
    format = '%(asctime)s %(pid)s %(levelname)s %(dbname)s %(name)s: %(message)s %(perf_info)s'
    old = logging.getLogRecordFactory()
    def factory(*a, **kw):
        record = old(*a, **kw)
        record.perf_info = ''
        return record
    logging.setLogRecordFactory(factory)
    handler = logging.StreamHandler()
    handler.setFormatter(DBFormatter(format))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
"""

# Stands in for odoo-bin run by the environment's interpreter: the site
# directory's .pth files run first (as `site` does for a virtualenv), then it
# imports netsvc the way tools/config.py does and calls it through the module
# attribute.
FAKE_ODOO_BIN = """
import site, sys
site.addsitedir(sys.argv[1])
import logging, threading
import odoo.netsvc
odoo.netsvc.init_logger()
log = logging.getLogger('odoo.fake')
log.info('starting')
threading.current_thread().dbname = 'acme'
log.info('hello')
log.warning('careful')
try:
    raise ValueError('boom')
except ValueError:
    log.exception('failed')
"""


def record(level, msg, exc_info=None, **attrs):
    rec = logging.LogRecord("odoo.test", level, __file__, 1, msg, None, exc_info)
    for k, v in attrs.items():
        setattr(rec, k, v)
    return rec


def fmt(rec):
    return odoo_journald.OdooFormatter().format(rec)


class Formatter(unittest.TestCase):
    def test_priorities(self):
        for level, prio in [
            (logging.DEBUG, 7),
            (9, 7),  # odoo DEBUG_RPC
            (logging.INFO, 6),
            (25, 6),  # odoo RUNBOT
            (logging.WARNING, 4),
            (logging.ERROR, 3),
            (logging.CRITICAL, 2),
        ]:
            self.assertTrue(fmt(record(level, "x")).startswith(f"<{prio}>"), level)

    def test_line(self):
        self.assertEqual(
            fmt(record(logging.WARNING, "hi", dbname="acme")), "<4>odoo.test [acme] hi"
        )

    def test_dbname_from_thread_and_perf_info(self):
        # 18.0: dbname is not on the record, only on the thread
        threading.current_thread().dbname = "t1"
        try:
            out = fmt(record(logging.INFO, "GET /", perf_info="3 0.002 0.010"))
        finally:
            del threading.current_thread().dbname
        self.assertEqual(out, "<6>odoo.test [t1] GET / 3 0.002 0.010")

    def test_no_database(self):
        # Odoo's "no database" is '?': no brackets at all, as with none
        self.assertEqual(fmt(record(logging.INFO, "x")), "<6>odoo.test x")
        self.assertEqual(fmt(record(logging.INFO, "x", dbname="?")), "<6>odoo.test x")

    def test_ansi_stripped(self):
        out = fmt(record(logging.INFO, "\x1b[1;32mgreen\x1b[0m", dbname="d"))
        self.assertEqual(out, "<6>odoo.test [d] green")

    def test_traceback_every_line_prefixed(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()
        out = fmt(
            record(
                logging.ERROR,
                "failed\nsecond",
                exc_info,
                dbname="d",
                perf_info="1 0.1 0.2",
            )
        )
        lines = out.split("\n")
        self.assertGreater(len(lines), 3)
        # perf_info stays on the message's line, not after the traceback
        self.assertEqual(lines[0], "<3>odoo.test [d] failed 1 0.1 0.2")
        self.assertEqual(lines[1], "<3>second")
        self.assertTrue(all(line.startswith("<3>") for line in lines), lines)
        self.assertEqual(lines[-1], "<3>RuntimeError: boom")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        os.makedirs(os.path.join(t, "fake", "odoo"))
        with open(os.path.join(t, "fake", "odoo", "__init__.py"), "w"):
            pass
        with open(os.path.join(t, "fake", "odoo", "netsvc.py"), "w") as f:
            f.write(FAKE_NETSVC)
        # The environment's site-packages, as lib.python.withGrafts leaves it.
        self.site = os.path.join(t, "site")
        os.makedirs(self.site)
        os.symlink(
            os.path.join(GRAFT, "odoo_journald"),
            os.path.join(self.site, "odoo_journald"),
        )
        with open(os.path.join(self.site, "zzz-odoo-journald.pth"), "w") as f:
            f.write("import odoo_journald; odoo_journald.install()\n")
        script = os.path.join(t, "odoo-bin.py")
        with open(script, "w") as f:
            f.write(FAKE_ODOO_BIN)
        self.odoo_bin = os.path.join(t, "odoo-bin")
        with open(self.odoo_bin, "w") as f:
            f.write(f'#!/bin/sh\nexec {sys.executable} {script} {self.site} "$@"\n')
        os.chmod(self.odoo_bin, 0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def run_odoo(self, journal_stream_matches=True, extra_env=None):
        """`odoo -c ...` as odoo.service runs it: the CLI, with the
        environment on PYTHONPATH, execs odoo-bin."""
        t = self.tmp.name
        err_path = os.path.join(t, "stderr")
        with open(err_path, "w") as err:
            st = os.fstat(err.fileno())
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": os.pathsep.join([CLI, os.path.join(t, "fake"), GRAFT]),
                "ODOO_NIX_RAW_ODOO": self.odoo_bin,
                "JOURNAL_STREAM": f"{st.st_dev}:{st.st_ino + (0 if journal_stream_matches else 1)}",
                **(extra_env or {}),
            }
            subprocess.run(
                [sys.executable, "-m", "odoo_nix_cli", "-c", "/dev/null"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=err,
                check=True,
            )
        with open(err_path) as f:
            return f.read().splitlines()

    def test_journald(self):
        lines = self.run_odoo()
        self.assertEqual(lines[0], "<6>odoo.fake starting")
        self.assertEqual(lines[1], "<6>odoo.fake [acme] hello")
        self.assertEqual(lines[2], "<4>odoo.fake [acme] careful")
        self.assertEqual(lines[3], "<3>odoo.fake [acme] failed")
        self.assertTrue(all(line.startswith("<3>") for line in lines[3:]), lines)
        self.assertEqual(lines[-1], "<3>ValueError: boom")

    def test_not_the_journal(self):
        # $JOURNAL_STREAM inherited, but stderr is somewhere else: Odoo's format
        lines = self.run_odoo(journal_stream_matches=False)
        self.assertRegex(
            lines[1], r"^\d{4}-\d\d-\d\d .* \d+ INFO acme odoo\.fake: hello $"
        )

    def test_old_switch_warns_and_changes_nothing(self):
        # $ODOO_NIX_JOURNALD is accepted, and ignored with a warning, through
        # 1.x: "0" no longer turns the journal format off.
        lines = self.run_odoo(extra_env={"ODOO_NIX_JOURNALD": "0"})
        self.assertRegex(
            lines[0], r"^<4>odoo_nix \$ODOO_NIX_JOURNALD is no longer read"
        )
        self.assertEqual(lines[2], "<6>odoo.fake [acme] hello")
        self.assertFalse(any("no longer read" in line for line in self.run_odoo()))

    def test_cli_root_handler(self):
        # The CLI's own commands, where init_logger never runs: WARNING and up
        # through the journal format, once, only when stderr is the journal.
        code = (
            "import logging, odoo_journald\n"
            "odoo_journald.install_root_handler(); odoo_journald.install_root_handler()\n"
            "root = logging.getLogger()\n"
            "print(len(root.handlers), type(root.handlers[0].formatter).__name__ if root.handlers else '-',"
            " root.handlers[0].level if root.handlers else '-')\n"
        )
        for matches, expected in ((True, "1 OdooFormatter 30"), (False, "0 - -")):
            with tempfile.TemporaryFile() as err:
                st = os.fstat(err.fileno())
                out = subprocess.run(
                    [sys.executable, "-c", code],
                    env={
                        "PYTHONPATH": GRAFT,
                        "JOURNAL_STREAM": f"{st.st_dev}:{st.st_ino + (0 if matches else 1)}",
                    },
                    stdout=subprocess.PIPE,
                    stderr=err,
                    text=True,
                    check=True,
                ).stdout.strip()
            self.assertEqual(out, expected, matches)


if __name__ == "__main__":
    unittest.main(verbosity=2)
