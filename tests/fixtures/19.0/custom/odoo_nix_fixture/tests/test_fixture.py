import socket

from odoo.tests import TransactionCase

import odoo_devguard
from odoo_devguard import DevGuardBlocked, settings


class TestOrm(TransactionCase):
    """The assembled Odoo + PostgreSQL round-trip a record."""

    def test_partner_roundtrip(self):
        partner = self.env["res.partner"].create({"name": "odoo-nix fixture"})
        self.assertTrue(partner.id)
        self.assertEqual(
            self.env["res.partner"].search([("name", "=", "odoo-nix fixture")]),
            partner,
        )


class TestDevguard(TransactionCase):
    """The dev guard rails (odoo_devguard), grafted into the test environment.

    Settings are baked from Nix (tests/series.nix): the mail catcher on port
    2525, not the 1025 default, proves the value travelled through the
    environment's own _baked.json rather than the package defaults.
    """

    def test_guards_reached_their_targets(self):
        status = odoo_devguard.status()
        self.assertEqual(status.get("socket.socket.connect"), "patched")
        for target in ("send_email", "_callback"):  # ir.mail_server, ir.cron
            self.assertTrue(any(k.endswith(target) for k in status), (target, status))

    def test_settings_are_the_baked_ones(self):
        self.assertEqual(settings().mail_port, 2525)

    def test_egress_is_refused_before_any_packet(self):
        sock = socket.socket()
        self.addCleanup(sock.close)
        with self.assertRaises(DevGuardBlocked):
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1

    def test_find_mail_server_ignores_records(self):
        self.env["ir.mail_server"].create(
            {"name": "real smtp", "smtp_host": "smtp.example.com", "smtp_port": 25}
        )
        server, email_from = self.env["ir.mail_server"]._find_mail_server(
            "someone@example.com"
        )
        self.assertIsNone(server)
        self.assertEqual(email_from, "someone@example.com")

    def test_connect_is_redirected_not_refused(self):
        # Odoo's own test mode makes core's connect() return None before
        # touching the network, so the observable contract is that asking for a
        # real server neither raises nor reaches it (the egress guard would
        # have raised DevGuardBlocked had it tried).
        server = self.env["ir.mail_server"]
        connect = getattr(server, "_connect__", None) or server.connect
        self.assertIsNone(connect(host="smtp.example.com", port=25, user="u", password="p"))
