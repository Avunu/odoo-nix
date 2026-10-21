---
title: Migrations
description: How odoo db migrate decides which modules to update, the snapshot and rollback around it, and the marker that makes a migrated build a one-query no-op.
order: 2
tags: [migrate, database, snapshot]
updated: 2026-10-21
---

Odoo only creates columns, reloads views and data and runs migration scripts for modules being installed or updated. Changed code without `-u` leaves the schema silently behind it. `odoo db migrate` updates what changed, not everything, and it is the same command in the dev shell, on a server and in a container.

```bash
odoo db migrate                 # the default database
odoo db migrate acme --rollback # roll back to the snapshot if it fails
odoo db migrate --all --full    # every database matching dbfilter, -u all
```

## What gets updated

Two signals put a module in the update set:

- **Its content checksum** differs from the one stored the last time a migration of this database succeeded.
- **Version drift**: `ir_module_module.latest_version` is behind the manifest on disk, as in a database restored from somewhere its modules were never updated.

The checksums use OCA [`module_auto_update`](https://github.com/OCA/server-tools/tree/18.0/module_auto_update)'s algorithm and storage (`module_auto_update.installed_checksums`, honouring `module_auto_update.exclude_patterns`), so that module, `click-odoo-update` and this command agree on what changed and can share a database. A database with no stored checksums is updated in full once, as a baseline; `odoo db provision` records the baseline for a fresh install. The plan is printed before anything runs:

```text
3 module(s) to update: queue_job (18.0.3.4.1 → 18.0.4.0.0), sale_x (code changed), …
```

`--full` updates every installed module instead, and `--also <M,…>` adds modules even when unchanged.

## The build marker

A build assembled in the Nix store also records which build migrated the database (`odoo_nix.migrated_build`). With `--if-needed`, a database that this build already migrated costs one query and nothing else. That is the path every start of `services.odoo-nix` takes. The marker lives in the database, not on disk, so restoring a dump from elsewhere is itself what triggers the next migration.

## The safety net

- **A lock.** An advisory lock, so a manual migration and a deploy cannot run at once.
- **A verified snapshot.** Before anything changes, the database is snapshotted and the snapshot verified readable (`pg_restore --list` for `dump`; every member's CRC and its `dump.sql` for `zip`). One that does not verify is removed and nothing is migrated. `--snapshot zip` (the default) includes the filestore, `dump` is the database alone, and `none` (or `--no-backup`) skips it.
- **Snapshot files.** They are written as `premigrate-<DB>-YYYYmmdd-HHMMSS.dump[.zip]` in `<data_dir>/backups/<DB>/premigrate/`, 0600 from the first byte in a 0700 directory. `--keep N` prunes only these, never a backup somebody took on purpose, and never after a failure.
- **Rollback.** `--rollback` drops the database, recreates it with the same encoding and collation, and loads the snapshot. The filestore is left alone: attachments are content-addressed and only ever added. That is also why rollback does not use Odoo's own `exp_drop` (it deletes the filestore) or `restore_db` (it loads the new code against the restored old schema).
- **An uninitialised database** is skipped with exit 0, or provisioned with `--provision-if-empty`.

The snapshot steps are python-devops-nix's migrate flow, the same one frappe-nix runs. Their messages are `odoo-migrate(<DB>): …` lines, at their syslog priority under systemd, so a failed migration is visible in `journalctl -p err`.

On a server, `odoo-migrate.service` runs this before every start of Odoo: see [Migrations on deploy](../production/operations.md#migrations-on-deploy).
