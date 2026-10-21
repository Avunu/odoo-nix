{
    "name": "odoo-nix test fixture",
    "summary": "Smoke-test addon for odoo-nix's own checks (tests/fixtures)",
    # No series prefix on purpose: odoo.modules.module.adapt_version prepends
    # it, so the same addon serves every fixture series.
    "version": "1.0.0",
    "category": "Hidden",
    "author": "odoo-nix",
    "license": "LGPL-3",
    "depends": ["base"],
    "installable": True,
    "auto_install": False,
}
