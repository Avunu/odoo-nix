"""Version scheme, release tool and branching models (DESIGN.md §2.2).

``develop+series`` (the default): pull requests go to ``develop``; after a merge the CI App
bumps each changed addon's version (``odoo-nix ci bump``: ``OdooSeries`` over the units
``ManifestTool`` reads) and fast-forwards the series branch ``.odoo-series`` names. A
project has no release branch. ``trunk``: one ``main``, no release flow.

Each addon is a release unit with its own ``<series>.x.y.z`` in its ``__manifest__.py``:
a breaking change (``type!:`` or a ``BREAKING CHANGE`` footer) raises ``x``, ``feat``
raises ``y``, ``fix`` and ``perf`` raise ``z``. Changes to an addon's tests, READMEs,
translations or description page alone never bump it (``EXEMPT``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from standards_core.common.report import ConfigError
from standards_core.product import Branching, ReleaseUnit
from standards_core.scaffold import globs

from odoo_nix_tools import manifests
from odoo_nix_tools.manifests import SERIES_VERSION

if TYPE_CHECKING:
    from standards_core.product import Facts, Level
    from standards_core.scaffold.context import NS

# An addon's own paths whose changes alone never bump it (relative to the addon).
EXEMPT = (
    "tests/**",
    "README.md",
    "README.rst",
    "readme/**",
    "i18n/**",
    "i18n_extra/**",
    "static/description/**",
)
_RELEASE_AS = re.compile(r"^Release-As:", re.IGNORECASE | re.MULTILINE)


def _series(cfg: Mapping[str, Any], facts: Facts) -> str:
    return str(facts.get("series") or cfg.get("series") or "")


class OdooSeries:
    """``odoo-series``: ``<series>.x.y.z`` per addon. ``major`` raises x, ``minor`` y and
    ``patch`` z, each resetting the parts after it: ``18.0.1.2.3`` + minor is
    ``18.0.1.3.0``. The series prefix never moves."""

    name = "odoo-series"

    def valid(self, version: str, cfg: Mapping[str, Any], facts: Facts) -> str | None:
        return manifests.version_problem(version, _series(cfg, facts))

    def bump(
        self, version: str, level: Level, cfg: Mapping[str, Any], facts: Facts
    ) -> str:
        m = SERIES_VERSION.match(version)
        if m is None:
            raise ConfigError(f"version {version} is not <series>.x.y.z")
        x, y, z = int(m["x"]), int(m["y"]), int(m["z"])
        if level == "major":
            x, y, z = x + 1, 0, 0
        elif level == "minor":
            y, z = y + 1, 0
        else:
            z += 1
        return f"{m['series']}.{x}.{y}.{z}"

    def message_problems(
        self, text: str, cfg: Mapping[str, Any], facts: Facts
    ) -> list[str]:
        if _RELEASE_AS.search(text):
            return [
                (
                    "Release-As has no meaning here: each addon's version moves in"
                    " `ci bump`, from the commits that touch it"
                )
            ]
        return []

    def tag_problem(self, tag: str, cfg: Mapping[str, Any], facts: Facts) -> str | None:
        return "odoo-series releases make no tags" if tag else None


class ManifestTool:
    """The release units of an Odoo checkout: one per installable addon, its version in
    its ``__manifest__.py``."""

    name = "odoo-manifest"
    commit_subject = "chore(release): bump {units}"

    def units(self, root: Path, ctx: NS) -> list[ReleaseUnit]:
        addons = ctx["discover"].get("addons", [])
        return [
            ReleaseUnit(a["name"], f"{a['path']}/", f"{a['path']}/__manifest__.py")
            for a in sorted(addons, key=lambda a: a["name"])
            if a.get("installable")
        ]

    def read_version(self, text: str, unit: ReleaseUnit) -> str | None:
        try:
            version = manifests.literal(text, unit.version_file).get("version")
        except ValueError:
            return None
        return version if isinstance(version, str) else None

    def write_version(self, text: str, unit: ReleaseUnit, version: str) -> str:
        return manifests.replace_version(text, version, unit.version_file)

    def exempt(self, unit: ReleaseUnit, path: str) -> bool:
        return globs.match_any(EXEMPT, path.removeprefix(unit.path))


BRANCHING = MappingProxyType(
    {
        "develop+series": Branching(
            name="develop+series",
            flow="post-merge-bump",
            integration=lambda cfg: "develop",
            release_branch=lambda cfg, facts: (
                str(facts.get("series") or "") if facts.get("shape") == "addons" else ""
            ),
            # Narrowed to the checkout's own series by hooks.repo_policy_values (O8).
            release_pattern="refs/heads/*.0",
            release_label="*.0",
            tags=False,
        ),
        "trunk": Branching(
            name="trunk",
            flow="none",
            integration=lambda cfg: "main",
            release_branch=lambda cfg, facts: "",
        ),
    }
)
