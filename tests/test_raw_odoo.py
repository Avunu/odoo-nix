"""lib/raw-odoo.nix with stand-in OCB trees: a tree's odoo-bin when it has one,
and Odoo as `python -m odoo` runs it when it has none (an Enterprise tree can
come without odoo-bin). The checks' built-odoo-no-odoo-bin-<major> run the
real Odoo the second way.

Run: python3 -I tests/test_raw_odoo.py <script>   (checks.raw-odoo)
  <script>  the shell text, run as `<script> <tree> <args...>`
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = os.path.abspath(sys.argv.pop(1))

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


class RawOdooTest(unittest.TestCase):
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

    def run_odoo(self, *argv):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(self.root / "wheel"),
        }
        out = subprocess.run(
            [SCRIPT, str(self.tree), *argv],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return json.loads(out)

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


if __name__ == "__main__":
    unittest.main()
