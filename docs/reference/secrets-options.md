---
title: Secrets options
description: Every odoo-nix.secrets option, declared at the top level of the project flake, with types and defaults.
order: 3
tags: [reference, options, secrets]
updated: 2026-10-23
---

These are declared at the top level of the project flake, beside `perSystem`, not inside it. The module is python-devops-nix's `lib.secrets.mkModule`. See [Secrets](../development/secrets.md).

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `odoo-nix.secrets.enable` | bool | `recipients != { }` | Wire agenix and agenix-shell into the project. |
| `odoo-nix.secrets.dir` | path | required | The directory of `.age` files, as a path literal: `./secrets`. |
| `odoo-nix.secrets.relDir` | string | `baseNameOf dir` | The same directory relative to the project root. Set it only when `dir` is nested (`dir = ./nix/secrets;` needs `relDir = "nix/secrets";`). |
| `odoo-nix.secrets.recipients` | attrs of SSH public keys | `{ }` | Who may read the secrets. The names are labels shown in messages. Run `rekey-secrets` after changing it. |
| `odoo-nix.secrets.hostRecipients` | attrs of SSH public keys | `{ }` | Deployment hosts, added to every secret the deployment reads. |
| `odoo-nix.secrets.identityPaths` | list of strings | `[ "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa" ]` | Private keys tried when decrypting, expanded at run time. |
| `odoo-nix.secrets.backupAccess.enable` | bool | `secrets.enable` | Declare `<dir>/backup-access.age`, the object-store credentials for backups. |
| `odoo-nix.secrets.backupAccess.hosts` | bool | `true` | Also encrypt it to `hostRecipients`, so the server reads the same file. |
| `odoo-nix.secrets.extra.<NAME>.format` | `"env"`, `"raw"` or `"json"` | `"env"` | How the shell reads it: `KEY=value` lines sourced as variables, one value in `$<VAR>`, or a JSON file at `$<VAR>_PATH`. |
| `odoo-nix.secrets.extra.<NAME>.var` | string | `"odoo_<NAME>"` | The shell variable; `$<VAR>_PATH` follows. |
| `odoo-nix.secrets.extra.<NAME>.hosts` | bool | `false` | Also encrypt it to `hostRecipients`. |

The project flake exports `lib.secrets`: `recipients`, and `files`, every declared file by its variable name (`lib.secrets.files.odoo_backup_access`). `lib.odooSecrets`, its old name, went in 2.0.0.
