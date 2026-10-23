---
title: The container image
description: The all-in-one OCI image odoo-nix builds from a project, its entrypoint's environment variables, and its volume and secret contract.
order: 4
tags: [containers, oci, docker]
updated: 2026-10-23
---

Set `odoo-nix.containers.enable = true` and the project gets `packages.<SYSTEM>.container-odoo`, an all-in-one image built with `dockerTools.buildLayeredImage` from the project's `packages.default`. It runs Odoo with its HTTP workers, the websocket process and cron.

```bash
nix build .#container-odoo
docker load < result
```

The image is named `<name>/odoo:latest`, or `<REGISTRY>/<name>/odoo:latest` with `containers.registry` set (`"ghcr.io/avunu"` gives `ghcr.io/avunu/acme/odoo`; a trailing slash is dropped); see [The image name](#the-image-name). It exposes 8069 and 8072, and its `odoo` is the full command, so `docker exec <CONTAINER> odoo db backup acme` works as it does on a server.

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

`addons_path` is the image's own, `data_dir` is `/var/lib/odoo/data` and `http_interface` is `0.0.0.0`. The variables were `ODOO_<NAME>` through 1.x; since 2.0.0 the image refuses to start while one of the old names is set, and names its replacement.

## Volumes and secrets

- `/var/lib/odoo/data`: the persistent filestore. Mount a volume.
- `/secrets/db_password` and `/secrets/admin_passwd`: appended to the configuration as `db_password` and `admin_passwd` when present.
- `/secrets/*.conf`: appended verbatim, so a mounted file can add or override any key (the last value wins).
- PostgreSQL is external.

The finished configuration is mode 0600.

## Healthcheck

The image has a `HEALTHCHECK`: `GET /web/health` on the HTTP port (`ODOO_NIX_HTTP_PORT`, default 8069) must answer 200. Odoo serves that route without a database. The probe uses Bash's `/dev/tcp`, since the image has no `curl`. Docker and Podman run it every 30 seconds after a 120-second start period, and three failures in a row mark the container unhealthy.

## Labels

The image carries the `org.opencontainers.image.*` labels: `title` (the image name), `source` (`https://github.com/Avunu/odoo-nix`), `version` (the odoo-nix version that built it), `licenses` (`MIT`), and `revision`, odoo-nix's commit, when your flake has odoo-nix as the `odoo-nix` input. They describe odoo-nix. `containers.labels` goes over them, so you can describe your project instead:

```nix
odoo-nix.containers.labels = {
  "org.opencontainers.image.source" = "https://github.com/acme/odoo";
  "org.opencontainers.image.revision" = self.rev or "dirty";
};
```

## The image name

python-devops-nix names images `<REGISTRY>/<name>/<role>`, and so does odoo-nix since 2.0.0: `<name>/odoo`. Through 1.x the default was `<name>-odoo`, with `containers.roleImageNames` to opt in to the new name. That option is gone, and setting it is an error. A host that pulls or runs the image by name has to change with it; otherwise it keeps running the last image it had under the old name.

## Running as non-root

The image runs as `odoo`, uid 1000 and gid 1000, with home `/var/lib/odoo`, since 2.0.0 (`containers.nonRoot`, on by default). Through 1.x it ran as root by default. `containers.nonRoot = false` still runs it as root.

The image owns `/etc/odoo`, where the entrypoint writes `odoo.conf`, and `/var/lib/odoo`, so a new named volume at `/var/lib/odoo/data` takes that ownership. A bind mount must be writable by uid 1000 (`chown -R 1000:1000 <DIR>` on the host), and the files in `/secrets` must be readable by it.

> [!IMPORTANT]
> A filestore volume that a root image wrote is owned by root, and a non-root image cannot write to it. Before the first start of a 2.x image on an existing deployment, change its owner once:
>
> ```bash
> docker run --rm --user 0 --entrypoint chown \
>   -v <VOLUME>:/var/lib/odoo/data <IMAGE> -R 1000:1000 /var/lib/odoo/data
> ```
