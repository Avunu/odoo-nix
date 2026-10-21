---
title: Manage modules
description: Add OCA modules, curated bundles or any git repository to an odoo-nix project, remove them again, and keep the workspace current with odoo project update.
order: 3
tags: [oca, modules, submodules]
updated: 2026-10-21
---

A project's modules live in three places, and these commands keep them in step:

- the repositories, as git submodules under `modules/` (`layout.externalDir`);
- `modules.txt`, the modules to install;
- the managed blocks of `pyproject.toml`, and `uv.lock`.

None of them touches a database: install a new module with `odoo db provision` or from Odoo's Apps, and uninstall one in Odoo before removing it. After each command, run `direnv reload` so Nix derives `addons_path` again and rebuilds the Python environment.

## Add OCA modules

```bash
odoo module add                            # interactive picker
odoo module add account_financial_report   # by module name
```

The picker is the scaffolder's (see [The module picker](../scaffolding/new-project.md#the-module-picker)). Each module resolves the OCA repositories it needs through its `depends`, transitively, from the bundled catalog (`data/oca-modules.json`). Only the new repositories are cloned, on the project's `odooSeries` branch, as partial clones.

## Add a bundle

```bash
odoo module add-bundle                     # pick: name — label — module count
odoo module add-bundle base sales          # by name; modules are unioned across bundles
```

A bundle expands to its module list and then goes through the same flow as `odoo module add`. Bundles are defined in the hand-maintained `data/oca-bundles.json` of odoo-nix (`base`, `oca-accounting`, `project`, `purchase`, `sales`). They are not tied to a series, so a member with no catalog record for the project's series is reported and dropped.

## Add any git repository

`odoo module add` also takes a git URL, from any host, or GitHub's `owner/repo` shorthand:

```bash
odoo module add                                  # interactive: choose "OCA catalog" or "Git URL"
odoo module add https://gitlab.com/foo/bar.git   # any git host
odoo module add foo/bar                          # → https://github.com/foo/bar.git
odoo module add foo/bar 17.0 my-bar              # explicit branch and submodule folder
```

The branch defaults to the project's `odooSeries`. When the repository has no such branch, its default branch is offered as an editable prompt, or used directly without a terminal. The folder defaults to a slug of the repository name, under `modules/`. The clone is scanned for `__manifest__.py`: a single module is recorded straight away, and several are offered as a multi-select with nothing pre-selected. The OCA catalog is not involved.

## Remove modules

```bash
odoo module remove account_tax_balance        # the module, and the repos only it needed
odoo module remove modules/my-vendor          # a repo, with the modules of it modules.txt lists
odoo module remove --keep-repos sale_foo      # modules.txt only
```

`odoo module remove` takes each named module out of `modules.txt`, then removes every repository under `modules/` that held one of them, or that their dependencies reached, and that no module left in `modules.txt` needs. What a module needs is read from the manifests on disk, and from the catalog for a module that is not cloned. A repository that a listed module still needs is refused. Then the path sources are regenerated and the workspace re-locked.

It refuses, unless you pass `--force`:

- while a database matching `dbfilter` still has one of the modules installed, or while it cannot read the databases (is PostgreSQL up?);
- while a repository to remove has uncommitted changes.

The removal uses git plumbing rather than `git rm`, which refuses while `.gitmodules` has any unstaged edit. The submodule is deinitialized, its gitlink and `.gitmodules` section are removed and staged, and any other `.gitmodules` edit stays as it was. The clone under `.git/modules/` is deleted too, so the repository can be added again later. `modules.txt`, `pyproject.toml` and `uv.lock` are left for you to review and commit.

## Update the workspace

```bash
odoo project update                # then migrates every database
odoo project update --no-migrate
```

It checks out any submodule this clone has never had, moves every submodule to the tip of the branch `.gitmodules` pins (fetched by name, so a repository whose default branch moved does not derail it), regenerates the managed blocks of `pyproject.toml`, runs `uv lock` and syncs the build dependencies (see [Python dependencies and locks](locks.md)). Then it runs `odoo db migrate` on every database matching `dbfilter`. Commit the new submodule pointers, `pyproject.toml` and `uv.lock` when you are happy with them.

With [`coreSource`](../scaffolding/write-the-flake.md#a-repository-of-modules), OCB is a flake input and is left alone: bump it with `nix flake update`.
