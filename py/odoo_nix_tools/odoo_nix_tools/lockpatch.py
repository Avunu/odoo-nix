"""What a plan job's patch may change, checked before a job that holds the CI App's key
pushes it (``odoo-nix verify-patch``; odoo-deps.yml's relock-push and project-update).

The plan jobs run the repository's code (its flake, ``nix run .#relock``, ``odoo project
update`` and the submodules' new code) with no write token, and hand over a patch. The
job that pushes it checks out the base itself, stages the patch in its index (``git apply
--cached``), and runs this against that index before it mints the App's token. Nothing in
the patch is trusted:

- **Entries.** Only the paths the plan's command writes: the lock directory's
  ``pyproject.toml`` and ``uv.lock`` (``nix/`` in a repository of addons, the root in a
  project), each a regular ``100644`` file, added or modified; and for ``project-update``
  a submodule's gitlink moved to another commit (``160000`` to ``160000``) at a path the
  base's ``.gitmodules`` registers. No other path (``.gitmodules``, ``flake.lock`` and
  ``.github/`` included), no deletion, rename, copy, mode change, symlink, ``..``,
  absolute path, ``.git`` component or control character, and not an empty patch.
- **pyproject.toml** differs from the base's only inside odoo-nix's managed blocks (the
  ``# >>> odoo-nix: … >>>`` sentinels lib/oca_sources.py and odoo-nix-build-deps
  rewrite), each present exactly as often as in the base, and each line in them is one
  the writer writes: in ``install set`` a quoted requirement with no ``@``, backslash or
  quote of its own (so no line closes the array or opens a table); in ``module sources``
  a relative path source inside the repository; in ``sdist build deps`` a name and a
  list of names, granting nothing but setuptools or what the base's block grants. Then
  both documents are parsed: with ``project.dependencies``, ``tool.uv.sources`` and
  ``tool.uv.extra-build-dependencies`` taken out they are equal, and those three hold
  only requirements without a URL, path sources inside the repository, and build
  dependency lists (or the base's own values).
- **Gitlinks** (``project-update --tips``): each moved submodule's new commit is the tip
  of the branch the base's ``.gitmodules`` pairs it with, at the URL it names
  (``git ls-remote``), which is all ``odoo project update`` moves it to; not a fork's
  pull-request commit or an older one. A submodule with no branch never moves.
- **uv.lock** sources are PyPI's registry (https://pypi.org/simple), a relative path inside
  the repository (a local or flake-input addon, OCB, the virtual root), or a source the
  base's lock already has. Every sdist and wheel URL is one the base's lock has for the
  same package, with the same hash, or is on https://files.pythonhosted.org and named for
  the package and version that lock it (PEP 503 names, PEP 440 versions). A new path
  source is accepted because what it builds is the checkout's (flake.lock, the gitlinks),
  not the plan's: an honest relock adds one for each new addon.

Each problem is printed as a GitHub error annotation. Exit 0 when there is none, else 1.
"""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
import tomllib
import urllib.parse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

PYPI = "https://pypi.org/simple"
PYPI_FILES = "files.pythonhosted.org"

REGULAR = "100644"
GITLINK = "160000"

# The managed blocks of a uv project's pyproject.toml: lib/oca_sources.py (install set,
# module sources) and odoo-nix-build-deps (python-devops-nix's python/uv_build_deps.py).
INSTALL_SET = (
    "# >>> odoo-nix: install set (managed from modules.txt) >>>",
    "# <<< odoo-nix: install set <<<",
)
MODULE_SOURCES = (
    "# >>> odoo-nix: module sources (managed) >>>",
    "# <<< odoo-nix: module sources <<<",
)
BUILD_DEPS = (
    "# >>> odoo-nix: sdist build deps (managed) >>>",
    "# <<< odoo-nix: sdist build deps (managed) <<<",
)
BLOCKS = (INSTALL_SET, MODULE_SOURCES, BUILD_DEPS)

# `name = { path = "<dir>" }` or `"name" = { path = "<dir>", editable = true }`, as
# lib/oca_sources.py writes a module source.
_SOURCE_LINE = re.compile(
    r'^[ \t]*(?:"[A-Za-z0-9][A-Za-z0-9._-]*"|[A-Za-z0-9][A-Za-z0-9._-]*)'
    r' = \{ path = "(?P<path>[^"\\]+)"(?:, editable = true)? \}[ \t]*$'
)
# `"name" = ["dep", ...]`, as uv_build_deps.render writes a build-deps entry.
_BUILD_DEP_LINE = re.compile(
    r'^[ \t]*"[A-Za-z0-9][A-Za-z0-9._-]*" = \[(?P<deps>[^\]]*)\][ \t]*$'
)
# `"name[extra]<spec>; marker",`, as lib/oca_sources.py writes an install root: one quoted
# string, no `@` (a direct reference), no backslash (a TOML escape), no quote of its own.
_INSTALL_LINE = re.compile(
    r'^[ \t]*"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9._,-]+\])?[^"\\@\x00-\x1f]*",?[ \t]*$'
)
_SDIST_EXT = (".tar.gz", ".zip", ".tar.bz2", ".tgz", ".tar.xz", ".tar")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Kind:
    """What one plan writes: the lock directory ("" for the root), and whether it moves
    submodules."""

    lock_dir: str
    gitlinks: bool

    def path(self, name: str) -> str:
        return f"{self.lock_dir}/{name}" if self.lock_dir else name


KINDS = {
    # odoo-deps.yml relock-plan: `nix run .#relock` in a repository of addons.
    "relock": Kind("nix", gitlinks=False),
    # odoo-deps.yml project-update-plan: `odoo project update --no-sync` in a project.
    "project-update": Kind("", gitlinks=True),
}


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True
    ).stdout


def _show(root: Path, spec: str) -> str | None:
    """``git show SPEC`` as text, or None when it names nothing."""
    done = subprocess.run(
        ["git", "-C", str(root), "cat-file", "blob", spec],
        check=False,
        capture_output=True,
    )
    return done.stdout.decode("utf-8") if done.returncode == 0 else None


def parse_raw(raw: bytes) -> list[tuple[str, str, str, str]]:
    """``git diff --raw -z --no-renames`` as ``(old mode, new mode, status, path)``."""
    out = []
    fields = raw.split(b"\0")
    i = 0
    while i + 1 < len(fields) and fields[i]:
        meta = fields[i].decode().lstrip(":").split()
        out.append(
            (meta[0], meta[1], meta[4], fields[i + 1].decode("utf-8", "replace"))
        )
        i += 2
    return out


def path_problem(path: str) -> str | None:
    """Why ``path`` is no path a patch may name, or None."""
    if not path or _CONTROL.search(path):
        return "a control character or an empty path"
    if path.startswith("/") or "\\" in path:
        return "an absolute path or a backslash"
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return "an empty, `.` or `..` component"
    if any(p.lower() == ".git" for p in parts):
        return "a .git component"
    if parts[0] == ".github":
        return "under .github/ (a workflow moves only through odoo-nix repo rollout)"
    return None


@dataclass(frozen=True)
class Submodule:
    """One ``.gitmodules`` entry: where it is, what it fetches, and the branch it follows."""

    path: str
    url: str
    branch: str


def submodules(gitmodules: str | None) -> dict[str, Submodule]:
    """The entries ``.gitmodules`` (its text) registers, by path."""
    if not gitmodules:
        return {}
    done = subprocess.run(
        ["git", "config", "--file", "-", "--null", "--list"],
        input=gitmodules.encode(),
        check=False,
        capture_output=True,
    )
    entries: dict[str, dict[str, str]] = {}
    for item in done.stdout.decode("utf-8", "replace").split("\0"):
        key, _, value = item.partition("\n")
        if not key.startswith("submodule."):
            continue
        name, _, attr = key.removeprefix("submodule.").rpartition(".")
        entries.setdefault(name, {})[attr] = value
    out = {}
    for entry in entries.values():
        path = entry.get("path", "").strip().strip("/")
        if path:
            out[path] = Submodule(path, entry.get("url", ""), entry.get("branch", ""))
    return out


def submodule_paths(gitmodules: str | None) -> set[str]:
    """The paths ``.gitmodules`` (its text) registers."""
    return set(submodules(gitmodules))


def entry_problems(
    entries: Sequence[tuple[str, str, str, str]], kind: Kind, submodules: set[str]
) -> list[str]:
    """Each entry the plan may not change, and an empty patch."""
    if not entries:
        return ["the patch changes nothing"]
    allowed = {kind.path("pyproject.toml"), kind.path("uv.lock")}
    out = []
    for old, new, status, path in entries:
        if why := path_problem(path):
            out.append(f"{path!r}: {why}")
            continue
        if path in allowed:
            if (
                status not in ("A", "M")
                or new != REGULAR
                or old not in (REGULAR, "000000")
            ):
                out.append(
                    f"{path}: {status} {old} -> {new}; only an added or modified regular"
                    " file (100644) is allowed"
                )
            elif status == "A" and path.endswith("pyproject.toml"):
                out.append(f"{path}: added; the base has none to compare it with")
        elif kind.gitlinks and path in submodules:
            if (status, old, new) != ("M", GITLINK, GITLINK):
                out.append(
                    f"{path}: {status} {old} -> {new}; a submodule may only move to"
                    " another commit"
                )
        else:
            out.append(f"{path}: not a path this job pushes")
    return out


def _escapes(lock_dir: str, value: str) -> bool:
    """Whether a path source ``value`` (relative to ``lock_dir``) leaves the repository."""
    if not value or "://" in value or value.startswith(("/", "~")) or "\\" in value:
        return True
    joined = posixpath.normpath(posixpath.join(lock_dir or ".", value))
    parts = PurePosixPath(joined).parts
    return joined == ".." or joined.startswith("../") or ".git" in parts


def _blocks(text: str) -> tuple[str, dict[tuple[str, str], list[str]]] | str:
    """``text`` with each managed block's lines taken out, and those lines by block;
    or why the sentinels are not in order."""
    lines = text.splitlines(keepends=True)
    outside: list[str] = []
    inside: dict[tuple[str, str], list[str]] = {}
    current: tuple[str, str] | None = None
    for line in lines:
        bare = line.strip()
        begins = [b for b in BLOCKS if bare == b[0]]
        ends = [b for b in BLOCKS if bare == b[1]]
        if current is None:
            if ends:
                return f"{bare!r} with no opening sentinel"
            if begins:
                if begins[0] in inside:
                    return f"{bare!r} twice"
                current = begins[0]
                inside[current] = []
            outside.append(line)
            continue
        if begins or (ends and ends[0] != current):
            return f"{bare!r} inside the block {current[0]!r}"
        if ends:
            current = None
            outside.append(line)
            continue
        if any(s in line for b in BLOCKS for s in b):
            return f"a sentinel inside the block {current[0]!r}"
        inside[current].append(line)
    if current is not None:
        return f"{current[0]!r} is never closed"
    return "".join(outside), inside


def _deps(lines: Iterable[str]) -> set[str] | None:
    """The build dependencies a build-deps block grants, or None for a line it would not
    write."""
    out: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        m = _BUILD_DEP_LINE.match(line.rstrip("\n"))
        if not m:
            return None
        for dep in m.group("deps").split(","):
            dep = dep.strip()
            if not re.fullmatch(r'"[A-Za-z0-9][A-Za-z0-9._-]*"', dep):
                return None
            out.add(dep.strip('"'))
    return out


def pyproject_problems(path: str, base: str, new: str, lock_dir: str) -> list[str]:
    """Why ``new`` is not ``base`` with only its managed blocks rewritten."""
    b, n = _blocks(base), _blocks(new)
    if isinstance(b, str):
        return [f"{path}: the base's managed blocks are malformed ({b})"]
    if isinstance(n, str):
        return [f"{path}: {n}"]
    out = []
    if b[0] != n[0]:
        out.append(f"{path}: changes text outside odoo-nix's managed blocks")
    if set(b[1]) != set(n[1]):
        out.append(f"{path}: adds or removes a managed block")
    for line in n[1].get(MODULE_SOURCES, []):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _SOURCE_LINE.match(line.rstrip("\n"))
        if not m:
            out.append(f"{path}: module sources: {line.strip()!r} is not a path source")
        elif _escapes(lock_dir, m.group("path")):
            out.append(
                f"{path}: module sources: {m.group('path')!r} is outside the repository"
            )
    for line in n[1].get(INSTALL_SET, []):
        bare = line.strip()
        if not bare or bare.startswith("#"):
            continue
        if "@" in bare or "://" in bare:
            out.append(f"{path}: install set: {bare!r} names a direct URL")
        elif not _INSTALL_LINE.match(line.rstrip("\n")):
            out.append(
                f"{path}: install set: {bare!r} is not one quoted requirement per line"
            )
    if BUILD_DEPS in n[1]:
        granted = _deps(n[1][BUILD_DEPS])
        had = _deps(b[1].get(BUILD_DEPS, [])) or set()
        if granted is None:
            out.append(
                f"{path}: sdist build deps: a line odoo-nix-build-deps does not write"
            )
        elif extra := sorted(granted - had - {"setuptools"}):
            out.append(f"{path}: sdist build deps: grants {', '.join(extra)}")
    return out + _parsed_problems(path, base, new, lock_dir)


# The tables the managed blocks write into: (path, what an entry may be).
_MANAGED_KEYS = (
    ("project", "dependencies"),
    ("tool", "uv", "sources"),
    ("tool", "uv", "extra-build-dependencies"),
)


def _without(doc: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """``doc``'s value at ``keys`` taken out of it (None when there is none)."""
    *parents, last = keys
    table: Any = doc
    for key in parents:
        table = table.get(key) if isinstance(table, dict) else None
    return table.pop(last, None) if isinstance(table, dict) else None


def _parsed_problems(path: str, base: str, new: str, lock_dir: str) -> list[str]:
    """Why ``new``, parsed, is more than ``base`` with its managed tables rewritten."""
    try:
        b, n = tomllib.loads(base), tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:
        return [f"{path}: not TOML: {e}"]
    deps_b, sources_b, build_b = (_without(b, k) for k in _MANAGED_KEYS)
    deps_n, sources_n, build_n = (_without(n, k) for k in _MANAGED_KEYS)
    out = []
    if b != n:
        out.append(
            f"{path}: parsed, differs from the base outside project.dependencies,"
            " tool.uv.sources and tool.uv.extra-build-dependencies"
        )
    old_deps = deps_b if isinstance(deps_b, list) else []
    if deps_n is None:
        deps_n = []
    if not isinstance(deps_n, list):
        out.append(f"{path}: project.dependencies is not a list")
    else:
        for dep in deps_n:
            if dep in old_deps:
                continue
            if not isinstance(dep, str):
                out.append(f"{path}: project.dependencies: {dep!r} is not a string")
                continue
            try:
                req = Requirement(dep)
            except InvalidRequirement:
                out.append(f"{path}: project.dependencies: {dep!r} is no requirement")
                continue
            if req.url:
                out.append(f"{path}: project.dependencies: {dep!r} names a direct URL")
    old_sources = sources_b if isinstance(sources_b, dict) else {}
    if sources_n is None:
        sources_n = {}
    if not isinstance(sources_n, dict):
        out.append(f"{path}: tool.uv.sources is not a table")
        sources_n = {}
    for name, value in sources_n.items():
        if old_sources.get(name) == value:
            continue
        if (
            not isinstance(value, dict)
            or not set(value) <= {"path", "editable"}
            or not isinstance(value.get("path"), str)
            or not isinstance(value.get("editable", True), bool)
        ):
            out.append(f"{path}: tool.uv.sources.{name}: not a path source")
        elif _escapes(lock_dir, value["path"]):
            out.append(
                f"{path}: tool.uv.sources.{name}: {value['path']!r} is outside the"
                " repository"
            )
    old_build = build_b if isinstance(build_b, dict) else {}
    granted_before = {
        d for v in old_build.values() if isinstance(v, list) for d in v
    } | {"setuptools"}
    if build_n is None:
        build_n = {}
    if not isinstance(build_n, dict):
        out.append(f"{path}: tool.uv.extra-build-dependencies is not a table")
        build_n = {}
    for name, value in build_n.items():
        if old_build.get(name) == value:
            continue
        if not isinstance(value, list) or not all(isinstance(d, str) for d in value):
            out.append(
                f"{path}: tool.uv.extra-build-dependencies.{name}: not a list of names"
            )
        elif extra := sorted(set(value) - granted_before):
            out.append(
                f"{path}: tool.uv.extra-build-dependencies.{name}: grants"
                f" {', '.join(extra)}"
            )
    return out


def _uv(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    doc = tomllib.loads(text)
    return doc if isinstance(doc, dict) else {}


def _packages(doc: dict[str, Any]) -> list[dict[str, Any]]:
    pkgs = doc.get("package") or []
    return [p for p in pkgs if isinstance(p, dict)] if isinstance(pkgs, list) else []


def _dists(pkg: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        d for d in [pkg.get("sdist"), *(pkg.get("wheels") or [])] if isinstance(d, dict)
    ]


def norm(name: str) -> str:
    """A distribution name normalised as PEP 503 and wheel file names compare it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _same_version(a: str, b: str) -> bool:
    try:
        return Version(a) == Version(b)
    except InvalidVersion:
        return a == b


def _source_keys(source: Any) -> list[str]:
    if not isinstance(source, dict):
        return []
    return sorted(f"{k}={v}" for k, v in source.items())


def pypi_file_problem(name: str, version: str, url: str) -> str | None:
    """Why ``url`` is not a files.pythonhosted.org file of ``name`` ``version``, or None."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != PYPI_FILES or parts.port:
        return f"{name} {version} downloads {url}, which is not on {PYPI_FILES}"
    filename = urllib.parse.unquote(PurePosixPath(parts.path).name)
    if filename.endswith(".whl"):
        fields = filename[: -len(".whl")].split("-")
        dist, ver = (fields[0], fields[1]) if len(fields) >= 5 else ("", "")
    else:
        stem = next(
            (filename[: -len(e)] for e in _SDIST_EXT if filename.endswith(e)), ""
        )
        dist, _, ver = stem.rpartition("-")
    if not dist or norm(dist) != norm(name) or not _same_version(ver, version):
        return f"{name} {version} downloads {filename!r}, which is not a file of that package and version"
    return None


def uv_problems(path: str, base: str | None, new: str, lock_dir: str) -> list[str]:
    """Why ``new`` locks something an honest relock of ``base`` would not."""
    try:
        new_doc, base_doc = _uv(new), _uv(base)
    except tomllib.TOMLDecodeError as e:
        return [f"{path}: not TOML: {e}"]
    trusted_sources: set[str] = set()
    # Each name's files as the base locks them: URL to hash.
    base_files: dict[str, dict[str, str]] = {}
    for pkg in _packages(base_doc):
        trusted_sources.update(_source_keys(pkg.get("source")))
        files = base_files.setdefault(norm(str(pkg.get("name", ""))), {})
        for dist in _dists(pkg):
            if "url" in dist:
                files[str(dist["url"])] = str(dist.get("hash", ""))
    out = []
    for pkg in _packages(new_doc):
        name, version = str(pkg.get("name", "")), str(pkg.get("version", ""))
        source = pkg.get("source")
        if not isinstance(source, dict) or not source:
            out.append(f"{path}: {name} has no source")
            continue
        for kind, value in source.items():
            if f"{kind}={value}" in trusted_sources:
                continue
            if kind == "registry" and value == PYPI:
                continue
            if (
                kind in ("editable", "virtual", "directory", "path")
                and isinstance(value, str)
                and not _escapes(lock_dir, value)
            ):
                continue
            out.append(
                f"{path}: {name} comes from {kind} {value!r}, which is not allowed"
            )
        had = base_files.get(norm(name), {})
        for dist in _dists(pkg):
            url = dist.get("url")
            if url is None:
                if "path" in dist and _escapes(lock_dir, str(dist["path"])):
                    out.append(f"{path}: {name} {version} builds from {dist['path']!r}")
                continue
            url = str(url)
            if url in had:
                if str(dist.get("hash", "")) != had[url]:
                    out.append(
                        f"{path}: {name} {version}: {url} has another hash than the base locks"
                    )
                continue
            if problem := pypi_file_problem(name, version, url):
                out.append(f"{path}: {problem}")
    return out


def remote_url(url: str, superproject: str) -> str | None:
    """The https URL ``git ls-remote`` reads a ``.gitmodules`` URL at: a relative one
    resolved against ``superproject`` (as git does), GitHub's ssh forms as https. None for
    any other scheme, so nothing but https is asked."""
    if url.startswith(("./", "../")):
        if not superproject:
            return None
        parts = urllib.parse.urlsplit(superproject.rstrip("/"))
        joined = posixpath.normpath(posixpath.join(parts.path or "/", url))
        url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, joined, "", ""))
    elif m := re.fullmatch(r"(?:ssh://)?git@github\.com[:/](.+)", url):
        url = f"https://github.com/{m.group(1)}"
    parts = urllib.parse.urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.query
        or parts.fragment
        or _CONTROL.search(url)
    ):
        return None
    return url


def ls_remote(url: str, ref: str) -> str | None:
    """The commit ``ref`` names at ``url`` (``git ls-remote``), or None when it names
    none or the remote cannot be read. Credentials come from the environment (the
    caller's GIT_CONFIG_* header); no prompt."""
    try:
        done = subprocess.run(
            ["git", "ls-remote", "--", url, ref],
            check=False,
            capture_output=True,
            timeout=120,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired:
        return None
    if done.returncode != 0:
        return None
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        sha, _, name = line.partition("\t")
        if name == ref and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
            return sha
    return None


def _valid_branch(branch: str) -> bool:
    if not branch or branch == "." or branch.startswith("-"):
        return False
    done = subprocess.run(
        ["git", "check-ref-format", f"refs/heads/{branch}"],
        check=False,
        capture_output=True,
    )
    return done.returncode == 0


def tip_problems(
    root: Path,
    base: str,
    entries: Sequence[tuple[str, str, str, str]],
    superproject: str,
    read_tip: Callable[[str, str], str | None] = ls_remote,
) -> list[str]:
    """Each moved gitlink whose new commit is not the tip of the branch the base's
    .gitmodules pairs it with, at the URL it names: `odoo project update` moves a
    submodule there and nowhere else (python-devops-nix ``sources pull``)."""
    subs = submodules(_show(root, f"{base}:.gitmodules"))
    out = []
    for _, new, _, path in entries:
        if new != GITLINK or path not in subs:
            continue
        sub = subs[path]
        sha = _git(root, "rev-parse", "--verify", "-q", f":0:{path}").decode().strip()
        if not _valid_branch(sub.branch):
            out.append(
                f"{path}: .gitmodules pairs it with no branch ({sub.branch!r}), so"
                " `odoo project update` would not move it"
            )
            continue
        url = remote_url(sub.url, superproject)
        if url is None:
            out.append(f"{path}: .gitmodules URL {sub.url!r} is not one this job reads")
            continue
        ref = f"refs/heads/{sub.branch}"
        tip = read_tip(url, ref)
        if tip is None:
            out.append(f"{path}: could not read {ref} at {url}")
        elif tip != sha:
            out.append(
                f"{path}: moves to {sha}, and the tip of {sub.branch} at {url} is {tip}"
            )
    return out


def verify(
    root: Path,
    base: str,
    kind: Kind,
    *,
    tips: bool = False,
    superproject: str = "",
    read_tip: Callable[[str, str], str | None] = ls_remote,
) -> list[str]:
    """Every problem of the patch staged in ``root``'s index, against ``base``; with
    ``tips``, each moved gitlink is also checked against its branch's tip."""
    raw = _git(root, "diff", "--cached", "--no-renames", "--raw", "-z", base)
    entries = parse_raw(raw)
    submodules = (
        submodule_paths(_show(root, f"{base}:.gitmodules")) if kind.gitlinks else set()
    )
    out = entry_problems(entries, kind, submodules)
    if out:
        return out
    for _, _, _, path in entries:
        if path == kind.path("pyproject.toml"):
            before = _show(root, f"{base}:{path}") or ""
            after = _show(root, f":0:{path}") or ""
            out += pyproject_problems(path, before, after, kind.lock_dir)
        elif path == kind.path("uv.lock"):
            out += uv_problems(
                path,
                _show(root, f"{base}:{path}"),
                _show(root, f":0:{path}") or "",
                kind.lock_dir,
            )
    if tips and kind.gitlinks:
        out += tip_problems(root, base, entries, superproject, read_tip)
    return out
