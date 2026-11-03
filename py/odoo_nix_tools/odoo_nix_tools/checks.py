"""What sync refuses, says, and reports about the checkout as a whole (DESIGN.md §3.4).

``preflight`` refuses (exit 2) a configuration the managed files cannot serve: a series
without data, ``releases`` with commit messages that carry no level, the wrong config
file for the shape, an addon repository without its addons-mode files. ``notices`` are
phase B's remarks. ``checks`` are whole-repo problems sync cannot fix (a missing README,
a submodule off its series): drift under ``--check`` and at the end of ``--write``.

The two lock checks are the lock handlers' own problem (``ToolsLock``, ``NodeLock``):
``tools/uv.lock`` and ``package-lock.json`` must hold what their manifests declare, or
uv2nix and importNpmLock would build the old tools. As a lock problem the item carries
the lock command, so ``--write`` reruns it and ``--write --offline`` names it.

``FIRST_OPT_IN`` lists the files a checkout often has of its own before it opts in:
replacing one needs ``--force`` unless it is what odoo-nix's own scaffolding wrote.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from standards_core.common.report import DRIFT, ConfigError
from standards_core.product import FirstOptIn
from standards_core.scaffold import engine
from standards_core.scaffold.engine import Item
from standards_core.scaffold.handlers import NpmLockHandler, UvLockHandler

from odoo_nix_tools import discover, series

if TYPE_CHECKING:
    from standards_core.common.config import Resolved
    from standards_core.scaffold.context import Checkout
    from standards_core.scaffold.engine import Plan
    from standards_core.scaffold.manifest import Entry

SERIES_BRANCH = re.compile(r"\d+\.0")
# odoo-nix's foreign blocks in nix/pyproject.toml (lib/oca_sources.py): the relock
# fills them, and skips a file without them.
ADDONS_BLOCKS = (
    "# >>> odoo-nix: install set",
    "# >>> odoo-nix: module sources",
)
SOURCES_BLOCK = re.compile(
    r"^# >>> odoo-nix: module sources.*?$(?P<body>.*?)^# <<< odoo-nix: module sources",
    re.MULTILINE | re.DOTALL,
)
_SOURCE_KEY = re.compile(r'^\s*"?(?P<name>[A-Za-z0-9_.-]+)"?\s*=', re.MULTILINE)
_PYTHON_ENVS = re.compile(r'"python-envs\.[^"]*"\s*:')
TOOLS_RELOCK = "uv lock --project tools"
NODE_RELOCK = "npm install --package-lock-only --ignore-scripts --no-audit --no-fund"


def _on(modules: Mapping[str, Any], name: str) -> bool:
    return bool(modules.get(name))


def _facts(checkout: Checkout, resolved: Resolved) -> dict[str, Any]:
    return discover.facts(checkout, resolved.cfg, resolved.modules)


def _read(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text()
    except (OSError, UnicodeDecodeError):
        return None


# --- preflight -----------------------------------------------------------------------


def preflight(checkout: Checkout, resolved: Resolved) -> None:
    """Refuse (exit 2) what no managed file can serve (DESIGN.md §3.4). The shape's own
    files come first: an addon repository without its addons-mode files (``develop``
    before the ``feat/dev-env`` merge) hears about ``odoo-init --addons``, the one fix,
    before anything about where its table goes. Nothing is written before this runs, the
    ``[tool.odoo-nix]`` table ``--standards`` creates included."""
    cfg = resolved.cfg
    modules = resolved.modules
    facts = _facts(checkout, resolved)
    shape = facts["shape"]
    series.load(facts["series"])
    if "flake.nix" not in checkout.tracked:
        raise ConfigError(_no_flake(shape))
    if shape == "addons":
        text = _read(checkout.root, discover.ADDONS_CONFIG) or ""
        if discover.ADDONS_CONFIG not in checkout.tracked or not all(
            block in text for block in ADDONS_BLOCKS
        ):
            raise ConfigError(_no_flake(shape))
    expected = discover.ADDONS_CONFIG if shape == "addons" else discover.PROJECT_CONFIG
    if facts["config_file"] != expected:
        raise ConfigError(
            f"[tool.odoo-nix] is in {facts['config_file']}, but this repository is"
            f" {'an addon repository' if shape == 'addons' else 'a project'}: move the"
            f" table to {expected}"
        )
    core_config = discover.checkout_extra(checkout)["core_config"]
    if core_config != expected:
        # Core CR1 (DESIGN.md §10): until hooks.config_file exists, the core reads and
        # --standards writes the root pyproject.toml, which an addon repository has not.
        raise ConfigError(
            f"an addon repository keeps [tool.odoo-nix] in {expected}, and this"
            f" odoo-nix-tools reads it from {core_config} only (its standards-core has"
            " no per-checkout config file yet): nothing was written"
        )
    if shape == "addons":
        lock_dir = facts["flake"]["lock_dir_literal"]
        if lock_dir is not None and lock_dir != "nix":
            raise ConfigError(
                f'flake.nix sets addons.lockDir = "{lock_dir}": odoo-nix\'s standards read'
                ' [tool.odoo-nix] from nix/pyproject.toml; keep addons.lockDir = "nix"'
            )
    commits = cfg.get("commits") or {}
    if _on(modules, "releases") and commits.get("convention") == "odoo":
        raise ConfigError(
            "releases needs conventional commits (the bump level comes from them):"
            ' commits.convention = "odoo" carries none; use "conventional" or turn'
            " releases off"
        )
    names = {a["name"] for a in facts["addons"]}
    for item in cfg.get("untested") or []:
        if isinstance(item, Mapping) and item.get("addon") not in names:
            raise ConfigError(
                f"[[tool.odoo-nix.untested]] names {item.get('addon')!r}, which is no"
                " addon of this repository"
            )
    branching = (cfg.get("releases") or {}).get("branching")
    integration = str(cfg.get("integration-branch") or "")
    if (
        _on(modules, "releases")
        and shape == "addons"
        and branching == "develop+series"
        and SERIES_BRANCH.fullmatch(integration)
    ):
        raise ConfigError(
            f"releases under develop+series needs an integration branch other than the"
            f" series branch it releases to, and it is {integration}: create develop and"
            " make it the default branch (or set integration-branch)"
        )


def _no_flake(shape: str) -> str:
    if shape == "addons":
        return (
            "this repository has no addons-mode flake.nix and nix/pyproject.toml: run"
            " `odoo-init --addons` first (or add --addons to this run)"
        )
    return (
        "this repository has no flake.nix: odoo-nix's standards need the project's"
        " dev shell (run `odoo-init` first)"
    )


# --- notices -------------------------------------------------------------------------


def notices(plan: Plan) -> list[str]:
    """Phase B's remarks (DESIGN.md §3.4). Two of the design's are the core's own now:
    sync leaves a file you had changed unstaged and says so (CR5), and the ``.gitignore``
    block's ``absorb`` takes a comment paragraph it leaves empty (CR4)."""
    out = []
    facts = plan.ctx.discover
    modules = plan.ctx.modules
    if facts["shape"] == "project":
        for module in ("releases", "packaging"):
            if _on(modules, module):
                out.append(
                    f"{module} applies to addon repositories; it does nothing in a project"
                )
    if _on(modules, "python-lint") and facts.get("dev_group_ruff"):
        out.append(
            f"{facts['config_file']}: [dependency-groups].dev lists ruff; hooks and the"
            " editor use tools/.venv/bin/ruff (drop it there)"
        )
    if _on(modules, "ide") and facts.get("vscode", {}).get("settings"):
        text = _read(plan.root, ".vscode/settings.json") or ""
        if _PYTHON_ENVS.search(text):
            out.append(
                ".vscode/settings.json sets python-envs.*, which overrides the"
                " interpreter the dev shell links: remove it"
            )
    if facts.get("shape_notice"):
        out.append(facts["shape_notice"])
    return out


# --- checks --------------------------------------------------------------------------


def _item(path: str, problem: str, module: str) -> Item:
    return Item(path, "check", None, None, problem, DRIFT, module=module)


def series_disagreements(facts: Mapping[str, Any]) -> list[str]:
    """Each place that names another series than the checkout's (DESIGN.md §2.3)."""
    sources = facts["series_sources"]
    found = facts["series"]
    out = []
    named = {
        "odoo-series": ".odoo-series",
        "flake": "flake.nix's odooSeries",
        "ocb-lock": "flake.lock's ocb",
        "branch": "the integration branch",
    }
    for key, where in named.items():
        value = sources.get(key)
        if value and value != found:
            out.append(f"series {found}, but {where} names {value}")
    for value, names in (sources.get("manifests") or {}).items():
        if value != found:
            out.append(f"series {found}, but {', '.join(names)} have {value} versions")
    return out


def _source_names(text: str) -> set[str]:
    m = SOURCES_BLOCK.search(text)
    if not m:
        return set()
    return {canonicalize_name(k["name"]) for k in _SOURCE_KEY.finditer(m["body"])}


def checks(plan: Plan) -> list[Item]:
    """Whole-repo problems (DESIGN.md §3.4): drift under ``--check`` and at the end of
    ``--write``."""
    out: list[Item] = []
    ctx = plan.ctx
    facts = ctx.discover
    modules = ctx.modules
    cfg = ctx.cfg
    shape = facts["shape"]
    if _on(modules, "readme") and (cfg.get("readme") or {}).get("required", True):
        for addon in facts["addons"]:
            if addon["installable"] and not addon["readme"]:
                out.append(
                    _item(
                        f"{addon['path']}/README.md",
                        f"addon {addon['name']} has no README.md (or README.rst)",
                        "readme",
                    )
                )
    if _on(modules, "ci") and shape == "project":
        for sub in facts["submodules"]:
            if sub["branch"] != facts["series"]:
                out.append(
                    _item(
                        ".gitmodules",
                        f"submodule {sub['path']} follows"
                        f" {sub['branch'] or 'no branch'}, not branch = {facts['series']}",
                        "ci",
                    )
                )
    if _on(modules, "packaging") and shape == "addons":
        sources = _source_names(_read(plan.root, discover.ADDONS_CONFIG) or "")
        for addon in facts["addons"]:
            if not addon["installable"]:
                continue
            if not addon["whool"]:
                out.append(
                    _item(
                        f"{addon['path']}/pyproject.toml",
                        f"addon {addon['name']} has no whool pyproject.toml: commit the"
                        " one the whool-init hook writes",
                        "packaging",
                    )
                )
            elif canonicalize_name(f"odoo-addon-{addon['name']}") not in sources:
                out.append(
                    _item(
                        discover.ADDONS_CONFIG,
                        f"nix/uv.lock predates {addon['path']}/pyproject.toml: run"
                        " `odoo project relock`",
                        "packaging",
                    )
                )
    if _on(modules, "python-lint"):
        text = _read(plan.root, facts["config_file"]) or ""
        try:
            tool = tomllib.loads(text).get("tool") if text else None
        except tomllib.TOMLDecodeError:
            tool = None
        if isinstance(tool, Mapping) and "ruff" in tool:
            out.append(
                _item(
                    facts["config_file"],
                    "[tool.ruff] is ignored: ruff reads .ruff.toml first; move its"
                    " settings to python-lint's parameters or .ruff.toml's local region",
                    "python-lint",
                )
            )
    where = discover.SERIES_FILE if shape == "addons" else "flake.nix"
    out += [_item(where, p, "dev-shell") for p in series_disagreements(facts)]
    return out


# --- locks ---------------------------------------------------------------------------


def _requirement_key(item: Any) -> tuple[str, str, str, str] | None:
    """(name, specifier, source, marker) of a ``[project].dependencies`` item."""
    if not isinstance(item, str):
        return None
    try:
        req = Requirement(item)
    except InvalidRequirement:
        return None
    source = ""
    if req.url and req.url.startswith("git+"):
        url = req.url.removeprefix("git+")
        head, sep, rev = url.rpartition("@")
        if not sep or "/" in rev:
            head, rev = url, ""
        source = f"git:{head.lower()}@{rev}"
    elif req.url:
        source = req.url
    return (
        canonicalize_name(req.name),
        str(SpecifierSet(str(req.specifier))),
        source,
        str(req.marker or ""),
    )


def _locked_key(item: Any) -> tuple[str, str, str, str] | None:
    """The same of a ``requires-dist`` table of ``uv.lock``'s root package."""
    if not isinstance(item, Mapping) or "name" not in item:
        return None
    try:
        spec = str(SpecifierSet(str(item.get("specifier", ""))))
    except InvalidSpecifier:
        spec = str(item.get("specifier", ""))
    source = ""
    if "git" in item:
        url, _, query = str(item["git"]).partition("?")
        rev = ""
        for part in query.split("#", 1)[0].split("&"):
            key, _, value = part.partition("=")
            if key in ("rev", "tag", "branch"):
                rev = value
        source = f"git:{url.lower()}@{rev}"
    elif "url" in item:
        source = str(item["url"])
    elif "path" in item or "directory" in item or "editable" in item:
        source = (
            f"path:{item.get('path') or item.get('directory') or item.get('editable')}"
        )
    return (
        canonicalize_name(str(item["name"])),
        spec,
        source,
        str(item.get("marker", "")),
    )


def declared_deps(text: str) -> set[tuple[str, str, str, str]] | None:
    """``tools/pyproject.toml``'s dependencies as comparable keys; ``None`` unreadable."""
    try:
        deps = tomllib.loads(text).get("project", {}).get("dependencies", [])
    except tomllib.TOMLDecodeError:
        return None
    keys = {_requirement_key(d) for d in deps if isinstance(d, str)}
    return {k for k in keys if k is not None}


def locked_deps(text: str) -> set[tuple[str, str, str, str]] | None:
    """The root package's ``requires-dist`` of a ``uv.lock`` (the virtual project), as
    comparable keys; ``None`` when the lock has no root package."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    for package in doc.get("package", []):
        source = package.get("source") if isinstance(package, Mapping) else None
        if isinstance(source, Mapping) and source.get("virtual") == ".":
            dist = (package.get("metadata") or {}).get("requires-dist", [])
            keys = {_locked_key(d) for d in dist}
            return {k for k in keys if k is not None}
    return None


def tools_lock_problem(pyproject: str | None, lock: str, *, subset: bool) -> str:
    """Why ``tools/uv.lock`` does not hold ``tools/pyproject.toml``'s dependencies
    (``""`` when it does). ``subset``: a lock with more tools than declared is fine (a
    throwaway checkout carries one lock for every profile, core CR2)."""
    if pyproject is None:
        return ""
    declared = declared_deps(pyproject)
    locked = locked_deps(lock)
    if declared is None:
        return ""
    if locked is None:
        return f"tools/uv.lock has no root package: run `{TOOLS_RELOCK}`"
    if declared == locked or (subset and declared <= locked):
        return ""
    missing = sorted(k[0] for k in declared - locked)
    extra = sorted(k[0] for k in locked - declared)
    detail = "; ".join(
        part
        for part in (
            f"not as locked: {', '.join(missing)}" if missing else "",
            f"locked but not declared: {', '.join(extra)}"
            if extra and not subset
            else "",
        )
        if part
    )
    return (
        f"tools/uv.lock predates tools/pyproject.toml ({detail}): run `{TOOLS_RELOCK}`"
    )


def node_lock_problem(package: str | None, lock: str) -> str:
    """Why ``package-lock.json`` does not hold ``package.json``'s devDependencies."""
    if package is None:
        return ""
    try:
        declared = json.loads(package).get("devDependencies") or {}
    except (ValueError, AttributeError):
        return ""
    try:
        locked = (json.loads(lock).get("packages") or {}).get("", {}).get(
            "devDependencies"
        ) or {}
    except (ValueError, AttributeError):
        locked = None
    if locked == declared:
        return ""
    return f"package-lock.json predates package.json: run `{NODE_RELOCK}`"


class ToolsLock(UvLockHandler):
    """``tools/uv.lock``: the core's uv lock, also stale when its root package's
    ``requires-dist`` is not ``tools/pyproject.toml``'s dependencies; deleted with the
    tools project once every tool module is off."""

    name = "tools-uv-lock"

    def lock_problem(self, plan: Plan, entry: Entry, path: str) -> str:
        problem = super().lock_problem(plan, entry, path)
        if problem:
            return problem
        lock = engine.read(plan.product, plan.root, path) or ""
        pyproject = engine.read(plan.product, plan.root, "tools/pyproject.toml")
        return tools_lock_problem(
            pyproject, lock, subset=bool(plan.ctx.options.get("throwaway"))
        )

    def retract(self, plan: Plan, entry: Entry, path: str, current: str) -> Item | None:
        return _retract_lock(plan, entry, path, current)


class NodeLock(NpmLockHandler):
    """``package-lock.json``: the core's npm lock, also stale when its root
    devDependencies are not ``package.json``'s; deleted once js-xml is off."""

    name = "node-npm-lock"

    def lock_problem(self, plan: Plan, entry: Entry, path: str) -> str:
        lock = engine.read(plan.product, plan.root, path) or ""
        package = engine.read(plan.product, plan.root, "package.json")
        return node_lock_problem(package, lock)

    def retract(self, plan: Plan, entry: Entry, path: str, current: str) -> Item | None:
        return _retract_lock(plan, entry, path, current)


def _retract_lock(plan: Plan, entry: Entry, path: str, current: str) -> Item | None:
    """A lock sync made goes with its manifest once its modules are off (and were on:
    a lock the checkout had before it opted in is left)."""
    if not engine.was_on(plan, entry):
        return None
    return Item(
        path,
        entry.strategy,
        current,
        None,
        "file should not exist (its module is off)",
        DRIFT,
        phase=entry.phase,
    )


# --- first opt-in --------------------------------------------------------------------

# What odoo-init wrote before the checkout opted in: replaced without --force.
LEGACY_ENVRC = (
    # templates/project/.envrc
    (
        "# Nix reads the submodules while it evaluates the flake (inputs.self.submodules),\n"
        "# before the dev shell can check them out: on a fresh clone, check them out first,\n"
        '# with odoo-nix-sources at the revision flake.lock pins (odoo-nix docs, "A fresh'
        ' clone").\n'
        "if git submodule status --recursive 2> /dev/null | grep '^-' > /dev/null; then\n"
        '  nix run github:Avunu/odoo-nix#bootstrap -- "$PWD" || true\n'
        "fi\n"
        "use flake . --no-pure-eval\n"
    ),
    # templates/addons/.envrc, millrun and the addon repositories
    "use flake . --no-pure-eval\n",
    # odoo-ruckus
    (
        "# The Python env is built from these, so rebuild the shell when they change.\n"
        "watch_file pyproject.toml uv.lock modules.txt\n"
        "use flake . --no-pure-eval\n"
    ),
)

FIRST_OPT_IN = (
    FirstOptIn(
        path=".pre-commit-config.yaml",
        hint=(
            "Move your own hooks into the `# odoo-nix:local-begin hooks` region of the"
            " managed file, and your own exclude alternatives into its `exclude` region,"
        ),
    ),
    FirstOptIn(
        path=".envrc",
        hint="Put your own lines in the `# odoo-nix:local-begin envrc` region,",
        legacy=lambda current, checkout: list(LEGACY_ENVRC),
    ),
    FirstOptIn(
        path=".ruff.toml",
        hint=(
            "Move your own rules into python-lint's extra-select, ignore and"
            " per-file-ignores, or the local region,"
        ),
    ),
    FirstOptIn(
        path=".github/dependabot.yml",
        hint="Move your own update entries into the `updates` local region,",
    ),
)
