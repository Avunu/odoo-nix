"""The OCA catalogue and curated bundles odoo-nix ships (data/oca-modules.json,
data/oca-bundles.json), and the repository names, URLs and module folders
derived from them. Was lib/oca-lib.sh.

Pure functions over the loaded JSON: nothing here prompts, clones or prints.
A message the caller should show is handed to its ``warn``.

Python dependencies are resolved by uv from each module's whool metadata; the
uv path sources in pyproject.toml are written by lib/oca_sources.py, not here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

Catalog = list[dict[str, Any]]
Bundles = dict[str, dict[str, Any]]


def load_catalog(path: str | os.PathLike[str]) -> Catalog:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_bundles(path: str | os.PathLike[str]) -> Bundles:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def in_series(catalog: Catalog, series: str) -> Catalog:
    """The records of SERIES: a module's version is <series>.<x>.<y>.<z>."""
    prefix = series + "."
    return [m for m in catalog if str(m.get("version", "")).startswith(prefix)]


def repo_url(repo: str) -> str:
    return f"https://github.com/OCA/{repo}.git"


def resolve_repos(catalog: Catalog, series: str, seeds: Iterable[str]) -> list[str]:
    """The OCA repositories SEEDS need within SERIES, sorted: their own and every
    repository their ``depends`` reach. A dependency that is no in-series OCA
    module is Odoo core, which OCB provides."""
    mods = in_series(catalog, series)
    repo_of = {m["module"]: m["repo"] for m in mods}
    deps_of = {m["module"]: m.get("depends") or [] for m in mods}
    queue = [s for s in seeds if s]
    seen: set[str] = set()
    repos: set[str] = set()
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        if cur in repo_of:
            repos.add(repo_of[cur])
        queue.extend(d for d in deps_of.get(cur, []) if d in repo_of)
    return sorted(repos)


def bundle_names(bundles: Bundles) -> list[str]:
    return sorted(bundles)


def expand_bundles(
    bundles: Bundles,
    catalog: Catalog,
    series: str,
    names: Iterable[str],
    warn: Callable[[str], None],
) -> list[str]:
    """The modules of the bundles NAMES that SERIES has, sorted and once each.

    Bundles are series-blind, so a member with no in-series record is named
    and dropped rather than recorded and left to fail at install time. An
    unknown bundle is named, with the known ones.
    """
    wanted: set[str] = set()
    for name in names:
        if not name:
            continue
        if name not in bundles:
            warn(
                f"unknown bundle: {name}   (available: {' '.join(bundle_names(bundles))})"
            )
            continue
        wanted.update(m for m in bundles[name].get("modules", []) if m)
    if not wanted:
        return []
    have = {m["module"] for m in in_series(catalog, series)}
    missing = sorted(wanted - have)
    if missing:
        warn(f"not available for {series}, skipped: {' '.join(missing)}")
    return sorted(wanted & have)


def installable(catalog: Catalog, series: str) -> Catalog:
    """Every installable module of SERIES, applications first, then by repo
    and name: the order the module picker lists them in."""
    rows = [m for m in in_series(catalog, series) if m.get("installable") is True]
    return sorted(
        rows, key=lambda m: (not m.get("application"), m["repo"], m["module"])
    )


def search(rows: Sequence[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """The ROWS a word of whose module name, repository or summary starts with
    QUERY (case-insensitive): prefix matching, so typing a repository's name
    lists its modules."""
    q = query.strip().lower()
    if not q:
        return []

    def words(m: dict[str, Any]) -> list[str]:
        text = f"{m['module']} {m['repo']} {m.get('summary') or ''}".lower()
        out = text.split()
        # module and repository names are matched whole, and from each part.
        for name in (m["module"].lower(), m["repo"].lower()):
            out += name.replace("-", "_").split("_")
        return out

    return [m for m in rows if any(w.startswith(q) for w in words(m))]


def label(m: dict[str, Any]) -> str:
    """A module as the picker shows it: ★ for an application."""
    summary = " ".join(str(m.get("summary") or "").split())[:60]
    star = "★" if m.get("application") else " "
    return f"{star} {m['module']}  ·  {m['repo']}  ·  {summary}"


# ── repositories outside the catalogue ──────────────────────────────────────
# An arbitrary git repository (any host) as a submodule: everything is derived
# from the URL itself.


def url_shaped(arg: str) -> bool:
    """ARG looks like a git URL or owner/repo rather than a module name: module
    names are Python identifiers and never contain '/'."""
    return "://" in arg or arg.startswith("git@") or arg.endswith(".git") or "/" in arg


def resolve_git_url(arg: str) -> str:
    """A full git URL from ARG: a URL with a scheme or scp-style git@ passes
    through (any host); exactly one slash and no scheme is GitHub's
    owner/repo. Anything else url-shaped is refused rather than guessed at
    (ValueError)."""
    if "://" in arg or arg.startswith("git@"):
        return arg
    if arg.count("/") == 1 and not arg.endswith("/"):
        return f"https://github.com/{arg.removesuffix('.git')}.git"
    raise ValueError(f"not a full git URL and not 'owner/repo' shorthand: {arg}")


def repo_slug(url: str) -> str:
    """A folder name for URL: its last path segment, without .git."""
    return url.removesuffix(".git").rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]


def scan_modules(path: str | os.PathLike[str]) -> list[str]:
    """The Odoo modules a cloned repository holds, sorted: the repository itself
    (a manifest at its root) or the folders one level down with one."""
    root = Path(path)
    found: set[str] = set()
    if (root / "__manifest__.py").exists():
        found.add(root.name)
    found.update(p.parent.name for p in root.glob("*/__manifest__.py"))
    return sorted(found)
