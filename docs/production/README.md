---
title: From development to production
description: The packages a project builds, the deployable that services.odoo-nix and the container image both run, and how to choose between them.
nav_title: Production
order: 5
tags: [production, deploy, packages]
updated: 2026-10-21
---

The development shell runs Odoo from your checkout. Production runs an immutable build of the same project, assembled in the Nix store from the same `uv.lock`, the same submodule commits and the same `addons_path` rules.

## What a project builds

With `odoo-nix.enable` set, the flake-parts module adds these packages to the project (`nix build .#<NAME>`):

| Package | What it is |
| --- | --- |
| `default` | **The deployable**: `builtOdoo` wrapped in the `odoo` command. Its `bin/odoo` handles `db`, `module`, `project`, `shell` and `test` and passes anything else to `odoo-bin`. `services.odoo-nix.package` and the container image take this one. |
| `builtOdoo` | The assembled Odoo tree, with the production Python environment and an absolute `addons_path`, without the wrapper. |
| `odooPythonEnv` | The production virtualenv: real wheels, no dev tools, no guard rails. |
| `odooDevEnv`, `odooTestEnv` | The development and test virtualenvs (see [Python dependencies and locks](../development/locks.md#the-environments)). |
| `odooCli` | The dev shell's `odoo` command, which runs the live checkout. |
| `odooConf` | The dev shell's synthesized `odoo.conf`. |
| `odoo-ls` | The language server the shell uses. |
| `container-odoo` | The OCI image, with `containers.enable`. |

The production `odoo` command has the same `db` subcommands as the dev shell, and `project backup` and `project restore`. `module …` and `project update` need a git checkout and `modules.txt`, so in a deployment they fail with a message.

The production environment carries the journald log graft (see [Logging](logging.md)) and never the development guard rails.

## Choose a target

| Target | Use it when | Read |
| --- | --- | --- |
| `services.odoo-nix` | You run NixOS. One Odoo instance per host or container, with PostgreSQL local or remote, nginx, secrets from files, migrations before every start and the journal. | [Run Odoo as a NixOS service](nixos-service.md), [Operate a deployment](operations.md), [Logging](logging.md) |
| `container-odoo` | You run containers. One image with Odoo, its HTTP workers, the websocket process and cron; PostgreSQL is external. | [The container image](container.md) |
