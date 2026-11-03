"""Sync's phase hooks (DESIGN.md §2.5): what odoo-nix runs around the core's phases.

- ``phase_a_before``: a project whose submodules are not checked out gets them from the
  locked odoo-nix's ``bootstrap`` app before phase A locks the flake (a project flake
  sets ``self.submodules = true``, so Nix reads them to evaluate it). Addons mode has no
  submodules (OCB is ``coreSource``).
- ``reexec_argv``/``reentry_argv``: the handovers run the **locked engine's own**
  ``odoo-init`` (``nix run github:<owner>/<repo>/<rev>#odoo-init``), never the project
  flake's ``.#odoo-init``: evaluating the project flake would need its submodules, and
  the engine's app needs only the lock.

The engine's coordinates come from ``flake.lock``'s ``odoo-nix`` node. Without one (no
lock yet, or an input locked from a path) the core's defaults stand.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from standards_core.common import flakelock
from standards_core.common.report import ConfigError, EnvError
from standards_core.scaffold import bootstrap

if TYPE_CHECKING:
    from standards_core.scaffold.bootstrap import Runner
    from standards_core.scaffold.engine import Plan

INIT_APP = "odoo-init"
BOOTSTRAP_APP = "bootstrap"
SUBMODULE_NOTICE = (
    "odoo-nix sync: notice: submodules are not checked out; nix may fail to evaluate"
    " the flake (self.submodules)"
)


def _product():
    # product imports this module: read PRODUCT when a hook runs, not at import.
    from odoo_nix_tools.product import PRODUCT

    return PRODUCT


def engine_ref(root: Path) -> str | None:
    """The flake reference of the odoo-nix revision ``root/flake.lock`` pins:
    ``github:<owner>/<repo>/<rev>`` (``?host=`` off github.com), ``git+<url>?rev=<rev>``;
    ``None`` without a lock or such a node (a ``path:`` input has no revision)."""
    product = _product()
    path = root / "flake.lock"
    if not path.is_file():
        return None
    try:
        pin = flakelock.locked_pin(
            product, flakelock.load(path), product.engine.flake_input
        )
    except (ConfigError, EnvError):
        return None
    if pin.type == "git":
        return f"git+{pin.url}?rev={pin.rev}"
    ref = f"{pin.type}:{pin.owner}/{pin.repo}/{pin.rev}"
    default_host = "gitlab.com" if pin.type == "gitlab" else "github.com"
    if pin.host and pin.host.lower() != default_host:
        ref += f"?host={pin.host}"
    return ref


def _app(root: Path, app: str) -> str | None:
    """``<engine>#<app>``: the URL override of an engine's self-tests, else the lock's
    engine; ``None`` when neither names one."""
    override = bootstrap.override_url(_product())
    ref = override or engine_ref(root)
    return f"{ref}#{app}" if ref else None


def unchecked_submodules(root: Path) -> list[str]:
    """The submodules ``git submodule status`` lists as not initialized (``-``)."""
    if not (root / ".gitmodules").is_file():
        return []
    try:
        proc = subprocess.run(
            ["git", "submodule", "status"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    out = []
    for line in proc.stdout.splitlines():
        if line.startswith("-"):
            fields = line[1:].split()
            if len(fields) >= 2:
                out.append(fields[1])
    return out


def phase_a_before(plan: Plan, runner: Runner, args: argparse.Namespace) -> None:
    """A project with submodules not checked out runs the locked odoo-nix's
    ``bootstrap`` app over the checkout (``lib/bootstrap.sh``: it reads ``flake.lock``
    and never evaluates the project). Offline, ``--skip-lock`` or without a locked
    odoo-nix: a notice, and nothing runs. Addons mode: nothing."""
    if plan.ctx.discover.get("shape") != "project":
        return
    missing = unchecked_submodules(runner.root)
    if not missing:
        return
    app = _app(runner.root, BOOTSTRAP_APP)
    if args.offline or args.skip_lock or app is None:
        runner.say(f"{SUBMODULE_NOTICE}: {', '.join(missing)}")
        return
    runner.run(["nix", "run", app, "--", str(runner.root)])


def reexec_argv(passthrough: list[str]) -> list[str]:
    """``nix run <locked odoo-nix>#odoo-init -- --sync <passthrough>``: the locked
    engine's own app. Without a locked engine, the core's default
    (``nix run --no-pure-eval .#odoo-init``)."""
    app = _app(Path.cwd(), INIT_APP)
    if app is None:
        return ["nix", "run", "--no-pure-eval", f".#{INIT_APP}", "--", "--sync"] + list(
            passthrough
        )
    return ["nix", "run", app, "--", "--sync", *passthrough]


def reentry_argv(passthrough: list[str]) -> list[str]:
    """The same app with ``--phase b``. Only a no-Nix install (``uv tool install``)
    without uv or npm on PATH gets here: ``odoo-init`` and the dev shell have both."""
    app = _app(Path.cwd(), INIT_APP)
    if app is None:
        return [
            "nix",
            "run",
            "--no-pure-eval",
            f".#{INIT_APP}",
            "--",
            "--sync",
            "--phase",
            "b",
            *passthrough,
        ]
    return ["nix", "run", app, "--", "--sync", "--phase", "b", *passthrough]
