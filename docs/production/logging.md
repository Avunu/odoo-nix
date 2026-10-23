---
title: Logging
description: Everything services.odoo-nix logs goes to the journal with APP_SERVICE and APP_SITE fields and real syslog priorities, including nginx's JSON access log and PostgreSQL's slow queries.
order: 3
tags: [logging, journald, nginx, postgresql]
updated: 2026-10-23
---

Everything goes to the journal, with no log files, in a shape a shipper reading it (Vector to Loki, or `journalctl -p warning`) can filter without parsing text. It is the same contract as frappe-nix's and wordpress-nix's, so one query spans all three.

```bash
journalctl APP_SITE=acme -p warning           # everything wrong with one site
journalctl APP_SERVICE=migrate APP_SITE=acme  # its deploy-time migrations
journalctl SYSLOG_IDENTIFIER=nginx_access -o cat | jq 'select(.status >= 500)'
```

## Fields

Every unit the module defines or turns on carries `APP_SERVICE` and `APP_SITE` (systemd `LogExtraFields`, so they are on everything journald attributes to the unit: its output, its syslog messages and systemd's own lines about it).

| `APP_SERVICE` | Unit | `SyslogIdentifier` |
| --- | --- | --- |
| `web` | `odoo` | `odoo-web` |
| `migrate` | `odoo-migrate` | `odoo-migrate` |
| `init` | `odoo-init` | `odoo-init` |
| `db` | `postgresql`, `postgresql-setup`, with `database.createLocally` | their own |
| `nginx` | `nginx`, with `nginx.enable` | their own |

`APP_SITE` is `dbName`. With no pinned `dbName` (several databases behind `dbFilter`) it is left out. The roles are python-devops-nix's one written list (`lib.journald.roles`).

## Priorities

Odoo's stderr format is made for a terminal and lands in the journal at priority 6 whatever its level. Instead, each record is written as `<N>odoo.http [acme] …`: journald reads `<N>` as the syslog priority (DEBUG 7, INFO 6, WARNING 4, ERROR 3, CRITICAL 2) and strips it, `[acme]` is the record's database (left out when there is none), Odoo's `perf_info` follows a request line's message, and the timestamp, PID and colour codes, which the journal records or does not need, are dropped. journald splits on newlines, so every line of a record carries its `<N>`: a traceback stays at the priority of its error.

`odoo-migrate`'s own progress lines stay at priority 6; Odoo's warnings and errors during a migration get their priorities too.

This is the `odoo_journald` graft (`lib/journald.nix`, over python-devops-nix's `lib.journald`), in every Python environment odoo-nix builds, production included, loaded by a `.pth` file so `odoo-bin` run any way gets it. It only acts when stderr really is the journal stream (`$JOURNAL_STREAM`), so running the same package from a terminal keeps Odoo's own format. `logging.journald` and `$ODOO_NIX_JOURNALD` no longer do anything; both are accepted with a warning through 1.x.

## Requests

`logging.accessLog` (on by default, with `nginx.enable`) logs one JSON object per request to the journal, as `SYSLOG_IDENTIFIER=nginx_access`: `time`, `site` (the Host), `method`, `uri`, `status`, `bytes`, `request_time`, `upstream_time`, `remote_addr` (the real client, in socket mode too), `user_agent` and `referer`. `false` turns it off.

nginx's error log goes to the journal over syslog (`SYSLOG_IDENTIFIER=nginx`, `services.nginx.logError`, a `mkDefault`) at `error` and above, each line at its own priority. It is nginx-wide, as `logError` is.

## PostgreSQL

With `database.createLocally`, each line is prefixed with the database and role (`log_line_prefix = "%d %u "`, a `mkDefault`). `database.slowQueryMs = 500;` logs every statement that runs that long (`log_min_duration_statement`; `0` logs them all).

## Log levels and files

`logging.level`, `logging.handlers` (per-logger overrides such as `"werkzeug:WARNING"`) and `logging.db`/`logging.dbLevel` (mirror records into a database table) set Odoo's own `log_level`, `log_handler`, `log_db` and `log_db_level`.

`logging.file` still works, but Odoo's file and stderr handlers are mutually exclusive: with a file set, the journal only sees what is printed before Odoo's logging starts. Leave it null under systemd, since the journal already timestamps, rotates and ships. `logging.rotate` wires `services.logrotate` to the file, daily with 14 kept; Odoo's `WatchedFileHandler` picks up the rotated file by itself.
