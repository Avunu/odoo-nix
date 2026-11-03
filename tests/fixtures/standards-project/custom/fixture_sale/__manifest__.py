# Copyright 2026 Fixture LLC
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    "name": "Fixture Sale",
    "summary": "A stand-in addon for odoo-nix's standards fixtures",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "author": "Fixture LLC",
    "license": "LGPL-3",
    "depends": ["sale"],
    "data": ["views/sale_order_views.xml"],
    "assets": {
        "web.assets_backend": ["fixture_sale/static/src/js/fixture_sale.js"],
    },
    "installable": True,
}
