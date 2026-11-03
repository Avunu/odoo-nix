"""What odoo-nix adds to the template context (DESIGN.md §2.4), and its gates.

``template_globals`` adds the discovery facts every template reads (shape, series, addons),
the effective series data (``series.effective``) and the tools each live module puts in
``tools/pyproject.toml`` and ``package.json``. ``gates`` decides which CI gates a checkout
has. ``url_placeholders`` fills the org URL templates (``{repo_name}``, ``{repo}``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from odoo_nix_tools import series

if TYPE_CHECKING:
    from standards_core.common.config import Resolved
    from standards_core.scaffold.context import NS, Checkout

# The modules whose gate is `lint` (product.LINT_MODULES; repeated so this module does
# not import the product, which imports it).
LINT_MODULES = (
    "python-lint",
    "pylint-odoo",
    "addon-manifest",
    "js-xml",
    "workflow-lint",
    "shell-lint",
    "nix-lint",
    "hygiene",
    "packaging",
    "icons",
)
GATES = ("pr-policy", "lint", "test")
# Every module that puts a tool into tools/pyproject.toml (DESIGN.md §3.1): the
# pre-commit modules need prek even when their tool comes from Nix or npm.
TOOLS_MODULES = (
    "python-lint",
    "pylint-odoo",
    "addon-manifest",
    "hygiene",
    "tests",
    "packaging",
    "icons",
    "js-xml",
    "workflow-lint",
    "shell-lint",
    "nix-lint",
    "commits",
)
NODE_TOOLS = (
    "prettier",
    "@prettier/plugin-xml",
    "eslint",
    "eslint-plugin-jsdoc",
    "globals",
)

# Product.help: command and flag help odoo-nix rewords (none yet).
HELP: Mapping[str, str] = MappingProxyType({})


def _on(modules: Mapping[str, bool], name: str) -> bool:
    return bool(modules.get(name))


def untested(cfg: Mapping[str, Any]) -> list[str]:
    """The addon names ``[[tool.odoo-nix.untested]]`` lists."""
    return [
        str(item["addon"])
        for item in cfg.get("untested") or []
        if isinstance(item, Mapping) and "addon" in item
    ]


def gates(
    modules: Mapping[str, bool], cfg: Mapping[str, Any], facts: Mapping[str, Any]
) -> list[str]:
    """The checkout's CI gates, in ``ci.gates`` order: ``pr-policy`` with commits or
    releases; ``lint`` with any lint module; ``test`` with tests and an installable
    addon that is not untested."""
    tested = set(facts.get("installable", [])) - set(untested(cfg))
    on = {
        "pr-policy": _on(modules, "commits") or _on(modules, "releases"),
        "lint": any(_on(modules, m) for m in LINT_MODULES),
        "test": _on(modules, "tests") and bool(tested),
    }
    return [gate for gate in GATES if on[gate]]


def live_tools(
    data: series.SeriesData,
    modules: Mapping[str, bool],
    cfg: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> dict[str, str]:
    """``{tool: requirement}`` for ``tools/pyproject.toml``'s dependencies, in the order
    the ``deps`` group writes them (DESIGN.md §3.1): what the live modules run."""
    tools = data.tools
    out: dict[str, str] = {}

    def add(*names: str) -> None:
        for name in names:
            if name in tools:
                out[name] = tools[name].requirement

    if not any(_on(modules, m) for m in TOOLS_MODULES):
        return out
    add("prek")
    if _on(modules, "python-lint"):
        add("ruff")
    if _on(modules, "pylint-odoo"):
        add("pylint-odoo", "odoo-pre-commit-hooks")
    if _on(modules, "hygiene"):
        add("pre-commit-hooks")
    if (_on(modules, "addon-manifest") and series.website(cfg)) or _on(
        modules, "icons"
    ):
        add("maintainer-tools")
    if _on(modules, "addon-manifest"):
        add("manifestoo")
    if _on(modules, "packaging") and facts.get("shape") == "addons":
        add("whool")
        if data.series == "20.0":
            add("manifestoo-core")
    if _on(modules, "tests"):
        add("coverage", "checklog-odoo")
    return out


def node_tools(data: series.SeriesData, modules: Mapping[str, bool]) -> dict[str, str]:
    """``{package: version}`` for ``package.json``'s devDependencies (js-xml)."""
    if not _on(modules, "js-xml"):
        return {}
    return {
        data.tools[name].package: str(data.tools[name].version)
        for name in NODE_TOOLS
        if name in data.tools
    }


def scopes(cfg: Mapping[str, Any], facts: Mapping[str, Any]) -> list[str]:
    """committed's allowed scopes: the addon names and ``commits.extra-scopes`` when
    ``commits.scopes`` is ``addons``; ``[]`` (any scope) otherwise."""
    commits = cfg.get("commits") or {}
    if commits.get("scopes", "addons") != "addons":
        return []
    names = [a["name"] for a in facts.get("addons", [])]
    return sorted({*names, *commits.get("extra-scopes", [])})


def template_globals(
    checkout: Checkout, resolved: Resolved, base_ctx: NS
) -> dict[str, Any]:
    """odoo-nix's template keys (DESIGN.md §2.4). The pre-commit hook list (``hooks``,
    stage O4) and the editor data (``ide``, stage O5) arrive with their files."""
    facts = base_ctx["discover"]
    cfg = resolved.cfg
    modules = resolved.modules
    data = series.effective(facts["series"], cfg, facts)
    return {
        **{
            key: facts[key]
            for key in (
                "shape",
                "series",
                "addons_root",
                "lock_dir",
                "config_file",
                "addons",
                "installable",
                "not_installable",
            )
        },
        "series_data": data,
        "tools": live_tools(data, modules, cfg, facts),
        "node_tools": node_tools(data, modules),
        "tools_python": data.tools_python,
        "odoo_python": data.odoo_python,
        "website": series.website(cfg),
        "scopes": scopes(cfg, facts),
    }


class Gen:
    """The generated bodies of the files no single template can hold (DESIGN.md §2.4):
    ``pylintrc``, ``eslint_config``, ``ruff_toml`` and ``exclude_block`` arrive with
    their managed files (stage O4). Pure functions of the context."""

    def __init__(self, ctx: NS) -> None:
        self.ctx = ctx


def render_helpers(ctx: NS, current: str | None) -> Mapping[str, Any]:
    return {"gen": Gen(ctx)}


def url_placeholders(ctx: NS) -> Sequence[tuple[str, str]]:
    """``{repo_name}`` (the Avunu profile's docs-url) before ``{repo}``."""
    return series.url_pairs(str(ctx.get("repo") or ""))


def regex_alt(patterns: Sequence[str]) -> str:
    """Regular expressions joined as alternatives (each kept as written)."""
    return "|".join(patterns)


def path_prefix_regex(prefixes: Sequence[str]) -> str:
    """``^(?:<p1>|<p2>)``: a regex matching paths under any of ``prefixes`` (escaped)."""
    return "^(?:" + "|".join(re.escape(p) for p in prefixes) + ")"
