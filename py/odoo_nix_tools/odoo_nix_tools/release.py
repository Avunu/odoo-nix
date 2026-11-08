"""Version scheme, release tool and branching models (DESIGN.md §2.2).

``series``: each series branch (``18.0``, ``19.0``) is its own integration branch, the
way OCA works: pull requests go to the series they are for, and series are developed in
parallel. Releases are tags, cut by release-please on each series branch: its release PR
raises each changed addon's version and writes its ``CHANGELOG.md``; merging it tags
``<addon>-<series>.x.y.z`` and publishes a GitHub release carrying the addon's zip and
wheel (``odoo-nix release``, ``releaseplease.py``). No branch is moved.

``develop+series``: pull requests go to ``develop``; after a merge the CI App bumps each
changed addon's version (``odoo-nix ci bump``: ``OdooSeries`` over the units
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
        # release-please honours Release-As; only the post-merge bump has no use for it.
        if (cfg.get("releases") or {}).get("branching") == SERIES:
            return []
        if _RELEASE_AS.search(text):
            return [
                (
                    "Release-As has no meaning here: each addon's version moves in"
                    " `ci bump`, from the commits that touch it"
                )
            ]
        return []

    def tag_problem(self, tag: str, cfg: Mapping[str, Any], facts: Facts) -> str | None:
        # No odoo-series flow moves a branch to a tag: under series the tags are
        # release-please's and no branch follows them.
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


# The branching whose releases are release-please's tags (module docstring).
SERIES = "series"
# release-please's tag is `<component><separator><x.y.z>`: with the component
# `<addon>-<series>` and the separator ".", it reads `<addon>-<series>.x.y.z`, the addon's
# full Odoo version, and release-please still parses it back (its tag pattern takes the
# longest component that leaves an x.y.z).
TAG_SEPARATOR = "."


def component(addon: str, series: str) -> str:
    """release-please's component of ``addon`` on ``series``: ``web_x-18.0``."""
    return f"{addon}-{series}"


def tag(addon: str, version: str) -> str:
    """The release tag of ``addon`` at its full manifest ``version``:
    ``web_x-18.0.1.2.3``."""
    return f"{addon}-{version}"


def rp_branch(series: str) -> str:
    """The head branch of release-please's release PR on ``series``."""
    return f"release-please--branches--{series}"


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
        SERIES: Branching(
            name=SERIES,
            # The core moves nothing: release-please tags, and no branch follows a tag.
            flow="none",
            # discover.derive sets the series; a checkout without one has no default.
            integration=lambda cfg: str(cfg.get("series") or ""),
            release_branch=lambda cfg, facts: "",
            # The tags ruleset (`<addon>-<series>.x.y.z` tags: fleet.repo_policy_values).
            tags=True,
        ),
        "trunk": Branching(
            name="trunk",
            flow="none",
            integration=lambda cfg: "main",
            release_branch=lambda cfg, facts: "",
        ),
    }
)
