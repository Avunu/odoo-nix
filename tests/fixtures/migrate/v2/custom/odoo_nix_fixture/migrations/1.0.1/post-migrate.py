from odoo import api


def migrate(cr, version):
    """Record that the 1.0.1 migration ran (and from which version), and
    write a filestore attachment, as a migration that loads data files with
    images or regenerates assets does: module-odoo checks that nginx can
    still send it under nginx.xSendfile."""
    cr.execute(
        """
        INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date)
        VALUES ('odoo_nix_fixture.migrated_to', '1.0.1', 1, 1, now(), now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """
    )
    env = api.Environment(cr, 1, {})
    env["ir.attachment"].create(
        {
            "name": "odoo_nix_fixture_migrated.txt",
            "raw": b"written during migrate",
            "public": True,
        }
    )
