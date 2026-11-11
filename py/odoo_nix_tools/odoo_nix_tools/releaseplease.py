"""Releases under the ``series`` branching: release-please, and each addon's zip and wheel
(DESIGN.md §2.2; release.py).

release-please runs on each series branch with one package per installable addon. Its
config (``release-please-config.json``) and manifest (``.release-please-manifest.json``)
are managed files rendered from the addons' manifests (``config``, ``manifest``), so a new
addon joins on the next sync and ``sync --check`` fails whenever a manifest's version and
release-please's disagree.

release-please only knows ``x.y.z``; an addon's version is ``<series>.x.y.z``. So:

- each package's component is ``<addon>-<series>`` and its tag separator ``.``: the tag
  is ``<addon>-<series>.x.y.z``, the addon's full version, unique across series;
- release-please cannot write a Python manifest (its generic updater would read
  ``18.0.1`` as the version), so ``sync`` copies its manifest's ``x.y.z`` into each
  ``__manifest__.py`` on the release PR's branch;
- the ``simple`` strategy writes only ``CHANGELOG.md`` in the addon (it writes
  ``version.txt`` only where one exists).

``seed`` gives an addon with no release yet one for the version it has, at the head of the
series branch, so release-please counts from there instead of proposing every commit since
the addon began (adoption, and each new addon). ``package`` builds the release artifacts:
the addon's tracked files plus whatever its front-end build writes (``releases.build``),
as ``<addon>-<version>.zip`` (the addon directory at the zip's root, the form Odoo's
addons path and apps listing take) and the whool wheel built from the same tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from standards_core.common import repo
from standards_core.common.report import ConfigError, EnvError

from odoo_nix_tools import manifests, release
from odoo_nix_tools.manifests import SERIES_VERSION

CONFIG_FILE = "release-please-config.json"
MANIFEST_FILE = ".release-please-manifest.json"
SCHEMA = "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json"
# An addon's directories whose changes alone never release it (release.EXEMPT's
# directories: release-please's exclude-paths are directory prefixes, so the README's
# own changes fall to their commit type, `docs:`, which releases nothing either).
EXCLUDE_DIRS = ("tests", "readme", "i18n", "i18n_extra", "static/description")
# Never in a package, whatever the build leaves.
NEVER = ("node_modules", "__pycache__", ".ruff_cache", ".pytest_cache")
NEVER_SUFFIXES = (".pyc", ".pyo")
# A fixed timestamp for every zip member (the zip format's earliest), so a package's
# bytes depend on its files only.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
# The release PR's title: it passes the commit rules (scope `release`).
PR_TITLE_PATTERN = "chore(release): release ${branch}"

CHANGELOG_SECTIONS = [
    {"type": "feat", "section": "Features"},
    {"type": "fix", "section": "Bug Fixes"},
    {"type": "perf", "section": "Performance Improvements"},
    {"type": "revert", "section": "Reverts"},
    {"type": "deps", "section": "Dependencies"},
    {"type": "docs", "section": "Documentation", "hidden": True},
    {"type": "style", "section": "Styles", "hidden": True},
    {"type": "chore", "section": "Miscellaneous Chores", "hidden": True},
    {"type": "refactor", "section": "Code Refactoring", "hidden": True},
    {"type": "test", "section": "Tests", "hidden": True},
    {"type": "build", "section": "Build System", "hidden": True},
    {"type": "ci", "section": "Continuous Integration", "hidden": True},
]


def _installable(addons: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        (a for a in addons if a.get("installable")), key=lambda a: str(a["name"])
    )


def short(version: str, series: str) -> str:
    """``x.y.z`` of a ``<series>.x.y.z`` manifest version; ConfigError otherwise."""
    problem = manifests.version_problem(version, series)
    m = SERIES_VERSION.match(version or "")
    if problem or m is None:
        raise ConfigError(problem or f"version {version!r} is not {series}.x.y.z")
    return f"{m['x']}.{m['y']}.{m['z']}"


def config(addons: Iterable[Mapping[str, Any]], series: str) -> dict[str, Any]:
    """``release-please-config.json``: one ``simple`` package per installable addon."""
    packages: dict[str, Any] = {}
    for addon in _installable(addons):
        path = str(addon["path"])
        packages[path] = {
            "component": release.component(str(addon["name"]), series),
            "exclude-paths": [f"{path}/{d}" for d in EXCLUDE_DIRS],
        }
    return {
        "$schema": SCHEMA,
        "release-type": "simple",
        "include-component-in-tag": True,
        "include-v-in-tag": False,
        "tag-separator": release.TAG_SEPARATOR,
        "separate-pull-requests": False,
        # Both patterns, the same: release-please reads a merged release PR's title with the
        # packages' pattern before the group's, and its default one
        # (`chore${scope}: release${component} ${version}`) takes the series in
        # "chore(release): release 18.0" for a version it then cannot parse, so no release
        # is tagged. This one has no version: each addon's comes from the PR's body.
        "pull-request-title-pattern": PR_TITLE_PATTERN,
        "group-pull-request-title-pattern": PR_TITLE_PATTERN,
        "pull-request-header": (
            f"Merging this releases the addons below on {series}: release-please tags"
            f" each `<addon>-{series}.x.y.z` and publishes its GitHub release, which"
            " carries the addon's zip and wheel."
        ),
        "changelog-sections": CHANGELOG_SECTIONS,
        "packages": packages,
    }


def manifest(addons: Iterable[Mapping[str, Any]], series: str) -> dict[str, str]:
    """``.release-please-manifest.json``: each installable addon's ``x.y.z``."""
    return {
        str(a["path"]): short(str(a.get("version") or ""), series)
        for a in _installable(addons)
    }


# --- sync: release-please's versions into the manifests ------------------------------


def sync(root: Path, addons: Iterable[Mapping[str, Any]], series: str) -> list[str]:
    """Write each addon's version from ``.release-please-manifest.json`` into its
    ``__manifest__.py``; the manifests changed, relative to ``root``."""
    path = root / MANIFEST_FILE
    try:
        wanted = json.loads(path.read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"{MANIFEST_FILE} is missing: run odoo-nix sync") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"{MANIFEST_FILE}: {e}") from e
    changed = []
    for addon in _installable(addons):
        addon_path = str(addon["path"])
        xyz = wanted.get(addon_path)
        if not isinstance(xyz, str):
            continue
        version = f"{series}.{xyz}"
        if SERIES_VERSION.match(version) is None:
            raise ConfigError(f"{MANIFEST_FILE}: {addon_path} is {xyz!r}, not x.y.z")
        rel = f"{addon_path}/__manifest__.py"
        text = (root / rel).read_text()
        new = manifests.replace_version(text, version, rel)
        if new != text:
            (root / rel).write_text(new)
            changed.append(rel)
    return changed


# --- seed: a first release for each addon that has none ------------------------------


def unreleased(
    addons: Iterable[Mapping[str, Any]], series: str, tags: Iterable[str]
) -> list[tuple[str, str]]:
    """``(addon path, tag)`` for each installable addon with no release tag on this
    series at all (``tags``: the repository's release tags)."""
    tags = list(tags)
    out = []
    for addon in _installable(addons):
        name = str(addon["name"])
        prefix = f"{release.component(name, series)}{release.TAG_SEPARATOR}"
        if any(t.startswith(prefix) for t in tags):
            continue
        version = str(addon.get("version") or "")
        short(version, series)
        out.append((str(addon["path"]), release.tag(name, version)))
    return out


# --- package: the zip and the wheel --------------------------------------------------


@dataclass(frozen=True)
class Built:
    zip: Path
    wheel: Path | None


def _never(rel: PurePosixPath) -> bool:
    return any(part in NEVER for part in rel.parts) or rel.suffix in NEVER_SUFFIXES


def _run(argv: Sequence[str], cwd: Path, env: Mapping[str, str] | None = None) -> None:
    print(f"$ {' '.join(argv)}  (in {cwd})", flush=True)
    try:
        subprocess.run(argv, cwd=cwd, check=True, env=dict(env) if env else None)
    except FileNotFoundError as e:
        raise EnvError(f"{argv[0]} is not on PATH") from e
    except subprocess.CalledProcessError as e:
        raise EnvError(f"{' '.join(argv)} exited {e.returncode}") from e


def build_frontend(root: Path, addon_path: str, build_dir: str) -> None:
    """``npm ci`` and ``npm run build`` in ``<addon>/<build_dir>``: the front end whose
    output the addon serves but git does not track (``static/dist``)."""
    where = (root / addon_path / build_dir).resolve()
    if not where.is_relative_to((root / addon_path).resolve()):
        raise ConfigError(f"releases.build: {build_dir!r} is outside {addon_path}")
    if not (where / "package.json").is_file():
        raise ConfigError(
            f"releases.build: {addon_path}/{build_dir} has no package.json"
        )
    npm = shutil.which("npm")
    if npm is None:
        raise EnvError("npm is not on PATH: run in the dev shell (`nix develop`)")
    # The lock when there is one; without, an install that leaves none behind (it
    # would land in the package).
    lock = (where / "package-lock.json").is_file()
    install = ["ci"] if lock else ["install", "--no-package-lock"]
    _run([npm, *install, "--no-audit", "--no-fund"], where)
    _run([npm, "run", "build"], where)


def files(root: Path, addon_path: str, *, built: bool = False) -> list[str]:
    """The addon's files that go into its package, relative to ``root``: every tracked
    file and, after a front-end build (``built``), every untracked one under the addon
    (ignored or not: ``static/dist``), minus caches and ``node_modules``."""
    found = repo.git(root, "ls-files", "-z", "--", addon_path).split("\0")
    if built:
        found += repo.git(root, "ls-files", "-z", "--others", "--", addon_path).split(
            "\0"
        )
        found += repo.git(
            root,
            "ls-files",
            "-z",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            addon_path,
        ).split("\0")
    out = set()
    for rel in found:
        if not rel:
            continue
        p = PurePosixPath(rel)
        if _never(p) or not (root / rel).is_file():
            continue
        out.add(rel)
    return sorted(out)


def stage(root: Path, addon_path: str, dest: Path, *, built: bool = False) -> Path:
    """A copy of the addon's package files under ``dest/<addon>``; that directory."""
    name = PurePosixPath(addon_path).name
    out = dest / name
    for rel in files(root, addon_path, built=built):
        inner = PurePosixPath(rel).relative_to(addon_path)
        target = out / inner
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, target)
    if not (out / "__manifest__.py").is_file():
        raise ConfigError(f"{addon_path} has no tracked __manifest__.py")
    return out


def write_zip(staged: Path, path: Path) -> Path:
    """``staged`` (an addon directory) as a zip whose root holds that directory, every
    member in name order with a fixed timestamp."""
    members = sorted(p for p in staged.rglob("*") if p.is_file())
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for member in members:
            arc = PurePosixPath(staged.name, *member.relative_to(staged).parts)
            info = zipfile.ZipInfo(str(arc), date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if os.access(member, os.X_OK) else 0o644) << 16
            zf.writestr(info, member.read_bytes())
    return path


def build_wheel(staged: Path, out: Path, pyproject_build: str) -> Path:
    """The whool wheel of ``staged``, built where git cannot see it, so whool packs the
    whole tree (the built front end included) and adds no ``.postN`` to the version."""
    before = set(out.glob("*.whl"))
    env = {**os.environ, "WHOOL_POST_VERSION_STRATEGY_OVERRIDE": "none"}
    _run(
        [pyproject_build, "--wheel", "--no-isolation", "--outdir", str(out), "."],
        staged,
        env,
    )
    made = sorted(set(out.glob("*.whl")) - before)
    if len(made) != 1:
        raise EnvError(f"{staged.name}: expected one wheel, found {len(made)}")
    return made[0]


def package(
    root: Path,
    addon: Mapping[str, Any],
    out: Path,
    *,
    build_dir: str = "",
    wheel: bool = True,
    pyproject_build: str = "",
) -> Built:
    """``<out>/<addon>-<version>.zip`` and, when the addon has a whool ``pyproject.toml``
    and ``wheel``, its wheel."""
    addon_path = str(addon["path"])
    version = str(addon.get("version") or "")
    if build_dir:
        build_frontend(root, addon_path, build_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="odoo-nix-package-") as tmp:
        staged = stage(root, addon_path, Path(tmp), built=bool(build_dir))
        name = release.tag(str(addon["name"]), version)
        zipped = write_zip(staged, out / f"{name}.zip")
        made = None
        if wheel and addon.get("whool"):
            if not pyproject_build:
                raise EnvError(
                    "no pyproject-build for the wheel: run in the dev shell, which links"
                    " tools/.venv (or pass --no-wheel)"
                )
            made = build_wheel(staged, out, pyproject_build)
    return Built(zipped, made)
