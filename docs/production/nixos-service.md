---
title: Run Odoo as a NixOS service
description: Deploy an odoo-nix project with the services.odoo-nix module, including its secrets, PostgreSQL, nginx over TCP or a unix socket, X-Sendfile and the systemd sandbox.
order: 1
tags: [nixos, systemd, nginx, deploy]
updated: 2026-10-23
---

`services.odoo-nix` is a standalone NixOS module, imported separately from the flake-parts module. It runs one Odoo instance per deployment; several databases are served through `dbFilter`.

```nix
{
  imports = [ odoo-nix.nixosModules.default ];

  services.odoo-nix = {
    enable = true;
    package = projectFlake.packages.x86_64-linux.default;  # the odoo command
    dbName = "acme";
    database.createLocally = true;                          # local PostgreSQL, socket peer auth
    adminPasswordFile = "/run/secrets/odoo-admin";
    workers = 4;
    nginx = {
      enable = true;
      domain = "erp.example.com";
    };
  };
}
```

Import `odoo-nix.nixosModules.default`, not `modules/nixos.nix` on its own: the flake's module hands it the python-devops-nix library it needs. `package` must be the project's `packages.default`, because the migration runs its `odoo db migrate`; the raw `builtOdoo` is refused unless `migrate.enable = false`.

## The units

| Unit | What it does |
| --- | --- |
| `odoo-init` | A oneshot, as the service user, that writes the runtime `odoo.conf`: the store's base config (no secrets) plus `db_password` and `admin_passwd` read from the secret files. |
| `odoo-migrate` | Runs `odoo db migrate` before every start of `odoo.service`. See [Migrations on deploy](operations.md#migrations-on-deploy). |
| `odoo` | `odoo -c <stateDir>/odoo.conf`: the HTTP workers, the websocket process and cron. It requires both units above. |

The runtime configuration is `<stateDir>/odoo.conf` (`/var/lib/odoo` by default), mode 0600. The filestore is `<stateDir>/data`, and backups go to `<stateDir>/data/backups`, which is kept 0700.

## odoo.conf

`settings` is `odoo.conf` by section ([NixOS RFC 42](https://github.com/NixOS/rfcs/blob/master/rfcs/0042-config-option.md), the shape of nixpkgs' `services.odoo.settings`): `settings.options` is `[options]`, and any other attribute is a section of its own. The module sets the keys it computes (`http_port`, `workers`, `proxy_mode`, `dbfilter`, `addons_path`, ...) into `settings.options`, so `config.services.odoo-nix.settings` is the effective file, secrets aside.

```nix
services.odoo-nix.settings = {
  options = {
    limit_time_cpu = 600;
    workers = 8;                                    # wins over `workers`' mkDefault
    server_wide_modules = [ "base" "web" "queue_job" ];
  };
  queue_job.channels = "root:2";                    # its own [queue_job] section
};
```

Bools render as `True`/`False`, lists comma-separated, and `null` leaves a key out. Every computed key is a `mkDefault` except `addons_path` and `db_user`, which follow `package` and `database.user` (see [settings](../reference/nixos-options.md#settings)). Keep secrets out: `settings` is written to the Nix store.

1.0's flat `settings.<key> = value` still works through 1.x, as `settings.options.<key>`, with a warning that names each key to rename.

## Secrets

Secret values never enter the Nix store. `database.passwordFile` and `adminPasswordFile` are read by systemd (`LoadCredential`, so root-only files are fine) and handed to `odoo-init` as private copies, which it appends to the runtime configuration.

`environmentFiles` are systemd `EnvironmentFile=`s for the `odoo` and `odoo-migrate` units: `KEY=value` lines such as the backup credentials, read by an `fs.storage` with `eval_options_from_env`. With agenix, point it at the ciphertext the developers use:

```nix
age.secrets.odoo-backup.file = inputs.myproject.lib.secrets.files.odoo_backup_access;
services.odoo-nix.environmentFiles = [ config.age.secrets.odoo-backup.path ];
```

The host's key must be in the project's `odoo-nix.secrets.hostRecipients`. See [Secrets](../development/secrets.md#on-the-server).

## PostgreSQL

With `database.createLocally`, the module enables PostgreSQL, creates `database.user` with `CREATEDB` and the database `dbName`, and connects over the unix socket with peer authentication when there is no `passwordFile`. Otherwise it connects to `database.host` and `database.port`.

PostGIS, for OCA's `base_geoengine`: `database.extensions = ps: [ ps.postgis ];` builds it into the local server, and `database.ensureExtensions = [ "postgis" "postgis_topology" ];` creates both in `dbName` as the `postgres` superuser. The module's `pre_init_hook` tries to create them itself, which only works for a superuser; the dev shell's role is one, the production role is not.

## nginx

`nginx.enable` puts an nginx virtual host in front of Odoo, with `proxy_mode` on, `/websocket` and `/longpolling` routed to the websocket port (`http.longpollingPort`) and a ten-day `expires` on `/web/static/`. It needs `nginx.domain`, unless it listens on a socket. The module configures no TLS: set `forceSSL` and `enableACME` on `services.nginx.virtualHosts.<DOMAIN>` yourself, or terminate TLS in front of it.

- `nginx.socketPath` serves the virtual host on a unix socket instead of a TCP port, for a co-located reverse proxy or tunnel connector that terminates TLS. Odoo itself stays on loopback TCP, because its server cannot bind a unix socket. The public scheme is then https, and the client address is taken from `CF-Connecting-IP`. nginx makes its socket 0666, so the module creates the socket's directory 0770 for the service user and group, and that directory is the real gate. Give it a directory of its own, such as `/run/odoo/nginx.sock`.
- `nginx.xSendfile` lets nginx send filestore attachments instead of an Odoo worker. Odoo still authorizes each download, then answers with an empty body and `X-Accel-Redirect`, and nginx serves the file from the filestore through an `internal` location; `/web/filestore/` from outside is a 404. nginx joins the service's group to read the filestore. It is off by default, because anything talking to Odoo's port directly gets empty bodies.
- `nginx.clientMaxBodySize` is `64m`, above NixOS's 10m default.

## The operator's odoo command

`adminCli` (on by default) installs an `odoo` command. From a root shell it runs as a transient unit with the service's user, working directory, `PATH` (`pg_dump`, `psql`, `wkhtmltopdf`), environment and `environmentFiles`, so `odoo db backup`, `restore`, `migrate` and `odoo shell` behave exactly as under `odoo.service` and write files the service can read.

## Hardening

With `hardening.enable = true`, every unit the module defines runs under python-devops-nix's systemd sandboxing baseline (`lib.nixos.hardening`): `ProtectSystem=strict` with only the state directory writable (plus `logging.file`'s directory, and `settings.options.data_dir` if you move it), `ProtectHome`, `PrivateTmp`, `PrivateDevices`, no capabilities, `NoNewPrivileges`, a `@system-service` syscall filter and the rest of its [list](https://github.com/Avunu/python-devops-nix/blob/main/CONVENTIONS.md#unit-hardening). `odoo` and `odoo-migrate` may map W+X memory, for wkhtmltopdf (PDF reports) and rtlcss (right-to-left assets). There is no unit-wide `UMask`: nginx reads the filestore through the service group, and backups and snapshots are made private where they are written.

Each key is a `mkDefault`, so a host relaxes one with `systemd.services.odoo.serviceConfig.<KEY>` and adds a writable path with `systemd.services.odoo.serviceConfig.ReadWritePaths = [ … ];`.

> [!WARNING]
> Hardening is off by default through 1.x and turns on by default in 2.0.0. Turn it on one deployment at a time and watch one start (`journalctl -u odoo-init -u odoo-migrate -u odoo`), especially inside a NixOS (nspawn) container. A unit that cannot set up its mount namespace there fails with `226/NAMESPACE`, and through `Requires=` that keeps Odoo down until you relax the key or turn hardening off.

Every option is in [`services.odoo-nix` options](../reference/nixos-options.md).
