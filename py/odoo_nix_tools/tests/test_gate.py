"""``odoo-nix gate lint|test`` (DESIGN.md §6.1, §7.2 test_gate): which steps run per
module and shape, failure aggregation (every step runs; odoo-nix's own 2 and 3 win over 1,
an external tool's 2 or 3 is a failure), the report
against ``schema/gate-report.schema.json`` and the job summary. The commands are faked;
the in-process ``odoo-nix …`` steps are recorded like the rest. ``tested`` agrees with
``odoo test --all`` (lib/odoo_nix_cli/testrun.py) on both fixtures."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from odoo_nix_tools.commands import common, gate
from odoo_nix_tools.product import PRODUCT
from standards_core.common import schema
from support import SyncCase, git, need_root, run_cli


class Fake:
    """A runner: records every command line and answers from ``codes`` (the first key
    that is a prefix of the command's words, the tool's base name first)."""

    def __init__(self, codes: Mapping[str, int] | None = None):
        self.codes = dict(codes or {})
        self.calls: list[list[str]] = []
        self.envs: list[Mapping[str, str]] = []

    def __call__(self, argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> int:
        words = [Path(argv[0]).name, *argv[1:]]
        self.calls.append(words)
        self.envs.append(env)
        line = " ".join(words)
        for key, code in self.codes.items():
            if line.startswith(key):
                if code < 0:
                    raise FileNotFoundError(argv[0])
                return code
        return 0

    def names(self) -> list[str]:
        return [" ".join(c[:3]) for c in self.calls]


class GateCase(SyncCase):
    def setUp(self) -> None:
        super().setUp()
        for key in (
            "GITHUB_ACTIONS",
            "GITHUB_EVENT_NAME",
            "GITHUB_BASE_REF",
            "ODOO_NIX_CI",
        ):
            os.environ.pop(key, None)

    def tools(self, root: Path, *names: str) -> None:
        bin_dir = root / common.TOOLS_BIN
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            (bin_dir / name).write_text("#!/bin/sh\n")
            (bin_dir / name).chmod(0o755)

    def project(self, profile: str = "recommended", edit: dict | None = None) -> Path:
        root = self.profile_fixture("standards-project", profile, edit or {})
        self.tools(root, "prek", "checklog-odoo", "coverage", "manifestoo")
        return root

    def addons(self, profile: str = "example-org", edit: dict | None = None) -> Path:
        root = self.profile_fixture("standards-addons", profile, edit or {})
        self.tools(root, "prek", "checklog-odoo", "coverage", "manifestoo")
        return root

    def gate(
        self,
        root: Path,
        which: str,
        fake: Fake,
        product=PRODUCT,
        env: Mapping[str, str] | None = None,
        **kw,
    ) -> tuple[int, dict]:
        rc = common.load(product, root)
        environment = {"PATH": os.environ["PATH"], **(env or {})}
        with contextlib.redirect_stdout(io.StringIO()):
            code = gate.run_gate(product, rc, which, runner=fake, env=environment, **kw)
        report = json.loads((root / ".odoo-nix/gate" / f"{which}.json").read_text())
        errors = schema.Validator(product, "gate-report.schema.json", "report").errors(
            report
        )
        self.assertEqual(errors, [])
        return code, report

    @staticmethod
    def steps(report: dict) -> dict[str, str]:
        return {s["name"]: s["status"] for s in report["steps"]}


class Lint(GateCase):
    def test_project_under_recommended(self) -> None:
        root = self.project()
        fake = Fake()
        code, report = self.gate(root, "lint", fake)
        self.assertEqual(code, 0)
        self.assertEqual(
            self.steps(report),
            {
                "sync-check": "passed",
                "prek": "passed",
                "manifests": "passed",
                "icons": "skipped",
                "submodules": "passed",
                "ratchet": "skipped",
            },
        )
        self.assertEqual(
            fake.calls,
            [
                ["odoo-nix", "sync", "--check"],
                [
                    "prek",
                    "run",
                    "--all-files",
                    "--show-diff-on-failure",
                    "-c",
                    ".pre-commit-config.yaml",
                ],
                ["odoo-nix", "check", "manifests", "--format", "text"],
                ["odoo-nix", "check", "submodules", "--format", "text"],
            ],
        )
        reasons = {s["name"]: s["reason"] for s in report["steps"]}
        self.assertEqual(reasons["icons"], "icons is off")
        self.assertIn("not a pull request", reasons["ratchet"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["odoo_nix"], {"version": PRODUCT.identity.version})

    def test_addons_under_example_org(self) -> None:
        root = self.addons()
        fake = Fake()
        code, report = self.gate(root, "lint", fake, base="HEAD", expect_rev="abc")
        self.assertEqual(code, 0)
        steps = self.steps(report)
        self.assertEqual(steps["icons"], "passed")
        self.assertEqual(steps["submodules"], "skipped")
        self.assertEqual(steps["ratchet"], "passed")
        self.assertIn(
            ["odoo-nix", "sync", "--check", "--expect-rev", "abc"], fake.calls
        )
        self.assertIn(
            ["odoo-nix", "ratchet", "coverage", "--base", "HEAD", "--format", "text"],
            fake.calls,
        )
        self.assertEqual(report["odoo_nix"]["expect_rev"], "abc")

    def test_minimal_runs_only_the_sync_check(self) -> None:
        root = self.project("minimal")
        code, report = self.gate(root, "lint", Fake())
        self.assertEqual(code, 0)
        self.assertEqual(
            [n for n, s in self.steps(report).items() if s != "skipped"], ["sync-check"]
        )
        reasons = {s["name"]: s["reason"] for s in report["steps"]}
        self.assertEqual(reasons["prek"], "every module with a pre-commit hook is off")

    def test_the_merge_base_of_a_pull_request(self) -> None:
        root = self.project()
        git(root, "checkout", "-q", "-b", "topic")
        git(root, "commit", "-q", "--allow-empty", "-m", "feat: x")
        fake = Fake()
        env = {"GITHUB_EVENT_NAME": "pull_request", "GITHUB_BASE_REF": "main"}
        code, report = self.gate(root, "lint", fake, env=env)
        self.assertEqual(code, 0)
        base = git(root, "rev-parse", "main").strip()
        self.assertIn(
            ["odoo-nix", "ratchet", "coverage", "--base", base, "--format", "text"],
            fake.calls,
        )
        # A base branch that is not fetched fails the step, as the environment.
        env["GITHUB_BASE_REF"] = "nowhere"
        code, report = self.gate(root, "lint", Fake(), env=env)
        self.assertEqual(code, 3)
        self.assertEqual(self.steps(report)["ratchet"], "failed")

    def test_every_step_runs_and_failures_aggregate(self) -> None:
        root = self.project()
        fake = Fake({"prek run": 1, "odoo-nix check manifests": 1})
        code, report = self.gate(root, "lint", fake)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        steps = self.steps(report)
        self.assertEqual((steps["prek"], steps["manifests"]), ("failed", "failed"))
        self.assertEqual(steps["submodules"], "passed")
        prek = next(s for s in report["steps"] if s["name"] == "prek")
        self.assertEqual((prek["reason"], prek["exit"]), ("prek run exited 1", 1))

    def test_configuration_and_environment_codes_win(self) -> None:
        root = self.project()
        cases = (
            ({"odoo-nix sync": 2, "prek": 1}, 2),
            ({"odoo-nix sync": 2, "odoo-nix check submodules": 3}, 3),
            ({"prek": -1}, 3),
        )
        for codes, want in cases:
            with self.subTest(codes=codes):
                code, report = self.gate(root, "lint", Fake(codes))
                self.assertEqual(code, want)
                self.assertEqual(report["exit"], want)

    def test_an_external_tools_2_or_3_is_a_failure(self) -> None:
        root = self.project()
        for code in (2, 3):
            with self.subTest(code=code):
                got, report = self.gate(root, "lint", Fake({"prek": code}))
                self.assertEqual((got, report["status"]), (1, "failed"))
                prek = next(s for s in report["steps"] if s["name"] == "prek")
                self.assertEqual(prek["exit"], code)

    def test_an_unlinked_tool_is_the_environment(self) -> None:
        root = self.project()
        (root / common.TOOLS_BIN / "prek").unlink()
        code, report = self.gate(root, "lint", Fake())
        self.assertEqual(code, 3)
        prek = next(s for s in report["steps"] if s["name"] == "prek")
        self.assertIn("tools/.venv/bin/prek is missing", prek["reason"])

    def test_report_path_summary_and_github_format(self) -> None:
        root = self.project()
        summary = self.tmp / "summary.md"
        rc = common.load(PRODUCT, root)
        out = self.tmp / "out/lint.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = gate.run_gate(
                PRODUCT,
                rc,
                "lint",
                runner=Fake({"prek": 1}),
                env={"GITHUB_STEP_SUMMARY": str(summary)},
                fmt="github",
                report=out,
            )
        self.assertEqual(code, 1)
        self.assertTrue(out.is_file())
        self.assertIn(
            "::error title=gate lint: prek::prek run exited 1", buf.getvalue()
        )
        text = summary.read_text()
        self.assertIn("| prek | ❌ failed | prek run exited 1 |", text)
        self.assertIn("| icons | ⏭️ skipped | icons is off |", text)

    def test_cli(self) -> None:
        root = self.project("minimal")
        code, out, err = run_cli(
            "gate", "lint", "--report", str(self.tmp / "r.json"), cwd=root
        )
        # The real sync --check of a fixture that minimal has not synced: drift.
        self.assertEqual(code, 1, out + err)
        self.assertIn("✗ sync-check: odoo-nix sync exited 1", out)
        report = json.loads((self.tmp / "r.json").read_text())
        self.assertEqual(
            report["steps"][0]["command"], [["odoo-nix", "sync", "--check"]]
        )


class Test(GateCase):
    def test_project(self) -> None:
        root = self.project()
        (root / "odoo.conf").write_text("[options]\naddons_path = /a,/b\n")
        fake = Fake()
        code, report = self.gate(root, "test", fake)
        self.assertEqual(code, 0)
        self.assertEqual(
            self.steps(report),
            {
                "modules": "passed",
                "postgres": "skipped",
                "odoo-test": "passed",
                "checklog": "passed",
                "coverage": "passed",
                "manifestoo": "passed",
            },
        )
        rc = "--rcfile=tools/pyproject.toml"
        mo = ["manifestoo", "--select-addons-dir", "custom", "--addons-path", "/a,/b"]
        self.assertEqual(
            fake.calls,
            [
                [
                    "odoo",
                    "test",
                    "fixture_sale",
                    "--fresh-db",
                    "--coverage",
                    "tools/pyproject.toml",
                    "--log",
                    ".odoo-nix/test/odoo.log",
                ],
                ["checklog-odoo", ".odoo-nix/test/odoo.log"],
                ["coverage", "combine", rc],
                ["coverage", "report", rc],
                ["coverage", "xml", rc, "-o", ".odoo-nix/coverage/coverage.xml"],
                [*mo, "check-licenses"],
                [*mo, "check-dev-status"],
            ],
        )
        self.assertEqual(
            {e["COVERAGE_FILE"] for e in fake.envs},
            {str(root / ".odoo-nix/coverage/.coverage")},
        )

    def test_ci_cluster(self) -> None:
        root = self.addons()
        conf = self.tmp / "odoo.conf"
        conf.write_text("[options]\naddons_path = /x\n")
        fake = Fake()
        env = {"ODOO_NIX_CI": "1", "ODOO_RC": str(conf), "COVERAGE_FILE": "/elsewhere"}
        code, _ = self.gate(root, "test", fake, env=env)
        self.assertEqual(code, 0)
        names = [c[0] for c in fake.calls]
        self.assertEqual(names[:3], ["initdb", "pg_ctl", "odoo"])
        self.assertEqual(fake.calls[-1][-1], "stop")
        start = fake.calls[1]
        sock = start[start.index("-o") + 1].split()[1]
        self.assertTrue(sock.startswith("/"))
        self.assertEqual(
            fake.calls[2][:6], ["odoo", "--db-host", sock, "--db-user", "odoo", "test"]
        )
        self.assertEqual(fake.calls[2][6], "fixture_a,fixture_b")
        self.assertFalse(Path(sock).exists())
        # An exported COVERAGE_FILE wins.
        self.assertEqual({e["COVERAGE_FILE"] for e in fake.envs}, {"/elsewhere"})

    def test_cluster_stopped_after_a_failure(self) -> None:
        root = self.addons()
        fake = Fake({"odoo": 1})
        env = {"ODOO_NIX_CI": "true", "ODOO_RC": str(self.tmp / "missing.conf")}
        code, report = self.gate(root, "test", fake, env=env)
        self.assertEqual(code, 3)  # manifestoo: odoo.conf is unreadable
        steps = self.steps(report)
        self.assertEqual(steps["odoo-test"], "failed")
        self.assertEqual(steps["checklog"], "passed")  # every step runs
        self.assertEqual((fake.calls[-1][0], fake.calls[-1][-1]), ("pg_ctl", "stop"))

    def test_coverage_under_fail_under_is_a_failure(self) -> None:
        # coverage exits 2 (FAIL_UNDER) when the total is under fail_under: a failed
        # step, not the configuration.
        root = self.project()
        (root / "odoo.conf").write_text("[options]\naddons_path = /a\n")
        code, report = self.gate(root, "test", Fake({"coverage report": 2}))
        self.assertEqual((code, report["status"], report["exit"]), (1, "failed", 1))
        step = next(s for s in report["steps"] if s["name"] == "coverage")
        self.assertEqual(
            (step["status"], step["reason"], step["exit"]),
            ("failed", "coverage report exited 2", 2),
        )

    def test_no_tested_addon(self) -> None:
        root = self.project()
        config = root / "pyproject.toml"
        config.write_text(
            config.read_text()
            + '\n[[tool.odoo-nix.untested]]\naddon = "fixture_sale"\nreason = "planted for the test"\n'
        )
        git(root, "commit", "-q", "-am", "untested")
        fake = Fake()
        code, report = self.gate(root, "test", fake)
        self.assertEqual(code, 0)
        self.assertEqual(set(self.steps(report).values()), {"skipped"})
        self.assertEqual({s["reason"] for s in report["steps"]}, {"no tested addon"})
        self.assertEqual(fake.calls, [])

    def test_checklog_off(self) -> None:
        root = self.project()
        config = root / "pyproject.toml"
        config.write_text(
            config.read_text().replace(
                "[tool.odoo-nix]\n", "[tool.odoo-nix]\ntests.checklog = false\n", 1
            )
        )
        git(root, "commit", "-q", "-am", "checklog off")
        (root / "odoo.conf").write_text("[options]\naddons_path = /a\n")
        code, report = self.gate(root, "test", Fake())
        self.assertEqual(code, 0)
        reasons = {s["name"]: s["reason"] for s in report["steps"]}
        self.assertEqual(reasons["checklog"], "tests.checklog is off")

    def test_tests_off(self) -> None:
        root = self.project("minimal")
        code, report = self.gate(root, "test", Fake())
        self.assertEqual(code, 0)
        self.assertEqual(
            {s["reason"] for s in report["steps"]},
            {"tests is off", "addon-manifest is off"},
        )


class AgreesWithOdooTestAll(GateCase):
    """``gate.tested`` and ``odoo test --all`` (testrun.all_modules) name the same
    addons."""

    def setUp(self) -> None:
        super().setUp()
        path = need_root(self) / "lib/odoo_nix_cli/testrun.py"
        if not path.is_file():
            self.skipTest("lib/odoo_nix_cli/testrun.py is not available")
        spec = importlib.util.spec_from_file_location("testrun", path)
        assert spec is not None and spec.loader is not None
        self.testrun = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.testrun)

    def untested(self, config: Path, addon: str) -> None:
        config.write_text(
            config.read_text()
            + f'\n[[tool.odoo-nix.untested]]\naddon = "{addon}"\nreason = "planted for the test"\n'
        )

    def test_both_shapes(self) -> None:
        cases = (
            ("standards-project", PRODUCT, "pyproject.toml", {}, "fixture_sale"),
            (
                "standards-addons",
                PRODUCT,
                "nix/pyproject.toml",
                {"ODOO_NIX_LOCAL_ADDONS": "."},
                "fixture_b",
            ),
        )
        for name, product, config, env, skip in cases:
            with self.subTest(fixture=name):
                root = self.profile_fixture(name, "recommended")
                rc = common.load(product, root)
                self.assertEqual(gate.tested(rc), self.testrun.all_modules(root, env))
                self.untested(root / config, skip)
                git(root, "commit", "-q", "-am", "untested")
                rc = common.load(product, root)
                if gate.tested(rc):
                    self.assertEqual(
                        gate.tested(rc), self.testrun.all_modules(root, env)
                    )
                self.assertNotIn(skip, gate.tested(rc))
