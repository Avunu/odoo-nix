"""``odoo-nix gate lint|test`` (DESIGN.md §6.1): the CI gates, one command each, that a
developer runs the same way.

``gate lint`` runs in the lint shell (``nix develop --no-pure-eval .#odoo-nix-lint``; in CI
the engine's ``lib.standards.lintShell``): ``sync-check`` (``sync --check``), ``prek``
(every hook of ``.pre-commit-config.yaml``, always with ``-c`` so no nested config runs),
``manifests``, ``icons`` and ``submodules`` (``odoo-nix check …``) and ``ratchet``
(``ratchet coverage --base <the pull request's merge-base>``).

``gate test`` runs in the dev shell (``ODOO_NIX_CI=1 nix develop --no-pure-eval -c
odoo-nix gate test``): ``modules`` (the installable addons less ``untested``),
``postgres`` (under ``ODOO_NIX_CI``, a throwaway cluster on a socket), ``odoo-test``
(``odoo test <modules> --fresh-db --coverage tools/pyproject.toml --log
.odoo-nix/test/odoo.log``), ``checklog`` (checklog-odoo over that log), ``coverage``
(combine, report against ``fail_under``, ``coverage.xml``) and ``manifestoo``
(``check-licenses``, ``check-dev-status``).

Every step runs (a step whose module is off is skipped, with the reason); the report
(``--report``, default ``.odoo-nix/gate/<gate>.json``, ``schema/gate-report.schema.json``)
lists them all, and under GitHub Actions a table goes to the job summary. Exit 0 when
every step passed or was skipped, 1 when one failed, 2 for the configuration, 3 for the
environment. Only the gate's own errors (a tool that is not there, a base branch not
fetched) and the in-process ``odoo-nix …`` sub-steps pass a 2 or a 3 on; any other tool
that exits non-zero (coverage exits 2 under ``fail_under``) is a failed step, exit 1, its
own code kept in the step's ``exit``.
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from standards_core.commands import Command, help_text
from standards_core.common import repo
from standards_core.common.report import (
    CLEAN,
    DRIFT,
    ENVIRONMENT,
    INVALID,
    EnvError,
    StandardsError,
)

from odoo_nix_tools import context, groups
from odoo_nix_tools.commands import common

if TYPE_CHECKING:
    from standards_core.common.repoconfig import RepoConfig
    from standards_core.product import Product

GATES = ("lint", "test")
PRECOMMIT_CONFIG = ".pre-commit-config.yaml"
# The modules with a hook in the managed .pre-commit-config.yaml (data/manifest.d).
PRECOMMIT_MODULES = (
    "python-lint",
    "pylint-odoo",
    "addon-manifest",
    "js-xml",
    "workflow-lint",
    "shell-lint",
    "nix-lint",
    "hygiene",
)
TEST_LOG = ".odoo-nix/test/odoo.log"
TEST_DIR = ".odoo-nix/test"
COVERAGE_XML = ".odoo-nix/coverage/coverage.xml"
RCFILE = "tools/pyproject.toml"
PG_USER = "odoo"
STATUS = {CLEAN: "passed", DRIFT: "failed", INVALID: "invalid", ENVIRONMENT: "error"}

# argv, cwd, env → exit code; FileNotFoundError when argv[0] does not exist.
Runner = Callable[[Sequence[str], Path, Mapping[str, str]], int]


@dataclass
class StepResult:
    status: Literal["passed", "failed", "skipped"]
    reason: str = ""
    seconds: float = 0.0
    command: list[list[str]] = field(default_factory=list)
    exit: int | None = None
    # ``exit`` is odoo-nix's own code (the gate's error, an ``odoo-nix …`` sub-step), not
    # an external tool's: only then does a 2 or a 3 make the gate's code.
    internal: bool = False


@dataclass
class GateContext:
    product: Product
    rc: RepoConfig
    gate: str
    run: Runner
    env: dict[str, str]
    base: str = ""
    expect_rev: str = ""
    fmt: str = "text"
    # what one step leaves for the next (the tested addons, the database socket)
    state: dict[str, Any] = field(default_factory=dict)
    commands: list[list[str]] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.rc.root

    @property
    def cli(self) -> str:
        return self.product.identity.cli

    def on(self, module: str) -> bool:
        return bool(self.rc.modules.get(module))

    def tool(self, name: str) -> str:
        return common.tool(self.root, name)

    def sh(self, *argvs: Sequence[str], label: str = "") -> StepResult:
        """Run ``argvs`` in order from the root; the first that fails ends the step,
        named ``label`` (default: the tool and its first argument)."""
        for argv in argvs:
            argv = [str(a) for a in argv]
            self.commands.append(argv)
            try:
                code = self.run(argv, self.root, self.env)
            except FileNotFoundError:
                return StepResult(
                    "failed", f"{argv[0]} is not there", exit=ENVIRONMENT, internal=True
                )
            if code != 0:
                what = label or " ".join([Path(argv[0]).name, *argv[1:2]])
                return StepResult(
                    "failed",
                    f"{what} exited {code}",
                    exit=code,
                    internal=argv[0] == self.cli,
                )
        return StepResult("passed")


@dataclass(frozen=True)
class Step:
    name: str
    # any of these on runs the step; () always
    modules: tuple[str, ...]
    run: Callable[[GateContext], StepResult]


# --- lint ---------------------------------------------------------------------------


def _sync_check(ctx: GateContext) -> StepResult:
    argv = [ctx.cli, "sync", "--check"]
    if ctx.expect_rev:
        argv += ["--expect-rev", ctx.expect_rev]
    return ctx.sh(argv)


def _prek(ctx: GateContext) -> StepResult:
    return ctx.sh(
        [
            ctx.tool("prek"),
            "run",
            "--all-files",
            "--show-diff-on-failure",
            "-c",
            PRECOMMIT_CONFIG,
        ]
    )


def _check(what: str) -> Callable[[GateContext], StepResult]:
    def step(ctx: GateContext) -> StepResult:
        return ctx.sh([ctx.cli, "check", what, "--format", ctx.fmt])

    return step


def _submodules(ctx: GateContext) -> StepResult:
    if ctx.rc.facts.get("shape") != "project":
        return StepResult("skipped", "an addon repository pins no submodules")
    return _check("submodules")(ctx)


def merge_base(root: Path, env: Mapping[str, str]) -> str:
    """The pull request's merge-base under GitHub Actions, else ``""``."""
    if env.get("GITHUB_EVENT_NAME") not in ("pull_request", "pull_request_target"):
        return ""
    base = env.get("GITHUB_BASE_REF", "")
    if not base:
        return ""
    for ref in (f"origin/{base}", base):
        with contextlib.suppress(EnvError):
            return repo.git(root, "merge-base", ref, "HEAD").strip()
    raise EnvError(
        f"the base branch {base!r} is not fetched (actions/checkout: fetch-depth: 0)"
    )


def _ratchet(ctx: GateContext) -> StepResult:
    base = ctx.base or merge_base(ctx.root, ctx.env)
    if not base:
        return StepResult(
            "skipped", "not a pull request: the ratchet compares with its base"
        )
    return ctx.sh([ctx.cli, "ratchet", "coverage", "--base", base, "--format", ctx.fmt])


LINT = (
    Step("sync-check", (), _sync_check),
    Step("prek", PRECOMMIT_MODULES, _prek),
    Step("manifests", ("addon-manifest",), _check("manifests")),
    Step("icons", ("icons",), _check("icons")),
    Step("submodules", ("ci",), _submodules),
    Step("ratchet", ("tests",), _ratchet),
)


# --- test ---------------------------------------------------------------------------

NO_TESTED = "no tested addon"


def tested(rc: RepoConfig) -> list[str]:
    """The installable addons less ``[[tool.odoo-nix.untested]]``, sorted (what ``odoo
    test --all`` computes from the files, DESIGN.md §6.1.2)."""
    skip = set(context.untested(rc.cfg))
    return sorted(set(rc.facts.get("installable", [])) - skip)


def _modules(ctx: GateContext) -> StepResult:
    names = tested(ctx.rc)
    ctx.state["modules"] = names
    if not names:
        return StepResult("skipped", NO_TESTED)
    return StepResult("passed", ", ".join(names))


def truthy(value: str | None) -> bool:
    """odoo-nix's CI mode: set to anything but "", 0 or false."""
    return (value or "").strip().lower() not in ("", "0", "false")


def _postgres(ctx: GateContext) -> StepResult:
    if not truthy(ctx.env.get("ODOO_NIX_CI")):
        return StepResult("skipped", "outside CI: the dev shell's PostgreSQL")
    data = ctx.root / TEST_DIR / "pg"
    shutil.rmtree(data, ignore_errors=True)
    data.parent.mkdir(parents=True, exist_ok=True)
    # A unix socket path is at most 107 bytes: the socket goes in a short temp dir.
    sock = tempfile.mkdtemp(prefix="odoo-nix-pg-")
    result = ctx.sh(
        [
            "initdb",
            "-D",
            str(data),
            "-U",
            PG_USER,
            "--auth=trust",
            "--encoding=UTF8",
            "--no-sync",
        ],
        [
            "pg_ctl",
            "-D",
            str(data),
            "-l",
            str(data.parent / "pg.log"),
            "-o",
            f"-k {sock} -c listen_addresses=''",
            "-w",
            "start",
        ],
    )
    if result.status == "passed":
        ctx.state["pg"] = (str(data), sock)
        result.reason = f"a throwaway cluster on {sock}"
    return result


def _odoo_test(ctx: GateContext) -> StepResult:
    argv = ["odoo"]
    if "pg" in ctx.state:
        argv += ["--db-host", ctx.state["pg"][1], "--db-user", PG_USER]
    argv += [
        "test",
        ",".join(ctx.state["modules"]),
        "--fresh-db",
        "--coverage",
        RCFILE,
        "--log",
        TEST_LOG,
    ]
    return ctx.sh(argv, label="odoo test")


def _checklog(ctx: GateContext) -> StepResult:
    if not (ctx.rc.cfg.get("tests") or {}).get("checklog", True):
        return StepResult("skipped", "tests.checklog is off")
    return ctx.sh([ctx.tool("checklog-odoo"), TEST_LOG])


def _coverage(ctx: GateContext) -> StepResult:
    cov = ctx.tool("coverage")
    rc = f"--rcfile={RCFILE}"
    return ctx.sh(
        [cov, "combine", rc],
        [cov, "report", rc],
        [cov, "xml", rc, "-o", COVERAGE_XML],
    )


def addons_path(root: Path, env: Mapping[str, str]) -> str:
    """``[options] addons_path`` of the dev shell's odoo.conf (``$ODOO_RC``, else
    ``./odoo.conf``)."""
    conf = Path(env.get("ODOO_RC") or root / "odoo.conf")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(conf.read_text())
    except (OSError, configparser.Error) as e:
        raise EnvError(f"cannot read {conf}: {e} (enter the dev shell)") from e
    value = parser.get("options", "addons_path", fallback="")
    if not value:
        raise EnvError(f"{conf} has no addons_path")
    return value


def _manifestoo(ctx: GateContext) -> StepResult:
    mo = ctx.tool("manifestoo")
    base = [
        mo,
        "--select-addons-dir",
        str(ctx.rc.facts.get("addons_root") or "."),
        "--addons-path",
        addons_path(ctx.root, ctx.env),
    ]
    # Beta for an addon with no development_status, as OCA reads it: many OCA addons
    # have none, and the check also reads the addons' dependencies.
    return ctx.sh(
        [*base, "check-licenses"],
        [*base, "check-dev-status", "--default-dev-status=Beta"],
    )


TEST = (
    Step("modules", ("tests",), _modules),
    Step("postgres", ("tests",), _postgres),
    Step("odoo-test", ("tests",), _odoo_test),
    Step("checklog", ("tests",), _checklog),
    Step("coverage", ("tests",), _coverage),
    Step("manifestoo", ("addon-manifest",), _manifestoo),
)
STEPS: Mapping[str, tuple[Step, ...]] = {"lint": LINT, "test": TEST}


def _stop_postgres(ctx: GateContext) -> None:
    pg = ctx.state.pop("pg", None)
    if pg is None:
        return
    data, sock = pg
    with contextlib.suppress(FileNotFoundError):
        ctx.run(["pg_ctl", "-D", data, "-m", "fast", "-w", "stop"], ctx.root, ctx.env)
    shutil.rmtree(sock, ignore_errors=True)


# --- running ------------------------------------------------------------------------


def _skip_reason(ctx: GateContext, step: Step) -> str | None:
    if step.modules and not any(ctx.on(m) for m in step.modules):
        if len(step.modules) == 1:
            return f"{step.modules[0]} is off"
        return "every module with a pre-commit hook is off"
    if ctx.gate == "test" and step.name != "modules" and not ctx.state.get("modules"):
        return NO_TESTED if ctx.on("tests") else "tests is off"
    return None


def run_steps(ctx: GateContext) -> list[tuple[Step, StepResult]]:
    """Every step of the gate, in order."""
    out = []
    try:
        for step in STEPS[ctx.gate]:
            reason = _skip_reason(ctx, step)
            if reason is not None:
                out.append((step, StepResult("skipped", reason)))
                continue
            ctx.commands = []
            started = time.monotonic()
            try:
                result = step.run(ctx)
            except StandardsError as e:
                result = StepResult("failed", str(e), exit=e.code, internal=True)
            result.seconds = round(time.monotonic() - started, 3)
            result.command = ctx.commands
            out.append((step, result))
    finally:
        _stop_postgres(ctx)
    return out


def exit_code(results: Sequence[tuple[Step, StepResult]]) -> int:
    failed = [r for _, r in results if r.status == "failed"]
    if not failed:
        return CLEAN
    special = [
        r.exit for r in failed if r.internal and r.exit in (INVALID, ENVIRONMENT)
    ]
    return max(special) if special else DRIFT


def report_doc(
    ctx: GateContext, results: Sequence[tuple[Step, StepResult]], code: int
) -> dict[str, Any]:
    engine: dict[str, str] = {"version": ctx.product.identity.version}
    if ctx.expect_rev:
        engine["expect_rev"] = ctx.expect_rev
    steps = []
    for step, r in results:
        item: dict[str, Any] = {
            "name": step.name,
            "modules": list(step.modules),
            "status": r.status,
            "reason": r.reason,
            "seconds": r.seconds,
        }
        if r.command:
            item["command"] = r.command
        if r.exit is not None:
            item["exit"] = r.exit
        steps.append(item)
    return {
        "schema": 1,
        "gate": ctx.gate,
        "status": STATUS[code],
        "exit": code,
        ctx.product.identity.report_key: engine,
        "steps": steps,
    }


def summary(gate: str, results: Sequence[tuple[Step, StepResult]]) -> str:
    """A Markdown table for ``$GITHUB_STEP_SUMMARY``."""
    mark = {"passed": "✅", "failed": "❌", "skipped": "⏭️"}
    lines = [f"### gate {gate}", "", "| Step | Result | Notes |", "| --- | --- | --- |"]
    for step, r in results:
        note = context.md_cell(r.reason)
        lines.append(f"| {step.name} | {mark[r.status]} {r.status} | {note} |")
    return "\n".join(lines) + "\n"


def _print(
    ctx: GateContext, results: Sequence[tuple[Step, StepResult]], code: int
) -> None:
    for step, r in results:
        if r.status == "passed":
            print(
                f"✓ {step.name} ({r.seconds:.1f}s){': ' + r.reason if r.reason else ''}"
            )
        elif r.status == "skipped":
            print(f"- {step.name}: skipped ({r.reason})")
        else:
            print(f"✗ {step.name}: {r.reason}")
            if ctx.fmt == "github":
                title = f"gate {ctx.gate}: {step.name}"
                print(f"::error title={title}::{r.reason}")
    print(f"{ctx.cli} gate {ctx.gate}: {STATUS[code]}")


def default_runner(product: Product) -> Runner:
    """External commands as subprocesses; ``<cli> …`` in-process, from ``cwd``."""

    def run(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> int:
        if argv[0] == product.identity.cli:
            from standards_core import cli

            from odoo_nix_tools.commands import EXTRA

            sys.stdout.flush()
            with _chdir(cwd):
                return cli.main(product, list(argv[1:]), extra_commands=EXTRA)
        return subprocess.run(
            list(argv), cwd=cwd, env=dict(env), check=False
        ).returncode

    return run


@contextlib.contextmanager
def _chdir(path: Path) -> Iterator[None]:
    old = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def run_gate(
    product: Product,
    rc: RepoConfig,
    gate: str,
    *,
    runner: Runner | None = None,
    env: Mapping[str, str] | None = None,
    base: str = "",
    expect_rev: str = "",
    fmt: str = "text",
    report: Path | None = None,
) -> int:
    env = dict(os.environ if env is None else env)
    root = rc.root
    # Every coverage process reads and writes the same data file, wherever it runs.
    env.setdefault("COVERAGE_FILE", str(root / groups.DATA_FILE))
    ctx = GateContext(
        product,
        rc,
        gate,
        runner or default_runner(product),
        env,
        base=base,
        expect_rev=expect_rev,
        fmt=fmt,
    )
    results = run_steps(ctx)
    code = exit_code(results)
    _print(ctx, results, code)
    path = report or root / ".odoo-nix" / "gate" / f"{gate}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report_doc(ctx, results, code), indent=2) + "\n")
    summary_file = env.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(summary(gate, results))
    return code


def run(args: argparse.Namespace) -> int:
    product: Product = args.product
    rc = common.load(product)
    expect_rev = (
        args.expect_rev
        if args.expect_rev is not None
        else os.environ.get(f"{product.identity.env_prefix}_EXPECT_REV", "")
    )
    return run_gate(
        product,
        rc,
        args.gate,
        base=args.base,
        expect_rev=expect_rev,
        fmt=args.format or common.default_format(),
        report=Path(args.report).resolve() if args.report else None,
    )


def register(sub: argparse._SubParsersAction, product: Product) -> None:
    p = sub.add_parser(
        "gate",
        help="run a CI gate: lint or test",
        description=help_text(product, "gate", __doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "gate", choices=GATES, help=help_text(product, "gate gate", "the gate")
    )
    p.add_argument(
        "--base",
        metavar="SHA",
        default="",
        help=help_text(
            product,
            "gate --base",
            "lint: the revision the ratchet compares with (default: the pull request's"
            " merge-base; none on a push)",
        ),
    )
    p.add_argument(
        "--expect-rev",
        metavar="REV",
        default=None,
        help=help_text(
            product,
            "gate --expect-rev",
            "lint: passed to sync --check (default: $ODOO_NIX_EXPECT_REV)",
        ),
    )
    p.add_argument(
        "--report",
        metavar="PATH",
        default="",
        help=help_text(
            product,
            "gate --report",
            "the JSON report (default: .odoo-nix/gate/<gate>.json)",
        ),
    )
    common.add_format(p)
    p.set_defaults(func=run)


GATE = Command("gate", register)
