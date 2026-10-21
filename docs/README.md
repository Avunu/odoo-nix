---
title: odoo-nix documentation
description: Reusable Nix infrastructure for Odoo Community (OCB) and OCA projects, from scaffolding and the development shell to a container image and a NixOS module.
nav_title: Overview
order: 0
tags: [odoo, oca, nix, overview]
updated: 2026-10-21
---

odoo-nix packages everything needed to develop and ship an [Odoo](https://www.odoo.com/) project built on the [Odoo Community Backports (OCB)](https://github.com/OCA/OCB) distribution and [OCA](https://odoo-community.org/) modules, declaratively. A project that uses it is a thin wrapper: a `flake.nix`, a `pyproject.toml` with its `uv.lock`, a `modules.txt`, and git submodules for OCB and the module repositories. The same description builds the development shell on a laptop and the production system on a server.

You consume it as a [flake-parts](https://flake.parts/) module.

## What you get

- A **scaffolder**, `nix run github:Avunu/odoo-nix`, that creates a project, optionally with OCA bundles or modules from a bundled catalog and the module repositories they depend on, or brings an existing Odoo tree into odoo-nix in place.
- A **devenv development shell** with PostgreSQL, Odoo and Mailpit. Modules are editable installs, the server restarts itself on a Python change, and **guard rails** stop a database restored from production from mailing customers, calling integrations or writing to a production bucket.
- An **`addons_path` derived from the folders on disk** and an **`odoo.conf` synthesized by Nix**, so neither can drift from the submodules.
- A reproducible **Python environment**, built by [uv2nix](https://github.com/pyproject-nix/uv2nix) from your committed `uv.lock`.
- One **`odoo` command** for the database lifecycle (`db provision`, `migrate`, `backup`, `restore`, …), module management (`module add`, `add-bundle`, `remove`) and workspace updates. Anything else passes straight through to `odoo-bin`. The dev shell, the server and the container all run the same command.
- A single-instance **NixOS module**, `services.odoo-nix`, that migrates the database behind a verified snapshot before every start, keeps secrets out of the Nix store and logs to the journal.
- An **OCI container image**.
- **Age-encrypted secrets** committed next to the code, which the dev shell decrypts and the server can read from the same ciphertext.

## How the pieces fit

| You commit                 | Nix builds from it                                                          |
| -------------------------- | --------------------------------------------------------------------------- |
| `pyproject.toml`, `uv.lock` | the Python environments, through uv2nix                                     |
| `odoo/`, `modules/*`       | OCB and the module repositories, as git submodules; `addons_path` is derived from them |
| `modules.txt`              | the modules `odoo db provision` installs, and the Python install set         |
| `flake.nix`, `flake.lock`  | the configuration, and the pinned odoo-nix, nixpkgs, devenv and uv2nix       |

The deployable is the project's `packages.default`: the assembled Odoo tree wrapped in the `odoo` command. `services.odoo-nix` and the container image both consume it. See [From development to production](production/README.md).

## Choose your starting point

| You have                                 | Do this                                       | Read                                                       |
| ---------------------------------------- | --------------------------------------------- | ---------------------------------------------------------- |
| Nothing yet, and want to try it          | Scaffold a project with `nix run`              | [Getting started](getting-started.md)                      |
| An Odoo tree with OCB and module repos   | Migrate it in place                           | [Migrate an existing tree](scaffolding/migrate.md)         |
| A library of modules other projects mount | Take OCB as a flake input                     | [Write the flake by hand](scaffolding/write-the-flake.md#a-repository-of-modules) |
| A project already on odoo-nix            | Pull a newer odoo-nix                         | [Upgrading odoo-nix](development/upgrading.md)             |
| A built project to deploy                | Run it as a NixOS service or a container      | [Production](production/README.md)                         |

## Where to go next

- **Working in the development shell?** See [The development shell](development/README.md), [The odoo command](development/commands.md) and [Development guard rails](development/guard-rails.md).
- **Deploying?** See [Run Odoo as a NixOS service](production/nixos-service.md) or [The container image](production/container.md).
- **Looking something up?** Every option is in the [reference](reference/README.md), and [Troubleshooting](reference/troubleshooting.md) lists the errors you are most likely to meet, with their fixes.

## The project

odoo-nix is open source under the [MIT License](../LICENSE). The source, issues and pull requests are at [github.com/Avunu/odoo-nix](https://github.com/Avunu/odoo-nix). Its sibling for Frappe and ERPNext is [frappe-nix](https://docs.avunu.net/frappe-nix/docs/); both build on the shared pieces of [python-devops-nix](https://github.com/Avunu/python-devops-nix).

> [!NOTE]
> These pages describe the `main` branch of odoo-nix. They live in the `docs/` folder of the repository and change with the code, so the version you read is the version in the checkout you have.
