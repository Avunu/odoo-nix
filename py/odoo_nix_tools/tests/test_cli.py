"""The ``odoo-nix`` command line (DESIGN.md §7.2 test_cli)."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from odoo_nix_tools import __version__
from support import PACKAGE, TempRepos, odoo_nix_root, run_cli

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "help.txt"


def words(text: str) -> list[str]:
    # argparse's column layout differs between Python versions (3.11's wraps a long
    # command name onto its own line); the snapshot compares the words.
    return text.split()


class Help(unittest.TestCase):
    def test_help_snapshot(self) -> None:
        saved = os.environ.get("COLUMNS")
        os.environ["COLUMNS"] = "100"
        self.addCleanup(
            lambda: (
                os.environ.pop("COLUMNS", None)
                if saved is None
                else os.environ.__setitem__("COLUMNS", saved)
            )
        )
        code, out, err = run_cli("--help")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(words(out), words(SNAPSHOT.read_text()))

    def test_no_command_is_exit_2(self) -> None:
        code, _, err = run_cli()
        self.assertEqual(code, 2)
        self.assertIn("usage: odoo-nix", err)


class Version(unittest.TestCase):
    def test_version_is_the_package_version(self) -> None:
        code, out, _ = run_cli("--version")
        self.assertEqual((code, out.strip()), (0, __version__))
        project = tomllib.loads((PACKAGE / "pyproject.toml").read_text())["project"]
        self.assertEqual(out.strip(), project["version"])

    def test_version_is_version_txt(self) -> None:
        root = odoo_nix_root()
        if root is None:
            self.skipTest("version.txt is not available")
        _, out, _ = run_cli("--version")
        self.assertEqual(out.strip(), (root / "version.txt").read_text().strip())

    def test_python_dash_m(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "odoo_nix_tools", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, __version__))


class Commands(TempRepos):
    def test_config_in_the_project_fixture(self) -> None:
        root = self.fixture("standards-project")
        for key, want in (
            ("shape", "project"),
            ("series", "18.0"),
            ("integration-branch", "main"),
            ("modules.tests", "true"),
            ("modules.ide", "false"),
        ):
            code, out, err = run_cli("config", key, cwd=root)
            self.assertEqual((code, out.strip()), (0, want), (key, err))

    def test_a_shape_error_is_exit_2(self) -> None:
        root = self.make_tree({"pyproject.toml": "[tool.odoo-nix]\nschema = 1\n"})
        code, _, err = run_cli("config", "shape", cwd=root)
        self.assertEqual(code, 2)
        self.assertIn("cannot tell this repository's shape", err)


if __name__ == "__main__":
    unittest.main()
