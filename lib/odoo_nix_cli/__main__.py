"""Entrypoint: `odoo` either runs its own click app (db/module/project/shell)
or execs straight into the real odoo-bin, preserving every existing odoo-bin
subcommand (server, shell passthrough for anything beyond the sugar in
commands/__init__.py, scaffold, populate, cloc, deploy, neutralize, …) with
zero duplication -- mirrors how `bench`'s own entrypoint decides between
running its own commands and os.execv-ing into the framework CLI
(bench/cli.py).

`-c/--config` and `-d/--database` are accepted before the subcommand name
(matching every existing odoo-bin invocation style in this repo), so the
dispatch scan below has to recognize and skip them while looking for the
first real token -- the same thing odoo.cli.command.main() does for its own
`--addons-path=` special case.
"""
from __future__ import annotations

import os
import sys

OWN_COMMANDS = {"db", "module", "project", "shell", "test", "help", "--help", "-h"}
_VALUE_OPTS = {
    "-c",
    "--config",
    "-d",
    "--database",
    "--db-host",
    "--db-port",
    "--db-user",
    "--db-password",
}
_VALUE_OPT_PREFIXES = tuple(f"{opt}=" for opt in _VALUE_OPTS if opt.startswith("--"))


def _first_command(argv: list[str]) -> str | None:
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in _VALUE_OPTS:
            i += 2
            continue
        if tok.startswith(_VALUE_OPT_PREFIXES):
            i += 1
            continue
        return tok
    return None


def _raw_odoo_bin() -> str:
    path = os.environ.get("ODOO_NIX_RAW_ODOO")
    if not path:
        sys.exit("odoo: $ODOO_NIX_RAW_ODOO is not set -- this entrypoint must run from the odoo-nix-built wrapper.")
    return path


def _setup_journald() -> None:
    """journald-native logging (services.odoo-nix sets $ODOO_NIX_JOURNALD; see
    journald.py). Both halves are set up here, before dispatch, because this
    is the one point every invocation passes through: the in-process handler
    for our own commands, and -- since most invocations leave this process
    through os.execv -- the sitecustomize directory on PYTHONPATH, which is
    what carries the patch into odoo-bin and whatever it spawns."""
    from . import journald

    if not journald.enabled():
        return
    site_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_journald_site")
    current = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = f"{site_dir}{os.pathsep}{current}" if current else site_dir
    journald.install_root_handler()


def _install_devguard() -> None:
    """The dev environment's guard rails (odoo_devguard), for this process.

    The raw odoo-bin path is covered by the .pth the dev virtualenv carries;
    this interpreter is a separate one (rich + click) with the dev environment
    only on PYTHONPATH, where .pth files are not processed -- so `odoo db ...`,
    which imports Odoo in-process, installs the guard itself.

    Absent from the production environment by construction (lib/python.nix), so
    there the import fails and this does nothing.
    """
    try:
        import odoo_devguard
    except ImportError:
        return
    odoo_devguard.install()


def main() -> None:
    argv = sys.argv[1:]
    _setup_journald()
    if _first_command(argv) not in OWN_COMMANDS:
        raw = _raw_odoo_bin()
        os.execv(raw, [raw, *argv])
        return  # unreachable

    _install_devguard()
    from .commands import cli

    cli(args=argv)


if __name__ == "__main__":
    main()
