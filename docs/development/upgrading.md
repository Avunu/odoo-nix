---
title: Upgrading odoo-nix
description: How odoo-nix is released and versioned, which branch or tag a project should follow, how to move a project to a newer odoo-nix, and the options, flags and variables renamed in 1.x.
order: 10
tags: [upgrade, versioning, release]
updated: 2026-10-23
---

## Releases

odoo-nix is released with [release-please](https://github.com/googleapis/release-please). Each `fix:` or `feat:` commit merged to `main` lands in a release pull request, and merging that tags `vX.Y.Z` and updates `CHANGELOG.md`. A `fix:` makes a patch release, Dependabot's `fix(deps)` bumps of the flake inputs included, and a `feat:` a minor one. A major release is only ever deliberate.

Within a major release nothing a project sets is taken away. A renamed option, command-line flag or environment variable keeps its old name as an alias, with a warning, through every release of that major, and the aliases go in the next major release. That release's changelog says what to change.

## Which odoo-nix to follow

| `odoo-nix.url`                         | Follows                                         |
| -------------------------------------- | ----------------------------------------------- |
| `github:Avunu/odoo-nix/release-1`      | every 1.x release, and nothing that breaks it   |
| `github:Avunu/odoo-nix/v1.0.0`         | that one release                                |
| `github:Avunu/odoo-nix`                | `main`, unreleased changes included             |

Each `vN.*` tag moves a `release-N` branch, which only ever fast-forwards. The scaffolder writes plain `github:Avunu/odoo-nix`; change it to `release-1` if you want only releases.

## Upgrade a project

```bash
nix flake update odoo-nix
direnv reload
```

Evaluating the shell prints a warning for every renamed option the project still sets. Fix those, commit `flake.lock`, and push. The production side follows when the host deploys the new `flake.lock`: `odoo-migrate.service` brings each database's schema along (see [Migrations on deploy](../production/operations.md#migrations-on-deploy)).

Two files are the project's own, and an upgrade never rewrites them:

- `.envrc`. A project scaffolded before `bootstrap` existed has a one-line `.envrc` and fails to evaluate on a fresh clone; replace it with [the current one](README.md#a-fresh-clone).
- The managed blocks of `pyproject.toml` are regenerated only by `odoo module …` and `odoo project update`. To refresh the template's other files, run the scaffolder in [repair mode](../scaffolding/migrate.md#repair); it only adds what is missing.

## Renamed options

odoo-nix and frappe-nix name the things they share the same way (python-devops-nix's [CONVENTIONS.md](https://github.com/Avunu/python-devops-nix/blob/main/CONVENTIONS.md)). Each old name below was an alias through 1.x. Since 2.0.0 it is refused: evaluating the shell, or the host, fails with an error that names the new one.

In `perSystem.odoo-nix`:

| Old | New |
| --- | --- |
| `projectName` | `name`, which also sets devenv's own `name` |
| `mailcatch.enable` | `devguard.mail.enable` |
| `mailcatch.{host,port,httpPort}`, `devguard.mail.{host,port,httpPort}` | `mailpit.{host,port,httpPort}` |
| `dev.autoReload` | `watch.python`; the `dev` tree is gone |
| `devguard.crons.*` | `devguard.jobs.*` |
| `restore.attachments` | `restore.files` (`"mirror"` is `true`) |

In `services.odoo-nix`:

| Old | New |
| --- | --- |
| `logging.slowQueryMs` | `database.slowQueryMs` |
| `logging.journald` | nothing: Odoo logs to the journal natively. Remove it. |

Elsewhere:

| Old | New |
| --- | --- |
| `odoo-init --series` | `--version` |
| `"series"` in `lib/odoo-presets.json` | `"branch"` |
| `lib.odooSecrets` | `lib.secrets` |
| `odoo db restore --force` | the default; `--no-force` refuses to overwrite. `--force` is a usage error. |
| `odoo db restore --attachments` | `--files` |

## The dev shell's `settings` (2.0.0)

`perSystem.odoo-nix.settings` is `odoo.conf` by section now, as `services.odoo-nix.settings` is ([NixOS RFC 42](https://github.com/NixOS/rfcs/blob/master/rfcs/0042-config-option.md)): `settings.options.<key>` is `[options]`, keys in Odoo's own spelling. The camelCase tree, and `odooConf` before it, is refused with an error that names where each key went:

| Old | New |
| --- | --- |
| `settings.dbName`, `odooConf.dbName` | `dbName` |
| `settings.devMode` | `devMode` |
| `settings.dbHost` | `settings.options.db_host`; `null` (not `""`) for the unix socket |
| `settings.dbUser`, `settings.dbPassword` | `settings.options.db_user`, `settings.options.db_password` |
| `settings.dataDir`, `settings.adminPasswd`, `settings.httpInterface`, `settings.workers` | `settings.options.data_dir`, `admin_passwd`, `http_interface`, `workers` |
| `settings.withoutDemo = true` | `settings.options.without_demo = true` |
| `settings.logging.{level,handlers,dbLevel,file}` | `settings.options.{log_level,log_handler,log_db_level,logfile}` |
| `settings.logging.db = true` | `settings.options.log_db = "%d"` |
| `settings.extra.<key>` | `settings.options.<key>` |
| `settings.{httpPort,geventPort,dbPort}`, `odooConf.{httpPort,geventPort,dbPort}` | `ports.{http,gevent,db}` |

The rendered `odoo.conf` is the same for the same values. See [odoo.conf: `settings`](../reference/dev-shell-options.md#odooconf-settings).

## Coming in 2.0.0: the container image's name and user

In 2.0.0 the container image becomes `<name>/odoo` (python-devops-nix's `<REGISTRY>/<name>/<role>`) instead of `<name>-odoo`, and runs as a non-root user. Each changes a running deployment, so through 1.x they are opt-in: `containers.roleImageNames` and `containers.nonRoot`. See [The image name](../production/container.md#the-image-name) and [Running as non-root](../production/container.md#running-as-non-root).

## Renamed environment variables

The variables odoo-nix's own tools read or export are `ODOO_NIX_*`. Odoo's own, such as `ODOO_RC`, and the guard rails' `ODOO_DEVGUARD_*` keep their names. An old name was read, with a warning, through 1.x. Since 2.0.0 it is not read, except that the container image refuses to start while one of its old names is set.

| Old | New |
| --- | --- |
| `ODOO_DB`, the `odoo` command's default database | `ODOO_NIX_DB` |
| `ODOO_TEST_ALLOW_SKIP` | `ODOO_NIX_TEST_ALLOW_SKIP` |
| `ODOO_HTTP_PORT`, `ODOO_GEVENT_PORT`, exported by the dev shell | `ODOO_NIX_HTTP_PORT`, `ODOO_NIX_GEVENT_PORT` |
| the container entrypoint's `ODOO_<NAME>` | `ODOO_NIX_<NAME>` (see [The container image](../production/container.md)) |
| `ODOO_DEVGUARD_CRONS_ENABLE`, `ODOO_DEVGUARD_CRONS_EXTRA_BLOCKED_CRONS` | `ODOO_DEVGUARD_JOBS_ENABLE`, `ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED` |
| `ODOO_NIX_JOURNALD` | nothing |
