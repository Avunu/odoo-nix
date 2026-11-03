# Copyright 2026 Fixture LLC
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Fixture B",
    "summary": "A stand-in addon for odoo-nix's standards fixtures",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "author": "Fixture LLC",
    "website": "https://github.com/fixture/fixture-addons",
    "license": "AGPL-3",
    "depends": ["base"],
    "assets": {
        "web.assets_backend": ["fixture_b/static/src/js/fixture_b.js"],
    },
    "installable": True,
}
