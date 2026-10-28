"""The lock sequence, and the lock-time shadow of an OCB tree in the Nix store.
Shared by a project's relock (``odoo project relock`` and ``nix run
.#relock``, and so ``project update`` and ``module add|add-bundle|remove``,
through odoo_nix_cli.workspace.update) and by ``nix run .#relock-fixtures``,
which re-locks odoo-nix's own test fixtures (tests/relock-fixtures.nix runs
this module's ``main``). Was lib/core-shadow.sh and the tail of
lib/cli-scripts.nix's regenerateAndLock.

Stdlib only: tests/relock-fixtures.nix runs it on a plain interpreter.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator, Sequence

from odoo_nix_cli.init.proc import attempt

USAGE = (
    "usage: python -m odoo_nix_cli.workspace.lock --uv UV --build-deps BIN"
    " [--core LINK=STORE] [--] [uv lock flags…]"
)

#: The two big OCB entries a shadow links instead of copying.
LINKED = ("odoo", "addons")


def _relink(target: str, link: str) -> None:
    """``ln -sfn TARGET LINK``, atomically."""
    tmp = f"{link}.odoo-nix-tmp"
    with contextlib.suppress(FileNotFoundError):
        os.unlink(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, link)


def _writable(root: str) -> None:
    """``chmod -R u+w``: a copy out of the store keeps its 0444 and 0555."""
    for parent, dirs, files in os.walk(root):
        for name in [parent, *(os.path.join(parent, n) for n in [*dirs, *files])]:
            if not os.path.islink(name):
                os.chmod(name, os.stat(name).st_mode | 0o200)


@contextlib.contextmanager
def core_shadow(link: str, store: str | None) -> Iterator[str | None]:
    """For the duration of a lock, LINK points at a writable shadow of STORE.

    With ``coreSource``, <coreSrc> (./odoo) is a symlink to a read-only store
    path. ``uv lock`` resolves ``odoo = { path = "odoo" }`` through it and asks
    setuptools for the package metadata, whose egg_info step writes
    ``odoo.egg-info`` into the project root: that fails on the store. uv also
    refuses a ``backend-path`` (``setup/``) that resolves outside the source
    tree, so the tree cannot simply be a directory of symlinks either.

    So the shadow copies the small top-level entries (setup/, setup.py,
    pyproject.toml, …) and links the two big ones, odoo/ and addons/: writable
    at the root, identical everywhere setuptools looks. Afterwards LINK points
    at STORE again, which is what everything else (odoo-bin, the IDE mirror)
    wants. A missing LINK is made, as shell entry would make it: ``nix run
    .#relock`` runs where the shell has never started. Nothing is done when
    STORE is None or LINK is something else (a submodule checkout). Yields
    the shadow directory, or None.
    """
    if not store or (os.path.lexists(link) and not os.path.islink(link)):
        yield None
        return
    shadow = tempfile.mkdtemp(prefix="odoo-nix-core-shadow.")
    try:
        for name in sorted(os.listdir(store)):
            src = os.path.join(store, name)
            dst = os.path.join(shadow, name)
            if not os.path.exists(src):
                continue
            if name in LINKED:
                os.symlink(src, dst)
            elif os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, dst, symlinks=True)
            else:
                shutil.copy(src, dst, follow_symlinks=False)
        _writable(shadow)
        _relink(shadow, link)
        yield shadow
    finally:
        _writable(shadow)
        shutil.rmtree(shadow, ignore_errors=True)
        _relink(store, link)


def lock(uv: str, build_deps: str, uv_args: Sequence[str] = ()) -> tuple[int, int]:
    """``uv lock [UV_ARGS]``, then the managed sdist build-dependency block
    (odoo-nix-build-deps) and ``uv lock`` again, in the working directory.

    Returns (the first lock's status, the status of what followed it): the
    first nonzero of the two later steps, which both run either way. Nothing
    follows a first lock that failed.
    """
    rc = attempt([uv, "lock", *uv_args])
    if rc != 0:
        return rc, 0
    after = attempt([build_deps, "update", "pyproject.toml", "uv.lock"])
    again = attempt([uv, "lock"])
    return 0, after or again


def main(argv: Sequence[str]) -> int:
    """The fixtures' relock (tests/relock-fixtures.nix): every step must pass."""
    args = list(argv)
    opts: dict[str, str] = {}
    while args and args[0] in ("--uv", "--build-deps", "--core"):
        if len(args) < 2:
            print(USAGE, file=sys.stderr)
            return 2
        opts[args[0]] = args[1]
        del args[:2]
    if args[:1] == ["--"]:
        del args[0]
    if "--uv" not in opts or "--build-deps" not in opts:
        print(USAGE, file=sys.stderr)
        return 2
    link, _, store = opts.get("--core", "").partition("=")
    with core_shadow(link, store or None):
        first, after = lock(opts["--uv"], opts["--build-deps"], args)
    return 1 if first or after else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
