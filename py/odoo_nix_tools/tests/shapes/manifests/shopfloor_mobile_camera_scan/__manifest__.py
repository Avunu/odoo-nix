# Copyright 2026 Avunu LLC (avu.nu)
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl.html).
{
    "name": "Shopfloor Mobile Camera Scanning",
    "summary": "Add device-camera barcode scanning to the Shopfloor mobile app. "
    "Every scenario's search bar gains a camera button — scans feed the "
    "exact same flow as a hardware wedge scanner.",
    "version": "18.0.1.0.0",
    "category": "Warehouse Management",
    "author": "Avunu LLC",
    "website": "https://avu.nu",
    "license": "LGPL-3",
    "installable": True,
    # Frontend-only augmentation of the Shopfloor mobile PWA.
    "depends": ["shopfloor_mobile_base"],
    "data": [
        "templates/assets.xml",
    ],
}
