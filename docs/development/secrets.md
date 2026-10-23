---
title: Secrets
description: Keep a project's credentials as age-encrypted files in the repository, decrypt them per command in the dev shell, check who can read them, and let the server read the same ciphertext.
order: 5
tags: [secrets, agenix, age]
updated: 2026-10-23
---

A project's credentials live in `.age` files encrypted with [age](https://github.com/FiloSottile/age), committed next to the code. The machinery is python-devops-nix's secrets toolkit, shared with frappe-nix: [agenix](https://github.com/ryantm/agenix) for the files and [agenix-shell](https://github.com/aciceri/agenix-shell) for the dev shell.

## Declare who may read them

At the top level of the project flake, beside `perSystem`:

```nix
odoo-nix.secrets = {
  dir = ./secrets;
  recipients.you = "ssh-ed25519 AAAA… you@host";
  hostRecipients.myserver = "ssh-ed25519 AAAA… root@myserver";  # the production host
};
```

Declaring `recipients` turns the module on. There is no `secrets.nix` to maintain: the agenix rules file is generated from `recipients`, and `hostRecipients` are added to every secret the deployment reads. A new project's `secrets/README.md` says the same.

The `.age` files are meant to be committed. A flake's source tree is exactly its git-tracked files, so an untracked one is invisible to the build and the shell reports it missing.

## The commands

In the dev shell:

| Command | What it does |
| --- | --- |
| `setup-backup-access` | Prompts for the object-store values, tests them against the bucket, and writes `secrets/backup-access.age`. |
| `edit-secret <NAME>` | Creates or edits any other secret. |
| `rekey-secrets` | Re-encrypts every file after `recipients` or `hostRecipients` change. |
| `check-secrets` | Verifies that every `.age` file is encrypted to exactly the declared keys. |

Secrets are decrypted per command, never at shell entry, so credentials are not in your shell's environment. `odoo db restore` re-runs itself under a wrapper that decrypts the file (one key prompt). The private keys tried are `~/.ssh/id_ed25519` and `~/.ssh/id_rsa` (`identityPaths`). Decryption needs the shell loaded with `--no-pure-eval`, which the scaffolded `.envrc` already does.

## The backup-access secret

`backupAccess` is the one secret odoo-nix declares itself: `secrets/backup-access.age`, the object-store credentials for database backups, as `KEY=value` lines that are also valid systemd `EnvironmentFile=` syntax:

```text
BACKUPS_URL=https://s3.us-east-005.backblazeb2.com
BACKUPS_ACCESS_KEY=…
BACKUPS_SECRET_KEY=…
BACKUPS_BUCKET=my-backups
BACKUPS_PREFIX=odoo
```

`BACKUPS_PREFIX` is optional. Unlike the toolkit's default, it is encrypted to `hostRecipients` by default (`backupAccess.hosts`), because the server reads the same file to write its backups. See [Restore a production backup](restore-from-production.md).

Declare any other secret under `extra.<NAME>`, with a `format` of `env`, `raw` or `json`. See [Secrets options](../reference/secrets-options.md).

## On the server

The project flake exports every declared file as `lib.secrets.files.<VAR>`, so a host decrypts the same ciphertext:

```nix
age.secrets.odoo-backup.file = inputs.myproject.lib.secrets.files.odoo_backup_access;
services.odoo-nix.environmentFiles = [ config.age.secrets.odoo-backup.path ];
```

The host's key must be in `hostRecipients`. `lib.odooSecrets`, the old name of `lib.secrets`, went in 2.0.0.
