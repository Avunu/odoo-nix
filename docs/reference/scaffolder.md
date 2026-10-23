---
title: Scaffolder
description: The flags and exit codes of odoo-init, the program behind nix run github:Avunu/odoo-nix that creates, migrates and repairs projects.
order: 4
tags: [reference, odoo-init, scaffolding]
updated: 2026-10-23
---

```bash
nix run github:Avunu/odoo-nix -- [FLAGS] [TARGET_DIR]
```

`odoo-init --help` lists the flags. With a terminal and no flags it prompts for what it needs. It never prompts when stdin or stdout is not a terminal, so a scripted run passes what it needs. See [Choose a mode](../scaffolding/README.md) for how it picks a mode.

## Flags

| Flag | Meaning |
| --- | --- |
| `--init` | Force scaffold mode. Needs an empty directory unless you add `--force`. |
| `--migrate` | Force migration mode; also repairs an odoo-nix project. |
| `--force` | Relax the mode guard. It never overwrites an existing file. |
| `--dry-run` | Print the plan, including the files it would write, and exit without changing anything. |
| `-y`, `--yes` | Assume yes. Required to migrate without a terminal. |
| `--version <V>` | The Odoo series, `18.0`, `19.0` or `20.0`; overrides detection. |
| `--bundles <A,B>` | Curated OCA bundles to install (`data/oca-bundles.json`). |
| `--modules <A,B,C>` | OCA modules to install. `--apps` is an alias. |
| `--name <NAME>` | The project name (`odoo-nix.name`). Defaults to the existing one, or the target directory's name. |
| `--db <NAME>` | The default database (`dbName`). Defaults to the existing one, or `odoo`. |
| `--skip-lock` | Do not run `uv lock`. |
| `--commit[=<MESSAGE>]` | Commit the result instead of only staging it. The message is only taken as `--commit=<MESSAGE>`, so `--commit <DIR>` is the flag and a target. |
| `-h`, `--help` | Show the help. |

`--version` was `--series` before odoo-nix and frappe-nix agreed on one set of scaffolder flags. Since 2.0.0 the old name is a usage error that names `--version`. In `lib/odoo-presets.json` the key holding each preset's git branch is `branch` (it was `series`, which is refused since 2.0.0); the schema is the one both products share, `label`, `branch`, `python` and `requiresPython`, with `nodejs` and `overrideDependencies` optional.

## Exit codes

They follow frappe-nix's table where it applies.

| Code | Meaning |
| --- | --- |
| `0` | Done, or `--dry-run` finished. |
| `1` | A usage error, a forced `--migrate` on an empty or missing directory, OCB could not be cloned, or another error with no more specific code. |
| `2` | `--init` into a directory that is not empty, without `--force`. |
| `4` | A `flake.nix` or `pyproject.toml` that is not odoo-nix's is in the way. `--force` writes odoo-nix's beside it to merge. |
| `5` | The Odoo series is missing, unknown, undetectable, or has no preset. |
| `6` | The directory is not the shape the mode needs (not empty and not an Odoo tree), or the confirmation was declined or could not be asked (no terminal and no `-y`). |
| `7` | `custom/` or `modules/` with no module in them and no OCB: nothing to migrate. |
| `8` | The tree is inside another git repository. `--force` creates a nested one anyway. |
| `130` | Interrupted. |

A failing `git` step exits with git's own status. frappe-nix's `3` belongs to its `--sync` and `--check`, which odoo-nix does not have.
