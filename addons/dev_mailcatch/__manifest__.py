{
    "name": "Dev Mail Catch-All",
    "summary": "Redirect every outgoing email to a local catcher (Mailpit). Dev only.",
    "description": """
Catch-all outgoing mail redirection for local development.

Loaded as a *server-wide* module (``server_wide_modules`` in odoo.conf), so the
redirection applies to every database on the server without installing anything
into any of them. The manifest's ``post_load`` hook patches
``ir.mail_server``'s connect and ``_find_mail_server`` methods so that SMTP
sessions always land on the configured catcher, no matter which
``ir.mail_server`` record (or explicit ``mail_server_id``) the caller picked.

Configure via odoo.conf::

    [options]
    server_wide_modules = base,web,dev_mailcatch

    [dev_mailcatch]
    enabled = True
    host = 127.0.0.1
    port = 1025

Environment overrides (win over odoo.conf): ``ODOO_MAILCATCH_ENABLED``,
``ODOO_MAILCATCH_HOST``, ``ODOO_MAILCATCH_PORT``.
""",
    "version": "1.0.0",
    "category": "Technical",
    "author": "odoo-nix",
    "license": "LGPL-3",
    "depends": ["base"],
    "post_load": "post_load",
    "installable": True,
    "auto_install": False,
}
