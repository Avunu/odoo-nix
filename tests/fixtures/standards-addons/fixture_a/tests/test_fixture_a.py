from odoo.tests.common import TransactionCase


class TestFixtureA(TransactionCase):
    def test_code(self):
        partner = self.env["res.partner"].create({"name": "A", "fixture_a_code": "x"})
        self.assertEqual(partner.fixture_a_code, "x")
