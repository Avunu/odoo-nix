"""``odoo-init``'s entry point: the arguments, the mode, and dispatch.

Exit codes (README, "Scaffolder reference"; frappe-nix's table, where it
applies): 0 done or a finished --dry-run; 1 a forced --migrate on an empty or
missing directory, a usage error, or any error without a more specific code; 2
--init into a directory that is not empty; 4 a flake.nix or pyproject.toml that
is not odoo-nix's; 5 the Odoo series (missing, unknown, undetectable or without
a preset); 6 the directory is not the shape the mode needs, or the
confirmation was declined; 7 custom/ or modules/ with no module and no OCB,
so nothing to migrate; 8 a tree inside another git repository. A failing step
(git, odoo-nix-sources) exits with its own status. odoo-nix has no --sync or
--check, so frappe-nix's 3 is not used.
"""

from __future__ import annotations

import os
import sys

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.args import RENAMED, USAGE, UsageError, parse_args
from odoo_nix_cli.init.config import ConfigError
from odoo_nix_cli.init.config import load as load_config
from odoo_nix_cli.init.detect import (
    dir_is_empty,
    has_foreign_flake,
    is_odoo_nix_project,
    looks_like_empty_tree,
    looks_like_odoo_tree,
)
from odoo_nix_cli.init.presets import PresetError
from odoo_nix_cli.init.presets import load as load_presets
from odoo_nix_cli.init.state import Run

#: Variables that would send every git command at the wrong repository: a hook,
#: or `git submodule foreach`, leaves them set.
GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY")


def decide_mode(st: Run) -> str:
    """The mode for the (non-empty) working directory: the one forced when the
    directory fits it (or --force), else what the directory looks like."""
    mode, force = st.args.mode, st.args.force
    here = os.getcwd()
    if mode == "init":
        if not (dir_is_empty(".") or force):
            ui.die(
                f"'{here}' is not empty. Use --migrate to bring an existing Odoo tree into odoo-nix, or --init --force to scaffold into it anyway.",
                2,
            )
        return "init"
    if mode == "migrate":
        if not (looks_like_odoo_tree() or is_odoo_nix_project() or force):
            ui.die(
                f"'{here}' does not look like an Odoo tree (no OCB at odoo/, no module under custom/ or modules/). Re-run with --migrate --force to try anyway.",
                6,
            )
        st.repair = is_odoo_nix_project()
        return "migrate"

    if is_odoo_nix_project():
        ui.info("already an odoo-nix project — reconciling (repair mode)")
        st.repair = True
        return "migrate"
    if has_foreign_flake() and looks_like_odoo_tree():
        ui.die(
            f"'{here}' is an Odoo tree, but its flake.nix is not odoo-nix's. Re-run with --migrate --force: odoo-nix's will be written to flake.nix.odoo-nix for you to merge.",
            4,
        )
    if looks_like_odoo_tree():
        return "migrate"
    if looks_like_empty_tree():
        ui.die(
            f"'{here}' has custom/ or modules/ but no Odoo module in them and no OCB at odoo/. Nothing to migrate.",
            7,
        )
    ui.die(
        f"'{here}' is not empty and is not an Odoo tree. Use --init --force to scaffold into it, or --migrate --force to try anyway.",
        6,
    )


def dispatch(st: Run) -> None:
    from odoo_nix_cli.init.migrate import cmd_migrate
    from odoo_nix_cli.init.scaffold import cmd_init

    a = st.args
    for old in a.renamed:
        st.warn(
            f"{old} is now {RENAMED[old]}; the old name works through 1.x and goes in odoo-nix 2.0.0"
        )

    # No target: the current directory when it is an Odoo tree or an odoo-nix
    # project, or when --migrate forces it (decide_mode then says what is
    # wrong with it); otherwise a new project, which asks where.
    target = a.target
    if not target and (
        a.mode == "migrate"
        or is_odoo_nix_project()
        or looks_like_odoo_tree()
        or looks_like_empty_tree()
    ):
        target = "."

    if target and os.path.isdir(target) and not dir_is_empty(target):
        try:
            os.chdir(target)
        except OSError as e:
            ui.die(f"cannot enter {target}: {e.strerror}")
        st.mode = decide_mode(st)
        target = "."
    else:
        if a.mode == "migrate":
            ui.die(
                f"'{target or '.'}' is empty or does not exist — there is nothing to migrate."
            )
        st.mode = "init"
    st.target = target
    st.cd = "" if a.target in ("", ".") else a.target

    if st.mode == "init":
        cmd_init(st)
    else:
        cmd_migrate(st)


def main(argv: list[str] | None = None) -> int:
    for var in GIT_ENV:
        os.environ.pop(var, None)
    try:
        try:
            args = parse_args(list(sys.argv[1:] if argv is None else argv))
        except UsageError as e:
            if e.show_usage:
                print(USAGE, file=sys.stderr, end="")
            raise ui.Die(str(e), e.code) from None
        if args.help:
            print(USAGE, end="")
            return 0
        try:
            config = load_config()
            presets = load_presets(config.presets)
        except (ConfigError, PresetError) as e:
            raise ui.Die(str(e)) from None
        os.environ.pop("ODOO_NIX_INIT_CONFIG", None)
        st = Run(args=args, config=config, presets=presets, version=args.version)
        dispatch(st)
    except ui.Die as e:
        ui.error_line(str(e))
        return e.code
    except ui.Exit as e:
        return e.code
    except KeyboardInterrupt:
        return 130
    finally:
        sys.stdout.flush()
    return 0


def entry() -> None:
    sys.exit(main())
