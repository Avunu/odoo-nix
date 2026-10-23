"""`odoo module add` / `add-bundle` / `remove`: the workspace's OCA modules
and third-party git repositories (python-devops-nix docs/conventions.md, Source
management). The logic is odoo_nix_cli.workspace; lib/cli-scripts.nix bakes
its configuration (ODOO_NIX_WORKSPACE_CONFIG) and the re-lock script.
"""

from __future__ import annotations

import os
import sys

import click

from .. import odooenv

_RAW = {"ignore_unknown_options": True}
# remove reads its own --help (odoo_nix_cli.workspace.remove.USAGE).
_OWN_HELP = {**_RAW, "help_option_names": []}


def _run(fn, args, *extra) -> None:
    from ..init import ui
    from ..workspace import config
    from ..workspace.add import Stop

    try:
        cfg = config.load()
    except config.ConfigError as e:
        raise click.ClickException(str(e)) from None
    os.chdir(odooenv.repo_root())
    try:
        rc = fn(cfg, list(args), *extra)
    except Stop as e:
        if str(e):
            sys.stdout.flush()
            print(str(e), file=sys.stderr)
        rc = e.code
    except ui.Exit as e:
        rc = e.code
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


@click.group("module")
def module_group():
    """Workspace addons: add OCA modules or third-party git repos, or remove them."""


@module_group.command("add", context_settings=_RAW)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def module_add(args):
    """Pick OCA module(s) interactively, or add a git URL / owner/repo as a
    submodule: `odoo module add [module …]` | `odoo module add <git-url-or-owner/repo> [branch] [path]`."""
    from ..workspace.add import add

    _run(add, args)


@module_group.command("add-bundle", context_settings=_RAW)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def module_add_bundle(args):
    """Add a curated OCA module bundle (data/oca-bundles.json)."""
    from ..workspace.add import add_bundle

    _run(add_bundle, args)


@module_group.command("remove", context_settings=_OWN_HELP)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def module_remove(ctx, args):
    """Take modules out of modules.txt, and the repositories nothing needs any
    more out of the workspace: `odoo module remove [--force] [--keep-repos]
    <module | repo> …` (--help for more)."""
    from ..workspace.remove import remove

    _run(remove, args, ctx.obj or {})
