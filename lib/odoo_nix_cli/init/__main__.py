"""``python -I -m odoo_nix_cli.init``: how lib/init.nix runs odoo-init."""

from odoo_nix_cli.init.command import entry

entry()
