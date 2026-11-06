"""`odoo test`'s pieces: which addons `--all` means, the odoo-bin command line,
and running it with its output also written to a log.

Standard library only, and never `odoo_nix_tools`: the `odoo` CLI runs in
Odoo's own interpreter with the project's environment on PYTHONPATH, which the
standards tools (standards_core, jinja2, tomlkit, ...) must not reach
(py/odoo_nix_tools/DESIGN.md §5.1). `odoo-nix gate test` works out the same
list of addons from its own discovery and passes it explicitly, so the two
agree by test, not by shared code.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

#: The standards' config files, in the order `--all` reads them: a project's
#: root pyproject.toml, then a repository of addons' nix/pyproject.toml.
CONFIG_FILES = ("pyproject.toml", "nix/pyproject.toml")
#: Where the coverage data goes unless $COVERAGE_FILE says otherwise, from the
#: repository root (gitignored with the rest of .odoo-nix/).
COVERAGE_FILE = ".odoo-nix/coverage/.coverage"
#: The variable lib/raw-odoo.nix's coverage hook reads: Odoo then runs under
#: `coverage run --rcfile=<it> --parallel-mode`.
COVERAGE_ENV = "ODOO_NIX_COVERAGE_RCFILE"


class OdooTestError(Exception):
    """A configuration `odoo test` cannot run with; the message says why."""


def installable_addons(directory: Path) -> list[str]:
    """Every addon directly under `directory` whose manifest does not say
    `installable: False`, sorted. A manifest `ast.literal_eval` cannot read is
    skipped, as Odoo would fail on it too."""
    found = []
    for manifest in sorted(directory.glob("*/__manifest__.py")):
        try:
            data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        if isinstance(data, dict) and data.get("installable", True) is not False:
            found.append(manifest.parent.name)
    return found


def addons_dir(root: Path, env: Mapping[str, str]) -> Path:
    """The directory of the repository's own addons: $ODOO_NIX_LOCAL_ADDONS in
    addons mode, else the layout's customDir from the workspace configuration
    (lib/cli-scripts.nix), else custom/."""
    local = env.get("ODOO_NIX_LOCAL_ADDONS")
    if local:
        return root / local
    path = env.get("ODOO_NIX_WORKSPACE_CONFIG")
    if path:
        try:
            custom = json.loads(Path(path).read_text())["layout"]["customDir"]
        except (OSError, ValueError, KeyError, TypeError):
            custom = None
        if isinstance(custom, str) and custom:
            return root / custom
    return root / "custom"


def standards_table(root: Path) -> dict:
    """The [tool.odoo-nix] table of the first config file that has one, else
    {}. A file that is not TOML is an error: the gate would refuse it too."""
    for name in CONFIG_FILES:
        path = root / name
        if not path.is_file():
            continue
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise OdooTestError(f"{name}: {exc}") from exc
        table = doc.get("tool", {}).get("odoo-nix")
        if isinstance(table, dict):
            return table
    return {}


def untested(root: Path) -> set[str]:
    """The addons `[[tool.odoo-nix.untested]]` lists: `{addon, reason}` items."""
    items = standards_table(root).get("untested", [])
    if not isinstance(items, list):
        raise OdooTestError("[tool.odoo-nix] untested must be an array of tables")
    names = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("addon"), str):
            raise OdooTestError(
                "each [[tool.odoo-nix.untested]] item needs an `addon` (and a `reason`)"
            )
        names.add(item["addon"])
    return names


def all_modules(root: Path, env: Mapping[str, str]) -> list[str]:
    """`--all`: the repository's installable addons, minus the untested ones."""
    directory = addons_dir(root, env)
    skip = untested(root)
    modules = [m for m in installable_addons(directory) if m not in skip]
    if not modules:
        where = os.path.relpath(directory, root)
        raise OdooTestError(
            f"no addon to test in {where}/ (every installable addon is untested, or there is none)"
        )
    return modules


def demo_args(major: int) -> list[str]:
    """Demo data in the test database. 19.0 loads none unless asked
    (`--with-demo`); through 18.0 it loads unless `without_demo` says
    otherwise, and an empty `--without-demo=` overrides a project's
    `without_demo = True` (a client project's settings) for this run."""
    return ["--with-demo"] if major >= 19 else ["--without-demo="]


def tags_for(modules: Sequence[str]) -> str:
    """`a,b` -> `/a,/b`: each addon's own tests, none of its dependencies'."""
    return ",".join(f"/{m}" for m in modules)


def odoo_argv(
    raw: str,
    conf_path: Path,
    database: str,
    modules: Sequence[str],
    *,
    fresh: bool,
    major: int,
    db_args: Sequence[str],
) -> list[str]:
    """The odoo-bin command line: `-i` into a fresh database, or `-u` on an
    existing one."""
    joined = ",".join(modules)
    argv = [raw, "-c", str(conf_path), "-d", database]
    if fresh:
        argv += ["-i", joined, *demo_args(major)]
    else:
        argv += ["-u", joined]
    argv += ["--test-enable", "--test-tags", tags_for(modules), "--stop-after-init"]
    # To stdout, whatever odoo.conf's logfile says: `--log` tees stdout for checklog-odoo,
    # which fails on a file with no log records, and the run's result belongs on screen.
    argv.append("--logfile=")
    if fresh:
        argv.append("--workers=0")
    return [*argv, *db_args]


def coverage_env(root: Path, rcfile: Path, env: Mapping[str, str]) -> dict[str, str]:
    """The variables a measured run adds: the rcfile for lib/raw-odoo.nix's
    hook, and an absolute $COVERAGE_FILE, so the data file does not depend on
    whether coverage resolves `data_file` against the current directory or the
    rcfile's (py/odoo_nix_tools/DESIGN.md §6.1.2). One the caller exported
    (`odoo-nix gate test`) is kept, made absolute against `root` when it is
    relative: the raw odoo-bin runs from the repository root, so that is where
    coverage writes it, wherever `odoo test` was started."""
    exported = env.get("COVERAGE_FILE")
    data_file = os.path.abspath(root / (exported or COVERAGE_FILE))
    return {COVERAGE_ENV: str(rcfile.resolve()), "COVERAGE_FILE": data_file}


def coverage_files(data_file: Path) -> list[Path]:
    """The data file and its parallel-mode siblings (`<data_file>.<host>.<pid>…`)."""
    if not data_file.parent.is_dir():
        return []
    return sorted(
        p
        for p in data_file.parent.iterdir()
        if p.is_file()
        and (p.name == data_file.name or p.name.startswith(data_file.name + "."))
    )


def run(argv: Sequence[str], env: Mapping[str, str], log: Path | None) -> int:
    """Run `argv` to its end and return its exit code. With `log`, its output
    (stdout and stderr, in order) is written there as well as to stdout."""
    if log is None:
        proc = subprocess.Popen(argv, env=dict(env))
        return _wait(proc)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as sink:
        proc = subprocess.Popen(
            argv, env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        assert proc.stdout is not None
        pipe = proc.stdout.fileno()
        out = sys.stdout.buffer
        while True:
            try:
                chunk = os.read(pipe, 65536)
            except KeyboardInterrupt:
                # The terminal sent Odoo the same SIGINT: keep its output
                # flowing until it stops its own way.
                continue
            if not chunk:
                break
            sink.write(chunk)
            out.write(chunk)
            out.flush()
        proc.stdout.close()
        return _wait(proc)


def _wait(proc: subprocess.Popen) -> int:
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue
