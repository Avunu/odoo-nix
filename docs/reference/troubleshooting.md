---
title: FAQ and troubleshooting
description: The errors you are most likely to meet with odoo-nix in the dev shell, with the odoo command and on a deployed host, what they mean and how to fix them.
order: 6
tags: [faq, troubleshooting, errors]
updated: 2026-10-21
---

Each entry starts with what you see, then what it means and what to do.

## The shell will not open

### A fresh clone fails to evaluate: `does not appear to be a git repository`

```text
fatal: '…/modules/account-analytic' does not appear to be a git repository
error: Failed to fetch git repository 'file:///…/modules/account-analytic'
```

The project's flake sets `self.submodules = true`, so Nix reads every submodule while it evaluates the flake, before the shell exists to check them out. On a fresh clone with any change in the tree (an updated `flake.lock` counts) it reads each submodule from its empty directory and fails as above. With a clean tree it fetches every submodule itself instead, a full clone each.

The `.envrc` the scaffolder writes handles it (see [A fresh clone](../development/README.md#a-fresh-clone)). A project scaffolded before that has a one-line `.envrc`, which is the project's own file and no command rewrites. Either replace it with the current one, or check the submodules out once and reload:

```bash
nix run github:Avunu/odoo-nix#sources -- enter --treeless odoo "$PWD"
direnv reload
```

To check: clone the project, change any tracked file, `direnv allow`. The submodules are checked out first, then the flake evaluates.

### `uv.lock does not cover every declared dependency`

`pyproject.toml` declares a dependency `uv.lock` lacks, usually a module added to `modules.txt` without re-locking. The message names it. Run `uv lock` from the project root, commit `uv.lock`, and re-enter the shell. See [A stale lock is an evaluation error](../development/locks.md#a-stale-lock-is-an-evaluation-error).

### `uv.lock` or a module is missing, but the file is on disk

A flake's source tree is exactly its git-tracked files, so an untracked file is invisible to evaluation, and so is an untracked submodule. Stage it with `git add`. The same goes for `.age` files under `secrets/`.

### `odoo/ exists but coreSource is set`

With `coreSource`, `odoo/` must be a symlink the shell maintains, and a real directory there is a leftover submodule checkout. Remove it (`git submodule deinit -f odoo`, then delete the directory) and re-enter the shell.

### `./.venv exists and is not a symlink — leaving it alone`

`ide.enable` links the Nix-built environment at `./.venv`, and will not replace a real virtualenv there. Delete the directory if you do not need it.

### A warning about a renamed option

`The option '…' defined in … has been renamed to '…'`: the project sets an option by its old name. It still works through 1.x; rename it. See [Renamed options](../development/upgrading.md#renamed-options).

## In the dev shell

### The server does not reload on a Python change

Look for `AutoReload watcher running with watchdog` at start-up. `Code autoreload feature is disabled` means Odoo found no watcher: keep `watch.python` on. The watcher also needs `settings.workers = 0` and a `settings.devMode` containing `all` or `reload`; the shell warns about either. Changes to `odoo/odoo/*.py` are never watched. See [Live reload](../development/editors.md#live-reload).

### Mail does not arrive, or sending fails

With the mail guard on, every mail goes to Mailpit at the address the banner prints. If the shell warned `the mail guard is on but mailpit.enable is false`, nothing listens on that port: turn `mailpit.enable` back on.

### `blocked connection to <ADDRESS>:<PORT> (<HOST>)`

The egress guard refused an outbound connection. To allow it for one command, `ODOO_DEVGUARD_EGRESS_ALLOW_HOSTS=<HOST> odoo …`; permanently, add the host to `devguard.egress.allowHosts`. See [Letting something through](../development/guard-rails.md#letting-something-through).

### `extension "…" is not available` when installing a module

The dev PostgreSQL only has the extensions it is built with. Add the extension to `postgres.extensions`, for example `ps: [ ps.postgis ]` for `base_geoengine`, and restart `devenv up`.

### `… holds a database on btrfs with copy-on-write on`

The PostgreSQL cluster predates `postgres.noCow`. Stop `devenv up` and run the `odoo-nix-db-nocow migrate` command it prints. See [Memory and disk](../development/memory-and-disk.md#postgresql-off-copy-on-write).

### `odoo test` refuses: `Browser tours cannot run here`

Odoo would skip every browser tour and report it as a pass. Add `websocket-client` to `[dependency-groups].dev` and re-lock, and keep `testBrowser` set (Chromium by default). `ODOO_NIX_TEST_ALLOW_SKIP=1` runs anyway.

### `odoo module remove` refuses

- `modules whose code would go are still installed`: uninstall them in Odoo (Apps) first.
- `could not read the installed modules of the databases`: start `devenv up`, so it can check.
- `has uncommitted changes that removing it would discard`: commit or discard them.

`--force` skips these checks.

### `odoo db restore` refuses: `devguard.enable is false in this project`

Restoring production data without the guard rails would let it mail customers and write to production storage. Turn `devguard.enable` back on, or set `ODOO_NIX_RESTORE_ALLOW_UNGUARDED=1` for one command.

## On a deployed host

### `odoo.service` does not start after a deploy

`odoo-migrate.service` failed, rolled the database back to its snapshot, and kept Odoo down on purpose. Read why with `journalctl -u odoo-migrate`, then deploy a fix or roll back the system generation. See [Migrations on deploy](../production/operations.md#migrations-on-deploy).

### `database schema is outdated, -u queue_job required`

The code is ahead of the schema, as after a deploy with `migrate.enable = false`. As root, run `odoo db migrate <DB>`: without `--if-needed` it compares every module's checksum and version, and updates what changed. Keep `migrate.enable` on so deploys do this themselves.

### `services.odoo-nix.migrate needs the odoo CLI package`

`package` is the raw `builtOdoo`. Set it to the project's `packages.default`.

### A unit fails with `226/NAMESPACE`

With `hardening.enable`, a unit could not set up its mount namespace, typically inside an nspawn container or on a FUSE-mounted state directory. Relax the offending key with `systemd.services.<UNIT>.serviceConfig.<KEY>`, or turn hardening off. See [Hardening](../production/nixos-service.md#hardening).

### `journalctl -u odoo` shows almost nothing

`logging.file` is set, and Odoo's file and stderr handlers are exclusive. Leave `logging.file` null under systemd. See [Logging](../production/logging.md#log-levels-and-files).
