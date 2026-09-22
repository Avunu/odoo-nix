def migrate(cr, version):
    """Fail on purpose, AFTER committing a change.

    Odoo commits module by module, so a real failed migration leaves earlier
    work committed; a failure inside one transaction would roll itself back
    and prove nothing about the snapshot. The committed 'partial' value is
    what the rollback must make disappear."""
    cr.execute(
        "UPDATE ir_config_parameter SET value = 'partial' WHERE key = 'odoo_nix_fixture.migrated_to'"
    )
    cr.commit()
    raise RuntimeError("odoo-nix fixture: deliberate migration failure")
