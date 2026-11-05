"""Move every pin of python-devops-nix (standards-core) to one commit (core DESIGN.md §10.3).

odoo-nix reaches the core three ways, and ``checks.standards-core-pins`` requires them
to name the same commit:

- ``flake.lock``'s ``python-devops-nix`` node (flake.nix keeps the ref-less
  ``github:Avunu/python-devops-nix``; the lock carries the commit);
- the ``standards-core @ git+https://github.com/Avunu/python-devops-nix@<sha>`` line
  of ``py/odoo_nix_tools/pyproject.toml``, which ``uv tool install`` resolves;
- every ``Avunu/python-devops-nix/…@<sha>`` in ``.github/**`` (composite actions and
  reusable workflows), with the trailing version comment ``ci-pins`` requires.

    bump_base.py ROOT SHA COMMENT

rewrites the last two in the work tree ``ROOT``; the app (lib/standards/bump-base.nix)
locks the flake input and relocks the dev ``uv.lock`` around it. Exit 0, or 1 naming what
it could not find.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

OWNER_REPO = "Avunu/python-devops-nix"
PYPROJECT = "py/odoo_nix_tools/pyproject.toml"
_REV = re.compile(r"[0-9a-f]{40}")
_URL = re.compile(
    r"(standards-core @ git\+https://github\.com/"
    + re.escape(OWNER_REPO)
    + r"@)[0-9a-f]{40}(#subdirectory=standards)"
)
# `uses: Avunu/python-devops-nix/<path>@<sha> # <comment>`; a commented-out line is left.
_USES = re.compile(
    r"^(?P<head>(?!\s*#).*?(?<![A-Za-z0-9_.-])"
    + re.escape(OWNER_REPO)
    + r"/[^\s@'\"]+@)[0-9a-f]{40}(?P<tail>[^\n#]*?)(?:[ \t]+#[^\n]*)?$",
    re.MULTILINE | re.IGNORECASE,
)


def bump_pyproject(root: Path, sha: str) -> int:
    path = root / PYPROJECT
    text = path.read_text()
    new, count = _URL.subn(rf"\g<1>{sha}\g<2>", text)
    if count:
        path.write_text(new)
    return count


def bump_github(root: Path, sha: str, comment: str) -> list[str]:
    changed = []
    for path in sorted((root / ".github").rglob("*")):
        if path.suffix not in (".yml", ".yaml") or not path.is_file():
            continue
        text = path.read_text()
        new = _USES.sub(lambda m: f"{m['head']}{sha}{m['tail']} # {comment}", text)
        if new != text:
            path.write_text(new)
            changed.append(path.relative_to(root).as_posix())
    return changed


def main(argv: list[str]) -> int:
    if len(argv) != 3 or not _REV.fullmatch(argv[1]) or not argv[2].strip():
        print("usage: bump_base.py ROOT SHA(40 hex) COMMENT", file=sys.stderr)
        return 2
    root, sha, comment = Path(argv[0]), argv[1], argv[2].strip()
    if not bump_pyproject(root, sha):
        print(f"{PYPROJECT}: no standards-core @ git+…{OWNER_REPO}@<sha> line")
        return 1
    print(f"{PYPROJECT}: standards-core @ {sha[:12]}")
    for rel in bump_github(root, sha, comment):
        print(f"{rel}: {OWNER_REPO}/…@{sha[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
