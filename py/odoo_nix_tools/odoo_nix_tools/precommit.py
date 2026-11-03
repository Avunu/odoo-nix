"""The managed ``.pre-commit-config.yaml``: its hooks and its top-level exclude (DESIGN.md §3.3).

Every hook runs a locked executable, so no hook depends on ``PATH`` and the editor, a
commit from any client, the shell and CI run the same binaries: a tool of
``tools/uv.lock`` from ``tools/.venv/bin``, one of ``package-lock.json`` from
``node_modules/.bin``, and the engine's Nix tools from ``tools/.bin``. The relative
paths resolve from the repository root, where prek runs hooks.

``hooks`` starts from OCA's hooks for the series, after the deviations
(``series.effective``: dropped hooks, ``language: system``, the per-hook ``^\\.github/``
exclude), keeps those whose module is on, and appends odoo-nix's own (rule 5).
``exclude_block`` writes the top-level exclude: the not-installable addons, OCA's
alternatives under their comments, the ``exclude`` local region and the locks.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, Literal

from odoo_nix_tools import series

# Rule 2: the module a hook of OCA's belongs to, by the tool that provides it.
TOOL_MODULES = {
    "pre-commit-hooks": "hygiene",
    "ruff": "python-lint",
    "pylint-odoo": "pylint-odoo",
    "odoo-pre-commit-hooks": "pylint-odoo",
    "prettier": "js-xml",
    "eslint": "js-xml",
    "whool": "packaging",
    "maintainer-tools": "addon-manifest",
}
# The js-xml hooks js-xml.exclude applies to.
JS_XML_HOOKS = ("prettier", "eslint")
# The modules whose hooks the managed file holds (DESIGN.md §3.3, the entry's list).
MODULES = (
    "python-lint",
    "pylint-odoo",
    "addon-manifest",
    "js-xml",
    "workflow-lint",
    "shell-lint",
    "nix-lint",
    "hygiene",
    "commits",
    "packaging",
)
EXCLUDE_REGION = "exclude"
HOOKS_REGION = "hooks"


@dataclass(frozen=True)
class Hook:
    id: str  # OCA's id ("obsolete dotfiles" keeps its space; ids may repeat: pylint_odoo)
    name: str
    entry: str  # locked executable + OCA's entry args: "tools/.venv/bin/ruff check …"
    language: Literal["system", "fail"]
    module: str
    args: tuple[str, ...] = ()
    files: str | None = None
    exclude: str | None = None
    types: tuple[str, ...] = ()
    types_or: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    pass_filenames: bool | None = None
    always_run: bool | None = None
    require_serial: bool | None = None
    verbose: bool | None = None


# The keys a hook is written with, in this order (``module`` is odoo-nix's own).
_KEYS = (
    "id",
    "name",
    "entry",
    "args",
    "language",
    "pass_filenames",
    "always_run",
    "require_serial",
    "verbose",
    "files",
    "exclude",
    "types",
    "types_or",
    "stages",
)


def _on(modules: Mapping[str, Any], name: str) -> bool:
    return bool(modules.get(name))


def _param(cfg: Mapping[str, Any], module: str, key: str, default: Any) -> Any:
    table = cfg.get(module)
    return table.get(key, default) if isinstance(table, Mapping) else default


def module_of(hook: Mapping[str, Any]) -> str:
    """The module that owns one of OCA's hooks (rule 2); a hook no rule names is a
    product bug."""
    if hook.get("language") == "fail" or hook.get("kind") == "fail":
        return "hygiene"
    tool = hook.get("tool") or ""
    if tool not in TOOL_MODULES:
        raise RuntimeError(f"hook {hook['id']!r} (tool {tool!r}) belongs to no module")
    return TOOL_MODULES[tool]


def prefix_regex(prefixes: list[str] | tuple[str, ...]) -> str:
    """``^(?:<p1>|<p2>)``: paths under any of ``prefixes`` (escaped)."""
    return "^(?:" + "|".join(re.escape(p) for p in prefixes) + ")"


def _oca(
    data: series.SeriesData,
    modules: Mapping[str, Any],
    cfg: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> list[Hook]:
    out = []
    js_exclude = list(_param(cfg, "js-xml", "exclude", []) or [])
    optional = bool(_param(cfg, "pylint-odoo", "optional-run", True))
    for raw in data.hooks:
        module = module_of(raw)
        if not _on(modules, module):
            continue
        if raw["id"] == "whool-init" and facts.get("shape") != "addons":
            continue
        if (
            raw["id"] == "pylint_odoo"
            and "--rcfile=.pylintrc" in raw.get("args", ())
            and not optional
        ):
            continue
        exclude = raw.get("exclude")
        if raw["id"] in JS_XML_HOOKS and js_exclude:
            own = prefix_regex(js_exclude)
            exclude = f"{exclude}|{own}" if exclude else own
        out.append(
            Hook(
                id=raw["id"],
                name=raw.get("name") or raw["id"],
                entry=raw["entry"],
                language=raw["language"],
                module=module,
                args=tuple(raw.get("args") or ()),
                files=raw.get("files"),
                exclude=exclude,
                types=tuple(raw.get("types") or ()),
                types_or=tuple(raw.get("types_or") or ()),
                stages=tuple(raw.get("stages") or ()),
                pass_filenames=raw.get("pass_filenames"),
                always_run=raw.get("always_run"),
                require_serial=raw.get("require_serial"),
                verbose=raw.get("verbose"),
            )
        )
    return out


def _own(modules: Mapping[str, Any], facts: Mapping[str, Any]) -> list[Hook]:
    """odoo-nix's hooks (rule 5), after OCA's."""
    out: list[Hook] = []
    if _on(modules, "hygiene"):
        out += [
            Hook(
                "check-json",
                "check-json",
                "tools/.venv/bin/check-json",
                "system",
                "hygiene",
                types=("json",),
                # The editor's files are JSONC.
                exclude=r"^\.vscode/",
            ),
            Hook(
                "check-yaml",
                "check-yaml",
                "tools/.venv/bin/check-yaml",
                "system",
                "hygiene",
                types=("yaml",),
            ),
        ]
    if _on(modules, "workflow-lint"):
        out += [
            Hook(
                "actionlint",
                "actionlint",
                "tools/.bin/actionlint",
                "system",
                "workflow-lint",
                files=r"^\.github/workflows/.*\.ya?ml$",
            ),
            # --offline: with GH_TOKEN set (CI, a `gh auth` shell) zizmor would run its
            # online audits too, and a laptop and CI would disagree.
            Hook(
                "zizmor",
                "zizmor",
                "tools/.bin/zizmor --offline --config .github/zizmor.yml",
                "system",
                "workflow-lint",
                files=r"^\.github/(workflows/.*\.ya?ml|dependabot\.ya?ml)$",
            ),
        ]
    if _on(modules, "shell-lint") and facts.get("has_sh"):
        out.append(
            Hook(
                "shellcheck",
                "shellcheck",
                "tools/.bin/shellcheck",
                "system",
                "shell-lint",
                types=("shell",),
            )
        )
    if _on(modules, "nix-lint") and facts.get("has_nix"):
        out += [
            Hook(
                "nixfmt",
                "nixfmt",
                "tools/.bin/nixfmt",
                "system",
                "nix-lint",
                types=("nix",),
            ),
            Hook(
                "statix",
                "statix",
                "tools/.bin/statix check",
                "system",
                "nix-lint",
                files=r"\.nix$",
                pass_filenames=False,
            ),
            Hook(
                "deadnix",
                "deadnix",
                "tools/.bin/deadnix --fail",
                "system",
                "nix-lint",
                types=("nix",),
            ),
        ]
    if _on(modules, "commits"):
        out.append(
            Hook(
                "committed",
                "committed",
                "tools/.bin/committed --commit-file",
                "system",
                "commits",
                stages=("commit-msg",),
            )
        )
    return out


def hooks(
    data: series.SeriesData,
    modules: Mapping[str, Any],
    cfg: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> list[Hook]:
    """The managed hooks, OCA's first (in OCA's order), then odoo-nix's."""
    return _oca(data, modules, cfg, facts) + _own(modules, facts)


# --- YAML ------------------------------------------------------------------------------

# A plain YAML scalar this writer leaves unquoted: no indicator first, no ": " or " #",
# no surrounding space, and not a word YAML would read as another type.
_PLAIN = re.compile(r"[A-Za-z0-9_./\\^($][^\n]*")
_NOT_STRINGS = re.compile(
    r"(?i)(true|false|yes|no|on|off|null|~|[-+]?(\d[\d_]*)?\.?\d+([eE][-+]?\d+)?)"
)


def scalar(value: str) -> str:
    """``value`` as a YAML scalar: plain when that reads back as the same string, else
    double-quoted (JSON's escapes are YAML's)."""
    if (
        _PLAIN.fullmatch(value)
        and ": " not in value
        and " #" not in value
        and not value.endswith((" ", ":"))
        and not _NOT_STRINGS.fullmatch(value)
    ):
        return value
    return json.dumps(value)


def flow(values: tuple[str, ...]) -> str:
    """A list of strings as a YAML flow sequence of double-quoted strings."""
    return "[" + ", ".join(json.dumps(v) for v in values) + "]"


def hook_yaml(hook: Hook, indent: str = "      ") -> str:
    """One hook as an item of ``hooks:``."""
    lines = []
    values = {f.name: getattr(hook, f.name) for f in fields(hook)}
    for key in _KEYS:
        value = values[key]
        if value is None or value == ():
            continue
        if isinstance(value, bool):
            text = "true" if value else "false"
        elif isinstance(value, tuple):
            text = flow(value)
        else:
            text = scalar(value)
        lead = "- " if not lines else "  "
        lines.append(f"{indent}{lead}{key}: {text}")
    return "\n".join(lines) + "\n"


def hooks_yaml(items: list[Hook]) -> str:
    """The hooks as the items of ``hooks:``, without the final newline."""
    return "".join(hook_yaml(h) for h in items).rstrip("\n")


def exclude_block(
    data: series.SeriesData,
    facts: Mapping[str, Any],
    local: str,
    indent: str = "  ",
) -> str:
    """The top-level ``exclude`` block scalar's lines (rule 6), ``(?x)`` first and the
    locks last; ``local`` is the region's leader (``# odoo-nix:local``)."""
    markers = data.raw["exclude"]["excluded_addons_markers"]
    lines = [data.raw["exclude"]["flags"], markers["begin"]]
    for name in facts.get("not_installable", []):
        addon = next(a for a in facts.get("addons", []) if a["name"] == name)
        lines.append(f"^{addon['path']}/|")
    lines.append(markers["end"])
    locks = None
    groups: list[tuple[str, list[str]]] = []
    for alt in data.exclude:
        if alt["pattern"] == series.LOCKS:
            locks = alt
            continue
        if groups and groups[-1][0] == alt["comment"]:
            groups[-1][1].append(alt["pattern"])
        else:
            groups.append((alt["comment"], [alt["pattern"]]))
    for comment, patterns in groups:
        lines.append(f"# {comment}")
        lines.append("".join(f"{p}|" for p in patterns))
    lines.append(f"{local}-begin {EXCLUDE_REGION}")
    lines.append(f"{local}-end {EXCLUDE_REGION}")
    if locks is None:
        raise RuntimeError("the series data has no locks alternative (locks-excluded)")
    lines.append(f"# {locks['comment']}")
    lines.append(locks["pattern"])
    return "".join(f"{indent}{line}\n" for line in lines)
