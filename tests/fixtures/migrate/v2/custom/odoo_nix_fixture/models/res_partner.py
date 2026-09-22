from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # A column that exists only once the module has been updated to 1.0.1:
    # loading the new code without `-u` leaves it missing from the table.
    odoo_nix_fixture_flag = fields.Boolean()
