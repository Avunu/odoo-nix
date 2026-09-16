from unittest.mock import patch

from odoo.tests import TransactionCase

# Loaded server-wide (server_wide_modules in the fixture odoo.conf) from
# odoo-nix's addons/ store path, so it is importable without being installed.
from odoo.addons.dev_mailcatch import patch as mailcatch


class TestOrm(TransactionCase):
    """The assembled Odoo + PostgreSQL round-trip a record."""

    def test_partner_roundtrip(self):
        partner = self.env["res.partner"].create({"name": "odoo-nix fixture"})
        self.assertTrue(partner.id)
        self.assertEqual(
            self.env["res.partner"].search([("name", "=", "odoo-nix fixture")]),
            partner,
        )


class TestMailcatch(TransactionCase):
    """dev_mailcatch redirected ir.mail_server, configured from odoo.conf.

    No SMTP sink: Odoo's own test mode makes core's connect() return None
    before touching the network, so the observable contract is what the patch
    hands core -- captured by mocking the saved original.
    """

    def test_patch_installed(self):
        cls = mailcatch.IrMailServer
        self.assertTrue(getattr(cls, mailcatch._PATCHED_FLAG, False))
        self.assertIs(getattr(cls, mailcatch._CONNECT), mailcatch._connect)
        self.assertIs(cls._find_mail_server, mailcatch._find_mail_server)
        self.assertIs(cls.send_email, mailcatch._send_email)

    def test_settings_come_from_odoo_conf(self):
        # [dev_mailcatch] port in the fixture conf is 2525, not the 1025 default
        self.assertEqual(mailcatch._settings(), (True, "127.0.0.1", 2525))

    def test_find_mail_server_ignores_records(self):
        self.env["ir.mail_server"].create(
            {"name": "real smtp", "smtp_host": "smtp.example.com", "smtp_port": 25}
        )
        server, email_from = self.env["ir.mail_server"]._find_mail_server(
            "someone@example.com"
        )
        self.assertIsNone(server)
        self.assertEqual(email_from, "someone@example.com")

    def test_connect_dials_the_catcher(self):
        with patch.object(mailcatch, "_orig_connect", return_value=None) as orig:
            getattr(self.env["ir.mail_server"], mailcatch._CONNECT)(
                host="smtp.example.com",
                port=25,
                user="someone",
                password="secret",
                encryption="starttls",
            )
        orig.assert_called_once()
        kwargs = orig.call_args.kwargs
        self.assertEqual((kwargs["host"], kwargs["port"]), ("127.0.0.1", 2525))
        self.assertEqual(kwargs["encryption"], "none")
        self.assertFalse(kwargs["user"])
        self.assertFalse(kwargs["password"])
        self.assertIsNone(kwargs["mail_server_id"])
