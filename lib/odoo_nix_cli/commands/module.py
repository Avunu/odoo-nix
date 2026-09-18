"""`odoo module add` / `odoo module add-bundle` -- OCA catalog picking and
arbitrary git-repo submodule management.

Interactive (gum-driven) and git-plumbing-heavy, so this delegates to the same
bash implementation the old odoo-add-module/odoo-add-bundle devenv scripts
used (now built by lib/cli-scripts.nix and wrapper-injected via
ODOO_NIX_MODULE_ADD[_BUNDLE]) rather than a Python rewrite of proven logic.
"""
from __future__ import annotations

import os

import click

from .. import odooenv


@click.group("module")
def module_group():
    """Workspace addons: add OCA modules or third-party git repos."""


@module_group.command("add", context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def module_add(args):
    """Pick OCA module(s) interactively, or add a git URL / owner/repo as a
    submodule: `odoo module add [module …]` | `odoo module add <git-url-or-owner/repo> [branch] [path]`."""
    script = odooenv.require_env("ODOO_NIX_MODULE_ADD")
    os.execv(script, [script, *args])


@module_group.command("add-bundle", context_settings={"ignore_unknown_options": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def module_add_bundle(args):
    """Add a curated OCA module bundle (data/oca-bundles.json)."""
    script = odooenv.require_env("ODOO_NIX_MODULE_ADD_BUNDLE")
    os.execv(script, [script, *args])
