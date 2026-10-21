---
title: Dev shell options
description: Every perSystem.odoo-nix option that configures the development shell, the production packages and the container image, with types and defaults.
order: 1
tags: [reference, options, devenv]
updated: 2026-10-21
---

All of these are under `perSystem.odoo-nix`. Secrets are declared at the top level instead: see [Secrets options](secrets-options.md). Options renamed in 1.x are listed in [Upgrading odoo-nix](../development/upgrading.md#renamed-options).

## The project

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `enable` | bool | `false` | Build the dev shell and the packages. |
| `name` | string | required | The project's identity, a slug: names its environments, packages and container image, seeds the port offset, and is devenv's own `name` by default. |
| `workspaceRoot` | path | required | The project root, where `pyproject.toml`, `odoo.conf` and the layout directories live. Usually `./.`. |
| `coreSource` | null or path | `null` | OCB from outside the workspace, typically a `flake = false` input, instead of the `odoo/` submodule. See [A repository of modules](../scaffolding/write-the-flake.md#a-repository-of-modules). |
| `odooSeries` | string | `"18.0"` | The Odoo series: the OCB and OCA branch and the catalog filter. It does not pick a nixpkgs package. |
| `python` | package | the series' preset: `python311` for 18.0, `python312` for 19.0 | The interpreter. Match the series' `requires-python`. |
| `nodejs` | package | `pkgs.nodejs_22` | Node.js, for rtlcss and asset tooling. |
| `pythonOverrides` | overlay | `_: _: { }` | A uv2nix package-set overlay, applied last. |
| `pythonLibraries` | attrs of lists of packages | `{ }` | Native libraries for a Python package's build, by package name, e.g. `{ python-snappy = [ pkgs.snappy ]; }`. See [C extensions](../development/locks.md#c-extensions-that-need-a-library). |
| `testBrowser` | null or package | `pkgs.chromium` | The browser Odoo's browser tours drive. `null` relies on one on `PATH`; without any, `odoo test` refuses to run. |

## Layout

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `layout.coreSrc` | string | `"odoo"` | The OCB submodule, or the symlink `coreSource` maintains. |
| `layout.externalDir` | string | `"modules"` | The directory of module-repository submodules. |
| `layout.customDir` | string | `"custom"` | The directory of your own modules. `"."` for a repository of modules. |
| `layout.extraAddons` | list of strings | `[ ]` | Extra `addons_path` entries, relative to the workspace, appended after `customDir`. |

## odoo.conf: `settings`

Rendered into the dev shell's `odoo.conf` `[options]`. The production module has its own options; see [`services.odoo-nix` options](nixos-options.md).

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `settings.dbHost` | string | `"127.0.0.1"` | `db_host`. Empty or `"False"` leaves it out: the unix socket. |
| `settings.dbUser` | string | `"odoo"` | `db_user`, and the dev PostgreSQL role, created as a superuser. |
| `settings.dbPassword` | string | `"False"` | `db_password`. Empty or `"False"` leaves it out. |
| `settings.dbName` | null or string | `"odoo_dev"` | `db_name`, the default database, created empty in the dev PostgreSQL. The scaffolder sets it from `--db`. |
| `settings.dataDir` | string | `"./.devenv/state/odoo"` | `data_dir`, the filestore. |
| `settings.adminPasswd` | string | `"admin"` | `admin_passwd`, the database manager's master password. Development only. |
| `settings.httpInterface` | string | `"127.0.0.1"` | `http_interface`. `"0.0.0.0"` to reach the server from another host or container. |
| `settings.workers` | int | `0` | `workers`. 0 is the threaded server, which live reload needs. |
| `settings.devMode` | string | `"all"` | The dev process's `--dev` flag. Not written to `odoo.conf`. |
| `settings.withoutDemo` | bool | `false` | `without_demo = True`: no demo data for any module. |
| `settings.logging.level` | enum | `"info"` | `log_level`. |
| `settings.logging.handlers` | list of `"logger:LEVEL"` | `[ ]` | `log_handler`, e.g. `[ "werkzeug:WARNING" ]`. |
| `settings.logging.db` | bool or string | `false` | `log_db`: `true` is the request's own database (`%d`), a string that database. |
| `settings.logging.dbLevel` | enum | `"warning"` | `log_db_level`. |
| `settings.logging.file` | null or string | `null` | `logfile`. Odoo's file and stderr handlers are exclusive, so the console then stays quiet. |
| `settings.extra` | attrs of string, int or bool | `{ }` | Any other `[options]` key, merged last. |

`odoo.conf` also gets `http_port`, `gevent_port` and `db_port` from `ports`, and `server_wide_modules` (`base,web`, and `rpc` from 19.0 on).

## Ports

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `ports.offset` | int, 0 to 899 | a hash of `name` | The offset every port is derived from. `ODOO_NIX_PORT_OFFSET` overrides it for one shell. |
| `ports.worktreeSalt` | bool | `true` | A linked worktree hashes `name@<path>`, so it gets its own ports. |
| `ports.base` | null or port | `null` | Pin the HTTP port alone. |
| `ports.http` | port | `ports.base`, else 10000 + offset | Odoo's `http_port`. |
| `ports.gevent` | port | 11000 + offset | Odoo's `gevent_port`. |
| `ports.db` | port | 12000 + offset | PostgreSQL's port and `db_port`. |
| `ports.smtp` | port | 13000 + offset | Mailpit's SMTP port. |
| `ports.mailUi` | port | 14000 + offset | Mailpit's web UI. |

The derived ports are read by the rest of the module; pin one with `lib.mkForce`. See [Ports](../development/README.md#ports).

## Mailpit and reload

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `mailpit.enable` | bool | `true` | Run Mailpit, before the server, whether or not the mail guard is on. |
| `mailpit.host` | string | `"127.0.0.1"` | The SMTP listener's host, which the mail guard redirects to. |
| `mailpit.port` | port | `ports.smtp` | The SMTP port. |
| `mailpit.httpPort` | port | `ports.mailUi` | The web UI's port. |
| `watch.python` | bool | `true` | Make Odoo's `--dev=reload` watcher work by providing `watchdog`. See [Live reload](../development/editors.md#live-reload). |

## Guard rails: `devguard`

See [Development guard rails](../development/guard-rails.md).

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `devguard.enable` | bool | `true` | Graft the guard rails into the dev and test environments. Off, `odoo db restore` refuses to run. |
| `devguard.egress.enable` | bool | `true` | Refuse every non-loopback connection from Odoo's Python. |
| `devguard.egress.allowHosts` | list of strings | `[ ]` | Destinations to let through: hostnames (`*.example.com`), IP literals or CIDRs. |
| `devguard.mail.enable` | bool | `true` | Redirect all outgoing mail to Mailpit; refuse IMAP and POP3. |
| `devguard.jobs.enable` | bool | `true` | Skip denylisted scheduled actions. |
| `devguard.jobs.extraBlocked` | list of strings | `[ ]` | More cron external ids (`<module>.<name>`) to skip. |
| `devguard.objectstore.enable` | bool | `true` | Refuse to open an `fs.storage` that is not local. |
| `devguard.backups.enable` | bool | `true` | Skip `auto_backup` jobs to a remote destination, and their retention. |
| `devguard.webhooks.enable` | bool | `true` | Make outbound webhook actions do nothing. |
| `devguard.iap.enable` | bool | `true` | Make IAP calls fail with a readable error. |

## Restore: `restore`

See [Restore a production backup](../development/restore-from-production.md).

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `restore.enable` | bool | `secrets.backupAccess.enable` | Offer `setup-backup-access` and let `odoo db restore` decrypt the backup-access secret. |
| `restore.sourceDatabase` | string | `""` | The database folder to restore from. Empty: the target's name. |
| `restore.prefix` | string | `""` | The bucket prefix, when the secret has no `BACKUPS_PREFIX`. |
| `restore.files` | bool | `false` | Also mirror object-store attachments (`--files`). |
| `restore.neutralize` | bool | `true` | Neutralize restored databases. |
| `restore.migrate` | bool | `true` | Run `odoo db migrate` on a restored database. |
| `restore.requireDevguard` | bool | `true` | Refuse to restore while `devguard.enable` is false. |

## PostgreSQL, editors and extras

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `postgres.extensions` | function to list of packages | `_: [ ]` | Extensions built into the dev PostgreSQL 16, e.g. `ps: [ ps.postgis ]`. The dev role is a superuser, so a module can create them itself. |
| `postgres.noCow` | bool | `true` | On btrfs, keep the data directory off copy-on-write (Linux). See [Memory and disk](../development/memory-and-disk.md). |
| `ide.enable` | bool | `true` | Create `./.venv` and the merged analysis root. |
| `ide.vscodeSettings` | bool | `true` | Seed `.vscode/settings.json` (and `extensions.json`) when absent. Never overwrites. |
| `ide.languageServer.enable` | bool | `true` | Put `odoo_ls_server` on `PATH` and link `./odools.toml`. Needs `ide.enable`. |
| `ide.languageServer.package` | package | odoo-ls from odoo-nix's pinned inputs | The `odoo_ls_server` to use. |
| `extraDevPackages` | list of packages | `[ ]` | More packages in the shell. |
| `extraLibraryPaths` | list of packages | `[ ]` | More packages on `LD_LIBRARY_PATH`. |
| `extraScripts` | attrs | `{ }` | More devenv scripts. |
| `extraEnv` | attrs of strings | `{ }` | More environment variables. |

## Containers

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `containers.enable` | bool | `false` | Build `packages.container-odoo`. See [The container image](../production/container.md). |
| `containers.registry` | string | `""` | A prefix for the image's name: `"ghcr.io/avunu"` names it `ghcr.io/avunu/<name>-odoo`, or `ghcr.io/avunu/<name>/odoo` with `roleImageNames`. |
| `containers.roleImageNames` | bool | `false` | Name the image `<name>/odoo` instead of 1.0's `<name>-odoo`; building under the old name warns. The default becomes `true` in 2.0.0. See [The image name](../production/container.md#the-image-name). |
| `containers.nonRoot` | bool | `false` | Run the image as `odoo` (uid/gid 1000) instead of root. The default becomes `true` in 2.0.0; an existing filestore volume needs a one-time chown first. See [Running as non-root](../production/container.md#running-as-non-root). |
| `containers.labels` | attribute set of strings | `{ }` | Image labels over the `org.opencontainers.image.*` ones, which describe odoo-nix. See [Labels](../production/container.md#labels). |
