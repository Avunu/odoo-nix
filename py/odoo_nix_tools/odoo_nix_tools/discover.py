"""What a checkout is, read from its tracked files (DESIGN.md §2.3).

A checkout is a *project* (OCB and OCA as submodules, its own addons under ``custom/``,
``[tool.odoo-nix]`` in the root ``pyproject.toml``) or an *addons* repository (addons
mode: addons at the root, OCB a flake input, ``[tool.odoo-nix]`` in
``nix/pyproject.toml``). Everything here reads ``git ls-files`` and tracked file contents
only, in sorted order and never the clock (core DESIGN.md §3.4): ``--check`` recomputes
the facts, so a newly tracked file can be drift.
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from standards_core.common import repo
from standards_core.common.report import ConfigError, EnvError
from standards_core.scaffold import engine
from standards_core.scaffold.context import Checkout, default_load_checkout

from odoo_nix_tools import manifests, series
from odoo_nix_tools.pngsize import png_size

PROJECT_CONFIG = "pyproject.toml"
ADDONS_CONFIG = "nix/pyproject.toml"
DEFAULT_CUSTOM = "custom"
SERIES_FILE = ".odoo-series"
TABLE = "odoo-nix"

# The dev shell's opt-in line (core DESIGN.md §2.2): a line that opens [tool.odoo-nix],
# a subtable of it or an array of tables under it.
_OPT_IN = re.compile(r"[ \t\n\v\f\r]*\[{1,2}tool\.odoo-nix[].].*", re.DOTALL)
_SERIES = re.compile(r"\d+\.0")
_SERIES_VERSION = re.compile(r"(\d+\.0)\.\d+\.\d+\.\d+")
_ADDONS_ENABLE = re.compile(
    r"(?<![\w.'-])addons\s*(?:\.\s*enable\s*=\s*true\b|=\s*\{[^{}]*?\benable\s*=\s*true\b)"
)
_CUSTOM_DIR = re.compile(r'\bcustomDir\s*=\s*"([^"$\\]*)"')
_ODOO_SERIES = re.compile(r'\bodooSeries\s*=\s*"(\d+\.0)"')
_LOCK_DIR = re.compile(r'\blockDir\s*=\s*"([^"$\\]*)"')
_SELF_SUBMODULES = re.compile(r"\bself\s*\.\s*submodules\s*=\s*true\b")
_EXTERNAL_SOURCES = re.compile(r"\bexternalSources\s*=\s*\[\s*([^\]\s])")
_KINDS = {"sh": ".sh", "nix": ".nix", "js": ".js", "xml": ".xml", "py": ".py"}


# --- reading -------------------------------------------------------------------------


def _read(root: Path, rel: str) -> str:
    try:
        return (root / rel).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _opted_in(text: str) -> bool:
    return any(_OPT_IN.fullmatch(line) for line in text.split("\n"))


def _flake_text(root: Path, tracked: list[str]) -> str:
    """``flake.nix`` without its comments, or ``""`` when it is not tracked."""
    if "flake.nix" not in tracked:
        return ""
    return engine.strip_nix_comments(_read(root, "flake.nix"))


def _gitlinks(root: Path) -> dict[str, str]:
    """Submodule commits (``git ls-files -s`` mode 160000), by path."""
    out = {}
    for line in repo.git(root, "ls-files", "-s", "-z").split("\0"):
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[0] == "160000":
            out[path] = parts[1]
    return dict(sorted(out.items()))


def _table(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    tool = doc.get("tool")
    table = tool.get(TABLE) if isinstance(tool, Mapping) else None
    return table if isinstance(table, Mapping) else {}


# --- shape ---------------------------------------------------------------------------


def shape_signals(
    tracked: list[str], flake: str, gitlinks: Mapping[str, str]
) -> dict[str, list[str]]:
    """The tracked evidence for each shape, in words."""
    addons = []
    if _ADDONS_ENABLE.search(flake):
        addons.append("flake.nix enables addons mode")
    if any(m[1] == "." for m in _CUSTOM_DIR.finditer(flake)):
        addons.append('flake.nix sets layout.customDir = "."')
    root_manifests = sorted(p for p in tracked if _root_manifest(p))
    if root_manifests:
        addons.append(f"{root_manifests[0]} is at the root")
    project = []
    if "odoo" in gitlinks:
        project.append("odoo is a submodule")
    if "modules.txt" in tracked:
        project.append("modules.txt is tracked")
    return {"addons": addons, "project": project}


def _root_manifest(path: str) -> bool:
    parts = path.split("/")
    return len(parts) == 2 and parts[1] == "__manifest__.py"


def shape(
    table: Mapping[str, Any], signals: Mapping[str, list[str]]
) -> tuple[str, str | None]:
    """``(shape, notice)``: the explicit shape, else the addons signals, else the
    project signals; none is exit 2."""
    explicit = table.get("shape")
    if explicit in ("project", "addons"):
        return str(explicit), None
    if signals["addons"]:
        notice = None
        if signals["project"]:
            notice = (
                "both addons-mode and project signals; using addons (set shape to"
                f" choose): {'; '.join(signals['addons'] + signals['project'])}"
            )
        return "addons", notice
    if signals["project"]:
        return "project", None
    raise ConfigError(
        f"cannot tell this repository's shape: set [tool.{TABLE}] shape"
        ' ("project" or "addons")'
    )


# --- the config file (CR1) -----------------------------------------------------------


def _opted_in_files(root: Path) -> list[str]:
    """Which of ``pyproject.toml`` and ``nix/pyproject.toml`` open ``[tool.odoo-nix]``."""
    return [
        rel
        for rel in (PROJECT_CONFIG, ADDONS_CONFIG)
        if (root / rel).is_file() and _opted_in(_read(root, rel))
    ]


def config_file(root: Path) -> str:
    """The file holding ``[tool.odoo-nix]``, relative to ``root`` (DESIGN.md §2.3, CR1):
    whichever of ``pyproject.toml`` and ``nix/pyproject.toml`` opens the table; neither
    is the one of the checkout's shape (where ``--standards`` writes).

    The core's ``hooks.config_file``: it is also asked about every directory between the
    current one and the work tree's root, and outside git, while the checkout root is
    found, so it never raises. Outside git (no tracked files) and where both files open
    the table it answers the default ``pyproject.toml``; ``load_checkout`` refuses the
    second case at a checkout's root."""
    root = Path(root)
    opted = _opted_in_files(root)
    if len(opted) == 1:
        return opted[0]
    if opted:
        return PROJECT_CONFIG
    try:
        tracked = repo.ls_files(root)
        gitlinks = _gitlinks(root)
    except EnvError:
        return PROJECT_CONFIG
    signals = shape_signals(tracked, _flake_text(root, tracked), gitlinks)
    return ADDONS_CONFIG if signals["addons"] else PROJECT_CONFIG


def load_checkout(root: Path) -> Checkout:
    """The core's checkout plus ``extra``: the comment-stripped ``flake.nix``, the
    gitlinks and the config file's path. A checkout whose ``pyproject.toml`` and
    ``nix/pyproject.toml`` both open the table is exit 2."""
    from odoo_nix_tools.product import PRODUCT

    checkout = default_load_checkout(PRODUCT, root)
    if len(_opted_in_files(checkout.root)) > 1:
        raise ConfigError(
            f"both {PROJECT_CONFIG} and {ADDONS_CONFIG} open [tool.{TABLE}]: keep the one"
            " of this repository's shape"
        )
    checkout.extra = MappingProxyType(_extra(checkout))
    return checkout


def _extra(checkout: Checkout) -> dict[str, Any]:
    return {
        "flake": _flake_text(checkout.root, checkout.tracked),
        "gitlinks": MappingProxyType(_gitlinks(checkout.root)),
        "config_path": config_file(checkout.root),
    }


def checkout_extra(checkout: Checkout) -> Mapping[str, Any]:
    """``checkout.extra``, computed when the checkout came from elsewhere (a core
    ``Checkout`` built without ``load_checkout``)."""
    if "flake" in checkout.extra:
        return checkout.extra
    return _extra(checkout)


# --- series --------------------------------------------------------------------------


def _manifest_series(addons: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for addon in addons:
        if not addon["installable"]:
            continue
        m = _SERIES_VERSION.fullmatch(str(addon.get("version") or ""))
        if m:
            out.setdefault(m[1], []).append(addon["name"])
    return dict(sorted(out.items()))


def _ocb_lock(root: Path, tracked: list[str]) -> str | None:
    """The branch ``flake.lock``'s ``ocb`` input was locked from, when it is a series."""
    if "flake.lock" not in tracked:
        return None
    try:
        lock = json.loads(_read(root, "flake.lock"))
        ref = lock["nodes"][lock["root"]]["inputs"]["ocb"]
        original = lock["nodes"][ref]["original"]
    except (ValueError, KeyError, TypeError):
        return None
    branch = original.get("ref") if isinstance(original, dict) else None
    return branch if isinstance(branch, str) and _SERIES.fullmatch(branch) else None


def series_sources(
    checkout: Checkout,
    flake: str,
    addons: list[dict[str, Any]],
    integration_branch: str | None,
) -> dict[str, Any]:
    """Every place a series can be read from, for discovery and the agreement check."""
    tracked = checkout.tracked
    pinned = None
    if SERIES_FILE in tracked:
        pinned = _read(checkout.root, SERIES_FILE).strip()
        if not _SERIES.fullmatch(pinned):
            raise ConfigError(f"{SERIES_FILE} holds {pinned!r}, not a series like 18.0")
    literal = _ODOO_SERIES.search(flake)
    branch = integration_branch if integration_branch else None
    return {
        "odoo-series": pinned,
        "flake": literal[1] if literal else None,
        "manifests": _manifest_series(addons),
        "branch": branch if branch and _SERIES.fullmatch(branch) else None,
        "ocb-lock": _ocb_lock(checkout.root, tracked),
    }


def series_of(table: Mapping[str, Any], sources: Mapping[str, Any]) -> str:
    """The series: the explicit one, ``.odoo-series``, ``flake.nix``'s literal, the
    addons' versions (which must agree), a ``<n>.0`` integration branch; exit 2 when
    none says, or the series has no data."""
    found = table.get("series") or sources["odoo-series"] or sources["flake"]
    if not found and sources["manifests"]:
        per = sources["manifests"]
        if len(per) > 1:
            listed = "; ".join(f"{s}: {', '.join(names)}" for s, names in per.items())
            raise ConfigError(
                f"the addons' versions name more than one series ({listed}): add"
                f" {SERIES_FILE}"
            )
        found = next(iter(per))
    found = found or sources["branch"]
    if not found:
        raise ConfigError(f"cannot tell the Odoo series: add {SERIES_FILE}")
    series.load(str(found))  # exit 2 when odoo-nix-tools has no data for it
    return str(found)


# --- addons --------------------------------------------------------------------------


def addons_root(shape_name: str, flake: str) -> str:
    if shape_name == "addons":
        return "."
    m = _CUSTOM_DIR.search(flake)
    return (m[1].strip("/") or ".") if m else DEFAULT_CUSTOM


def _under(path: str, prefix: str) -> str | None:
    """``path`` relative to the directory ``prefix``, or ``None`` outside it."""
    if prefix in ("", "."):
        return path
    return path[len(prefix) + 1 :] if path.startswith(prefix + "/") else None


def _top_dir(path: str) -> str:
    return path.split("/", 1)[0]


def addon_facts(
    checkout: Checkout, root_dir: str, not_source: tuple[str, ...]
) -> list[dict[str, Any]]:
    """One record per tracked ``<root_dir>/<name>/__manifest__.py``, sorted by name."""
    tracked = checkout.tracked
    by_addon: dict[str, list[str]] = {}
    for path in tracked:
        rel = _under(path, root_dir)
        if rel is None or "/" not in rel:
            continue
        name, inner = rel.split("/", 1)
        if root_dir in ("", ".") and name in not_source:
            continue
        by_addon.setdefault(name, []).append(inner)
    out = []
    for name in sorted(by_addon):
        inner = by_addon[name]
        if "__manifest__.py" not in inner:
            continue
        path = name if root_dir in ("", ".") else f"{root_dir}/{name}"
        out.append(_addon(checkout.root, name, path, inner))
    return out


def _addon(root: Path, name: str, path: str, inner: list[str]) -> dict[str, Any]:
    rel = f"{path}/__manifest__.py"
    try:
        manifest = manifests.literal(_read(root, rel), rel)
    except ValueError as e:
        raise ConfigError(f"cannot read {rel}: {e}") from e
    files = set(inner)
    author = manifest.get("author", "")
    if isinstance(author, list | tuple):
        author = ", ".join(str(a) for a in author)
    pyproject = (
        _read(root, f"{path}/pyproject.toml") if "pyproject.toml" in files else ""
    )
    try:
        backend = (
            tomllib.loads(pyproject).get("build-system", {}).get("build-backend")
            if pyproject
            else None
        )
    except tomllib.TOMLDecodeError:
        backend = None
    readme = next((r for r in ("README.md", "README.rst") if r in files), None)
    return {
        "name": name,
        "path": path,
        "installable": bool(manifest.get("installable", True)),
        "license": manifest.get("license"),
        "author": str(author or ""),
        "summary": " ".join(str(manifest.get("summary") or "").split()),
        "website": manifest.get("website"),
        "version": manifest.get("version"),
        "depends": list(manifest.get("depends", [])),
        "has_py": any(
            f.endswith(".py") and f not in ("__init__.py", "__manifest__.py")
            for f in files
        ),
        "has_js": any(f.endswith(".js") for f in files),
        "has_xml": any(f.endswith(".xml") for f in files),
        "has_tests": "tests/__init__.py" in files,
        "readme": readme,
        "icon": _icon(root, path, files),
        "packaged": "pyproject.toml" in files or "setup.py" in files,
        "whool": backend == "whool.buildapi",
        "package_json": any(
            f == "package.json" or f.endswith("/package.json")
            for f in files
            if "node_modules" not in PurePosixPath(f).parts
        ),
    }


ICON = "static/description/icon.png"


def _icon(root: Path, path: str, files: set[str]) -> dict[str, Any]:
    if ICON not in files:
        return {"present": False, "width": None, "height": None, "bytes": None}
    try:
        data = (root / path / ICON).read_bytes()
    except OSError:
        data = b""
    try:
        width, height = png_size(data)
    except ValueError:
        width = height = None
    return {"present": True, "width": width, "height": height, "bytes": len(data)}


# --- submodules ----------------------------------------------------------------------


def submodules(checkout: Checkout, gitlinks: Mapping[str, str]) -> list[dict[str, Any]]:
    """The tracked ``.gitmodules`` entries, sorted by path."""
    if ".gitmodules" not in checkout.tracked:
        return []
    try:
        listing = repo.git(
            checkout.root, "config", "--file", ".gitmodules", "--null", "--list"
        )
    except EnvError as e:
        raise ConfigError(f".gitmodules is unreadable: {e}") from e
    entries: dict[str, dict[str, str]] = {}
    for item in listing.split("\0"):
        key, _, value = item.partition("\n")
        if not key.startswith("submodule."):
            continue
        name, _, attr = key.removeprefix("submodule.").rpartition(".")
        entries.setdefault(name, {})[attr] = value
    out = []
    for entry in entries.values():
        if "path" not in entry:
            continue
        out.append(
            {
                "path": entry["path"],
                "url": entry.get("url", ""),
                "branch": entry.get("branch"),
                "shallow": entry.get("shallow", "false").lower() == "true",
                "gitlink": entry["path"] in gitlinks,
            }
        )
    return sorted(out, key=lambda e: e["path"])


# --- the facts -----------------------------------------------------------------------


def _not_source() -> tuple[str, ...]:
    from odoo_nix_tools.product import PRODUCT

    return PRODUCT.paths.not_source


def _dev_group_ruff(doc: Mapping[str, Any]) -> bool:
    groups = doc.get("dependency-groups")
    dev = groups.get("dev", []) if isinstance(groups, Mapping) else []
    for item in dev if isinstance(dev, list) else []:
        if not isinstance(item, str):
            continue
        try:
            if canonicalize_name(Requirement(item).name) == "ruff":
                return True
        except InvalidRequirement:
            continue
    return False


def _flake_facts(tracked: list[str], flake: str, raw: str) -> dict[str, Any]:
    lock_dir = _LOCK_DIR.search(flake)
    return {
        "present": "flake.nix" in tracked,
        "addons_mode": bool(_ADDONS_ENABLE.search(flake)),
        "self_submodules": bool(_SELF_SUBMODULES.search(flake)),
        "lock_dir_literal": lock_dir[1] if lock_dir else None,
        "external_sources": bool(_EXTERNAL_SOURCES.search(flake)),
        "inputs": engine.flake_input_specs(raw) if raw else {},
    }


def _resolve(
    checkout: Checkout, cfg: Mapping[str, Any]
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """``(table, partial facts)``: shape, series and addons, which ``derive`` needs too."""
    extra = checkout_extra(checkout)
    doc = checkout.config
    table = {**_table(doc), **{k: cfg[k] for k in ("shape", "series") if k in cfg}}
    flake = extra["flake"]
    gitlinks = extra["gitlinks"]
    signals = shape_signals(checkout.tracked, flake, gitlinks)
    shape_name, notice = shape(table, signals)
    if notice is None and "shape" not in _table(doc) and all(signals.values()):
        # cfg["shape"] is derive's copy of the discovered shape, not an explicit one:
        # the notice is the checkout's table's to silence.
        notice = shape(_table(doc), signals)[1]
    root_dir = addons_root(shape_name, flake)
    addons = addon_facts(checkout, root_dir, _not_source())
    branch = cfg.get("integration-branch") or _table(doc).get("integration-branch")
    sources = series_sources(checkout, flake, addons, branch)
    return doc, {
        "shape": shape_name,
        "shape_signals": signals,
        "shape_notice": notice,
        "series": series_of(table, sources),
        "series_sources": sources,
        "config_file": extra["config_path"],
        "lock_dir": "nix" if shape_name == "addons" else ".",
        "addons_root": root_dir,
        "addons": addons,
    }


def facts(
    checkout: Checkout, cfg: Mapping[str, Any], modules: Mapping[str, bool]
) -> dict[str, Any]:
    """odoo-nix's discovery facts (DESIGN.md §2.3 "Fact keys")."""
    doc, out = _resolve(checkout, cfg)
    extra = checkout_extra(checkout)
    tracked = checkout.tracked
    not_source = set(_not_source())
    source = [p for p in tracked if _top_dir(p) not in not_source]
    addons = out["addons"]
    out.update(
        {
            "installable": [a["name"] for a in addons if a["installable"]],
            "not_installable": [a["name"] for a in addons if not a["installable"]],
            "submodules": submodules(checkout, extra["gitlinks"]),
            "flake": _flake_facts(
                tracked,
                extra["flake"],
                _read(checkout.root, "flake.nix") if "flake.nix" in tracked else "",
            ),
            **{
                f"has_{kind}": any(p.endswith(suffix) for p in source)
                for kind, suffix in _KINDS.items()
            },
            "root_package_json": "package.json" in tracked,
            "addon_package_json": sorted(
                str(PurePosixPath(p).parent)
                for p in tracked
                if p.endswith("/package.json")
                and "node_modules" not in PurePosixPath(p).parts
                and _top_dir(p) not in not_source
            ),
            "dev_group_ruff": _dev_group_ruff(doc),
            "vscode": {
                "settings": ".vscode/settings.json" in tracked,
                "extensions": ".vscode/extensions.json" in tracked,
            },
        }
    )
    return out


# --- configuration -------------------------------------------------------------------


def derive(cfg: dict[str, Any], checkout: Checkout | None) -> None:
    """Defaults that depend on the checkout (core DESIGN.md §4.4 step 8), in place."""
    if checkout is not None:
        doc, found = _resolve(checkout, cfg)
        cfg.setdefault("shape", found["shape"])
        cfg.setdefault("series", found["series"])
        if found["shape"] == "project" and "integration-branch" not in _table(doc):
            # A project has no develop+series flow: its integration branch is main
            # unless its table (or --standards, from origin/HEAD) names another.
            cfg["integration-branch"] = "main"
    dependabot = cfg.get("dependabot")
    if isinstance(dependabot, dict) and not dependabot.get("target-branches"):
        dependabot["target-branches"] = [cfg["integration-branch"]]
    manifest = cfg.get("addon-manifest")
    license_ = (cfg.get("org") or {}).get("license")
    if isinstance(manifest, dict) and not manifest.get("licenses-allowed") and license_:
        manifest["licenses-allowed"] = [license_]


def new_target_table(
    root: Path, checkout: Checkout, args: argparse.Namespace, profile: str
) -> dict[str, Any]:
    """``{"repo": "<owner>/<name>"}`` when the clone has no ``origin`` and exactly one
    other remote (a client project's ``upstream``), so the URL placeholders have a repository;
    else ``{}``."""
    try:
        remotes = [r for r in repo.git(root, "remote").split() if r]
    except EnvError:
        return {}
    if "origin" in remotes or len(remotes) != 1:
        return {}
    try:
        parsed = repo.parse_remote(
            repo.git(root, "remote", "get-url", remotes[0]).strip()
        )
    except EnvError:
        return {}
    return {"repo": parsed[1]} if parsed else {}
