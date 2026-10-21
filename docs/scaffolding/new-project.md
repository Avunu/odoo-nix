---
title: Create a new project
description: Scaffold a fresh Odoo project with odoo-nix, choosing a series and, if you want them, OCA bundles and modules with the repositories they depend on.
order: 1
tags: [scaffolding, odoo-init, oca]
updated: 2026-10-21
---

```bash
nix run github:Avunu/odoo-nix                     # interactive: prompts for what is missing
nix run github:Avunu/odoo-nix -- \
  --version 18.0 --bundles base \
  --modules account_financial_report,repair_order_group \
  --name acme --db acme acme                       # non-interactive
cd acme && direnv allow && devenv up               # then `odoo db provision` in another shell
```

The scaffolder:

1. picks an Odoo series, which fixes the Python version from a preset;
2. optionally takes OCA bundles and modules, and resolves the module repositories they need;
3. writes the wrapper `flake.nix`, `pyproject.toml`, `.envrc`, `.gitignore`, a `README.md`, an empty `custom/`, `modules.txt` and `secrets/README.md` (which says how to declare `odoo-nix.secrets`);
4. adds OCB at `odoo/` and each resolved repository under `modules/` as git submodules on the series' branch, as partial clones (OCB with its commits only);
5. generates the managed blocks of `pyproject.toml` and runs `uv lock`;
6. stages everything, and commits only with `--commit`.

Warnings, such as a repository with no branch for the series or a failed `uv lock`, are repeated in a summary at the end, before the next steps.

## Series presets

The presets are in `lib/odoo-presets.json`:

| Series | Python    | OCB and OCA branch |
| ------ | --------- | ------------------ |
| 18.0   | python311 | 18.0               |
| 19.0   | python312 | 19.0               |
| 20.0   | python312 | 20.0               |

18.0 is the default of `odoo-nix.odooSeries`, and the bundled OCA catalog is richest for it. 19.0 is supported and catalogued, but OCA's port to it is still in progress, so fewer modules exist there. 20.0 is supported the same way (the Python, CLI and NixOS paths are tested against OCB 20.0), but the bundled OCA catalog has no 20.0 modules yet, so the picker offers none for it: a 20.0 project starts as plain Odoo, and you add modules by hand or with `odoo module add` once OCA's 20.0 branches exist.

## OCA software is opt-in

The scaffolder asks two independent questions, "add curated bundles?" and then "add individual modules?", and each defaults to no. Decline both, or pass neither `--bundles` nor `--modules`, and you get a plain Odoo project. Answer both and the two selections are unioned. You can always add modules later with `odoo module add` and `odoo module add-bundle` (see [Manage modules](../development/modules.md)).

### The module picker

The picker searches every installable module of the series. Type a module or repository name: it matches word prefixes of the module, its repository and its summary, so typing a repository's name lists its modules. Pick from the numbered matches by number or name, then search again; an empty search finishes. Modules flagged `application` in their manifest are marked with ★, but every installable module can be picked: most useful OCA modules, localizations and feature modules alike, are not applications.

Picking a module resolves the OCA repositories it needs, transitively through each module's `depends`, and only the new ones are added as submodules. The modules you chose go into `modules.txt`, which drives both what `odoo db provision` installs and the Python install set.

### Bundles

Bundles are named module sets in `data/oca-bundles.json`: `base`, `oca-accounting`, `project`, `purchase` and `sales`. They are not tied to a series, so a member with no catalog record for the project's series is reported and dropped instead of being recorded in `modules.txt`.

## What to read next

- [Getting started](../getting-started.md#2-enter-the-shell) for the first shell entry and `odoo db provision`.
- [Write the flake by hand](write-the-flake.md) for what the generated `flake.nix` holds.
- [Scaffolder](../reference/scaffolder.md) for every flag and exit code.
