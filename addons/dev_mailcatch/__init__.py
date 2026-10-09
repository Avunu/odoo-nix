import logging

_logger = logging.getLogger(__name__)


def post_load():
    """Manifest ``post_load`` hook: a deprecation notice, nothing more.

    The mail catch-all is part of odoo-nix's dev guard rails now
    (``odoo_devguard``, grafted into the dev virtualenv), which covers every
    interpreter rather than just this server-wide module, and sends *all* mail
    -- SMTP, IMAP/POP3, API transports -- to Mailpit. This module stays for one
    release so a ``server_wide_modules`` line that still names it keeps loading
    instead of taking the server down at start.
    """
    _logger.warning(
        "dev_mailcatch is deprecated and does nothing: outgoing mail is redirected by "
        "odoo-nix's devguard (odoo-nix.devguard.mail). Remove 'dev_mailcatch' from "
        "server_wide_modules."
    )
