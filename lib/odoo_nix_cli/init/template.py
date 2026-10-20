"""templates/project: rendered into a staging directory, then installed into
the project without overwriting anything that is already there.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from pathlib import Path

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.state import Run

#: The files the tokens are substituted in.
RENDERED = ("flake.nix", "pyproject.toml", "README.md")
TOKEN = re.compile(r"@[A-Z_]+@")


def tokens(st: Run) -> dict[str, str]:
    return {
        "@PROJECT_NAME@": st.name,
        "@DB_NAME@": st.db,
        "@SERIES@": st.version,
        "@PYTHON@": st.p.python,
        "@REQUIRES_PYTHON@": st.p.requires_python,
    }


def substitute(text: str, values: dict[str, str]) -> str:
    """Every known @TOKEN@ in TEXT replaced, literally and in one pass: a value
    holding |, & or another @TOKEN@ is written as it is."""
    return TOKEN.sub(lambda m: values.get(m.group(0), m.group(0)), text)


def render(st: Run) -> Path:
    """The template, rendered for ST, in a fresh staging directory."""
    staging = Path(tempfile.mkdtemp(prefix="odoo-init-"))
    shutil.copytree(st.config.template, staging, dirs_exist_ok=True, symlinks=True)
    # The copy keeps the store's read-only modes, the staging directory's own
    # included.
    staging.chmod(staging.stat().st_mode | stat.S_IWUSR)
    for root, dirs, files in os.walk(staging):
        for name in dirs + files:
            p = Path(root, name)
            if not p.is_symlink():
                p.chmod(p.stat().st_mode | stat.S_IWUSR)
    values = tokens(st)
    for name in RENDERED:
        p = staging / name
        if p.is_file():
            p.write_text(
                substitute(p.read_text(encoding="utf-8"), values), encoding="utf-8"
            )
    return staging


def files(staging: Path) -> list[str]:
    """The template's files, relative and sorted."""
    return sorted(
        str(p.relative_to(staging))
        for p in staging.rglob("*")
        if p.is_file() or p.is_symlink()
    )


def _merge_gitignore(src: Path, dest: Path) -> bool:
    """Append the template's patterns DEST lacks; whether any were."""
    have = {
        line.strip()
        for line in dest.read_text(encoding="utf-8", errors="replace").splitlines()
    }
    lines = [
        line
        for line in src.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and not line.lstrip().startswith("#")
        and line.strip() not in have
    ]
    if not lines:
        return False
    text = dest.read_text(encoding="utf-8", errors="replace")
    sep = "" if not text or text.endswith("\n") else "\n"
    dest.write_text(
        text + sep + "\n# odoo-nix\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )
    return True


def install(
    staging: Path, *, skip: tuple[str, ...] = (), verbose: bool = False
) -> list[str]:
    """Copy each staged file that is not in the project yet (nor in SKIP); a
    .gitignore that is gains the patterns it lacks. The files written."""
    written: list[str] = []
    for rel in files(staging):
        src, dest = staging / rel, Path(rel)
        if rel in skip:
            continue
        if os.path.lexists(dest):
            if rel == ".gitignore" and dest.is_file() and _merge_gitignore(src, dest):
                written.append(rel)
                if verbose:
                    ui.info(f"~ {rel} (the patterns odoo-nix needs, appended)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest, follow_symlinks=False)
        written.append(rel)
        if verbose:
            ui.info(f"+ {rel}")
    return written
