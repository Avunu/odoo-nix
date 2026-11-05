"""The merged files' key groups: ``tools/pyproject.toml`` and ``package.json`` (DESIGN.md §3.1).

``tools/pyproject.toml`` is the tools project every module that runs a tool contributes
to. Each key belongs to one group (core DESIGN.md §5.3), so ``[project].dependencies`` is
owned by one group, ``deps``, and which tools it holds is decided by package name in
``reconcile``: a known tool whose module is off is removed, a hand-raised pin at or above
the rendered one is kept, a package odoo-nix does not know is the checkout's and stays.

``package.json`` holds the locked JavaScript tools of ``js-xml``; every other key (a
frontend's own scripts and dependencies) is the checkout's.

Both handlers delete the file when the merge leaves nothing in it: every key was sync's,
and its modules are off now.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from standards_core.common.report import DRIFT, INVALID
from standards_core.scaffold import floors, tomlmerge
from standards_core.scaffold.engine import Item
from standards_core.scaffold.jsonmerge import JsonGroups, JsonGroupsHandler
from standards_core.scaffold.tomlmerge import TomlGroups, TomlMergeHandler

from odoo_nix_tools import context, series

if TYPE_CHECKING:
    from standards_core.scaffold.context import NS
    from standards_core.scaffold.engine import Plan
    from standards_core.scaffold.manifest import Entry

KeyPath = tuple[str, ...]
DEPS = ("project", "dependencies")
COVERAGE_OMIT = [
    ".odoo-nix/*",
    "*/tests/*",
    "*/migrations/*",
    "*/upgrades/*",
    "*/__manifest__.py",
]
DATA_FILE = ".odoo-nix/coverage/.coverage"


def _on(modules: Mapping[str, Any], name: str) -> bool:
    return bool(modules.get(name))


def tools_on(modules: Mapping[str, Any]) -> bool:
    """Whether the tools project exists: a module that puts a tool in it is on."""
    return any(_on(modules, m) for m in context.TOOLS_MODULES)


# --- tools/pyproject.toml ------------------------------------------------------------


def _deps(ctx: NS) -> list[str]:
    """The ``deps`` group's list: the live modules' tools. With every tool module off it
    is what ``HEAD``'s modules rendered, so the core retracts the list only while it is
    still that (core DESIGN.md §5.3)."""
    if tools_on(ctx.modules):
        return list(ctx.tools.values())
    previous = ctx.get("previous")
    if not previous:
        return []
    data = ctx.series_data
    return list(
        context.live_tools(data, previous.modules, previous.cfg, ctx.discover).values()
    )


def tools_groups(ctx: NS) -> dict[str, list[tuple[KeyPath, Any]]]:
    facts = ctx.discover
    return {
        "project": [
            (("project", "name"), f"{ctx.name}-tools"),
            (("project", "version"), "0"),
            (("project", "requires-python"), ctx.odoo_python),
            (("tool", "uv", "package"), False),
        ],
        "deps": [(DEPS, _deps(ctx))],
        "tests": [
            (
                ("tool", "coverage", "run"),
                {
                    # Addons mode's "." would reach OCB and the external sources
                    # through the .odoo-nix/ links: they are omitted.
                    "source": [facts["addons_root"]],
                    "branch": True,
                    "parallel": True,
                    "data_file": DATA_FILE,
                    "omit": list(COVERAGE_OMIT),
                },
            ),
            (("tool", "coverage", "report", "show_missing"), True),
            (("tool", "coverage", "report", "skip_covered"), True),
        ],
    }


def tools_on_group(ctx: Any, group: str) -> bool:
    """``project`` and ``deps`` while a tool module is on; ``tests`` with tests."""
    if group == "tests":
        return _on(ctx.modules, "tests")
    return tools_on(ctx.modules)


def _name(item: str) -> str | None:
    try:
        return canonicalize_name(Requirement(item).name)
    except InvalidRequirement:
        return None


def known_packages(data: series.SeriesData) -> set[str]:
    """Every Python package odoo-nix may put in the list: the series' tools and the
    pins of ``data/tool-pins.json``."""
    names = {
        canonicalize_name(t.package)
        for t in data.tools.values()
        if t.ecosystem != "npm"
    }
    return names | {canonicalize_name(n) for n in series.tool_pins()}


def _floor(item: str) -> tuple[str, Version] | None:
    """``(operator, version)`` of a one-clause ``==`` or ``>=`` requirement."""
    try:
        req = Requirement(item)
    except InvalidRequirement:
        return None
    if req.url or req.marker:
        return None
    specs = list(req.specifier)
    if len(specs) != 1 or specs[0].operator not in ("==", ">="):
        return None
    try:
        return specs[0].operator, Version(specs[0].version)
    except InvalidVersion:
        return None


def keep_raised(have: str, rendered: str) -> bool:
    """Whether a hand-raised pin wins over the rendered one (floor semantics): an
    ``==`` pin at or above the rendered ``==`` pin; for a rendered ``>=`` floor, an
    ``==`` or ``>=`` at or above it. A URL requirement is always the rendered one."""
    want, got = _floor(rendered), _floor(have)
    if want is None or got is None:
        return False
    if want[0] == "==" and got[0] != "==":
        return False
    return got[1] >= want[1]


def reconcile_deps(known: set[str], have: Any, rendered: list[str]) -> list[str]:
    """The list sync writes (DESIGN.md §3.1): the rendered tools in order, each kept as
    the checkout has it when raised by hand; known tools that are not rendered removed
    (their module is off); unknown packages kept, after the rendered ones."""
    if not isinstance(have, list):
        return list(rendered)
    by_name = {}
    for item in have:
        if isinstance(item, str) and (name := _name(item)) is not None:
            by_name.setdefault(name, item)
    out = []
    names = set()
    for item in rendered:
        name = _name(item)
        names.add(name)
        current = by_name.get(name) if name is not None else None
        out.append(
            current if current is not None and keep_raised(current, item) else item
        )
    for item in have:
        name = _name(item) if isinstance(item, str) else None
        if name in names or name in known:
            continue
        out.append(item)
    return out


def tools_reconcile(ctx: NS, path: KeyPath, have: Any, rendered: Any) -> Any:
    if path == DEPS:
        return reconcile_deps(known_packages(ctx.series_data), have, rendered)
    return rendered


def tools_seeds(ctx: NS, doc: dict) -> list[tuple[KeyPath, Any]]:
    """``fail_under`` from ``tests.initial-floor``, once; the checkout's from then on
    (``odoo-nix ratchet coverage --raise`` raises it)."""
    if not _on(ctx.modules, "tests"):
        return []
    floor = ctx.cfg["tests"]["initial-floor"]
    return [(("tool", "coverage", "report", "fail_under"), floor)]


def tools_extra(doc: Any, ctx: NS) -> None:
    """With tests off, the seeded ``fail_under`` goes too while it is still the seed
    (``initial-floor``) and tests was on: the file holds nothing of the checkout's."""
    if _on(ctx.modules, "tests"):
        return
    tool = doc.get("tool")
    coverage = tool.get("coverage") if tool is not None else None
    report = coverage.get("report") if coverage is not None else None
    if report is None or "fail_under" not in report:
        return
    if tomlmerge.plain(report["fail_under"]) != ctx.cfg["tests"]["initial-floor"]:
        return
    if not tomlmerge.was_on(TOOLS, ctx, "tests"):
        return
    del report["fail_under"]
    for parent, key, table in (
        (coverage, "report", report),
        (tool, "coverage", coverage),
        (doc, "tool", tool),
    ):
        if len(table):
            break
        del parent[key]


def tools_problems(doc: dict, ctx: NS) -> list[tuple[int, str]]:
    if "ruff" in (doc.get("tool") or {}):
        return [
            (
                INVALID,
                (
                    "tools/pyproject.toml has [tool.ruff]: move it to .ruff.toml (python-lint's"
                    " parameters, or its local region)"
                ),
            )
        ]
    return []


TOOLS = TomlGroups(
    groups=tools_groups,
    on=tools_on_group,
    canon_tables=("project", "tool.uv", "tool.coverage.run", "tool.coverage.report"),
    key_order={
        ("project",): ("name", "version", "requires-python", "dependencies"),
        ("tool", "coverage", "report"): ("fail_under", "show_missing", "skip_covered"),
    },
    reconcile=tools_reconcile,
    seeds=tools_seeds,
    extra=tools_extra,
    problems=tools_problems,
)


def _deleted(item_: Item) -> Item:
    """The merged file sync deletes: the merge left nothing in it."""
    item_.wanted = None
    item_.code = DRIFT
    item_.problem = (
        "file should not exist (every key of it was sync's, and its modules are off)"
    )
    return item_


class ToolsPyproject(TomlMergeHandler):
    """``tools/pyproject.toml``: the ``TOOLS`` groups; the file goes when the merge
    leaves it empty."""

    def render(
        self,
        plan: Plan,
        entry: Entry,
        path: str,
        current: str | None,
        templates: Path | None,
    ) -> list[Item]:
        out = super().render(plan, entry, path, current, templates)
        first = out[0]
        if (
            current is not None
            and first.wanted is not None
            and not first.wanted.strip()
            and first.code in (0, DRIFT)
        ):
            out[0] = _deleted(first)
        elif current is None and first.wanted is not None and not first.wanted.strip():
            out[0] = Item(
                path, entry.strategy, None, None, entry=entry, phase=entry.phase
            )
        return out


# --- package.json --------------------------------------------------------------------

NODE_ORDER = tuple(sorted(context.NODE_TOOLS))


def package_groups(ctx: NS) -> dict[str, list[tuple[KeyPath, Any]]]:
    tools = dict(ctx.node_tools)
    if not tools:
        # Off: the pins of the series, which is what sync wrote while it was on.
        data = ctx.series_data
        tools = {
            data.tools[n].package: str(data.tools[n].version)
            for n in context.NODE_TOOLS
            if n in data.tools
        }
    return {
        "js-xml": [
            (("private",), True),
            *((("devDependencies", pkg), tools[pkg]) for pkg in sorted(tools)),
        ]
    }


def package_on(ctx: Any, group: str) -> bool:
    return _on(ctx.modules, group)


def package_reconcile(ctx: NS, path: KeyPath, have: Any, rendered: Any) -> Any:
    """A hand-raised exact version of a tool is kept."""
    if (
        len(path) == 2
        and path[0] == "devDependencies"
        and isinstance(have, str)
        and floors.version(have) is not None
        and have.strip()[:1].isdigit()
        and floors.at_least(have, str(rendered))
    ):
        return have
    return rendered


PACKAGE = JsonGroups(
    groups=package_groups,
    on=package_on,
    key_order={
        (): ("name", "private", "devDependencies"),
        ("devDependencies",): NODE_ORDER,
    },
    reconcile=package_reconcile,
)


class PackageJson(JsonGroupsHandler):
    """``package.json``: the ``PACKAGE`` group; the file goes when the merge leaves an
    empty object."""

    def render(
        self,
        plan: Plan,
        entry: Entry,
        path: str,
        current: str | None,
        templates: Path | None,
    ) -> list[Item]:
        out = super().render(plan, entry, path, current, templates)
        first = out[0]
        if (
            current is not None
            and first.wanted is not None
            and first.wanted.strip() == "{}"
        ):
            out[0] = _deleted(first)
        elif (
            current is None
            and first.wanted is not None
            and first.wanted.strip() == "{}"
        ):
            out[0] = Item(
                path, entry.strategy, None, None, entry=entry, phase=entry.phase
            )
        return out


TOOLS_HANDLER = ToolsPyproject("tools-pyproject", TOOLS)
PACKAGE_HANDLER = PackageJson("package-json", PACKAGE)
