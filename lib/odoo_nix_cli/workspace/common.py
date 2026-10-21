"""What add and remove share: modules.txt, a submodule's registration, and
the re-lock."""

from __future__ import annotations

from pathlib import Path

from odoo_nix_cli.init.proc import attempt, git, probe, run
from odoo_nix_cli.workspace.config import WorkspaceConfig

MODULES_TXT = Path("modules.txt")


def read_modules() -> list[str]:
    if not MODULES_TXT.is_file():
        return []
    return [
        line.strip()
        for line in MODULES_TXT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_modules(names: list[str]) -> None:
    """modules.txt, sorted and once each (deterministic, clean diffs)."""
    MODULES_TXT.write_text(
        "".join(f"{m}\n" for m in sorted(set(names))), encoding="utf-8"
    )


def add_modules_txt(names: list[str]) -> None:
    write_modules([*read_modules(), *names])


def submodules() -> dict[str, str]:
    """{path: section name} from .gitmodules: .git/config and .git/modules/
    are keyed on the name, which is not always the path."""
    listing = (
        probe(
            git("config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$")
        )
        or ""
    )
    out: dict[str, str] = {}
    for line in listing.splitlines():
        key, _, path = line.partition(" ")
        out[path] = key.removeprefix("submodule.").removesuffix(".path")
    return out


def register(url: str, branch: str, path: str) -> None:
    """An already cloned PATH as a shallow submodule on BRANCH."""
    run(git("submodule", "add", "-q", "--force", "-b", branch, "--", url, path))
    run(git("config", "-f", ".gitmodules", f"submodule.{path}.shallow", "true"))


def regenerate(cfg: WorkspaceConfig) -> int:
    """pyproject.toml's path sources and install set from what is on disk, then
    `uv lock`: lib/cli-scripts.nix's regenerateAndLock, which keeps a
    store-resident OCB writable for the lock (lib/core-shadow.sh). Its status."""
    return attempt([cfg.regenerate])
