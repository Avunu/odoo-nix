"""Read-only probes of the working directory: what it is, and what an existing
tree says about its series, name and database.

An existing tree is one in odoo-nix's layout: OCB at odoo/ (a checkout, or a
submodule .gitmodules registers there), OCA repositories under modules/, the
project's own modules under custom/. An odoo-nix project is one whose
flake.nix uses odoo-nix's flake module.
"""

from __future__ import annotations

import ast
import os
import re
from collections import Counter
from pathlib import Path

from odoo_nix_cli.init.presets import Preset
from odoo_nix_cli.init.proc import git, probe
from odoo_nix_cli.init.state import CORE, CUSTOM, MODULES

MANIFEST_GLOBS = (
    f"{CUSTOM}/*/__manifest__.py",
    f"{MODULES}/*/__manifest__.py",
    f"{MODULES}/*/*/__manifest__.py",
)

#: pyproject.toml's managed install set (lib/oca_sources.py's DEP_BEGIN).
PYPROJECT_SENTINEL = "# >>> odoo-nix: install set"


def dir_is_empty(path: str | os.PathLike[str]) -> bool:
    """PATH does not exist, or is a directory with nothing in it."""
    p = Path(path)
    if not p.exists():
        return True
    return p.is_dir() and not any(p.iterdir())


def _code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def flake_text() -> str:
    try:
        return Path("flake.nix").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def is_odoo_nix_project() -> bool:
    """flake.nix uses odoo-nix's flake module, outside a comment."""
    return any(
        "odoo-nix.flakeModules" in line or "odoo-nix.lib.mkFlake" in line
        for line in _code_lines(flake_text())
    )


def has_foreign_flake() -> bool:
    return Path("flake.nix").is_file() and not is_odoo_nix_project()


def has_foreign_pyproject() -> bool:
    """A pyproject.toml without the blocks lib/oca_sources.py manages."""
    p = Path("pyproject.toml")
    return p.is_file() and PYPROJECT_SENTINEL not in p.read_text(
        encoding="utf-8", errors="replace"
    )


def submodules() -> dict[str, dict[str, str]]:
    """{path: {"name", "url", "branch"}} from .gitmodules."""
    if not Path(".gitmodules").is_file():
        return {}
    listing = (
        probe(
            git(
                "config",
                "-f",
                ".gitmodules",
                "--get-regexp",
                r"^submodule\..*\.(path|url|branch)$",
            )
        )
        or ""
    )
    by_name: dict[str, dict[str, str]] = {}
    for line in listing.splitlines():
        key, _, value = line.partition(" ")
        name, _, attr = key.removeprefix("submodule.").rpartition(".")
        by_name.setdefault(name, {"name": name})[attr] = value
    return {entry["path"]: entry for entry in by_name.values() if "path" in entry}


def has_ocb() -> bool:
    return Path(CORE, "odoo-bin").exists() or CORE in submodules()


def manifests() -> list[Path]:
    found: set[Path] = set()
    for pattern in MANIFEST_GLOBS:
        found.update(Path(".").glob(pattern))
    return sorted(found)


def looks_like_odoo_tree() -> bool:
    """OCB at odoo/, or an Odoo module under custom/ or modules/."""
    return has_ocb() or bool(manifests())


def looks_like_empty_tree() -> bool:
    """custom/ or modules/ with no module in either, and no OCB."""
    return (
        Path(CUSTOM).is_dir() or Path(MODULES).is_dir()
    ) and not looks_like_odoo_tree()


def repo_state() -> str:
    """none (not in a git repository), own (this directory is its top level) or
    nested (inside another repository)."""
    top = probe(git("rev-parse", "--show-toplevel"))
    if not top:
        return "none"
    return "own" if os.path.realpath(top) == os.path.realpath(".") else "nested"


def _flake_value(pattern: str) -> str | None:
    for line in _code_lines(flake_text()):
        m = re.match(pattern, line)
        if m:
            return m.group(1)
    return None


def existing_name() -> str | None:
    """The project name an odoo-nix flake.nix sets (odoo-nix.name, or the old
    projectName)."""
    return _flake_value(r'^\s*(?:name|projectName)\s*=\s*"([^"]+)"\s*;')


def existing_db() -> str | None:
    """The default database an odoo-nix flake.nix sets: odoo-nix.dbName, or
    settings.options.db_name, or 1.x's settings.dbName and odooConf.dbName."""
    return _flake_value(
        r'^\s*(?:(?:settings\.|odooConf\.)?dbName|settings\.options\.db_name)\s*=\s*"([^"]+)"\s*;'
    )


def _series_of_manifests() -> str | None:
    """The series most of the module manifests' versions name (18.0.1.0.0 is 18.0)."""
    seen: Counter[str] = Counter()
    for path in manifests():
        try:
            manifest = ast.literal_eval(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        version = manifest.get("version") if isinstance(manifest, dict) else None
        if isinstance(version, str):
            m = re.fullmatch(r"(\d+\.\d+)\.\d+\.\d+\.\d+", version.strip())
            if m:
                seen[m.group(1)] += 1
    return seen.most_common(1)[0][0] if seen else None


def _series_of_release() -> str | None:
    """OCB's own odoo/release.py: version_info = (18, 0, ...)."""
    try:
        text = Path(CORE, "odoo", "release.py").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^version_info\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,", text, re.MULTILINE)
    return f"{m.group(1)}.{m.group(2)}" if m else None


def detect_series() -> tuple[str, str] | None:
    """(series, where it was read) for the tree, or None: flake.nix's
    odooSeries, the branch .gitmodules pairs odoo/ with, OCB's release.py, or
    the module manifests' versions, in that order."""
    found = _flake_value(r'^\s*odooSeries\s*=\s*"([^"]+)"\s*;')
    if found:
        return found, "flake.nix"
    branch = submodules().get(CORE, {}).get("branch")
    if branch:
        return branch, ".gitmodules"
    found = _series_of_release()
    if found:
        return found, f"{CORE}/odoo/release.py"
    found = _series_of_manifests()
    if found:
        return found, "the module manifests"
    return None


def preset_for(series: str, presets: dict[str, Preset]) -> str | None:
    """The preset key whose branch is SERIES (the keys are the branches today)."""
    if series in presets:
        return series
    return next((k for k, p in presets.items() if p.branch == series), None)
