---
title: Upgrading odoo-nix
description: How odoo-nix is released and versioned, which branch or tag a project should follow, how to move a project to a newer odoo-nix, and how to move a 1.x project to 2.0.
order: 10
tags: [upgrade, versioning, release]
updated: 2026-10-23
---

## Releases

odoo-nix is released with [release-please](https://github.com/googleapis/release-please). Each `fix:` or `feat:` commit merged to `main` lands in a release pull request, and merging that tags `vX.Y.Z` and updates `CHANGELOG.md`. A `fix:` makes a patch release, Dependabot's `fix(deps)` bumps of the flake inputs included, and a `feat:` a minor one. A major release is only ever deliberate.

Within a major release nothing a project sets is taken away. A renamed option, command-line flag or environment variable keeps its old name as an alias, with a warning, through every release of that major, and the aliases go in the next major release. A change that alters a running deployment without anyone asking for it ships opt-in, and becomes the default in the next major release. A major release is cut by a `Release-As: <N>.0.0` footer (the pr-policy check refuses `!` and `BREAKING CHANGE`), and this page says what to change: [1.x to 2.0](#1x-to-20).

## Which odoo-nix to follow

| `odoo-nix.url`                         | Follows                                         |
| -------------------------------------- | ----------------------------------------------- |
| `github:Avunu/odoo-nix/release-2`      | every 2.x release, and nothing that breaks it   |
| `github:Avunu/odoo-nix/release-1`      | every 1.x release; it stays at the last one     |
| `github:Avunu/odoo-nix/v2.0.0`         | that one release                                |
| `github:Avunu/odoo-nix`                | `main`, unreleased changes included             |

Each `vN.*` tag moves a `release-N` branch, which only ever fast-forwards: `release-2` is created by the first 2.x release, and `release-1` stays where the last 1.x release left it. A project that follows `release-1` never gets 2.0 by itself; it moves when you change the URL. The scaffolder writes plain `github:Avunu/odoo-nix`; change it to `release-2` if you want only releases.

## Upgrade a project

```bash
nix flake update odoo-nix
direnv reload
```

Within a major release, evaluating the shell prints a warning for every renamed option the project still sets. Fix those, commit `flake.lock`, and push. The production side follows when the host deploys the new `flake.lock`: `odoo-migrate.service` brings each database's schema along (see [Migrations on deploy](../production/operations.md#migrations-on-deploy)).

Two files are the project's own, and an upgrade never rewrites them:

- `.envrc`. A project scaffolded before `bootstrap` existed has a one-line `.envrc` and fails to evaluate on a fresh clone; replace it with [the current one](README.md#a-fresh-clone).
- The managed blocks of `pyproject.toml` are regenerated only by `odoo module …` and `odoo project update`. To refresh the template's other files, run the scaffolder in [repair mode](../scaffolding/migrate.md#repair); it only adds what is missing.

## 1.x to 2.0

odoo-nix 2.0.0 removes every alias 1.x kept, reshapes the dev shell's `settings`, and turns on three defaults that 1.x shipped opt-in: unit hardening, a non-root container image, and the `<name>/odoo` image name. An old name is not ignored: the shell, the host or the command fails with a message that names its replacement, so evaluating your flake shows what is left to change.

Do it in this order:

1. [Point the flake at 2.x](#1-point-the-flake-at-2x).
2. [Reshape the dev shell's `settings`](#2-reshape-the-dev-shells-settings).
3. [Rename the dev shell options 1.x renamed](#3-rename-the-dev-shell-options).
4. [Rename the `services.odoo-nix` options](#4-rename-the-servicesodoo-nix-options), and drop 1.0's flat `settings`.
5. [Rename the environment variables, flags and other names](#5-environment-variables-flags-and-other-names).
6. [Check the dev shell](#6-check-the-dev-shell).
7. [Deploy the host with hardening on](#7-deploy-the-host-with-hardening-on).
8. [Move the container image](#8-move-the-container-image): its name, and its volume's owner.

### 1. Point the flake at 2.x

```nix
odoo-nix.url = "github:Avunu/odoo-nix/release-2";
```

Then `nix flake update odoo-nix`. A project on plain `github:Avunu/odoo-nix` gets 2.0 with its next update anyway.

### 2. Reshape the dev shell's `settings`

`perSystem.odoo-nix.settings` was a typed camelCase tree. It is `odoo.conf` by section now, as `services.odoo-nix.settings` is ([NixOS RFC 42](https://github.com/NixOS/rfcs/blob/master/rfcs/0042-config-option.md)): `settings.options.<key>` is `[options]`, with keys spelled as Odoo spells them, and any other attribute is a section of its own. The database and the `--dev` flag are top-level options. `odooConf`, 1.x's name for the same tree, is gone too.

Before:

```nix
odoo-nix = {
  settings = {
    dbName = "acme";
    devMode = "reload,xml";
    workers = 0;
    withoutDemo = true;
    logging = {
      level = "debug";
      handlers = [ "werkzeug:WARNING" ];
      db = true;
    };
    extra.limit_time_real = 1200;
  };
};
```

After:

```nix
odoo-nix = {
  dbName = "acme";
  devMode = "reload,xml";
  settings.options = {
    workers = 0;
    without_demo = true;
    log_level = "debug";
    log_handler = [ "werkzeug:WARNING" ];
    log_db = "%d";
    limit_time_real = 1200;
  };
};
```

| 1.x | 2.0 |
| --- | --- |
| `settings.dbName`, `odooConf.dbName` | `dbName` |
| `settings.devMode` | `devMode` |
| `settings.dbHost` | `settings.options.db_host`; `null`, not `""`, for the unix socket |
| `settings.dbUser`, `settings.dbPassword` | `settings.options.db_user`, `settings.options.db_password` |
| `settings.dataDir` | `settings.options.data_dir` |
| `settings.adminPasswd` | `settings.options.admin_passwd` |
| `settings.httpInterface` | `settings.options.http_interface` |
| `settings.workers` | `settings.options.workers` |
| `settings.withoutDemo` | `settings.options.without_demo` |
| `settings.logging.level`, `.handlers`, `.dbLevel`, `.file` | `settings.options.log_level`, `log_handler`, `log_db_level`, `logfile` |
| `settings.logging.db = true` | `settings.options.log_db = "%d"`; a database name stays a name |
| `settings.extra.<key>` | `settings.options.<key>` |
| `settings.{httpPort,geventPort,dbPort}`, `odooConf.{httpPort,geventPort,dbPort}` | `ports.{http,gevent,db}` |
| `odooConf.<anything else>` | as `settings.<anything else>` above |

The shell sets what it computes into `settings.options`. A plain value of yours wins over most of it. The ports, `addons_path` and `db_name` come from `ports.*`, `layout` and `dbName`, so a second value for one of those is a conflict: change it where it comes from. For the same values the rendered `odoo.conf` is byte for byte what 1.x wrote. See [odoo.conf: `settings`](../reference/dev-shell-options.md#odooconf-settings).

### 3. Rename the dev shell options

In `perSystem.odoo-nix`:

| 1.x | 2.0 |
| --- | --- |
| `projectName` | `name`, which also sets devenv's own `name` |
| `mailcatch.enable` | `devguard.mail.enable` |
| `mailcatch.{host,port,httpPort}`, `devguard.mail.{host,port,httpPort}` | `mailpit.{host,port,httpPort}` |
| `dev.autoReload` | `watch.python`; the `dev` tree is gone |
| `devguard.crons.{enable,extraBlocked}` | `devguard.jobs.{enable,extraBlocked}` |
| `restore.attachments = "mirror"` (`"none"`) | `restore.files = true` (`false`) |
| `containers.roleImageNames` | nothing: the image is always `<name>/odoo`. Remove it (see [step 8](#8-move-the-container-image)). |

`containers.nonRoot` stays an option, `true` by default now.

At the top level, `flake.lib.odooSecrets` is gone; it is `lib.secrets`.

### 4. Rename the `services.odoo-nix` options

| 1.x | 2.0 |
| --- | --- |
| `logging.slowQueryMs` | `database.slowQueryMs` |
| `logging.journald` | nothing: Odoo logs to the journal natively. Remove it. A `logging.file` no longer warns, so there is nothing for `false` to silence. |
| `settings.<key> = value`, 1.0's flat form | `settings.options.<key> = value` |

Each old name fails an assertion that names the new one. The flat form fails one assertion that lists every key to move. In 1.x a flat key won over a key the module computes; in `settings.options` a plain value still wins over a computed `mkDefault`, but `addons_path` and `db_user` follow `package` and `database.user` (or `mkForce`).

### 5. Environment variables, flags and other names

The variables odoo-nix's own tools read or export are `ODOO_NIX_*`. Odoo's own, such as `ODOO_RC`, and the guard rails' `ODOO_DEVGUARD_*` keep their names. The old names are not read, with one exception: the container image refuses to start while one of its old names is set, so that `ODOO_DB_HOST` cannot quietly turn into the default host.

| 1.x | 2.0 |
| --- | --- |
| `ODOO_DB`, the `odoo` command's default database | `ODOO_NIX_DB` |
| `ODOO_TEST_ALLOW_SKIP` | `ODOO_NIX_TEST_ALLOW_SKIP` |
| `ODOO_HTTP_PORT`, `ODOO_GEVENT_PORT`, exported by the dev shell | `ODOO_NIX_HTTP_PORT`, `ODOO_NIX_GEVENT_PORT` |
| the container entrypoint's `ODOO_<NAME>` (`ODOO_DB_HOST`, `ODOO_WORKERS`, …) | `ODOO_NIX_<NAME>` (see [The container image](../production/container.md#configuration)) |
| `ODOO_DEVGUARD_CRONS_ENABLE`, `ODOO_DEVGUARD_CRONS_EXTRA_BLOCKED_CRONS` | `ODOO_DEVGUARD_JOBS_ENABLE`, `ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED`; the old names are ignored, so the guard stays on |
| `ODOO_DEVGUARD_DISABLE=crons` | `ODOO_DEVGUARD_DISABLE=jobs` |
| `ODOO_NIX_JOURNALD` | nothing; remove it |

Commands and files:

| 1.x | 2.0 |
| --- | --- |
| `odoo-init --series <V>` | `--version <V>`; `--series` is a usage error |
| `"series"` in a presets file (`lib/odoo-presets.json`'s shape) | `"branch"` |
| `odoo db restore --force`, `odoo project restore --force` | nothing: overwriting is the default, and `--no-force` refuses. `--force` is a usage error. |
| `odoo db restore --attachments`, `odoo project restore --attachments` | `--files` (`--no-files`) |
| `dev_mailcatch` in a `server_wide_modules` you set by hand | remove it: the stub addon is gone. The mail guard (`devguard.mail`) does its job. |

### 6. Check the dev shell

```bash
direnv reload        # or: nix develop --no-pure-eval
```

Evaluation stops at the first removed name it finds, with every removed name in that part of the configuration and what replaced each. Fix them and reload until the shell starts. Then `odoo.conf` (the `./odoo.conf` symlink) should read as before, apart from what you changed on purpose. The one expected difference is `addons_path`: it no longer ends with odoo-nix's own addons directory, which held only the `dev_mailcatch` stub.

### 7. Deploy the host with hardening on

`services.odoo-nix.hardening.enable` is `true` by default. Every unit the module defines then runs under python-devops-nix's sandboxing baseline: `ProtectSystem=strict` with only the state directory writable, no capabilities, a syscall filter and the rest (see [Hardening](../production/nixos-service.md#hardening)). The VM tests run with it on, but a host may do something they do not:

- **Watch the first start**: `journalctl -u odoo-init -u odoo-migrate -u odoo`. `odoo.service` requires `odoo-migrate.service`, so a migrate unit that the sandbox stops keeps Odoo down.
- **A NixOS (nspawn) container** may not let a unit set up its mount namespace. The unit then fails with `226/NAMESPACE`.
- **A path outside the state directory** that Odoo writes to (a `data_dir` you moved is followed for you) needs `systemd.services.odoo.serviceConfig.ReadWritePaths = [ … ];`.
- Every key is a `mkDefault`, so relax one with `systemd.services.<UNIT>.serviceConfig.<KEY>`. To deploy without it and turn it on later, set `services.odoo-nix.hardening.enable = false;` for now.

### 8. Move the container image

With `containers.enable`, two defaults change, and each needs a step on the host that runs the image.

**The name.** The image is `<REGISTRY>/<name>/odoo` now (python-devops-nix's `<REGISTRY>/<name>/<role>`). It was `<REGISTRY>/<name>-odoo`. `containers.roleImageNames`, which opted in through 1.x, is gone. Point whatever pushes, pulls or runs the image at the new name (a compose file, a Quadlet unit, a registry's retention rule, a CI push). Otherwise the host keeps running the last image it had under the old name.

**The user.** The image runs as `odoo`, uid 1000 and gid 1000 (`containers.nonRoot`, now `true`). A filestore volume that a 1.x image wrote is owned by root, and the new image cannot write to it. Before the first start of the 2.0 image, change its owner once:

```bash
docker run --rm --user 0 --entrypoint chown \
  -v <VOLUME>:/var/lib/odoo/data <IMAGE> -R 1000:1000 /var/lib/odoo/data
```

A bind mount needs `chown -R 1000:1000 <DIR>` on the host, and the files mounted at `/secrets` must be readable by uid 1000. To keep running as root for now, set `containers.nonRoot = false;`.

Rename the entrypoint's variables at the same time ([step 5](#5-environment-variables-flags-and-other-names)): a 2.0 image refuses to start while an old `ODOO_<NAME>` is set.
