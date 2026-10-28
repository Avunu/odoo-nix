"""A project's one consumer-facing relock (python-devops-nix
docs/conventions.md, Relock), in its two forms: ``odoo project relock`` in the
dev shell, and ``nix run .#relock`` outside it (lib/relock.nix runs ``main``).
Both run ``run``, with the workspace configuration lib/cli-scripts.nix bakes.

The flake app exists for a project whose shell does not start: a lock too
stale for the shell to evaluate (the stale-lock audit in lib/python.nix) can
only be fixed by the relock, and the shell's ``odoo`` is built from that lock.
So the app evaluates nothing that reads uv.lock, and this module is stdlib
only: lib/relock.nix runs it on a plain interpreter.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.proc import attempt
from odoo_nix_cli.workspace import config
from odoo_nix_cli.workspace.update import relock

NAME = "odoo-nix-relock"

HELP = """\
Usage: nix run .#relock [-- UV_ARGS…]

Re-locks the project without its dev shell, with the same code as
`odoo project relock`: regenerates what odoo-nix manages in pyproject.toml
(OCB and every local module as uv path sources, the install set from
modules.txt), then re-locks uv.lock with the sdist build dependencies in step.
It pulls nothing and moves no submodule. UV_ARGS go to `uv lock`, e.g.
--upgrade or --upgrade-package NAME.

Run it from the project root, when the shell does not start because uv.lock
is stale. First it checks out the submodules this clone has never had, as
shell entry would: a module whose repository is not on disk is left out of
the lock."""

DONE = "✅ Re-locked. Commit pyproject.toml and uv.lock, then: direnv reload"
AFTER_FAILED = "⚠  odoo-nix-build-deps, or the uv lock after it, failed — see above."


def run(cfg: config.WorkspaceConfig, uv_args: Sequence[str] = ()) -> int:
    """The relock, in the working directory, and its closing line; its status."""
    r = relock(cfg, uv_args)
    if r.after:
        print(AFTER_FAILED, file=sys.stderr, flush=True)
    elif not r.status:
        print(DONE, flush=True)
    return r.status


def main(argv: Sequence[str]) -> int:
    """``nix run .#relock``: ``run`` from the project root ($REPO_ROOT, else
    the working directory), after what shell entry does first."""
    if any(a in ("-h", "--help") for a in argv):
        print(HELP)
        return 0
    try:
        cfg = config.load()
    except config.ConfigError as e:
        print(f"{NAME}: {e}", file=sys.stderr)
        return 1
    root = os.environ.get("REPO_ROOT") or os.getcwd()
    if not os.path.isfile(os.path.join(root, "pyproject.toml")):
        print(
            f"{NAME}: no pyproject.toml in {root}; run it from the project root.",
            file=sys.stderr,
        )
        return 1
    os.chdir(root)
    # The shell this clone never started would have checked out the
    # submodules it has never had (modules/devenv.nix). The install set is
    # what is on disk, so without them the lock would drop their modules: a
    # pull that brings a new repository and its modules.txt entry leaves
    # exactly that. odoo-nix-sources always exits 0 and says what it could not
    # do; the odoo/ link is core_shadow's.
    try:
        attempt([cfg.sources, "enter", "--treeless", cfg.layout.core_src, root])
        return run(cfg, argv)
    except ui.Exit as e:
        return e.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
