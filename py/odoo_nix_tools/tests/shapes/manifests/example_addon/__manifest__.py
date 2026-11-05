{
    "name": "Example Addon",
    "summary": "A representative project addon: no website, a long description",
    "description": """
Adds an **Example** tab to sales orders, so a salesperson can see a summary of
the order's lines from one place.

* Each line is listed with its product, quantity and unit price.
* Lines without a product are skipped.
* For each product: quantity ordered, quantity delivered, and what is left to
  deliver.
* The tab follows the order as it is edited, before it is saved: change a
  quantity and it recalculates. Nothing is reserved or ordered.

Sales > Orders > Example Summary adds up the open orders' lines, per product,
with the orders behind each figure.
""",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Example Author",
    "license": "LGPL-3",
    "depends": ["sale_mrp", "base_geolocalize"],
    "data": [
        "security/ir.model.access.csv",
        "views/example_addon_templates.xml",
        "views/sale_order_views.xml",
        "views/example_summary_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "example_addon/static/src/components/**/*",
        ],
        "web.assets_tests": [
            "example_addon/static/tests/tours/*.js",
        ],
    },
    "installable": True,
}
