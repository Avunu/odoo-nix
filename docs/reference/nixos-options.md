---
title: services.odoo-nix options
description: Every option of the odoo-nix NixOS module, with types and defaults.
order: 2
tags: [reference, options, nixos]
updated: 2026-10-21
---

See [Run Odoo as a NixOS service](../production/nixos-service.md) for how they fit together.

## The service

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enable` | bool | `false` | Run Odoo. |
| `package` | package | required | The project's `packages.default`, the `odoo` command. |
| `adminCli` | bool | `true` | Install the operator's `odoo` command. |
| `user`, `group` | string | `"odoo"` | The service's user and group. A user named `odoo` is created. |
| `stateDir` | path | `"/var/lib/odoo"` | The runtime `odoo.conf` and the filestore (`<stateDir>/data`). |
| `http.port` | port | `8069` | `http_port`. |
| `http.longpollingPort` | port | `8072` | `gevent_port`, the websocket process. |
| `http.interface` | string | `"127.0.0.1"` | `http_interface`. Keep loopback behind nginx. |
| `workers` | int | `2` | HTTP worker processes. 0 is the threaded server. |
| `maxCronThreads` | int | `2` | `max_cron_threads`. |
| `dbName` | null or string | `null` | Pin one database: sets `db_name` and `dbfilter = ^<NAME>$`. |
| `dbFilter` | string | `""` | An explicit `dbfilter` for several databases; wins over `dbName`'s. |
| `listDb` | bool | `false` | `list_db`: allow the database manager and listing. |
| `withoutDemo` | bool | `false` | `without_demo = True`. |
| `adminPasswordFile` | null or path | `null` | A file with `admin_passwd`, read through `LoadCredential`. |
| `settings` | attrs of string, int or bool | `{ }` | Any other `[options]` key. No secrets. |
| `extraEnv` | attrs of strings | `{ }` | More environment for the units and the operator's command. |
| `environmentFiles` | list of paths | `[ ]` | systemd `EnvironmentFile=`s for `odoo` and `odoo-migrate`, such as the backup credentials. |
| `hardening.enable` | bool | `false` | Run every unit under python-devops-nix's sandboxing baseline. On by default from 2.0.0. |

## Database

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `database.createLocally` | bool | `false` | Run PostgreSQL on the host; with no `passwordFile`, connect over the socket with peer authentication. |
| `database.host` | string | `"127.0.0.1"` | `db_host`, when not using the local socket. |
| `database.port` | port | `5432` | `db_port`, likewise. |
| `database.user` | string | `"odoo"` | `db_user`. Created with `CREATEDB` locally, and given ownership of `dbName`. |
| `database.passwordFile` | null or path | `null` | A file with `db_password`, read through `LoadCredential`. |
| `database.extensions` | function to list of packages | `_: [ ]` | Extensions built into the local server, e.g. `ps: [ ps.postgis ]`. |
| `database.ensureExtensions` | list of strings | `[ ]` | Extensions created in `dbName` as the superuser. Needs `createLocally` and `dbName`. |
| `database.slowQueryMs` | null or unsigned int | `null` | `log_min_duration_statement`. Was `logging.slowQueryMs`. Local server only. |

## Migrations and first start

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `migrate.enable` | bool | `true` | Run `odoo-migrate` before every start of Odoo. |
| `migrate.snapshot` | bool | `true` | Take a verified `pg_dump` snapshot first. |
| `migrate.rollbackOnFailure` | bool | `true` | Restore the snapshot when the migration fails. |
| `migrate.snapshotRetention` | positive int | `3` | Snapshots kept per database. |
| `migrate.full` | bool | `false` | Update every installed module on each new build. |
| `migrate.timeout` | string | `"infinity"` | `TimeoutStartSec` of `odoo-migrate`. |
| `update` | list of strings | `[ ]` | Modules to update on every deploy even when unchanged. Needs `dbName`. |
| `autoInit` | bool | `false` | Provision an empty `dbName` on first start: `base` and `<stateDir>/modules.txt`. Needs `dbName`. |

See [Migrations on deploy](../production/operations.md#migrations-on-deploy).

## nginx

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `nginx.enable` | bool | `false` | An nginx virtual host in front of Odoo, with `proxy_mode` on. |
| `nginx.domain` | string | `""` | The virtual host's server name. Required unless `socketPath` is set. |
| `nginx.clientMaxBodySize` | string | `"64m"` | `client_max_body_size`. |
| `nginx.socketPath` | string | `""` | Listen on this unix socket instead of TCP. Give it a directory of its own. |
| `nginx.xSendfile` | bool | `false` | Let nginx send filestore attachments (`x_sendfile`). |

## Logging

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `logging.level` | enum | `"info"` | `log_level`. |
| `logging.handlers` | list of `"logger:LEVEL"` | `[ ]` | `log_handler`. |
| `logging.db` | bool or string | `false` | `log_db`: `true` is the request's database (`%d`). |
| `logging.dbLevel` | enum | `"warning"` | `log_db_level`. |
| `logging.accessLog` | bool | `true` | nginx's JSON access log in the journal. |
| `logging.file` | null or path | `null` | `logfile`. Leave it null under systemd. |
| `logging.rotate` | bool | `false` | Rotate `logging.file` with logrotate. Needs `logging.file`. |
| `logging.journald` | null or bool | `null` | Deprecated and without effect. |

See [Logging](../production/logging.md).
