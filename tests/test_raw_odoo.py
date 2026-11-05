"""lib/raw-odoo.nix with stand-in OCB trees: a tree's odoo-bin when it has one,
and Odoo as `python -m odoo` runs it when it has none (an Enterprise tree can
come without odoo-bin). A tree with neither, such as an uninitialised
submodule, fails and names the tree, rather than running the wheel's Odoo.
The checks' built-odoo-no-odoo-bin-<major> run the real Odoo the second way.

With a coverage.py (the dev shell's), $ODOO_NIX_COVERAGE_RCFILE runs either
way under `coverage run --parallel-mode`, and the data lands where
$COVERAGE_FILE says; unset, or without coverage, the run is the plain one.
odoo-test-ci-18 measures the real Odoo.

Run: python3 -I tests/test_raw_odoo.py <script> <script-with-coverage>   (checks.raw-odoo)
  <script>                the shell text, run as `<script> <tree> <args...>`
  <script-with-coverage>  the same, built with `coverage`
"""

import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = os.path.abspath(sys.argv.pop(1))
MEASURED = os.path.abspath(sys.argv.pop(1))

ODOO_BIN = """import json, sys
print(json.dumps({"via": "odoo-bin", "argv": sys.argv[1:]}))
"""

# odoo/__main__.py, shaped like OCB's: a relative import, so it cannot run as
# a script. `spawn` runs sys.argv[0] again as `gevent`, the way Odoo's
# prefork server starts its websocket worker and --dev=reload re-executes.
MAIN = """import json, subprocess, sys

from . import here

if sys.argv[1:] == ["spawn"]:
    cmd = [sys.executable, sys.argv[0], "gevent"]
    print(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout, end="")
else:
    print(json.dumps({"via": here, "argv": sys.argv[1:], "argv0": sys.argv[0]}))
"""


class Trees(unittest.TestCase):
    """A stand-in OCB tree, and an `odoo` wheel in the environment."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tree = self.root / "odoo"
        self.package(self.tree, "the tree")
        # The wheel in the environment: the tree's `odoo` must win over it.
        self.package(self.root / "wheel", "the wheel")

    def tearDown(self):
        self.tmp.cleanup()

    def package(self, where, here):
        pkg = where / "odoo"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text(f"here = {here!r}\n")
        (pkg / "__main__.py").write_text(MAIN)

    def run_raw(self, tree, *argv, check=True, script=SCRIPT, env=None):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(self.root / "wheel"),
            **(env or {}),
        }
        return subprocess.run(
            [script, str(tree), *argv],
            env=env,
            capture_output=True,
            text=True,
            check=check,
        )

    def run_odoo(self, *argv):
        return json.loads(self.run_raw(self.tree, *argv).stdout)


class RawOdooTest(Trees):
    def test_odoo_bin(self):
        (self.tree / "odoo-bin").write_text(ODOO_BIN)
        self.assertEqual(
            self.run_odoo("-c", "odoo.conf", "--dev=all"),
            {"via": "odoo-bin", "argv": ["-c", "odoo.conf", "--dev=all"]},
        )

    def test_no_odoo_bin(self):
        out = self.run_odoo("-c", "odoo.conf", "--dev=all")
        self.assertEqual(out["via"], "the tree")
        self.assertEqual(out["argv"], ["-c", "odoo.conf", "--dev=all"])
        self.assertEqual(Path(out["argv0"]).name, "odoo-bin")
        self.assertNotEqual(Path(out["argv0"]).parent, self.tree)

    def test_no_odoo_bin_runs_again(self):
        out = self.run_odoo("spawn")
        self.assertEqual(out["via"], "the tree")
        self.assertEqual(out["argv"], ["gevent"])

    def test_no_tree(self):
        # An uninitialised submodule: an empty directory, or none at all. The
        # error names the tree, and the wheel's Odoo does not run.
        empty = self.root / "empty"
        empty.mkdir()
        for tree in (empty, self.root / "missing"):
            with self.subTest(tree=tree.name):
                run = self.run_raw(tree, "--version", check=False)
                self.assertNotEqual(run.returncode, 0)
                self.assertNotIn("the wheel", run.stdout)
                self.assertIn(str(tree / "odoo-bin"), run.stderr)


class CoverageHookTest(Trees):
    """$ODOO_NIX_COVERAGE_RCFILE: the run under coverage, either entry point."""

    def setUp(self):
        super().setUp()
        self.data = self.root / "data" / ".coverage"
        self.rcfile = self.root / "rc.toml"
        self.rcfile.write_text(
            f"[tool.coverage.run]\nsource = [{str(self.tree)!r}]\nbranch = true\n"
        )
        self.env = {
            "ODOO_NIX_COVERAGE_RCFILE": str(self.rcfile),
            "COVERAGE_FILE": str(self.data),
        }

    def measured(self):
        """The files the parallel data files name, or None without any. With
        `source` set, coverage also records the source's unexecuted files."""
        files = sorted(self.data.parent.glob(".coverage.*"))
        if not files:
            return None
        paths = set()
        for f in files:
            with contextlib.closing(sqlite3.connect(f)) as db:
                paths |= {Path(p).name for (p,) in db.execute("select path from file")}
        return paths

    def test_odoo_bin_measured(self):
        (self.tree / "odoo-bin").write_text(ODOO_BIN)
        run = self.run_raw(self.tree, "-c", "odoo.conf", script=MEASURED, env=self.env)
        self.assertEqual(
            json.loads(run.stdout), {"via": "odoo-bin", "argv": ["-c", "odoo.conf"]}
        )
        self.assertIn("odoo-bin", self.measured())

    def test_launcher_measured(self):
        run = self.run_raw(self.tree, "--dev=all", script=MEASURED, env=self.env)
        out = json.loads(run.stdout)
        # The tree's odoo still wins over the wheel, and runs as odoo-bin.
        self.assertEqual((out["via"], out["argv"]), ("the tree", ["--dev=all"]))
        self.assertEqual(Path(out["argv0"]).name, "odoo-bin")
        self.assertEqual(self.measured(), {"__init__.py", "__main__.py"})

    def test_unset_is_plain(self):
        (self.tree / "odoo-bin").write_text(ODOO_BIN)
        env = {"COVERAGE_FILE": str(self.data)}
        self.run_raw(self.tree, script=MEASURED, env=env)
        self.assertIsNone(self.measured())

    def test_no_hook_without_coverage(self):
        (self.tree / "odoo-bin").write_text(ODOO_BIN)
        run = self.run_raw(self.tree, "--version", env=self.env)
        self.assertEqual(json.loads(run.stdout)["via"], "odoo-bin")
        self.assertIsNone(self.measured())


if __name__ == "__main__":
    unittest.main()
