"""``odoo-nix release sync|unreleased|package`` (DESIGN.md §2.2, ``releaseplease.py``):
the steps of the ``series`` release flow that release-please cannot take.

``sync``: write each addon's version from ``.release-please-manifest.json`` into its
``__manifest__.py`` (the release workflow runs it on release-please's PR branch, then
commits and pushes what changed). Prints the manifests it changed.

``unreleased``: each installable addon that has no release on this series yet, as JSON
(``[{"path", "tag"}]``), from the tags the clone has (fetch them first). The release
workflow gives each one a first release at the series head before release-please runs.

``package``: ``<addon>-<version>.zip`` and the addon's whool wheel, in ``--out`` (default
``dist``): the tracked files plus what ``releases.build`` builds (``npm ci`` and ``npm
run build`` in the directory it names for the addon). Name addons by name or path, or
``--all``.

Exit 0, 1 when ``sync --check`` finds a version to write, 2 for the configuration, 3 for
the environment.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from standards_core.commands import Command, help_text
from standards_core.common import repo
from standards_core.common.report import CLEAN, DRIFT, ConfigError

from odoo_nix_tools import releaseplease
from odoo_nix_tools.commands import common

if TYPE_CHECKING:
    from standards_core.common.repoconfig import RepoConfig
    from standards_core.product import Product


def _installable(rc: RepoConfig) -> list[Mapping[str, Any]]:
    return [a for a in rc.facts.get("addons", []) if a.get("installable")]


def _series(rc: RepoConfig) -> str:
    series = str(rc.facts.get("series") or "")
    if not series:
        raise ConfigError("this checkout has no series (.odoo-series)")
    return series


def _require_addons(rc: RepoConfig) -> None:
    if rc.facts.get("shape") != "addons":
        raise ConfigError("odoo-nix release works in an addon repository")


def _sync(rc: RepoConfig, args: argparse.Namespace) -> int:
    root = Path(rc.root)
    if args.check:
        # Compare without writing: sync into a scratch copy of the manifests.
        wanted = json.loads((root / releaseplease.MANIFEST_FILE).read_text())
        stale = []
        for addon in _installable(rc):
            xyz = wanted.get(str(addon["path"]))
            if isinstance(xyz, str) and addon.get("version") != f"{_series(rc)}.{xyz}":
                stale.append(f"{addon['path']}/__manifest__.py")
        for path in stale:
            print(path)
        return DRIFT if stale else CLEAN
    for path in releaseplease.sync(root, _installable(rc), _series(rc)):
        print(path)
    return CLEAN


def _unreleased(rc: RepoConfig, args: argparse.Namespace) -> int:
    tags = repo.git(Path(rc.root), "tag", "--list").split()
    found = releaseplease.unreleased(_installable(rc), _series(rc), tags)
    print(json.dumps([{"path": p, "tag": t} for p, t in found]))
    return CLEAN


def _pick(rc: RepoConfig, names: list[str], every: bool) -> list[Mapping[str, Any]]:
    addons = _installable(rc)
    if every:
        if names:
            raise ConfigError("name addons or pass --all, not both")
        return addons
    if not names:
        raise ConfigError("name the addons to package, or pass --all")
    by_key = {str(a["name"]): a for a in addons} | {str(a["path"]): a for a in addons}
    missing = [n for n in names if n.rstrip("/") not in by_key]
    if missing:
        raise ConfigError(f"no installable addon named {', '.join(missing)}")
    return [by_key[n.rstrip("/")] for n in names]


def _package(rc: RepoConfig, args: argparse.Namespace) -> int:
    root = Path(rc.root)
    builds = dict((rc.cfg.get("releases") or {}).get("build") or {})
    names = {str(a["name"]) for a in _installable(rc)}
    unknown = sorted(set(builds) - names)
    if unknown:
        raise ConfigError(
            f"releases.build names {', '.join(unknown)}, which no installable addon is"
        )
    out = Path(args.out)
    if not out.is_absolute():
        out = Path.cwd() / out
    pyproject_build = ""
    if not args.no_wheel:
        linked = root / common.TOOLS_BIN / "pyproject-build"
        if linked.is_file() and os.access(linked, os.X_OK):
            pyproject_build = str(linked)
    for addon in _pick(rc, args.addons, args.all):
        built = releaseplease.package(
            root,
            addon,
            out,
            build_dir="" if args.no_build else str(builds.get(addon["name"], "")),
            wheel=not args.no_wheel,
            pyproject_build=pyproject_build,
        )
        print(built.zip)
        if built.wheel is not None:
            print(built.wheel)
    return CLEAN


def run(args: argparse.Namespace) -> int:
    product: Product = args.product
    rc = common.load(product)
    _require_addons(rc)
    return {"sync": _sync, "unreleased": _unreleased, "package": _package}[
        args.step
    ](rc, args)


def register(sub: argparse._SubParsersAction, product: Product) -> None:
    p = sub.add_parser(
        "release",
        help="the series release flow's steps: sync, unreleased, package",
        description=help_text(product, "release", __doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    steps = p.add_subparsers(dest="step", required=True, metavar="STEP")
    s = steps.add_parser(
        "sync",
        help="write .release-please-manifest.json's versions into the manifests",
    )
    s.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 listing each manifest whose version differs",
    )
    steps.add_parser(
        "unreleased",
        help="the addons with no release on this series yet, as JSON",
    )
    k = steps.add_parser(
        "package", help="build each addon's zip and wheel into --out"
    )
    k.add_argument("addons", nargs="*", metavar="ADDON", help="addon names or paths")
    k.add_argument("--all", action="store_true", help="every installable addon")
    k.add_argument("--out", default="dist", help="the output directory (dist)")
    k.add_argument(
        "--no-wheel", action="store_true", help="the zip only, no whool wheel"
    )
    k.add_argument(
        "--no-build",
        action="store_true",
        help="skip releases.build's front-end builds (package what is on disk)",
    )
    p.set_defaults(func=run)


RELEASE = Command("release", register)
