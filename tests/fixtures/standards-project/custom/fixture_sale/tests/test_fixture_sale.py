from odoo.tests.common import TransactionCase


class TestFixtureSale(TransactionCase):
    def test_note(self):
        partner = self.env["res.partner"].create({"name": "Fixture"})
        order = self.env["sale.order"].create({"partner_id": partner.id})
        order.fixture_note = "x"
        self.assertEqual(order.fixture_note, "x")
