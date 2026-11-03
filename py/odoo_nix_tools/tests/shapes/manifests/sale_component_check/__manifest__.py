{
    "name": "Quotation Component Check",
    "summary": "See whether a warehouse has the components for a quotation, and for all open bids",
    "description": """
Adds a **Component Check** tab to quotations, so a salesperson can see, from
anywhere, whether the quotation's warehouse has what it takes to fill it.

* Each product with a bill of materials is broken down into the components a
  manufacturing order at that warehouse would consume, planned waste included.
  The warehouse's own recipe is used where it has one.
* Products without a bill of materials count as themselves.
* For each component: quantity needed, free to use at the warehouse (on hand
  minus what is reserved), the shortfall, the forecast, and the vendor lead time
  of anything short.
* With several warehouses, the tab compares them: distance to the delivery
  address, components short and the cost of buying them. One click switches the
  quotation's warehouse, with a confirmation when the warehouse is farther from
  the job than another. Addresses are located through the geolocation provider
  set in Settings (OpenStreetMap by default).
* The check follows the quotation as it is edited, before it is saved: change a
  quantity or the warehouse and it recalculates. Nothing is reserved or ordered.

Sales > Orders > Component Demand adds up what all open quotations need, per
warehouse and component, against what is free to use there, with the bids
behind each figure.
""",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Walnook LLC",
    "license": "LGPL-3",
    "depends": ["sale_mrp", "mrp_bom_planned_waste", "base_geolocalize"],
    "data": [
        "security/ir.model.access.csv",
        "views/sale_component_check_templates.xml",
        "views/sale_order_views.xml",
        "views/sale_component_demand_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sale_component_check/static/src/components/**/*",
        ],
        "web.assets_tests": [
            "sale_component_check/static/tests/tours/*.js",
        ],
    },
    "installable": True,
}
