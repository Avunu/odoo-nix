---
title: The container image
description: The all-in-one OCI image odoo-nix builds from a project, its entrypoint's environment variables, and its volume and secret contract.
order: 4
tags: [containers, oci, docker]
updated: 2026-10-21
---

Set `odoo-nix.containers.enable = true` and the project gets `packages.<SYSTEM>.container-odoo`, an all-in-one image built with `dockerTools.buildLayeredImage` from the project's `packages.default`. It runs Odoo with its HTTP workers, the websocket process and cron.

```bash
nix build .#container-odoo
docker load < result
```

The image is named `<name>-odoo:latest`, or `<REGISTRY>/<name>-odoo:latest` with `containers.registry` set (`"ghcr.io/avunu"` gives `ghcr.io/avunu/acme-odoo`; a trailing slash is dropped). It exposes 8069 and 8072, and its `odoo` is the full command, so `docker exec <CONTAINER> odoo db backup acme` works as it does on a server.

## Configuration

The entrypoint writes `/etc/odoo/odoo.conf` at start from environment variables, each with a default:

| Variable | `odoo.conf` key | Default |
| --- | --- | --- |
| `ODOO_NIX_DB_HOST` | `db_host` | `db` |
| `ODOO_NIX_DB_PORT` | `db_port` | `5432` |
| `ODOO_NIX_DB_USER` | `db_user` | `odoo` |
| `ODOO_NIX_DB_NAME` | `db_name`, and `dbfilter = ^<NAME>$` | unset |
| `ODOO_NIX_HTTP_PORT` | `http_port` | `8069` |
| `ODOO_NIX_GEVENT_PORT` | `gevent_port` | `8072` |
| `ODOO_NIX_WORKERS` | `workers` | `2` |
| `ODOO_NIX_MAX_CRON_THREADS` | `max_cron_threads` | `2` |
| `ODOO_NIX_PROXY_MODE` | `proxy_mode` | `True` |
| `ODOO_NIX_LIST_DB` | `list_db` | `False` |
| `ODOO_NIX_WITHOUT_DEMO` | `without_demo` | `False` |
| `ODOO_NIX_LOG_LEVEL` | `log_level` | `info` |
| `ODOO_NIX_LOG_HANDLER` | `log_handler` | unset |
| `ODOO_NIX_LOG_DB` | `log_db` | unset |
| `ODOO_NIX_LOG_DB_LEVEL` | `log_db_level` | `warning` |

`addons_path` is the image's own, `data_dir` is `/var/lib/odoo/data` and `http_interface` is `0.0.0.0`. The variables were `ODOO_<NAME>` before; the old names are still read, with a warning, through 1.x.

## Volumes and secrets

- `/var/lib/odoo/data`: the persistent filestore. Mount a volume.
- `/secrets/db_password` and `/secrets/admin_passwd`: appended to the configuration as `db_password` and `admin_passwd` when present.
- `/secrets/*.conf`: appended verbatim, so a mounted file can add or override any key (the last value wins).
- PostgreSQL is external.

The finished configuration is mode 0600.
