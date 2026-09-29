"""lib/odoo_nix_cli/journald.py without Odoo: the formatter's contract
(level -> sd-daemon prefix, every line of a traceback prefixed, no asctime /
pid / colour), and the whole path a production start takes -- `odoo` puts the
sitecustomize on PYTHONPATH and execs "odoo-bin", whose init_logger is
patched on import -- against a stand-in `odoo.netsvc` shaped like OCB's
(DBFormatter on a stderr StreamHandler, the asctime/pid format).

Run: python3 tests/test_journald.py <path to lib/>   (checks.journald-formatter)
"""
import logging
import os
import subprocess
import sys
import tempfile
import threading
import unittest

LIB = os.path.abspath(sys.argv.pop(1)) if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, LIB)

from odoo_nix_cli import journald

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

# Stands in for odoo-bin: imports netsvc the way tools/config.py does and
# calls it through the module attribute.
FAKE_ODOO_BIN = """
import logging, os, threading
import odoo.netsvc
odoo.netsvc.init_logger()
threading.current_thread().dbname = 'acme'
log = logging.getLogger('odoo.fake')
log.info('hello')
log.warning('careful')
try:
    raise ValueError('boom')
except ValueError:
    log.exception('failed')
print('SHADOWED=' + os.environ.get('SHADOWED_SITECUSTOMIZE_RAN', '0'))
"""


def record(level, msg, exc_info=None, **attrs):
    rec = logging.LogRecord("odoo.test", level, __file__, 1, msg, None, exc_info)
    for k, v in attrs.items():
        setattr(rec, k, v)
    return rec


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
            self.assertEqual(journald.priority(level), prio, level)

    def test_line(self):
        out = journald.JournaldFormatter().format(record(logging.WARNING, "hi", dbname="acme"))
        self.assertEqual(out, "<4>acme odoo.test: hi")

    def test_dbname_from_thread_and_perf_info(self):
        # 18.0: dbname is not on the record, only on the thread
        threading.current_thread().dbname = "t1"
        try:
            out = journald.JournaldFormatter().format(record(logging.INFO, "GET /", perf_info="3 0.002 0.010"))
        finally:
            del threading.current_thread().dbname
        self.assertEqual(out, "<6>t1 odoo.test: GET / 3 0.002 0.010")
        self.assertEqual(journald.JournaldFormatter().format(record(logging.INFO, "x")), "<6>? odoo.test: x")

    def test_ansi_stripped(self):
        out = journald.JournaldFormatter().format(record(logging.INFO, "\x1b[1;32mgreen\x1b[0m", dbname="d"))
        self.assertEqual(out, "<6>d odoo.test: green")

    def test_traceback_every_line_prefixed(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()
        out = journald.JournaldFormatter().format(record(logging.ERROR, "failed\nsecond", exc_info, dbname="d"))
        lines = out.split("\n")
        self.assertGreater(len(lines), 3)
        self.assertEqual(lines[0], "<3>d odoo.test: failed")
        self.assertEqual(lines[1], "<3>second")
        self.assertTrue(all(line.startswith("<3>") for line in lines), lines)
        self.assertEqual(lines[-1], "<3>RuntimeError: boom")

    def test_root_handler(self):
        root = logging.getLogger()
        before = list(root.handlers)
        try:
            journald.install_root_handler()
            journald.install_root_handler()  # idempotent
            added = [h for h in root.handlers if h not in before]
            self.assertEqual(len(added), 1)
            self.assertIsInstance(added[0].formatter, journald.JournaldFormatter)
            self.assertEqual(added[0].level, logging.WARNING)
        finally:
            root.handlers[:] = before


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        os.makedirs(os.path.join(t, "fake", "odoo"))
        with open(os.path.join(t, "fake", "odoo", "__init__.py"), "w"):
            pass
        with open(os.path.join(t, "fake", "odoo", "netsvc.py"), "w") as f:
            f.write(FAKE_NETSVC)
        self.odoo_bin = os.path.join(t, "odoo-bin")
        with open(self.odoo_bin, "w") as f:
            f.write(f"#!{sys.executable}\n{FAKE_ODOO_BIN}")
        os.chmod(self.odoo_bin, 0o755)
        # An existing sitecustomize further down the path (nixpkgs' own
        # interpreter ships one) must still run.
        os.makedirs(os.path.join(t, "shadowed"))
        with open(os.path.join(t, "shadowed", "sitecustomize.py"), "w") as f:
            f.write("import os\nos.environ['SHADOWED_SITECUSTOMIZE_RAN'] = '1'\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_odoo(self, journal_stream_matches=True, flag="1"):
        t = self.tmp.name
        err_path = os.path.join(t, "stderr")
        with open(err_path, "w") as err:
            st = os.fstat(err.fileno())
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": os.pathsep.join([LIB, os.path.join(t, "fake"), os.path.join(t, "shadowed")]),
                "ODOO_NIX_RAW_ODOO": self.odoo_bin,
                "ODOO_NIX_JOURNALD": flag,
                "JOURNAL_STREAM": f"{st.st_dev}:{st.st_ino + (0 if journal_stream_matches else 1)}",
            }
            out = subprocess.run(
                [sys.executable, "-m", "odoo_nix_cli", "-c", "/dev/null"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=err,
                text=True,
                check=True,
            ).stdout
        with open(err_path) as f:
            return out, f.read().splitlines()

    def test_journald(self):
        out, lines = self.run_odoo()
        self.assertIn("SHADOWED=1", out)
        self.assertEqual(lines[0], "<6>acme odoo.fake: hello")
        self.assertEqual(lines[1], "<4>acme odoo.fake: careful")
        self.assertEqual(lines[2], "<3>acme odoo.fake: failed")
        self.assertTrue(all(line.startswith("<3>") for line in lines[2:]), lines)
        self.assertEqual(lines[-1], "<3>ValueError: boom")

    def test_not_the_journal(self):
        # $JOURNAL_STREAM inherited, but stderr is somewhere else: Odoo's format
        for kwargs in ({"journal_stream_matches": False}, {"flag": ""}):
            out, lines = self.run_odoo(**kwargs)
            self.assertIn("SHADOWED=1", out)
            self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\d .* \d+ INFO acme odoo\.fake: hello $", kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
