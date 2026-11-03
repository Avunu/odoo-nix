"""Sync's phase hooks (DESIGN.md §2.5, ``bootstrap.py``): the project's submodules before
phase A, and the handovers to the locked engine's ``odoo-init``.

A fake ``nix`` on PATH records what would run; git is the real one. The fixture locks pin
``github:avunu/odoo-nix`` at the fake rev ``a…a`` (§7.1).
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import unittest
from pathlib import Path
from types import SimpleNamespace

from odoo_nix_tools import bootstrap
from odoo_nix_tools.product import PRODUCT
from standards_core.scaffold.bootstrap import Runner
from support import SyncCase, git

REV = "a" * 40
ENGINE = f"github:avunu/odoo-nix/{REV}"
SUBMODULE = "b" * 40


def lock(**locked: str) -> str:
    """A flake.lock whose ``odoo-nix`` node is locked as ``locked``."""
    return json.dumps(
        {
            "version": 7,
            "root": "root",
            "nodes": {
                "root": {"inputs": {"odoo-nix": "odoo-nix"}},
                "odoo-nix": {"locked": {"narHash": "sha256-x", **locked}},
            },
        }
    )


class Case(SyncCase):
    def setUp(self) -> None:
        super().setUp()
        cwd = Path.cwd()
        self.addCleanup(os.chdir, cwd)
        os.environ.pop("ODOO_NIX_URL_OVERRIDE", None)

    def fake_nix(self) -> Path:
        """``nix`` on PATH: appends its argv (one JSON list per line) to the log."""
        bindir = self.tmp / "bin"
        bindir.mkdir(exist_ok=True)
        log = self.tmp / "nix.log"
        nix = bindir / "nix"
        nix.write_text(
            f'#!/bin/sh\nprintf "%s\\0" "$@" >> {log}\nprintf \'\\n\' >> {log}\n'
        )
        nix.chmod(nix.stat().st_mode | stat.S_IXUSR)
        os.environ["PATH"] = f"{bindir}{os.pathsep}{os.environ['PATH']}"
        return log

    @staticmethod
    def calls(log: Path) -> list[list[str]]:
        if not log.is_file():
            return []
        return [
            [w for w in line.split("\0") if w]
            for line in log.read_text().splitlines()
            if line
        ]

    def with_gitlink(self, root: Path) -> None:
        """``odoo`` as a submodule that is not checked out (``git submodule status``
        lists it with ``-``)."""
        git(root, "update-index", "--add", "--cacheinfo", f"160000,{SUBMODULE},odoo")
        git(root, "commit", "-q", "-m", "gitlink")


class EngineRef(Case):
    def test_github_node(self) -> None:
        root = self.make_tree(
            {"flake.lock": lock(type="github", owner="avunu", repo="odoo-nix", rev=REV)}
        )
        self.assertEqual(bootstrap.engine_ref(root), ENGINE)

    def test_enterprise_host(self) -> None:
        root = self.make_tree(
            {
                "flake.lock": lock(
                    type="github",
                    owner="avunu",
                    repo="odoo-nix",
                    rev=REV,
                    host="git.example.org",
                )
            }
        )
        self.assertEqual(bootstrap.engine_ref(root), f"{ENGINE}?host=git.example.org")

    def test_git_node(self) -> None:
        url = "https://git.example.org/avunu/odoo-nix.git"
        root = self.make_tree({"flake.lock": lock(type="git", url=url, rev=REV)})
        self.assertEqual(bootstrap.engine_ref(root), f"git+{url}?rev={REV}")

    def test_none(self) -> None:
        self.assertIsNone(bootstrap.engine_ref(self.make_tree({"x": ""})))
        # A path input (a local override) has no revision to run.
        root = self.make_tree({"flake.lock": lock(type="path", path="/src")}, "path")
        self.assertIsNone(bootstrap.engine_ref(root))


class Handovers(Case):
    def test_reexec_runs_the_locked_engines_odoo_init(self) -> None:
        os.chdir(self.fixture("standards-project"))
        self.assertEqual(
            bootstrap.reexec_argv(["--offline", "--standards", "recommended"]),
            [
                "nix",
                "run",
                f"{ENGINE}#odoo-init",
                "--",
                "--sync",
                "--offline",
                "--standards",
                "recommended",
            ],
        )
        self.assertIs(PRODUCT.sync.reexec_argv, bootstrap.reexec_argv)

    def test_reentry_is_phase_b_of_the_same_app(self) -> None:
        os.chdir(self.fixture("standards-addons"))
        self.assertEqual(
            bootstrap.reentry_argv(["--force"]),
            [
                "nix",
                "run",
                f"{ENGINE}#odoo-init",
                "--",
                "--sync",
                "--phase",
                "b",
                "--force",
            ],
        )
        self.assertIs(PRODUCT.sync.reentry_argv, bootstrap.reentry_argv)

    def test_without_a_lock_the_project_flakes_app(self) -> None:
        os.chdir(self.make_tree({"flake.nix": "{ }\n"}))
        self.assertEqual(
            bootstrap.reexec_argv([]),
            ["nix", "run", "--no-pure-eval", ".#odoo-init", "--", "--sync"],
        )
        self.assertEqual(
            bootstrap.reentry_argv(["--dry-run"])[-4:],
            ["--sync", "--phase", "b", "--dry-run"],
        )

    def test_url_override(self) -> None:
        os.chdir(self.fixture("standards-project"))
        os.environ["ODOO_NIX_URL_OVERRIDE"] = "path:/src/odoo-nix"
        self.assertEqual(
            bootstrap.reexec_argv([])[:3],
            ["nix", "run", "path:/src/odoo-nix#odoo-init"],
        )


class PhaseABefore(Case):
    def run_hook(
        self,
        root: Path,
        shape: str = "project",
        *,
        offline: bool = False,
        skip_lock: bool = False,
    ) -> tuple[list[list[str]], str]:
        log = self.fake_nix()
        plan = SimpleNamespace(ctx=SimpleNamespace(discover={"shape": shape}))
        args = argparse.Namespace(offline=offline, skip_lock=skip_lock)
        said: list[str] = []
        runner = Runner(root, PRODUCT)
        runner.say = said.append  # type: ignore[method-assign]
        bootstrap.phase_a_before(plan, runner, args)  # type: ignore[arg-type]
        return self.calls(log), "\n".join(said)

    def test_unchecked_submodules_run_the_locked_bootstrap(self) -> None:
        root = self.fixture("standards-project")
        self.with_gitlink(root)
        self.assertEqual(bootstrap.unchecked_submodules(root), ["odoo"])
        calls, _ = self.run_hook(root)
        self.assertEqual(calls, [["run", f"{ENGINE}#bootstrap", "--", str(root)]])

    def test_offline_and_skip_lock_only_say_so(self) -> None:
        root = self.fixture("standards-project")
        self.with_gitlink(root)
        for flag, (calls, said) in (
            ("offline", self.run_hook(root, offline=True)),
            ("skip_lock", self.run_hook(root, skip_lock=True)),
        ):
            self.assertEqual(calls, [], flag)
            self.assertIn("submodules are not checked out", said)
            self.assertIn("self.submodules", said)
            self.assertIn("odoo", said)

    def test_checked_out_or_none(self) -> None:
        # The fixture has a .gitmodules but no gitlink: nothing to check out.
        calls, said = self.run_hook(self.fixture("standards-project"))
        self.assertEqual((calls, said), ([], ""))

    def test_addons_mode_has_no_submodules(self) -> None:
        root = self.fixture("standards-addons")
        git(root, "config", "-f", ".gitmodules", "submodule.odoo.path", "odoo")
        self.with_gitlink(root)
        calls, said = self.run_hook(root, shape="addons")
        self.assertEqual((calls, said), ([], ""))

    def test_sync_runs_it(self) -> None:
        """Through ``odoo-nix sync``: offline, phase A says what it skipped."""
        root = self.profile_fixture("standards-project", "recommended")
        self.with_gitlink(root)
        code, text = self.write(root, ok=False)
        self.assertIn(code, (0, 1), text)
        self.assertIn("submodules are not checked out", text)


if __name__ == "__main__":
    unittest.main()
