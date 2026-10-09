{
    "name": "Dev Mail Catch-All (deprecated)",
    "summary": "Deprecated stub: the mail catch-all is odoo-nix's devguard now.",
    "description": """
Deprecated. Outgoing-mail redirection moved into odoo-nix's dev guard rails
(``odoo_devguard``, installed into the dev virtualenv; see the README's "Dev
guard-rails"), configured with ``odoo-nix.devguard.mail.*`` and overridable with
``ODOO_DEVGUARD_MAIL_HOST`` / ``ODOO_DEVGUARD_MAIL_PORT``.

This module remains for one release as a no-op that logs a warning, so a
``server_wide_modules`` line naming it does not stop the server from starting.
Remove it from ``server_wide_modules``.
""",
    "version": "2.0.0",
    "category": "Technical",
    "author": "odoo-nix",
    "license": "LGPL-3",
    "depends": ["base"],
    "post_load": "post_load",
    "installable": True,
    "auto_install": False,
}
