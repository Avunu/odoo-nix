"""``odoo-nix check manifests|icons|submodules`` (DESIGN.md §6.2): the checks the lint
gate runs that no pre-commit hook makes.

``manifests``: only what pylint-odoo cannot see from one manifest: its ``website`` is the
rendered ``addon-manifest.website`` (when that is set), its version is
``<series>.x.y.z``; a series integration branch and ``.odoo-series`` name the series.

``icons``: each installable addon has ``static/description/icon.png``, square, at least
``icons.min-size`` pixels and at most ``icons.max-bytes`` bytes. ``--fix`` adds a missing
icon with ``oca-gen-addon-icon`` from the org profile's ``icons.src-icon`` (exit 2 when
there is none) and stages it; oca-gen-addon-icon never replaces an icon that exists, so a
wrong one stays reported.

``submodules`` (projects): every ``.gitmodules`` entry follows the series branch
(``branch = <series>``), which ``odoo project update`` moves it along.

Exit 0, 1 with one line per problem, 2 for the configuration, 3 for the environment.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from standards_core.commands import Command, help_text
from standards_core.common import config, repo
from standards_core.common.report import ConfigError, EnvError

from odoo_nix_tools import discover, manifests, series
from odoo_nix_tools.commands import common
from odoo_nix_tools.commands.common import Problem

if TYPE_CHECKING:
    from standards_core.common.repoconfig import RepoConfig
    from standards_core.product import Product

SERIES_BRANCH = re.compile(r"\d+\.0")
ICON_TOOL = "oca-gen-addon-icon"


def _installable(facts: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [a for a in facts.get("addons", []) if a.get("installable")]


def manifests_problems(rc: RepoConfig) -> list[Problem]:
    cfg, facts = rc.cfg, rc.facts
    series_name = str(facts.get("series") or "")
    website = series.website(cfg) if rc.modules.get("addon-manifest") else ""
    out = []
    for addon in _installable(facts):
        path = f"{addon['path']}/__manifest__.py"
        if website and addon.get("website") != website:
            have = addon.get("website") or "not set"
            out.append(Problem(path, f"website is {have}, not {website}"))
        problem = manifests.version_problem(addon.get("version"), series_name)
        if problem:
            out.append(Problem(path, problem))
    integration = str(cfg.get("integration-branch") or "")
    if SERIES_BRANCH.fullmatch(integration) and integration != series_name:
        out.append(
            Problem(
                str(facts.get("config_file") or "pyproject.toml"),
                f"the integration branch {integration} is a series branch, and the"
                f" series is {series_name}",
            )
        )
    odoo_series = rc.root / discover.SERIES_FILE
    if odoo_series.is_file():
        named = odoo_series.read_text().strip()
        if named != series_name:
            out.append(
                Problem(
                    discover.SERIES_FILE,
                    f"names {named}, and the series is {series_name}",
                )
            )
    return out


def icon_problem(addon: Mapping[str, Any], cfg: Mapping[str, Any]) -> str | None:
    """Why the addon's icon does not pass, or ``None``."""
    icons = cfg.get("icons") or {}
    min_size = int(icons.get("min-size", 128))
    max_bytes = int(icons.get("max-bytes", 102400))
    icon = addon.get("icon") or {}
    if not icon.get("present"):
        return "no static/description/icon.png"
    width, height = icon.get("width"), icon.get("height")
    if width is None or height is None:
        return "static/description/icon.png is not a PNG image"
    out = []
    if width != height:
        out.append(f"is {width}×{height}, not square")
    if min(width, height) < min_size:
        out.append(f"is smaller than {min_size}×{min_size}")
    if icon.get("bytes", 0) > max_bytes:
        out.append(f"has {icon['bytes']} bytes, more than {max_bytes}")
    return "static/description/icon.png " + " and ".join(out) if out else None


def icons_problems(rc: RepoConfig) -> list[Problem]:
    """Reported against ``<addon>/__manifest__.py``: a ``--format github`` annotation
    needs a file, and the icon may not exist."""
    return [
        Problem(f"{addon['path']}/__manifest__.py", problem)
        for addon in _installable(rc.facts)
        if (problem := icon_problem(addon, rc.cfg))
    ]


def src_icon(product: Product, rc: RepoConfig) -> Path:
    """The org profile's ``icons.src-icon``: exit 2 when the profile is a built-in or
    has no such file."""
    rel = str((rc.cfg.get("icons") or {}).get("src-icon") or "")
    name = str(rc.cfg.get("profile") or "")
    if not rel or config.is_builtin(name):
        raise ConfigError(
            f"icons.src-icon: the profile {name!r} has no icon to copy; add the org"
            " profile's icon (icons.src-icon) or add the icons by hand"
        )
    directory, _rev = config.org_profile_dir(product, name, rc.root)
    path = Path(directory) / rel
    if not path.is_file():
        raise ConfigError(f"icons.src-icon: {rel} is not in the profile {name}")
    return path


def fix_icons(product: Product, rc: RepoConfig, problems: list[Problem]) -> None:
    """``oca-gen-addon-icon`` for the addons whose icon is missing."""
    missing = [
        PurePosixPath(p.path).parent.as_posix()
        for p in problems
        if p.text.startswith("no static/description/icon.png")
    ]
    if not missing:
        return
    source = src_icon(product, rc)
    argv = [common.tool(rc.root, ICON_TOOL), "--no-commit", f"--src-icon={source}"]
    argv += [f"--addon-dir={path}" for path in missing]
    proc = subprocess.run(argv, cwd=rc.root, check=False)
    if proc.returncode != 0:
        raise EnvError(f"{ICON_TOOL} exited {proc.returncode}")
    # Staged, as sync stages what it writes: discovery reads tracked files only.
    added = [f"{path}/{discover.ICON}" for path in missing]
    added = [rel for rel in added if (rc.root / rel).is_file()]
    if added:
        repo.git(rc.root, "add", "--", *added)


def submodules_problems(rc: RepoConfig) -> list[Problem]:
    series_name = str(rc.facts.get("series") or "")
    out = []
    for entry in rc.facts.get("submodules", []):
        branch = entry.get("branch")
        if branch != series_name:
            have = f"branch = {branch}" if branch else "no branch"
            out.append(
                Problem(
                    ".gitmodules",
                    f"submodule {entry['path']} has {have}, not branch = {series_name}",
                )
            )
    return out


def run(args: argparse.Namespace) -> int:
    product: Product = args.product
    rc = common.load(product)
    if args.what == "manifests":
        found = manifests_problems(rc)
    elif args.what == "icons":
        found = icons_problems(rc)
        if args.fix and found:
            fix_icons(product, rc, found)
            rc = common.load(product)
            found = icons_problems(rc)
    else:
        found = submodules_problems(rc)
    return common.report(
        found, args.format, f"{product.identity.cli} check {args.what}"
    )


def register(sub: argparse._SubParsersAction, product: Product) -> None:
    p = sub.add_parser(
        "check",
        help="the lint gate's checks no hook makes: manifests, icons, submodules",
        description=help_text(product, "check", __doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "what",
        choices=("manifests", "icons", "submodules"),
        help=help_text(product, "check what", "the check to run"),
    )
    p.add_argument(
        "--fix",
        action="store_true",
        help=help_text(
            product,
            "check --fix",
            "icons: add each missing icon with oca-gen-addon-icon from the org"
            " profile's icons.src-icon",
        ),
    )
    common.add_format(p)
    p.set_defaults(func=_run_checked)


def _run_checked(args: argparse.Namespace) -> int:
    if args.fix and args.what != "icons":
        raise ConfigError("--fix applies to `check icons` only")
    return run(args)


CHECK = Command("check", register)
