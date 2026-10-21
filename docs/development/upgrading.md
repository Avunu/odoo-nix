---
title: Upgrading odoo-nix
description: How odoo-nix is released and versioned, which branch or tag a project should follow, how to move a project to a newer odoo-nix, and the options, flags and variables renamed in 1.x.
order: 10
tags: [upgrade, versioning, release]
updated: 2026-10-21
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

odoo-nix and frappe-nix name the things they share the same way (python-devops-nix's [CONVENTIONS.md](https://github.com/Avunu/python-devops-nix/blob/main/CONVENTIONS.md)). Each old name below still works through 1.x and is removed in 2.0.0: it sets the new option, and evaluating the shell prints a warning naming both.

In `perSystem.odoo-nix`:

| Old | New |
| --- | --- |
| `projectName` | `name`, which also sets devenv's own `name` |
| `odooConf.*` | `settings.*`; every option under it keeps its name |
| `mailcatch.enable` | `devguard.mail.enable` |
| `mailcatch.{host,port,httpPort}`, `devguard.mail.{host,port,httpPort}` | `mailpit.{host,port,httpPort}` |
| `dev.autoReload` | `watch.python`; the `dev` tree is gone |
| `odooConf.{httpPort,geventPort,dbPort}`, `settings.{httpPort,geventPort,dbPort}` | `ports.{http,gevent,db}`; setting one pins it, as before |
| `devguard.crons.*` | `devguard.jobs.*` |
| `restore.attachments` | `restore.files` (`"mirror"` is `true`) |

In `services.odoo-nix`:

| Old | New |
| --- | --- |
| `logging.slowQueryMs` | `database.slowQueryMs` |
| `logging.journald` | nothing: Odoo logs to the journal natively. It is accepted with a warning; `false` only silences the `logging.file` warning. |

Elsewhere:

| Old | New |
| --- | --- |
| `odoo-init --series` | `--version` |
| `"series"` in `lib/odoo-presets.json` | `"branch"` |
| `lib.odooSecrets` | `lib.secrets` |
| `odoo db restore --force` | the default; `--no-force` refuses to overwrite. `--force` is accepted and does nothing. |
| `odoo db restore --attachments` | `--files` |

## Renamed environment variables

The variables odoo-nix's own tools read or export are `ODOO_NIX_*`. Odoo's own, such as `ODOO_RC`, and the guard rails' `ODOO_DEVGUARD_*` keep their names. An old name is still read, with a warning, through 1.x, and a new one that is set wins.

| Old | New |
| --- | --- |
| `ODOO_DB`, the `odoo` command's default database | `ODOO_NIX_DB` |
| `ODOO_TEST_ALLOW_SKIP` | `ODOO_NIX_TEST_ALLOW_SKIP` |
| `ODOO_HTTP_PORT`, `ODOO_GEVENT_PORT`, exported by the dev shell (the old names are still exported too) | `ODOO_NIX_HTTP_PORT`, `ODOO_NIX_GEVENT_PORT` |
| the container entrypoint's `ODOO_<NAME>` | `ODOO_NIX_<NAME>` (see [The container image](../production/container.md)) |
| `ODOO_DEVGUARD_CRONS_ENABLE`, `ODOO_DEVGUARD_CRONS_EXTRA_BLOCKED_CRONS` | `ODOO_DEVGUARD_JOBS_ENABLE`, `ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED` |
| `ODOO_NIX_JOURNALD` | nothing; it is accepted with a warning |
