# Catch-all outgoing-mail redirection, applied as an import-time monkeypatch.
#
# Why a patch and not a model override: an `_inherit` override only takes effect
# in databases where this module is installed, whereas a dev catcher must cover
# every database on the server — including ones created after the fact. The
# manifest's `post_load` hook runs once at server start, so patching the class
# object here covers every registry built afterwards.
#
# Why two patches and not just `smtp_server` in odoo.conf: core only falls back
# to the odoo.conf/CLI SMTP settings when `_find_mail_server()` turns up no
# `ir.mail_server` record. Any row in that table — or a `mail.mail` carrying an
# explicit `mail_server_id`, which skips `_find_mail_server` entirely — would win
# and send for real. Forcing both methods is what makes this a true catch-all.

import functools
import logging
import os

from odoo.addons.base.models.ir_mail_server import IrMailServer
from odoo.tools import config

_logger = logging.getLogger(__name__)

SECTION = "dev_mailcatch"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1025

_PATCHED_FLAG = "_dev_mailcatch_patched"

# Captured before patching so the wrappers can delegate (and so a disabled
# catcher behaves exactly like stock Odoo).
_orig_connect = IrMailServer.connect
_orig_find_mail_server = IrMailServer._find_mail_server


def _as_bool(value, default=True):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _settings():
    """Resolve the catcher target: odoo.conf ``[dev_mailcatch]``, env wins.

    Odoo's INI parser keeps unknown sections verbatim in ``config.misc``, so the
    section needs no registration.

    :return: ``(enabled, host, port)``
    """
    section = config.misc.get(SECTION) or {}

    enabled = _as_bool(os.environ.get("ODOO_MAILCATCH_ENABLED", section.get("enabled")))
    host = os.environ.get("ODOO_MAILCATCH_HOST") or section.get("host") or DEFAULT_HOST

    raw_port = os.environ.get("ODOO_MAILCATCH_PORT") or section.get("port") or DEFAULT_PORT
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        _logger.warning(
            "dev_mailcatch: invalid port %r, falling back to %s", raw_port, DEFAULT_PORT
        )
        port = DEFAULT_PORT

    return enabled, host, port


@functools.wraps(_orig_connect)
def _connect(
    self,
    host=None,
    port=None,
    user=None,
    password=None,
    encryption=None,
    smtp_from=None,
    ssl_certificate=None,
    ssl_private_key=None,
    smtp_debug=False,
    mail_server_id=None,
    allow_archived=False,
):
    enabled, catch_host, catch_port = _settings()
    if not enabled:
        return _orig_connect(
            self, host, port, user, password, encryption, smtp_from,
            ssl_certificate, ssl_private_key, smtp_debug, mail_server_id,
            allow_archived,
        )

    if mail_server_id or host:
        _logger.debug(
            "dev_mailcatch: ignoring requested SMTP target (mail_server_id=%s, host=%s), "
            "redirecting to %s:%s",
            mail_server_id, host, catch_host, catch_port,
        )

    # Everything that could route elsewhere or fail against a plain local
    # catcher is neutralised: no server record, no auth, no TLS. Delegating to
    # core (rather than building an SMTPConnection here) keeps the test-mode
    # short-circuit — core returns None while a test is running.
    connection = _orig_connect(
        self,
        host=catch_host,
        port=catch_port,
        user=False,
        password=False,
        encryption="none",
        smtp_from=smtp_from,
        ssl_certificate=False,
        ssl_private_key=False,
        smtp_debug=smtp_debug,
        mail_server_id=None,
        allow_archived=allow_archived,
    )

    if connection is not None:
        # A falsy from_filter matches every sender (`_match_from_filter`), which
        # stops `_prepare_email_message` from encapsulating the From header —
        # the catcher then shows the address the code actually meant to send as.
        connection.from_filter = False

    return connection


@functools.wraps(_orig_find_mail_server)
def _find_mail_server(self, email_from, mail_servers=None):
    enabled, _host, _port = _settings()
    if not enabled:
        return _orig_find_mail_server(self, email_from, mail_servers)

    # A None server is core's documented "use the odoo-bin SMTP arguments"
    # signal. Returning email_from untouched also skips core's fallback of
    # rewriting the sender to the notifications address.
    return None, email_from


def install():
    """Apply the patches. Idempotent."""
    if getattr(IrMailServer, _PATCHED_FLAG, False):
        return

    IrMailServer.connect = _connect
    IrMailServer._find_mail_server = _find_mail_server
    setattr(IrMailServer, _PATCHED_FLAG, True)

    enabled, host, port = _settings()
    if not enabled:
        _logger.info(
            "dev_mailcatch loaded but disabled — outgoing email is sent normally."
        )
        return

    _logger.warning(
        "dev_mailcatch ACTIVE — ALL outgoing email is redirected to %s:%s. "
        "No mail will reach real recipients.", host, port,
    )

    # These leak through the delegation above (core ORs the argument with the
    # config value), and would make the catcher connection try to authenticate
    # or negotiate TLS. odoo-nix never sets them; warn if something else did.
    leaked = [
        key for key in ("smtp_user", "smtp_ssl_certificate_filename")
        if config.get(key)
    ]
    if leaked:
        _logger.warning(
            "dev_mailcatch: odoo.conf sets %s — these still apply to the catcher "
            "connection and may break it. Unset them for local development.",
            ", ".join(leaked),
        )
