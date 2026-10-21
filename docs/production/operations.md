---
title: Operate a deployment
description: How services.odoo-nix migrates the schema on every deploy, what happens when a migration fails, how a first database is provisioned, and the day-to-day commands on a server.
order: 2
tags: [operations, migrate, deploy, backup]
updated: 2026-10-21
---

## Migrations on deploy

The schema follows the code by itself. `odoo-migrate.service` runs

```text
odoo db migrate <dbName> --if-needed --snapshot dump --keep <snapshotRetention> --rollback
```

before every start of `odoo.service` (`--all` when no `dbName` is pinned). It is a oneshot without `RemainAfterExit`, and `odoo.service` both requires it and is ordered after it. So:

- **A deploy** (switch-to-configuration stops `odoo.service` when its unit changes and starts it again) updates exactly the modules whose code or version changed, with Odoo stopped: no worker, cron or `queue_job` runner touches the database mid-update.
- **A restart of the same build**, a reboot, `systemctl restart odoo` or a crash, costs one query.
- **A restored dump** carries another build's marker, or none, so the next start migrates it: no manual `-u` after a restore.
- **A failed migration** is rolled back to its snapshot and `odoo.service` does not start. New code on a schema it was not migrated to fails in ways nothing reports (`queue_job`'s runner quietly pauses itself with `database schema is outdated, -u queue_job required` while every job sits in `pending`), so Odoo stays down and the failure is the unit's, where monitoring sees it. Recover with a fixed deploy or by rolling back the system generation.

How `odoo db migrate` decides and what the snapshot is: see [Migrations](../development/migrations.md).

The options:

| Option | Default | Effect |
| --- | --- | --- |
| `migrate.enable` | `true` | Run `odoo-migrate`. `false` restores the old behaviour: `autoInit`'s `-i base` and `update`'s `odoo db upgrade` in `ExecStartPre`, with no change detection and no snapshot. |
| `migrate.snapshot` | `true` | Take a verified `dump` snapshot first; `false` passes `--snapshot none`. |
| `migrate.rollbackOnFailure` | `true` | Restore the snapshot when the migration fails. |
| `migrate.snapshotRetention` | `3` | How many snapshots to keep per database, in `<data_dir>/backups/<DB>/premigrate/`. |
| `migrate.full` | `false` | Update every installed module (`-u all`) on each new build. |
| `migrate.timeout` | `"infinity"` | `TimeoutStartSec` of `odoo-migrate`. |
| `update` | `[ ]` | Modules to update on every deploy even when unchanged (`--also`). Needs a pinned `dbName`. |

The first start on a database with no stored checksums updates every module once to establish the baseline. On a large database that takes minutes, hence no timeout by default: killing a migration part-way leaves a half-updated schema for the rollback to undo.

## The first database

`autoInit = true` provisions an empty `dbName` on its first start: `base` and the modules listed in `<stateDir>/modules.txt` (`--provision-if-empty`). Without it, an empty database is skipped and Odoo starts anyway, so a dump can be restored into it. It needs a pinned `dbName`.

## Day to day

From a root shell, the operator's `odoo` command runs as the service user with the service's tools and environment (see [The operator's odoo command](nixos-service.md#the-operators-odoo-command)):

```bash
odoo db backup acme                  # <stateDir>/data/backups/acme/<TIMESTAMP>.dump.zip
odoo project backup --format dump    # every database matching dbFilter
odoo db restore acme /path/to/backup.dump.zip
odoo db migrate acme
odoo shell acme
```

A restore on a server is not neutralized unless you pass `--neutralize`. Fetching the newest backup from the S3 store (`odoo db restore` with no file) is a dev-shell feature: the server's package carries no minio client, so download the backup and restore the file.

For scheduled backups to object storage, use OCA's `auto_backup` with the FS Storage bridge described in [Restore a production backup](../development/restore-from-production.md#2-the-server-side).
