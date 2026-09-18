"""The odoo-nix dev-shell welcome banner, printed once on `enterShell`.

Invoked as `python banner.py <project_name> <series> <addons_count>
<http_port> <mailcatch_enabled 0|1> <mailcatch_http_port>` -- all Nix-eval-time
facts modules/devenv.nix already has as plain strings, so this stays a
one-shot render with no odoo.conf/CLI-runtime knowledge of its own. Not part
of the `odoo` CLI package: this is dev-shell furniture, unrelated to the
site-maintenance commands odoo_nix_cli implements.
"""
from __future__ import annotations

import sys

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

COMMANDS = [
    ("devenv up", "start postgres + odoo + mailpit"),
    ("odoo db provision", "create DB + install modules.txt"),
    ("odoo db migrate", "upgrade all modules, with progress"),
    ("odoo module add", "pick + wire in more OCA modules"),
    ("odoo module add-bundle", "add a curated OCA module bundle"),
    ("odoo project update", "pull submodules + refresh deps"),
    ("odoo test <mod> [db]", "run a module's tests"),
    ("odoo shell", "Odoo REPL"),
]


def main() -> None:
    project_name, series, addons_count, http_port, mailcatch_enabled, mailcatch_http_port = sys.argv[1:7]
    console = Console()

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column()
    for command, description in COMMANDS:
        # Table cells parse rich markup by default, and "[db]"/"[module2]"
        # style bracketed placeholders in these command strings look exactly
        # like markup tags ("[db]...[/db]") -- escape() keeps them literal.
        table.add_row(escape(command), escape(description))

    console.print(
        Panel(
            table,
            title=escape(f"{project_name} — Odoo {series} (OCB + OCA) dev environment"),
            title_align="left",
            border_style="cyan",
        )
    )
    console.print(f"  Odoo server: http://127.0.0.1:{http_port}")
    console.print(f"  addons_path entries: {addons_count}")
    if mailcatch_enabled == "1":
        console.print(f"  mail: ALL outgoing email → Mailpit (http://127.0.0.1:{mailcatch_http_port})")
    console.print()


if __name__ == "__main__":
    main()
