---
title: Getting started
description: Scaffold a new Odoo project with odoo-nix, start the development shell and provision your first database.
order: 2
tags: [quick-start, devenv, odoo]
updated: 2026-10-23
---

This page takes you from an empty directory to a running Odoo database. If you already have an Odoo tree, read [Migrate an existing tree](scaffolding/migrate.md) first and come back for the shell steps.

## Prerequisites

You need:

- [Nix](https://nixos.org/download.html) with flakes enabled.
- [direnv](https://direnv.net/), so the shell loads when you enter the directory. Without it, `nix develop --no-pure-eval` does the same job by hand.
- git, because OCB and the module repositories are git submodules.

The generated flake declares the `devenv.cachix.org` binary cache, so Nix may ask you to trust it the first time you enter the shell.

> [!IMPORTANT]
> Keep `--no-pure-eval` when you load the shell by hand. The generated `.envrc` ends with `use flake . --no-pure-eval`: the shell reads the checkout's path and the environment while it evaluates (per-project ports, decrypting secrets).

## 1. Scaffold a project

Run the scaffolder from the directory where the project should live. With a terminal and no flags it prompts for an Odoo series, optional OCA bundles and modules, and a directory name.

```bash
nix run github:Avunu/odoo-nix
```

For a scripted run, pass everything as flags. Without a terminal it never prompts, so `--version` is required.

```bash
nix run github:Avunu/odoo-nix -- \
  --version 18.0 --bundles base \
  --modules account_financial_report \
  --name acme --db acme acme
```

OCA software is opt-in: leave out `--bundles` and `--modules` and you get plain Odoo. The scaffolder writes the wrapper `flake.nix`, adds OCB and the module repositories as git submodules on the series' branch, records the modules in `modules.txt`, generates `pyproject.toml` and runs `uv lock`. See [Create a new project](scaffolding/new-project.md) for the presets, the module picker and what it writes.

## 2. Enter the shell

```bash
cd acme
direnv allow
```

The first entry builds the Python environment, so it takes a while. When it finishes, a banner prints the project name, the Odoo series, the server's and Mailpit's addresses and the most useful commands.

## 3. Start the services

```bash
devenv up
```

`devenv up` runs PostgreSQL, Mailpit and the Odoo server (`odoo-bin --dev=all`, threaded). Leave it running in this terminal. Every port is a base plus an offset hashed from the project's name, so several projects run at once. [The development shell](development/README.md#ports) has the details.

## 4. Provision the database

In a second terminal, in the same directory:

```bash
odoo db provision
```

It creates the database named by `dbName` (the `--db` you scaffolded with) and installs `base` and every module in `modules.txt`. Run it again later and it migrates the database instead of reinstalling, so it is safe to repeat.

## 5. Open Odoo

Open the server address the banner printed and log in with Odoo's defaults for a new database, `admin` and `admin`. Mail the database sends lands in Mailpit, whose address is in the banner too.

## Where next

- [The odoo command](development/commands.md) covers the database and module commands.
- [Manage modules](development/modules.md) adds OCA modules, bundles or any git repository, and removes them.
- [Write the flake by hand](scaffolding/write-the-flake.md) shows what the scaffolder wrote and the options you will touch most.
- [Development guard rails](development/guard-rails.md) explains what keeps a restored production database from reaching the outside world, and [Restore a production backup](development/restore-from-production.md) how to get one.
- When you are ready to deploy, read [From development to production](production/README.md).
