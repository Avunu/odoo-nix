---
title: Reference
description: The flake outputs and library functions of odoo-nix, with links to the option references, the scaffolder, the repository layout and troubleshooting.
nav_title: Reference
order: 6
tags: [reference, flake, outputs]
updated: 2026-10-21
---

## Flake outputs of odoo-nix

| Output | What it is |
| --- | --- |
| `flakeModules.default` | The flake-parts module: the dev shell, the packages, the container image and the `odoo-nix` option tree. |
| `nixosModules.default` | The standalone `services.odoo-nix` NixOS module. |
| `lib.mkFlake` | `flake-parts.lib.mkFlake` with odoo-nix's own inputs merged into the consumer's, so a project declares only `odoo-nix` and `nixpkgs.follows`. |
| `lib.overrides` | Python native-build overlays, `lib.overrides.<PACKAGE> { pkgs }`, each a `final: prev:` overlay: python-devops-nix's shared fixes one by one (psycopg2, python-ldap, lxml, pycups, python-magic, pyvips, cairocffi) and `libsass`. Every project's environment already has the shared ones; these are for a flake that builds its own package set. |
| `lib.addons` | The `addons_path` synthesis (`lib/addons.nix`), for testing and advanced use. |
| `lib.odoo-ls` | The odoo-ls package builder. |
| `packages.<SYSTEM>.odoo-init`, `.default` | The scaffolder. |
| `packages.<SYSTEM>.odoo-ls` | odoo-ls, pinned to the `odoo-ls-src` and `odoo-ls-typeshed` inputs. |
| `packages.<SYSTEM>.sources`, `apps.<SYSTEM>.sources` | `odoo-nix-sources`, the dev shell's submodule checkout, outside it: `nix run github:Avunu/odoo-nix#sources -- enter --treeless odoo <ROOT>`. |
| `packages.<SYSTEM>.bootstrap`, `apps.<SYSTEM>.bootstrap` | `odoo-nix-bootstrap <ROOT>`: a fresh clone's submodules, from the `sources` its `flake.lock` pins, before Nix evaluates the project. See [A fresh clone](../development/README.md#a-fresh-clone). |
| `apps.<SYSTEM>.odoo-init`, `.default` | What `nix run github:Avunu/odoo-nix` runs. |
| `apps.<SYSTEM>.relock-fixtures`, `.relock-odoo-ls` | Maintenance of odoo-nix itself: see [Repository layout](layout.md#re-locking). |
| `devShells.<SYSTEM>.default`, `formatter.<SYSTEM>` | For working on odoo-nix itself. |

## What a project gets

With `odoo-nix.enable`, a project's flake gets `packages.<SYSTEM>.{default, builtOdoo, odooCli, odooPythonEnv, odooDevEnv, odooTestEnv, odooConf, odoo-ls}`, `container-odoo` with `containers.enable`, `apps.<SYSTEM>.relock` (`odoo project relock` outside the shell, see [Re-locking a project](../development/locks.md#re-locking-a-project)), the dev shell, and, with secrets declared, `lib.secrets`. See [From development to production](../production/README.md#what-a-project-builds).

## Pages in this section

- [Dev shell options](dev-shell-options.md): every `perSystem.odoo-nix` option.
- [`services.odoo-nix` options](nixos-options.md).
- [Secrets options](secrets-options.md): `odoo-nix.secrets`.
- [Scaffolder](scaffolder.md): the flags and exit codes of `odoo-init`.
- [Repository layout](layout.md): where things live in odoo-nix, its checks, and how its pinned data is refreshed.
- [FAQ and troubleshooting](troubleshooting.md).
