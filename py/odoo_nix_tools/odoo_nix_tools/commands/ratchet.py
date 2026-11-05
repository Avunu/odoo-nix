"""``odoo-nix ratchet coverage`` (DESIGN.md §6.3): the coverage floor only rises.

``--base SHA`` compares the work tree with a base revision (the lint gate passes the pull
request's merge-base):

- R1: ``[tool.coverage.report] fail_under`` in ``tools/pyproject.toml`` is not lower than
  the base's;
- R2: ``[[tool.odoo-nix.untested]]`` names no addon the base's did not.

When the base's config file has no ``[tool.odoo-nix]`` (the adoption's own pull request,
which sets the start) there is nothing to compare: exit 0.

``--raise``, after a coverage run, sets ``fail_under`` to the measured total rounded down
when that is higher, and never lowers it; only the value changes. The total is
``--total PCT``, else ``coverage report --format=total`` over the run's data
(``COVERAGE_FILE``, default ``.odoo-nix/coverage/.coverage``). It is not a gate step:
developers and a scheduled job commit what it writes.

Exit 0, 1 when a rule is broken, 2 for the configuration, 3 for the environment.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit
from standards_core.commands import Command, help_text
from standards_core.common import pyproject, repo
from standards_core.common.report import CLEAN, ConfigError, EnvError

from odoo_nix_tools import context, discover, groups
from odoo_nix_tools.commands import common
from odoo_nix_tools.commands.common import Problem

if TYPE_CHECKING:
    from standards_core.product import Product

TOOLS_PYPROJECT = "tools/pyproject.toml"


def _toml(text: str | None, where: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{where}: {e}") from e


def fail_under(doc: Mapping[str, Any]) -> float:
    report = doc.get("tool", {}).get("coverage", {}).get("report", {})
    value = report.get("fail_under", 0) if isinstance(report, Mapping) else 0
    return float(value) if isinstance(value, int | float) else 0.0


def table(doc: Mapping[str, Any]) -> Mapping[str, Any] | None:
    found = doc.get("tool", {}).get(discover.TABLE)
    return found if isinstance(found, Mapping) else None


def _show(root: Path, rev: str, rel: str) -> str | None:
    try:
        return repo.git(root, "show", f"{rev}:{rel}")
    except EnvError:
        return None


def _number(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def compare(root: Path, base: str) -> tuple[list[Problem], str | None]:
    """R1 and R2 against ``base``: ``(problems, why skipped)``."""
    try:
        repo.git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except EnvError as e:
        raise EnvError(f"the base {base!r} is not a commit here: {e}") from e
    config = discover.config_file(root)
    head_table = table(
        _toml((root / config).read_text() if (root / config).is_file() else "", config)
    )
    if head_table is None:
        raise ConfigError(f"{config} has no [tool.{discover.TABLE}] table")
    base_table = table(_toml(_show(root, base, config), f"{base}:{config}"))
    if base_table is None:
        return [], (
            f"the base has no [tool.{discover.TABLE}] in {config}: the adoption sets"
            " the start"
        )
    out = []
    tools = root / TOOLS_PYPROJECT
    head_floor = fail_under(
        _toml(tools.read_text() if tools.is_file() else "", TOOLS_PYPROJECT)
    )
    base_floor = fail_under(
        _toml(_show(root, base, TOOLS_PYPROJECT), f"{base}:{TOOLS_PYPROJECT}")
    )
    if head_floor < base_floor:
        out.append(
            Problem(
                TOOLS_PYPROJECT,
                f"[tool.coverage.report] fail_under fell from {_number(base_floor)} to"
                f" {_number(head_floor)}: the coverage floor only rises",
            )
        )
    gained = sorted(
        set(context.untested(head_table)) - set(context.untested(base_table))
    )
    if gained:
        out.append(
            Problem(
                config,
                f"[[tool.{discover.TABLE}.untested]] gained {', '.join(gained)}: an addon"
                " leaves the tests only in a pull request of its own, which this check"
                " fails until a maintainer merges it",
            )
        )
    return out, None


def measured_total(root: Path) -> float:
    """``coverage report --format=total`` over the run's data: the first line that is a
    number. Under ``fail_under`` coverage prints the total, then ``Coverage failure: …``,
    and exits 2; the total is what counts (``--raise`` never lowers the floor)."""
    env = dict(os.environ)
    env.setdefault("COVERAGE_FILE", str(root / groups.DATA_FILE))
    argv = [
        common.tool(root, "coverage"),
        "report",
        f"--rcfile={TOOLS_PYPROJECT}",
        "--format=total",
        "--precision=2",
    ]
    proc = subprocess.run(
        argv, cwd=root, env=env, capture_output=True, text=True, check=False
    )
    for line in proc.stdout.splitlines():
        with contextlib.suppress(ValueError):
            return float(line.strip())
    raise EnvError(
        f"coverage report --format=total gave no total (exit {proc.returncode}):"
        f" {(proc.stderr or proc.stdout).strip()}"
    )


def raise_floor(root: Path, total: float) -> tuple[float, float]:
    """Set ``fail_under`` to ``floor(total)`` when that is higher: ``(old, new)``."""
    path = root / TOOLS_PYPROJECT
    if not path.is_file():
        raise ConfigError(f"no {TOOLS_PYPROJECT}: the tests module writes it")
    text = path.read_text()
    doc = tomlkit.parse(text)
    old = fail_under(doc.unwrap())
    new = math.floor(total)
    if new <= old:
        return old, old
    tool = doc.setdefault("tool", tomlkit.table())
    coverage = tool.setdefault("coverage", tomlkit.table())
    report = coverage.setdefault("report", tomlkit.table())
    report["fail_under"] = new
    path.write_text(tomlkit.dumps(doc))
    return old, float(new)


def run(args: argparse.Namespace) -> int:
    product: Product = args.product
    root = pyproject.checkout_root(product)
    cli = f"{product.identity.cli} ratchet coverage"
    if args.raise_:
        total = args.total if args.total is not None else measured_total(root)
        old, new = raise_floor(root, total)
        if new > old:
            print(
                f"{cli}: fail_under {_number(old)} → {_number(new)} (measured {total:g})"
            )
        else:
            print(f"{cli}: fail_under stays {_number(old)} (measured {total:g})")
        if not args.base:
            return CLEAN
    if not args.base:
        raise ConfigError("give --base SHA (compare) or --raise")
    found, skipped = compare(root, args.base)
    if skipped:
        print(f"{cli}: {skipped}")
        return CLEAN
    return common.report(found, args.format, cli)


def register(sub: argparse._SubParsersAction, product: Product) -> None:
    p = sub.add_parser(
        "ratchet",
        help="the coverage floor only rises",
        description=help_text(product, "ratchet", __doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "what",
        choices=("coverage",),
        help=help_text(product, "ratchet what", "what to ratchet"),
    )
    p.add_argument(
        "--base",
        metavar="SHA",
        default="",
        help=help_text(
            product,
            "ratchet --base",
            "compare with this revision (R1 fail_under, R2 untested)",
        ),
    )
    p.add_argument(
        "--raise",
        dest="raise_",
        action="store_true",
        help=help_text(
            product,
            "ratchet --raise",
            "set fail_under to the measured total, rounded down, when that is higher",
        ),
    )
    p.add_argument(
        "--total",
        type=float,
        default=None,
        metavar="PCT",
        help=help_text(
            product,
            "ratchet --total",
            "the measured total for --raise (default: coverage report --format=total)",
        ),
    )
    common.add_format(p)
    p.set_defaults(func=run)


RATCHET = Command("ratchet", register)
