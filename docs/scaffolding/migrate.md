---
title: Migrate an existing tree
description: Bring an Odoo tree with OCB at odoo/ and module repositories under modules/ into odoo-nix in place, or repair a project that is already on it.
order: 2
tags: [scaffolding, migrate, odoo-init]
updated: 2026-10-21
---

Run the scaffolder in, or pointed at, a directory that is already an Odoo tree in odoo-nix's layout:

- OCB at `odoo/`, as a checkout or as a submodule that `.gitmodules` registers there;
- OCA and other module repositories under `modules/`;
- your own modules under `custom/`.

```bash
cd my-odoo-tree
nix run github:Avunu/odoo-nix -- --dry-run      # print the plan
nix run github:Avunu/odoo-nix                   # migrate, after asking
```

It prints the plan and asks to go ahead. Without a terminal it needs `-y`. Then it:

- writes the template's files only where none exist; a `.gitignore` gains only the patterns it lacks;
- adds OCB if it is missing, and any repository that `--modules` or `--bundles` need;
- writes the uv path sources into `pyproject.toml` and locks;
- keeps the repository and its history, and commits nothing unless you pass `--commit`.

## How the series is found

The series is read from the first of these that says one: `flake.nix`, the branch `.gitmodules` pairs with `odoo/`, OCB's `odoo/release.py`, and the versions in the module manifests. `--version` overrides it, with a warning when it disagrees with what the tree says. A series with no preset stops the run with exit code 5.

## Files that are not odoo-nix's

A `flake.nix` or `pyproject.toml` that odoo-nix did not write is refused with exit code 4. With `--force` it is kept and odoo-nix's version is written beside it, as `flake.nix.odoo-nix` or `pyproject.toml.odoo-nix`, for you to merge by hand. Nothing is locked until `pyproject.toml` is odoo-nix's.

A tree inside another git repository is refused with exit code 8. `--force` creates a nested repository anyway.

## Repair

Run on an odoo-nix project, the same mode repairs it: missing template files come back, the path sources are regenerated and the project is re-locked. It keeps the `name` and `settings.dbName` that its `flake.nix` sets.

See [Scaffolder](../reference/scaffolder.md) for every flag and exit code.
