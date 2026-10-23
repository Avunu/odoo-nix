---
title: Restore a production backup
description: Clone a production database into the dev shell with odoo db restore, fetching the newest backup from S3-compatible storage, and set up the server side that writes those backups.
order: 6
tags: [restore, backup, s3]
updated: 2026-10-23
---

Production pushes database backups to S3-compatible storage. Any developer whose SSH key is a declared recipient restores one locally with one command:

```bash
odoo project restore                                  # the project database (dbName), newest backup
odoo db restore acme_dev --from acme --at 2026-10-01  # another name, a point in time
odoo db restore acme_dev --from acme --list           # what is there
```

Backups live at `s3://$BACKUPS_BUCKET/$BACKUPS_PREFIX/<DATABASE>/<YYYY_MM_DD_HH_MM_SS>.dump[.zip]`, the `auto_backup` naming that `odoo db backup` also uses.

## 1. The credentials

Declare the recipients (see [Secrets](secrets.md)), then run `setup-backup-access` in the dev shell. It prompts for the values, tests them against the bucket and writes `secrets/backup-access.age`. Commit it.

## 2. The server side

Install OCA's `auto_backup` and `fs_storage` modules and [`auto_backup_fs_storage`](https://github.com/Avunu/avunu-odoo-addons), a thin bridge that adds an FS Storage method to `auto_backup`, and give the server the same ciphertext:

```nix
age.secrets.odoo-backup.file = inputs.myproject.lib.secrets.files.odoo_backup_access;
services.odoo-nix.environmentFiles = [ config.age.secrets.odoo-backup.path ];
```

Installing the bridge module creates an `odoo_backup` `fs.storage` whose options are `$BACKUPS_*` references, resolved from the process environment by `fs_storage`'s `eval_options_from_env`, so no credentials are stored in the database. It also creates a daily `dump`-format job with 30-day retention.

To give the server its own write-capable key and keep developers read-only, set `odoo-nix.secrets.backupAccess.hosts = false` and declare the server's file under `odoo-nix.secrets.extra`.

## 3. Restoring

`odoo db restore <DB>` with no file:

1. lists `<prefix>/<source>/`, where the source is `--from`, else `restore.sourceDatabase`, else `<DB>`, and the prefix is `BACKUPS_PREFIX`, else `restore.prefix`;
2. takes the newest backup, or the newest within `--at`, which takes ISO 8601 (`2026-10-02`, `2026-10-02T03:00`), a backup's own name (`2026_10_02_03_00_00`) or any leading part of either;
3. downloads it to `.devenv/state/odoo-nix/restore/`, size-checked, keeping the one just fetched and one other (`--no-cache` downloads again);
4. restores it **neutralized**, so no outgoing mail and crons off (`--no-neutralize`, `restore.neutralize`);
5. replaces an existing database (`--no-force` refuses instead);
6. migrates it to the checkout's modules (`--no-migrate`, `restore.migrate`). No snapshot is taken first: the backup just restored is one.

Restoring a file you were handed works the same way: `odoo db restore <DB> <FILE>`. In the dev shell it is neutralized and its storages localized like a remote restore. `odoo project restore --restore <DB> <FILE> …` restores several pairs in one batch.

Restoring refuses to run while the guard rails are off; see [Development guard rails](guard-rails.md#restores-need-the-guard).

## Attachments in object storage

If production runs `fs_attachment` with an S3 storage, the dump holds only `<storage>://<path>` pointers, and a restored copy would otherwise carry production's bucket credentials and write new attachments into the production bucket. So after every restore in the dev shell, each non-local `fs.storage` row is rewritten to a local directory, `.devenv/state/odoo-nix/attachments/<CODE>`, with protocol `file`, its options cleared and `eval_options_from_env` off. The `odoo_backup` storage is left as it is.

With `restore.files = true`, or `--files`, the bucket's contents are mirrored there first, and repeat runs copy only what changed. That uses the backup-access credentials, which then need read access to the attachment bucket. Without it, attachments are simply missing locally. Restoring never writes to any bucket.

With attachments in object storage, `dump` is the complete backup format: the `zip` format's filestore would not contain them.

## For tests

`ODOO_NIX_BACKUP_SOURCE=<DIR>` points the restore at a directory laid out like the bucket instead of S3, and `ODOO_NIX_MC` names the minio-client binary. The listing, download and cache are python-devops-nix's backup fetch layer (`lib.backups`), with odoo-nix's layout in `lib/odoo_nix_cli/backup_layout.py`. `odoo-nix-backup-fetch {list,folders,fetch}` is the same layer as a command; `setup-backup-access` tests the credentials with it.
