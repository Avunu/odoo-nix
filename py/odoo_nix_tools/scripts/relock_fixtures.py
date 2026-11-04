#!/usr/bin/env python3
"""Write tests/fixtures/standards-locks/<fixture>/<profile>/{tools/uv.lock,package-lock.json}
and the manifests they lock (tools/pyproject.toml, package.json).

Each fixture is synced under each profile that puts a tool in the tools project or turns
js-xml on (``recommended``, ``example-org``; ``minimal`` has none), and the two lock
commands sync's phase B runs are run there: ``uv lock --project tools`` and ``npm
install --package-lock-only …`` (network). The tests and the ``standards-fixtures-*``
checks copy a profile's locks into the fixture before ``sync --check`` (DESIGN.md
§7.1). Run it whenever the series data, ``data/tool-pins.json`` or the tools groups
change, then ``scripts/gen_fixture_data.py``:

    cd py/odoo_nix_tools
    PYTHONPATH=.:tests uv run --no-project --with-editable <standards-core> \\
        python scripts/relock_fixtures.py

``nix run .#relock-standards-fixtures`` runs it, then ``scripts/gen_fixture_data.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "tests")]

from support import LOCKS, fixture_files, run_cli

REPO = HERE.parent.parent.parent
FIXTURES = ("standards-project", "standards-addons")
PROFILES = ("recommended", "example-org")
NPM = [
    "npm",
    "install",
    "--package-lock-only",
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
]


def git(root: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)


def relock(name: str, profile: str, work: Path) -> None:
    # The npm lock records the directory name when package.json has none: the fixture's.
    root = work / name / profile / name.removeprefix("standards-")
    root.mkdir(parents=True)
    for rel, body in fixture_files(REPO, name, profile, locks=False).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(body)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "fixture")
    code, out, err = run_cli("sync", "--write", "--offline", cwd=root)
    if code not in (0, 1):
        raise SystemExit(f"{name} × {profile}: sync exited {code}\n{out}{err}")
    target = REPO / LOCKS / name / profile
    shutil.rmtree(target, ignore_errors=True)
    # Each lock with the manifest it was made from: the tools project as uv2nix
    # and importNpmLock read it (the standards-prek-* checks build the tools from
    # these directories, lib/standards/tools.nix). The tests copy the locks only.
    if (root / "tools/pyproject.toml").is_file():
        subprocess.run(["uv", "lock", "--project", "tools"], cwd=root, check=True)
        (target / "tools").mkdir(parents=True)
        for rel in ("tools/pyproject.toml", "tools/uv.lock"):
            shutil.copy(root / rel, target / rel)
    if (root / "package.json").is_file():
        subprocess.run(NPM, cwd=root, check=True)
        target.mkdir(parents=True, exist_ok=True)
        for rel in ("package.json", "package-lock.json"):
            shutil.copy(root / rel, target / rel)
    print(
        f"{name} × {profile}: {sorted(p.name for p in target.rglob('*') if p.is_file())}"
    )


def main() -> int:
    os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
    os.environ["ODOO_NIX_ALLOW_SKEW"] = "1"
    os.environ.setdefault("GIT_AUTHOR_NAME", "relock")
    os.environ.setdefault("GIT_AUTHOR_EMAIL", "relock@example.org")
    os.environ.setdefault("GIT_COMMITTER_NAME", "relock")
    os.environ.setdefault("GIT_COMMITTER_EMAIL", "relock@example.org")
    with tempfile.TemporaryDirectory(prefix="relock-standards-") as tmp:
        for name in FIXTURES:
            for profile in PROFILES:
                relock(name, profile, Path(tmp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
