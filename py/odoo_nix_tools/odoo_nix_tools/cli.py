"""``odoo-nix``: the core's commands with odoo-nix's product (DESIGN.md §1.1)."""

from __future__ import annotations

from collections.abc import Sequence

from standards_core import cli

from odoo_nix_tools.cabundle import ensure_ca_bundle
from odoo_nix_tools.commands import EXTRA
from odoo_nix_tools.product import PRODUCT


def main(argv: Sequence[str] | None = None) -> int:
    ensure_ca_bundle()
    return cli.main(PRODUCT, argv, extra_commands=EXTRA)
