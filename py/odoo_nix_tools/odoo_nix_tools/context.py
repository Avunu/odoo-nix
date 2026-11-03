"""What odoo-nix adds to the template context (DESIGN.md §2.4), and its gates.

``template_globals`` adds the discovery facts every template reads (shape, series, addons),
the effective series data (``series.effective``) and the tools each live module puts in
``tools/pyproject.toml`` and ``package.json``. ``gates`` decides which CI gates a checkout
has. ``url_placeholders`` fills the org URL templates (``{repo_name}``, ``{repo}``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from functools import cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import tomlkit
from standards_core.common.report import ConfigError

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


@cache
def ide_data() -> Mapping[str, Any]:
    """``data/ide/vscode.json``: the seed ``modules/devenv.nix`` writes and the ``ide``
    module's jsonc-merge spec (DESIGN.md §3.1 ide)."""
    from odoo_nix_tools.product import DATA

    return json.loads((DATA / "ide" / "vscode.json").read_text())


def template_globals(
    checkout: Checkout, resolved: Resolved, base_ctx: NS
) -> dict[str, Any]:
    """odoo-nix's template keys (DESIGN.md §2.4)."""
    from odoo_nix_tools import precommit

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
        "hooks": precommit.hooks(data, modules, cfg, facts),
        "tools_python": data.tools_python,
        "odoo_python": data.odoo_python,
        "website": series.website(cfg),
        "scopes": scopes(cfg, facts),
        "ide": ide_data(),
    }


# .ruff.toml's tables in OCA's layout; any other table of the series data follows.
RUFF_TABLES = (
    ("lint",),
    ("format",),
    ("lint", "per-file-ignores"),
    ("lint", "isort"),
    ("lint", "isort", "sections"),
    ("lint", "mccabe"),
)
RUFF_KEYS = {
    (): ("target-version", "fix", "extend-exclude"),
    ("lint",): (
        "extend-select",
        "extend-safe-fixes",
        "extend-ignore",
        "exclude",
        "ignore",
    ),
}
PYLINT_SECTIONS = ("MASTER", "IMPORTS", "ODOOLINT", "MESSAGES CONTROL", "REPORTS")
PYLINT_KEYS = {
    "ODOOLINT": (
        "readme-template-url",
        "manifest-required-authors",
        "manifest-required-keys",
        "manifest-deprecated-keys",
        "license-allowed",
        "valid-odoo-versions",
    ),
}
NIX_SH_EDITORCONFIG = "\n[*.{nix,sh}]\nindent_style = space\nindent_size = 2\n"


def plain(value: Any) -> Any:
    """``value`` with every read-only mapping and tuple of the series data made a plain
    dict or list."""
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    return value


def _toml_value(value: Any) -> str:
    return tomlkit.item(value).as_string()


def _toml_key(key: str) -> str:
    return tomlkit.key(key).as_string()


def _ordered(table: Mapping[str, Any], first: tuple[str, ...]) -> list[str]:
    keys = [k for k in first if k in table]
    return keys + [k for k in table if k not in keys]


def _tables(
    doc: Mapping[str, Any], path: tuple[str, ...] = ()
) -> list[tuple[str, ...]]:
    out = []
    for key, value in doc.items():
        if isinstance(value, Mapping):
            out.append((*path, key))
            out += _tables(value, (*path, key))
    return out


def _at(doc: Mapping[str, Any], path: tuple[str, ...]) -> Mapping[str, Any]:
    cur: Any = doc
    for part in path:
        cur = cur[part]
    return cur


def _local(ctx: NS) -> str:
    from odoo_nix_tools.product import PRODUCT

    return f"# {PRODUCT.markers.local}"


class Gen:
    """The generated bodies of the files no single template can hold (DESIGN.md §2.4):
    pure functions of the context and, for a local region's rule, the file on disk."""

    def __init__(self, ctx: NS, current: str | None = None) -> None:
        self.ctx = ctx
        self.current = current

    @property
    def data(self) -> series.SeriesData:
        return self.ctx["series_data"]

    # --- .editorconfig, checklog-odoo.cfg, the prettier and eslint configs -----------

    def editorconfig(self) -> str:
        """OCA's sections, then 2-space Nix and shell."""
        return self.data.files[".editorconfig"].lstrip("\n") + NIX_SH_EDITORCONFIG

    def checklog(self) -> str:
        return self.data.raw["reference_files"]["checklog-odoo.cfg"].lstrip("\n")

    def prettier_config(self) -> str:
        return self.data.files["prettier.config.cjs"].lstrip("\n")

    def eslint_config(self) -> str:
        """OCA's config with the series' ES-module globs (deviation esm-static) and,
        with ``js-xml.exclude``, a first object that ignores those paths."""
        body = self.data.files["eslint.config.cjs"].lstrip("\n")
        oca = "files: " + json.dumps(list(self.data.raw["eslint_esm_globs"])) + ","
        if oca not in body:
            raise RuntimeError(
                f"series {self.data.series}: eslint.config.cjs has no `{oca}` line"
            )
        body = body.replace(
            oca, "files: " + json.dumps(list(self.data.esm_globs)) + ","
        )
        exclude = list(self.ctx["cfg"]["js-xml"].get("exclude") or [])
        if exclude:
            start = "const config = [{"
            if start not in body:
                raise RuntimeError(
                    f"series {self.data.series}: eslint.config.cjs has no `{start}`"
                )
            ignores = json.dumps([f"{p}**" for p in exclude])
            body = body.replace(
                start, f"const config = [{{\n    ignores: {ignores},\n}}, {{", 1
            )
        return body

    # --- .ruff.toml -------------------------------------------------------------------

    def ruff_doc(self) -> dict[str, Any]:
        """The series' ruff settings with python-lint's parameters merged in."""
        params = self.ctx["cfg"]["python-lint"]
        doc = plain(self.data.ruff)
        exclude = ["odoo", "modules"] if self.ctx["shape"] == "project" else []
        exclude += [p for p in params.get("extend-exclude") or [] if p not in exclude]
        if exclude:
            doc["extend-exclude"] = exclude
        lint = doc.setdefault("lint", {})
        select = lint.setdefault("extend-select", [])
        select += [c for c in params.get("extra-select") or [] if c not in select]
        ignore = lint.get("ignore", [])
        ignore += [c for c in params.get("ignore") or [] if c not in ignore]
        if ignore:
            lint["ignore"] = ignore
        per_file = lint.setdefault("per-file-ignores", {})
        for glob, codes in (params.get("per-file-ignores") or {}).items():
            have = per_file.setdefault(glob, [])
            have += [c for c in codes if c not in have]
        return doc

    def ruff_toml(self) -> str:
        """The top-level keys first, then OCA's tables in OCA's layout; the local region
        follows in the template (DESIGN.md §3.1 python-lint)."""
        self._check_ruff_region()
        doc = self.ruff_doc()
        lines = []
        for key in _ordered(doc, RUFF_KEYS[()]):
            if not isinstance(doc[key], Mapping):
                lines.append(f"{_toml_key(key)} = {_toml_value(doc[key])}")
        tables = [t for t in RUFF_TABLES if t in _tables(doc)]
        tables += [t for t in _tables(doc) if t not in tables]
        for path in tables:
            table = _at(doc, path)
            keys = [
                k
                for k in _ordered(table, RUFF_KEYS.get(path, ()))
                if not isinstance(table[k], Mapping)
            ]
            if not keys:
                continue
            lines += ["", "[" + ".".join(path) + "]"]
            lines += [f"{_toml_key(k)} = {_toml_value(table[k])}" for k in keys]
        return "\n".join(lines) + "\n"

    def _check_ruff_region(self) -> None:
        if self.current is None:
            return
        from standards_core.scaffold import regions

        from odoo_nix_tools.product import PRODUCT

        bodies = regions.parse(PRODUCT, self.current, ".ruff.toml", ("ruff",))
        content = [
            line.strip()
            for line in bodies.get("ruff", [])
            if line.strip() and not line.strip().startswith("#")
        ]
        if content and not content[0].startswith("["):
            raise ConfigError(
                ".ruff.toml: the ruff local region follows [lint.mccabe]: start it with a"
                " table header, or use python-lint's parameters"
            )

    # --- .pylintrc, .pylintrc-mandatory -----------------------------------------------

    def pylint_sections(self, kind: str) -> dict[str, dict[str, str]]:
        """The sections of ``.pylintrc`` (``optional``) or ``.pylintrc-mandatory``, with
        addon-manifest's licenses."""
        name = ".pylintrc" if kind == "optional" else ".pylintrc-mandatory"
        sections = plain(self.data.pylint["sections"][name])
        licenses = list(
            (self.ctx["cfg"].get("addon-manifest") or {}).get("licenses-allowed") or []
        )
        odoolint = sections.setdefault("ODOOLINT", {})
        if licenses:
            odoolint["license-allowed"] = ",".join(licenses)
        odoolint["valid-odoo-versions"] = self.data.series
        return sections

    def pylintrc(self, kind: str) -> str:
        if kind not in ("optional", "mandatory"):
            raise ValueError(f"pylintrc kind {kind!r}")
        sections = self.pylint_sections(kind)
        blocks = []
        for name in _ordered(sections, PYLINT_SECTIONS):
            values = sections[name]
            lines = [f"[{name}]"]
            for key in _ordered(values, PYLINT_KEYS.get(name, ())):
                value = str(values[key]).replace("\n", "\n    ")
                lines.append(f"{key}={value}")
            blocks.append("\n".join(lines) + "\n")
        return "\n".join(blocks)

    # --- .pre-commit-config.yaml ------------------------------------------------------

    def exclude_block(self) -> str:
        from odoo_nix_tools import precommit

        return precommit.exclude_block(
            self.data, self.ctx["discover"], _local(self.ctx)
        )

    def hooks_yaml(self) -> str:
        from odoo_nix_tools import precommit

        return precommit.hooks_yaml(list(self.ctx["hooks"]))


def render_helpers(ctx: NS, current: str | None) -> Mapping[str, Any]:
    return {"gen": Gen(ctx, current)}


def url_placeholders(ctx: NS) -> Sequence[tuple[str, str]]:
    """``{repo_name}`` (the Avunu profile's docs-url) before ``{repo}``."""
    return series.url_pairs(str(ctx.get("repo") or ""))


def regex_alt(patterns: Sequence[str]) -> str:
    """Regular expressions joined as alternatives (each kept as written)."""
    return "|".join(patterns)


def md_cell(value: Any) -> str:
    """``value`` as the text of one Markdown table cell: one line, ``|`` escaped."""
    return " ".join(str(value or "").split()).replace("|", "\\|")


def path_prefix_regex(prefixes: Sequence[str]) -> str:
    """``^(?:<p1>|<p2>)``: a regex matching paths under any of ``prefixes`` (escaped)."""
    return "^(?:" + "|".join(re.escape(p) for p in prefixes) + ")"
