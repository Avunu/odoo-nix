def migrate(cr, version):
    """Record that the 1.0.1 migration ran (and from which version)."""
    cr.execute(
        """
        INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date)
        VALUES ('odoo_nix_fixture.migrated_to', '1.0.1', 1, 1, now(), now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """
    )
