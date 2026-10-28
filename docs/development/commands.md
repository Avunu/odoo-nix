---
title: The odoo command
description: The odoo command that the dev shell, services.odoo-nix and the container share, its database, module and project subcommands, and how everything else passes through to odoo-bin.
order: 1
tags: [cli, database, backup]
updated: 2026-10-28
---

The dev shell, `services.odoo-nix` and the container image share one `odoo` command. `db`, `module`, `project`, `shell` and `test` are odoo-nix's own subcommands. `ui` opens the dev shell's [menu](menu.md), and so does a bare `odoo` typed at a terminal there. Anything else, `server` (the default with no subcommand anywhere else), `scaffold`, `populate`, `cloc`, `deploy`, `neutralize` and the rest, passes straight through to the real `odoo-bin`, so nothing from Odoo is lost. A source tree without `odoo-bin`, as an Enterprise tree can be, runs Odoo the way `python -m odoo` does, with the same interpreter.

`-c/--config`, `-d/--database` and `--db-host`, `--db-port`, `--db-user`, `--db-password` are accepted before the subcommand, the way `odoo-bin` takes its own flags. The configuration defaults to `$ODOO_RC`, then `./odoo.conf`. A subcommand with no database falls back to `-d`, then `$ODOO_NIX_DB`, then `db_name` in `odoo.conf`.

## Databases

| Command | What it does |
| --- | --- |
| `odoo db list` | List the databases, with version compatibility. |
| `odoo db create <DB> [--demo] [--lang <LANG>]` | Create an empty database, with no modules installed. |
| `odoo db provision [DB] [--modules-file <FILE>] [--no-backup]` | Create the database and install `base` and everything in `modules.txt`, or migrate it when it already has an Odoo schema. Idempotent. |
| `odoo db upgrade <M[,M2]> [DB \| --all]` | Update the named modules (`-u`), with live progress and a per-module summary. |
| `odoo db migrate [DB \| --all] [...]` | Update the modules whose code or version changed. Run it after pulling new code. See [Migrations](migrations.md). |
| `odoo db duplicate <SRC> <DEST> [--neutralize]` | Copy a database, schema and filestore. |
| `odoo db rename <OLD> <NEW>` | Rename a database and its filestore. |
| `odoo db drop <DB> [--yes]` | Drop a database and its filestore. |
| `odoo db backup [DB \| --all] [--path <DIR>] [--format zip\|dump] [--keep-days <N>]` | Back up to `<data_dir>/backups/<DB>/` by default. `zip` (the default) is schema and filestore, Odoo's own Database Manager format; `dump` is a `pg_dump` custom-format dump with no filestore. |
| `odoo db restore <DB> [<BACKUP>] [...]` | Restore a backup into `<DB>`, overwriting an existing one unless `--no-force`, then migrate it unless `--no-migrate`. With no file it fetches the newest backup from the remote store: see [Restore a production backup](restore-from-production.md). |

`--all` means every database matching `dbfilter`, when the filter does not use the per-request `%h` or `%d` placeholders.

## Modules and the workspace

These need a git checkout and `modules.txt`, so they work only in the dev shell. Elsewhere they fail with a message.

| Command | What it does |
| --- | --- |
| `odoo module add [MODULE …]` | Pick OCA modules, add the repositories they need, record them in `modules.txt` and re-lock. |
| `odoo module add <GIT_URL \| OWNER/REPO> [BRANCH] [PATH]` | Add any git repository as a submodule and record its modules. |
| `odoo module add-bundle [NAME …]` | Add a curated bundle of OCA modules. |
| `odoo module remove [--force] [--keep-repos] <MODULE \| REPO> …` | Take modules out of `modules.txt`, and the repositories nothing needs any more out of the workspace. |
| `odoo project update [--no-migrate]` | Pull every submodule to the tip of its pinned branch, regenerate the managed blocks of `pyproject.toml`, `uv lock`, then migrate every database matching `dbfilter` unless `--no-migrate`. |
| `odoo project relock [UV_ARGS…]` | The project's one re-lock: regenerate the managed blocks of `pyproject.toml` from what is on disk, `uv lock` with the build-dependency block in step, pulling nothing. `UV_ARGS` go to `uv lock`. Outside the shell, `nix run .#relock [-- UV_ARGS…]` is the same. See [Re-locking a project](locks.md#re-locking-a-project). |

After any of them, run `direnv reload` so Nix derives `addons_path` again and rebuilds the Python environment. [Manage modules](modules.md) covers them in full.

## The whole project

| Command | What it does |
| --- | --- |
| `odoo project backup [--format zip\|dump] [--path <DIR>] [--keep-days <N>]` | Back up every database matching `dbfilter`. With `--path`, each one goes into its own `<DIR>/<DB>/`. |
| `odoo project restore [--restore <DB> <PATH> …] [...]` | Restore several database and file pairs in one batch, or, with no `--restore`, the project database (`dbName`) from the remote store. |
| `odoo shell [DB]` | Odoo's Python REPL, without workers or HTTP, so it runs next to a live server. |
| `odoo test <M[,M2]> [DB]` | Run modules' tests. It refuses to run when browser tours would be skipped, because Odoo reports a skipped tour like a pass: it needs the `websocket-client` package and a headless browser (`testBrowser`). `ODOO_NIX_TEST_ALLOW_SKIP=1` runs anyway. |

## Progress

`db upgrade`, `db migrate` and `db provision` read Odoo's own module-loading log records and render them as a live progress bar on a terminal, or as plain lines under journald or CI. Either way they end with a table of what was touched, how long each module took and which migration scripts ran. Odoo commits each module's update as it completes, so a failure part-way is reported as "N modules already committed, module X failed", not as an all-or-nothing rollback that Odoo does not have.

## Backup files

Backups use OCA [`auto_backup`](https://github.com/OCA/server-tools/tree/18.0/auto_backup)'s naming: `<data_dir>/backups/<DB>/<TIMESTAMP>.dump.zip` (or `.dump` for `--format dump`), with the timestamp as `YYYY_MM_DD_HH_MM_SS` and no database name in the file name, since the folder carries it. Backups made by this command and by an installed `auto_backup` are interchangeable in the same folder.

`--keep-days` prunes the way `auto_backup` does: every backup whose name sorts before "now minus N days", formatted the same way, is deleted.

Every backup and snapshot is written owner-only (0600), and any directory created for one is 0700.
