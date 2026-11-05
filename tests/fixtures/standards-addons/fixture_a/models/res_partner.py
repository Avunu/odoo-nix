from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    fixture_a_code = fields.Char()
