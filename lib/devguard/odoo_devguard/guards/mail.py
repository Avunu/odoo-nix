"""Mail guard, Odoo layer: ir.mail_server.

Ported from odoo-nix's former ``dev_mailcatch`` server-wide addon, which this
replaces. The transport layer (``mail_stdlib``) already sends every smtplib
connection to the catcher; this layer exists for fidelity -- so Odoo itself
believes it is talking to the catcher and does not rewrite the From header,
encapsulate it with a server's from-filter, or pick a server by record.

Why not just ``smtp_server`` in odoo.conf: core only falls back to it when
``_find_mail_server()`` turns up no ``ir.mail_server`` record. Any row in that
table -- or a ``mail.mail`` carrying an explicit ``mail_server_id``, which skips
``_find_mail_server`` entirely -- would win and send for real. Forcing both
methods is what makes this a true catch-all.

Why a third patch on ``send_email``: API-based transports (mail_cloudflare posts
to Cloudflare's Email Sending REST API) override ``connect()`` to hand back a
session that is not SMTP at all. Their override sits above the patched
``connect`` in the MRO, so for their servers it never runs. ``send_email`` is the
chokepoint every sender passes through: a non-SMTP session shows up there, is
discarded, and core is made to connect again -- through the patched ``connect``,
hence to the catcher. (``egress`` would stop the REST call regardless; this makes
the mail arrive in the catcher instead of failing.)
"""

import functools
import inspect
import logging
import smtplib

from .._hook import on_import
from .._patch import require, require_any
from .._settings import settings
from .mail_stdlib import announce_mail

NAME = "mail"

_logger = logging.getLogger(__name__)

_INSTALLED = False
_PATCHED_FLAG = "_odoo_devguard_patched"


def enabled():
    return settings().guard_enabled(NAME)


def _patch(module):
    # Odoo 19 renamed both the model class (IrMailServer -> IrMail_Server, the new
    # model-class naming convention) and the connect method (connect ->
    # _connect__). The parameter lists are identical, so resolving the two names
    # at patch time spans 18.0 and 19.0.
    _cls_name, cls = require_any(module, "IrMail_Server", "IrMailServer")
    if getattr(cls, _PATCHED_FLAG, False):
        return
    connect_name, orig_connect = require_any(cls, "_connect__", "connect")
    orig_find = require(cls, "_find_mail_server")
    orig_send = require(cls, "send_email")

    # 17.0+ wraps smtplib in `SMTPConnection`; anything else passed as
    # `smtp_session` is an API transport.
    session_types = (smtplib.SMTP,) + tuple(
        c for c in (getattr(module, "SMTPConnection", None),) if c
    )

    @functools.wraps(orig_connect)
    def connect(
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
        if not enabled():
            return orig_connect(
                self, host, port, user, password, encryption, smtp_from,
                ssl_certificate, ssl_private_key, smtp_debug, mail_server_id,
                allow_archived,
            )
        st = settings()
        announce_mail()
        # Everything that could route elsewhere or fail against a plain local
        # catcher is neutralised: no server record, no auth, no TLS. Delegating
        # to core (rather than building an SMTPConnection here) keeps the
        # test-mode short-circuit -- core returns None while a test is running.
        connection = orig_connect(
            self,
            host=st.mail_host,
            port=st.mail_port,
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
            # A falsy from_filter matches every sender, which stops
            # `_prepare_email_message` from encapsulating the From header -- the
            # catcher then shows the address the code actually meant to send as.
            connection.from_filter = False
        return connection

    @functools.wraps(orig_find)
    def find_mail_server(self, email_from, mail_servers=None):
        if not enabled():
            return orig_find(self, email_from, mail_servers)
        # A None server is core's documented "use the odoo-bin SMTP arguments"
        # signal. Returning email_from untouched also skips core's fallback of
        # rewriting the sender to the notifications address.
        return None, email_from

    @functools.wraps(orig_send)
    def send_email(self, *args, **kwargs):
        if not enabled():
            return orig_send(self, *args, **kwargs)
        # Bind against the real signature rather than assuming positions:
        # callers mix positional and keyword arguments.
        bound = inspect.signature(orig_send).bind(self, *args, **kwargs)
        bound.apply_defaults()
        session = bound.arguments.get("smtp_session")
        if session is not None and not isinstance(session, session_types):
            _logger.debug(
                "odoo_devguard: discarding non-SMTP session %s (mail_server_id=%s), "
                "reconnecting to the catcher",
                type(session).__name__, bound.arguments.get("mail_server_id"),
            )
            bound.arguments["smtp_session"] = None
            bound.arguments["mail_server_id"] = None
        return orig_send(*bound.args, **bound.kwargs)

    setattr(cls, connect_name, connect)
    cls._find_mail_server = find_mail_server
    # functools.wraps copies __dict__, so the `@api.model` marker survives.
    cls.send_email = send_email
    setattr(cls, _PATCHED_FLAG, True)
    announce_mail()


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    on_import("odoo.addons.base.models.ir_mail_server", _patch)
