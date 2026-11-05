from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    fixture_note = fields.Char()
