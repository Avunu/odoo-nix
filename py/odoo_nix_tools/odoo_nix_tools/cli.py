"""``odoo-nix``: the core's commands with odoo-nix's product (DESIGN.md §1.1)."""

from __future__ import annotations

from collections.abc import Sequence

from odoo_nix_tools.cabundle import ensure_ca_bundle


def main(argv: Sequence[str] | None = None) -> int:
    # Before the imports: standards_core builds its HTTPS opener, and with it the SSL
    # context that reads SSL_CERT_FILE, when it's imported.
    ensure_ca_bundle()

    from standards_core import cli

    from odoo_nix_tools.commands import EXTRA
    from odoo_nix_tools.product import PRODUCT

    return cli.main(PRODUCT, argv, extra_commands=EXTRA)
