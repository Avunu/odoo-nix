"""OCA's per-series data, and the deviations odoo-nix applies to it (DESIGN.md §3.0).

``data/series/<series>.json`` records OCA's template for one Odoo series verbatim
(``scripts/gen_series_data.py``): hooks, the top-level exclude, ruff and pylint settings,
file bodies and tool pins, with organisation answers left as ``@@…@@`` placeholders.
``effective`` returns that data as odoo-nix writes it: every deviation of ``DEVIATIONS``
that applies to the series, the configuration and the checkout's facts, then the
placeholders filled in. A placeholder left over is a ``RuntimeError`` (a product bug).

Every deviation changes the ``SeriesData`` fields it names and no other, which
``tests/test_series.py`` checks by building the data with and without it (``build``'s
``skip``); ``docs/standards/managed-files.md`` lists the table by hand, and
``tests/test_series.py`` holds its ids and ``Applies`` column to it.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from standards_core.common.report import ConfigError

DATA = Path(str(files("odoo_nix_tools") / "data"))
SERIES = re.compile(r"\d+\.0")
SCHEMA_VERSION = 1

# The managed files whose bodies the series data holds whole; .pylintrc* and .ruff.toml
# are written from the parsed settings instead (context.Gen).
FILES = (".editorconfig", "eslint.config.cjs", "prettier.config.cjs")
# odoo-nix's alternative of the top-level exclude: the locks, which their tools write.
LOCKS = r"(^|/)(uv|flake)\.lock$|(^|/)package-lock\.json$"
GITHUB = r"^\.github/"
VSCODE = r"^\.vscode/"
ESM_STATIC = ("**/static/src/**/*.js", "**/static/tests/**/*.js")
STAGES = {
    "commit": "pre-commit",
    "push": "pre-push",
    "merge-commit": "pre-merge-commit",
}
PLACEHOLDER = re.compile(r"@@[a-z_]+@@")
# Keys a `language: system` hook never carries (deviation system-language).
SYSTEM_DROPS = ("additional_dependencies", "rev", "default_language_version")


@dataclass(frozen=True)
class Tool:
    """One tool a hook or a gate runs, pinned for the locks."""

    name: str  # the series data's key: "odoo-pre-commit-hooks", "prettier"
    package: str  # what the lock installs: "oca-odoo-pre-commit-hooks"
    ecosystem: Literal["pypi", "git", "npm"]
    version: str | None  # the exact pin, or None for a range (manifestoo-core>=1.16.1)
    requirement: str  # PEP 508 (pypi, git) or <package>@<version> (npm)
    provides_hooks: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeriesData:
    series: str
    raw: Mapping[str, Any]  # the JSON file, as generated
    tools: Mapping[str, Tool]  # OCA's pins + data/tool-pins.json
    hooks: tuple[Mapping[str, Any], ...]  # OCA's order, after the deviations
    exclude: tuple[Mapping[str, Any], ...]  # the top-level exclude's alternatives
    ruff: Mapping[str, Any]
    pylint: Mapping[str, Any]
    files: Mapping[str, str]  # FILES' bodies
    esm_globs: tuple[str, ...]  # eslint's ES-module globs
    node: str  # the node major the shell and CI run ("22", "24")
    odoo_python: str  # the series' requires-python (lib/odoo-presets.json)
    tools_python: str  # the tools environment's interpreter ("python3.12")
    deviations: tuple[str, ...]  # the ids applied, in order


@dataclass(frozen=True)
class Deviation:
    id: str
    applies: str  # when, in words (docs/standards/managed-files.md)
    fields: tuple[str, ...]  # the SeriesData fields it changes
    change: str
    status: Literal["applied", "proposed"] = "applied"


# --- data files ----------------------------------------------------------------------


def known() -> tuple[str, ...]:
    """Every series with a data file, oldest first."""
    names = (p.stem for p in (DATA / "series").glob("*.json"))
    return tuple(sorted((n for n in names if SERIES.fullmatch(n)), key=_major))


def _major(series: str) -> int:
    return int(series.split(".", 1)[0])


def unknown_series(series: str) -> ConfigError:
    from odoo_nix_tools import __version__

    major = __version__.split(".", 1)[0]
    return ConfigError(
        f"no data for Odoo series {series}: odoo-nix-tools {major}.x knows series"
        f" {', '.join(known())}"
    )


@cache
def load(series: str) -> Mapping[str, Any]:
    """``data/series/<series>.json``; an unknown series is exit 2."""
    if not SERIES.fullmatch(series) or series not in known():
        raise unknown_series(series)
    doc = json.loads((DATA / "series" / f"{series}.json").read_text())
    if doc.get("schema_version") != SCHEMA_VERSION or doc.get("series") != series:
        raise RuntimeError(
            f"data/series/{series}.json: schema_version {doc.get('schema_version')!r}"
            f" for series {doc.get('series')!r}; odoo-nix-tools reads version"
            f" {SCHEMA_VERSION}"
        )
    return doc


@cache
def tool_pins() -> Mapping[str, str]:
    """``data/tool-pins.json``: package → specifier."""
    return json.loads((DATA / "tool-pins.json").read_text())["tools"]


@cache
def presets() -> Mapping[str, Any]:
    """``data/odoo-presets.json``, a copy of lib/odoo-presets.json (test_series keeps
    them equal)."""
    return json.loads((DATA / "odoo-presets.json").read_text())


# --- configuration values the data reads ---------------------------------------------


def _param(cfg: Mapping[str, Any], module: str, key: str, default: Any) -> Any:
    table = cfg.get(module)
    return table.get(key, default) if isinstance(table, Mapping) else default


def url_pairs(repo: str) -> tuple[tuple[str, str], ...]:
    """The URL template placeholders (``hooks.url_placeholders``), longest first."""
    return (("repo_name", repo.partition("/")[2]), ("repo", repo))


def website(cfg: Mapping[str, Any]) -> str:
    """``addon-manifest.website`` with its placeholders filled in; ``""`` when unset."""
    out = str(_param(cfg, "addon-manifest", "website", "") or "")
    for key, value in url_pairs(str(cfg.get("repo") or "")):
        out = out.replace("{" + key + "}", value)
    return out


def author(cfg: Mapping[str, Any]) -> str:
    return str(_param(cfg, "addon-manifest", "author", "") or "")


# --- the deviations ------------------------------------------------------------------


@dataclass
class _State:
    series: str
    cfg: Mapping[str, Any]
    facts: Mapping[str, Any]
    tools: dict[str, Tool]
    hooks: list[dict[str, Any]]
    exclude: list[dict[str, Any]]
    pylint: dict[str, Any]
    esm_globs: list[str]
    node: str

    def hook(self, hook_id: str) -> dict[str, Any] | None:
        return next((h for h in self.hooks if h["id"] == hook_id), None)


def _drop(hook_id: str) -> Callable[[_State], None]:
    def apply(s: _State) -> None:
        s.hooks = [h for h in s.hooks if h["id"] != hook_id]

    return apply


# The tools odoo-nix adds to OCA's: prek runs the hooks, coverage measures the tests.
OWN_TOOLS = ("prek", "coverage")


def _pins(s: _State) -> None:
    pins = tool_pins()
    for name, tool in list(s.tools.items()):
        if tool.ecosystem == "npm" or tool.version is not None:
            continue
        if name not in pins:
            raise RuntimeError(
                f"data/tool-pins.json pins no {name}, which series {s.series} leaves open"
            )
        s.tools[name] = _pinned(name, tool.package, pins[name], tool.provides_hooks)
    for name, spec in pins.items():
        if name not in s.tools and name in OWN_TOOLS:
            s.tools[name] = _pinned(name, name, spec, ())


def _pinned(name: str, package: str, spec: str, hooks: tuple[str, ...]) -> Tool:
    version = spec.removeprefix("==") if spec.startswith("==") else None
    return Tool(name, package, "pypi", version, f"{package}{spec}", hooks)


def _no_readme_fix(s: _State) -> None:
    hook = s.hook("oca-checks-odoo-module")
    if hook is None or "--fix" not in hook.get("args", []):
        raise RuntimeError(f"series {s.series}: oca-checks-odoo-module has no --fix")
    hook["args"] = [a for a in hook["args"] if a != "--fix"]


def _stage_names(s: _State) -> None:
    for hook in s.hooks:
        if "stages" in hook:
            hook["stages"] = [STAGES.get(stage, stage) for stage in hook["stages"]]


_CONTRIBUTING = r"CONTRIBUTING\.md|"


def _forbid_contributing(s: _State) -> None:
    hook = s.hook("obsolete dotfiles")
    if hook is None or _CONTRIBUTING not in hook.get("files", ""):
        raise RuntimeError(
            f"series {s.series}: the obsolete dotfiles hook's files regex has no"
            f" {_CONTRIBUTING!r}: check the deviation forbid-contributing"
        )
    hook["files"] = hook["files"].replace(_CONTRIBUTING, "", 1)


def _addons_dir(s: _State) -> None:
    hook = s.hook("oca-fix-manifest-website")
    if hook is not None:
        root = s.facts.get("addons_root") or "."
        hook["args"] = [f"--addons-dir={root}", *hook.get("args", [])]


def _github_per_hook(s: _State) -> None:
    s.exclude = [a for a in s.exclude if not a.get("moved_to_per_hook")]
    for hook in s.hooks:
        own = hook.get("exclude")
        hook["exclude"] = f"{GITHUB}|{own}" if own else GITHUB


def _prettier_vscode(s: _State) -> None:
    hook = s.hook("prettier")
    if hook is not None:
        own = hook.get("exclude")
        hook["exclude"] = f"{own}|{VSCODE}" if own else VSCODE


def _system_language(s: _State) -> None:
    for hook in s.hooks:
        for key in SYSTEM_DROPS:
            hook.pop(key, None)
        if hook.get("upstream_language") == "fail" or hook.get("kind") == "fail":
            hook["language"] = "fail"
            continue
        hook["language"] = "system"
        tool = s.tools.get(hook.get("tool") or "")
        if tool is None:
            raise RuntimeError(
                f"series {s.series}: hook {hook['id']!r} names no known tool"
            )
        prefix = "node_modules/.bin/" if tool.ecosystem == "npm" else "tools/.venv/bin/"
        hook["entry"] = prefix + hook["entry"]


def _locks_excluded(s: _State) -> None:
    s.exclude.append(
        {"comment": "odoo-nix: locks", "moved_to_per_hook": False, "pattern": LOCKS}
    )


def _esm_static(s: _State) -> None:
    s.esm_globs += [g for g in ESM_STATIC if g not in s.esm_globs]


def _split_enable(text: str) -> list[str]:
    return [m.strip() for m in text.split(",") if m.strip()]


def _join_enable(names: list[str]) -> str:
    return ",\n".join(names)


def _rewrite_enable(s: _State, fn: Callable[[list[str]], list[str]]) -> None:
    for name, messages in s.pylint["messages"].items():
        messages["enable"] = fn(list(messages["enable"]))
        control = s.pylint["sections"].get(name, {}).get("MESSAGES CONTROL")
        if control is not None and "enable" in control:
            control["enable"] = _join_enable(fn(_split_enable(control["enable"])))


def _pylint_dedupe(s: _State) -> None:
    _rewrite_enable(s, lambda names: list(dict.fromkeys(names)))


def _required_author(s: _State) -> None:
    s.pylint["odoolint"].pop("manifest-required-authors", None)
    for section in s.pylint["sections"].values():
        section.get("ODOOLINT", {}).pop("manifest-required-authors", None)
    _rewrite_enable(
        s, lambda names: [n for n in names if n != "manifest-required-author"]
    )


def _node_runtime(s: _State) -> None:
    s.node = _preset_node(s.series)


def _preset_node(series: str) -> str:
    attr = presets()[series]["nodejs"]  # "nodejs_24"
    return attr.removeprefix("nodejs_")


def _always(series: str, cfg: Mapping[str, Any], facts: Mapping[str, Any]) -> bool:
    return True


# (deviation, when it applies, how) in the order they are applied.
_PIPELINE: tuple[
    tuple[
        Deviation,
        Callable[[str, Mapping[str, Any], Mapping[str, Any]], bool],
        Callable[[_State], None],
    ],
    ...,
] = (
    (
        Deviation(
            "odoo-nix-pins",
            "always",
            ("tools",),
            "manifestoo, checklog-odoo and manifestoo-core (null in OCA's data), prek and"
            " coverage come from data/tool-pins.json",
        ),
        _always,
        _pins,
    ),
    (
        Deviation(
            "drop-gen-readme",
            "always",
            ("hooks",),
            "hook oca-gen-addon-readme dropped: READMEs are Markdown, written by hand"
            " (OCA's own CI skips it too)",
        ),
        _always,
        _drop("oca-gen-addon-readme"),
    ),
    (
        Deviation(
            "drop-excluded-addons",
            "always",
            ("hooks",),
            "hook oca-update-pre-commit-excluded-addons dropped: odoo-nix renders the"
            " NOT INSTALLABLE ADDONS region from discovery; the hook would rewrite"
            " .pre-commit-config.yaml, .gitignore and .coveragerc",
        ),
        _always,
        _drop("oca-update-pre-commit-excluded-addons"),
    ),
    (
        Deviation(
            "drop-external-deps",
            "always (proposed, pending sign-off)",
            ("hooks",),
            "hook oca-gen-external-dependencies dropped: the requirements.txt it writes"
            " is read by nothing in odoo-nix's uv model (addons mode derives the lock"
            " from the manifests)",
            status="proposed",
        ),
        _always,
        _drop("oca-gen-external-dependencies"),
    ),
    (
        Deviation(
            "no-readme-fix",
            "series 20.0",
            ("hooks",),
            "oca-checks-odoo-module loses --fix (20.0's hook can rename README.md to"
            " README.rst)",
        ),
        lambda series, cfg, facts: series == "20.0",
        _no_readme_fix,
    ),
    (
        Deviation(
            "stage-names",
            "series 18.0",
            ("hooks",),
            "stages commit/push/merge-commit become pre-commit/pre-push/pre-merge-commit"
            " (pre-commit-hooks v4.6.0's manifest uses the old names)",
        ),
        lambda series, cfg, facts: series == "18.0",
        _stage_names,
    ),
    (
        Deviation(
            "forbid-contributing",
            "hygiene.forbid-contributing = false",
            ("hooks",),
            "the obsolete dotfiles hook's files regex loses the CONTRIBUTING.md"
            " alternative",
        ),
        lambda series, cfg, facts: (
            _param(cfg, "hygiene", "forbid-contributing", True) is False
        ),
        _forbid_contributing,
    ),
    (
        Deviation(
            "addons-dir",
            "projects",
            ("hooks",),
            "oca-fix-manifest-website gets --addons-dir=<addons_root> before its URL (its"
            " default, ., finds no addon in a project)",
        ),
        lambda series, cfg, facts: facts.get("shape") == "project",
        _addons_dir,
    ),
    (
        Deviation(
            "github-per-hook",
            "always",
            ("hooks", "exclude"),
            "^.github/ leaves the top-level exclude; every OCA hook excludes ^\\.github/"
            " itself, so actionlint, zizmor and check-yaml see .github/",
        ),
        _always,
        _github_per_hook,
    ),
    (
        Deviation(
            "prettier-vscode",
            "always",
            ("hooks",),
            "prettier excludes ^\\.vscode/, as check-json does: the editor's JSONC files"
            " keep the layout jsonc-merge preserves",
        ),
        _always,
        _prettier_vscode,
    ),
    (
        Deviation(
            "system-language",
            "always",
            ("hooks",),
            "every hook is language: system (or fail) and runs the locked executable"
            " (tools/.venv/bin, node_modules/.bin); additional_dependencies, rev and"
            " default_language_version are dropped",
        ),
        _always,
        _system_language,
    ),
    (
        Deviation(
            "locks-excluded",
            "always",
            ("exclude",),
            "the top-level exclude gains the locks: (^|/)(uv|flake)\\.lock$ and"
            " (^|/)package-lock\\.json$",
        ),
        _always,
        _locks_excluded,
    ),
    (
        Deviation(
            "esm-static",
            "series 18.0 and later",
            ("esm_globs",),
            "eslint parses **/static/src/**/*.js and **/static/tests/**/*.js as ES"
            " modules: Odoo 18.0 and later load them as such",
        ),
        lambda series, cfg, facts: _major(series) >= 18,
        _esm_static,
    ),
    (
        Deviation(
            "pylint-dedupe",
            "always",
            ("pylint",),
            "a message listed twice in a .pylintrc* enable list is written once (the"
            " first)",
        ),
        _always,
        _pylint_dedupe,
    ),
    (
        Deviation(
            "required-author",
            'addon-manifest.author = ""',
            ("pylint",),
            "manifest-required-authors is not written and manifest-required-author"
            " leaves both enable lists (pylint-odoo would require OCA's author)",
        ),
        lambda series, cfg, facts: author(cfg) == "",
        _required_author,
    ),
    (
        Deviation(
            "node-runtime",
            "series 19.0 and 20.0",
            ("node",),
            "node is the series preset's (nodejs_24), not OCA's"
            " default_language_version.node",
        ),
        lambda series, cfg, facts: _preset_node(series) != _oca_node(load(series)),
        _node_runtime,
    ),
)

DEVIATIONS: tuple[Deviation, ...] = tuple(d for d, _, _ in _PIPELINE)


def _oca_node(raw: Mapping[str, Any]) -> str:
    return str(raw["node"]["default_language_version"]).split(".", 1)[0]


# --- the effective data --------------------------------------------------------------


def _tools(raw: Mapping[str, Any]) -> dict[str, Tool]:
    out = {}
    for name, tool in sorted(raw["tools"].items()):
        out[name] = Tool(
            name=name,
            package=tool["package"],
            ecosystem=tool["ecosystem"],
            version=tool["version"],
            requirement=tool["requirement"],
            provides_hooks=tuple(tool.get("provides_hooks", ())),
        )
    return out


def _fill(value: Any, pairs: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for token, text in pairs.items():
            value = value.replace(token, text)
        return value
    if isinstance(value, list):
        return [_fill(v, pairs) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, pairs) for k, v in value.items()}
    return value


def _frozen(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _frozen(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_frozen(v) for v in value)
    return value


def build(
    series: str,
    cfg: Mapping[str, Any],
    facts: Mapping[str, Any],
    *,
    skip: frozenset[str] | set[str] = frozenset(),
) -> SeriesData:
    """The series data with every applicable deviation but those in ``skip``, and the
    placeholders filled in where the configuration has a value. ``effective`` is this,
    with nothing skipped and no placeholder left."""
    raw = load(series)
    unknown = set(skip) - {d.id for d in DEVIATIONS}
    if unknown:
        raise ValueError(f"no deviation {', '.join(sorted(unknown))}")
    state = _State(
        series=series,
        cfg=cfg,
        facts=facts,
        tools=_tools(raw),
        hooks=copy.deepcopy(list(raw["hooks"])),
        exclude=copy.deepcopy(list(raw["exclude"]["alternatives"])),
        pylint=copy.deepcopy(dict(raw["pylint"])),
        esm_globs=list(raw["eslint_esm_globs"]),
        node=_oca_node(raw),
    )
    applied = []
    for deviation, applies, apply in _PIPELINE:
        if deviation.id in skip or not applies(series, cfg, facts):
            continue
        apply(state)
        applied.append(deviation.id)

    url = website(cfg)
    if not url:
        # The hook writes the website it is given; with none it has nothing to write
        # (the addon-manifest module's rule, applied here so no placeholder is left).
        state.hooks = [h for h in state.hooks if h["id"] != "oca-fix-manifest-website"]
    pairs = {"@@repo_website@@": url} if url else {}
    if author(cfg):
        pairs["@@org_name@@"] = author(cfg)
    return SeriesData(
        series=series,
        raw=raw,
        tools=MappingProxyType(state.tools),
        hooks=tuple(_frozen(_fill(h, pairs)) for h in state.hooks),
        exclude=tuple(_frozen(a) for a in state.exclude),
        ruff=_frozen(copy.deepcopy(raw["ruff"])),
        pylint=_frozen(_fill(state.pylint, pairs)),
        files=MappingProxyType({name: raw["files"][name] for name in FILES}),
        esm_globs=tuple(state.esm_globs),
        node=state.node,
        odoo_python=presets()[series]["requiresPython"],
        tools_python=raw["python"]["default_language_version"],
        deviations=tuple(applied),
    )


def placeholders_left(data: SeriesData) -> list[str]:
    """Every ``@@…@@`` token still in the data odoo-nix writes from, with where."""
    out = []

    def walk(value: Any, where: str) -> None:
        if isinstance(value, str):
            out.extend(f"{where}: {m}" for m in PLACEHOLDER.findall(value))
        elif isinstance(value, Mapping):
            for k, v in value.items():
                walk(v, f"{where}.{k}")
        elif isinstance(value, tuple | list):
            for i, v in enumerate(value):
                walk(v, f"{where}[{i}]")

    for name in ("hooks", "exclude", "ruff", "pylint", "files", "esm_globs"):
        walk(getattr(data, name), name)
    walk({k: t.requirement for k, t in data.tools.items()}, "tools")
    return out


def effective(
    series: str, cfg: Mapping[str, Any], facts: Mapping[str, Any]
) -> SeriesData:
    """The series data odoo-nix writes from (DESIGN.md §3.0)."""
    data = build(series, cfg, facts)
    left = placeholders_left(data)
    if left:
        raise RuntimeError(
            f"series {series}: placeholders left after the deviations: {'; '.join(left)}"
        )
    return data
