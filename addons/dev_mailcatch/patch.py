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
#
# Why a third patch on `send_email`: API-based transports (e.g. mail_cloudflare,
# which posts to Cloudflare's Email Sending REST API) override `connect()` to
# hand back a session object that is not an SMTP connection at all. Their
# override sits above this patched `connect` in the MRO, so for their servers it
# never runs and the mail would go out for real. `send_email` is the one chokepoint
# every sender passes through, so when a non-SMTP session shows up there it is
# discarded and core is made to connect again — through the patched `connect`,
# hence to the catcher.

import configparser
import functools
import inspect
import logging
import os
import smtplib

from odoo.addons.base.models import ir_mail_server as _ir_mail_server
from odoo.tools import config

_logger = logging.getLogger(__name__)

SECTION = "dev_mailcatch"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 1025

_PATCHED_FLAG = "_dev_mailcatch_patched"

# Odoo 19 renamed both the model class (IrMailServer -> IrMail_Server, the new
# model-class naming convention) and the connect method (connect ->
# _connect__). The parameter lists are identical, so resolving the two names at
# import time is all that is needed to span 16.0 through 19.0 -- and it must be
# resolved, not assumed: this module is loaded from `post_load` at server
# start, so an ImportError here takes the whole server down.
IrMailServer = getattr(_ir_mail_server, "IrMail_Server", None) or _ir_mail_server.IrMailServer
_CONNECT = "_connect__" if hasattr(IrMailServer, "_connect__") else "connect"

# Captured before patching so the wrappers can delegate (and so a disabled
# catcher behaves exactly like stock Odoo).
_orig_connect = getattr(IrMailServer, _CONNECT)
_orig_find_mail_server = IrMailServer._find_mail_server
_orig_send_email = IrMailServer.send_email

# 17.0+ wraps smtplib in `SMTPConnection`; 16.0 hands out `smtplib.SMTP`
# directly. Anything else passed as `smtp_session` is an API transport.
_SMTP_SESSION_TYPES = (smtplib.SMTP,) + tuple(
    cls for cls in (getattr(_ir_mail_server, "SMTPConnection", None),) if cls
)


def _as_bool(value, default=True):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _section():
    """The ``[dev_mailcatch]`` section of the loaded odoo.conf, as a dict.

    Through 18.0 Odoo's config loader keeps every unknown section verbatim in
    ``config.misc``, so the section needs no registration. 19.0 dropped
    ``misc`` and only parses ``[options]``, so there the file Odoo loaded
    (``config['config']``, the ``-c`` path) is read again with a plain
    configparser -- the same file, the same parser class Odoo uses.
    """
    misc = getattr(config, "misc", None)
    if misc is not None:
        return misc.get(SECTION) or {}
    rcfile = config.get("config")
    if not rcfile or not os.path.isfile(rcfile):
        return {}
    parser = configparser.RawConfigParser()
    parser.read([rcfile])
    return dict(parser.items(SECTION)) if parser.has_section(SECTION) else {}


def _settings():
    """Resolve the catcher target: odoo.conf ``[dev_mailcatch]``, env wins.

    :return: ``(enabled, host, port)``
    """
    section = _section()

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


@functools.wraps(_orig_send_email)
def _send_email(self, *args, **kwargs):
    enabled, _host, _port = _settings()
    if not enabled:
        return _orig_send_email(self, *args, **kwargs)

    # Bind against the real signature rather than assuming positions: callers
    # mix positional and keyword arguments (mail.mail passes `mail_server_id`
    # and `smtp_session` as keywords; direct callers may not).
    bound = inspect.signature(_orig_send_email).bind(self, *args, **kwargs)
    bound.apply_defaults()
    session = bound.arguments.get("smtp_session")
    if session is not None and not isinstance(session, _SMTP_SESSION_TYPES):
        _logger.debug(
            "dev_mailcatch: discarding non-SMTP session %s (mail_server_id=%s), "
            "reconnecting to the catcher",
            type(session).__name__, bound.arguments.get("mail_server_id"),
        )
        # With no session core calls `connect()`; with no `mail_server_id`
        # (and no host) that goes through the patched `_find_mail_server`,
        # which returns no server, so the transport's own `connect` override
        # has nothing to claim and delegates to the patched `connect` here.
        # Core quits the connection it opened itself once the mail is sent.
        bound.arguments["smtp_session"] = None
        bound.arguments["mail_server_id"] = None

    return _orig_send_email(*bound.args, **bound.kwargs)


def install():
    """Apply the patches. Idempotent."""
    if getattr(IrMailServer, _PATCHED_FLAG, False):
        return

    setattr(IrMailServer, _CONNECT, _connect)
    IrMailServer._find_mail_server = _find_mail_server
    # functools.wraps copies __dict__, so the `@api.model` marker survives.
    IrMailServer.send_email = _send_email
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
