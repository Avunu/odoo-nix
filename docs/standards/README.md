---
title: Repository standards
description: odoo-nix's standards tools (odoo-nix-tools). One table in your config file picks a profile, and `odoo-nix sync` writes and checks the lint, test, editor and CI files of a project or an addon repository.
nav_title: Standards
order: 7
tags: [standards, odoo-nix-tools, profiles, sync]
updated: 2026-11-04
---

odoo-nix ships a second command beside `odoo`: **`odoo-nix`**, from the **odoo-nix-tools** package. It keeps the repository's own files in line with a **profile**: OCA's per-series lint and format rules with tools locked by Nix, the test gate with coverage, the editor settings, Dependabot and the CI callers. You opt in once, with one table, and from then on `odoo-nix sync --check` tells you when anything has drifted.

odoo-nix-tools is built on [standards-core](https://github.com/Avunu/python-devops-nix/tree/2a96bf1b0e5006cf738e8dd16a5604e8dba8333a/standards), the engine frappe-nix's standards tools share. The command names, the sync flags and the exit codes below are that engine's, the same in both products (python-devops-nix [docs/conventions.md, Standards](https://github.com/Avunu/python-devops-nix/blob/2a96bf1b0e5006cf738e8dd16a5604e8dba8333a/docs/conventions.md#standards)).

## Two shapes, one table

A checkout is one of two shapes, and the table lives in the uv project file odoo-nix already reads for that shape:

| Shape | What it is | The table |
| --- | --- | --- |
| `project` | OCB and OCA as submodules, your addons under `custom/` ([Create a new project](../scaffolding/new-project.md)) | `[tool.odoo-nix]` in the root `pyproject.toml` |
| `addons` | addons at the root, OCB a flake input ([A repository of addons](../scaffolding/addons-repository.md)) | `[tool.odoo-nix]` in `nix/pyproject.toml`; an addon repository has no root `pyproject.toml` |

odoo-nix works the shape out from tracked files: `addons.enable = true` (or `layout.customDir = "."`) in `flake.nix`, or an addon manifest at the root, means `addons`; an `odoo` submodule or a `modules.txt` means `project`. Set `shape` in the table when a repository shows both. The series comes from `.odoo-series`, then a literal `odooSeries` in `flake.nix`, then the addons' manifest versions, then a `<n>.0` integration branch; `series` in the table overrides all four.

The smallest opted-in table:

```toml
[tool.odoo-nix]
schema = 1
profile = "recommended"
```

Anything else in it overrides the profile, one module at a time (see [Modules](modules.md)). Both files opening the table is refused with exit 2 by `sync` (and so by `odoo-init --sync`/`--check` and `gate lint`'s sync check), while `config` and `profile show` read the root `pyproject.toml`: keep the one of the repository's shape.

## Opt in

From the repository's root, with the dev shell or without it:

```bash
nix run github:Avunu/odoo-nix#odoo-init -- --sync --standards recommended
```

`odoo-init --standards` is `odoo-nix sync --write --standards`, run from the odoo-nix your `flake.lock` pins (it re-executes there once the flake is locked). It creates the table, writes every managed file, runs `uv lock --project tools` and `npm install --package-lock-only` for the locked tools, and stages what it wrote. It commits nothing. Commit or stash your own changes first: a file you had changed is written but left unstaged, and the report says so. On a first opt-in it exits 2, with a diff, when one of your files is in its way: a hand-written `.pre-commit-config.yaml`, `.envrc`, `.ruff.toml` or `.github/dependabot.yml`, or a `flake.nix` that defines the `odoo-nix` input otherwise. Move your lines where the diff says and rerun with `--force` ([First opt-in](managed-files.md#first-opt-in)).

An addon repository must already be in addons mode (a tracked `flake.nix`, and a `nix/pyproject.toml` with odoo-nix's two foreign blocks). Without them the run is refused with the hint to run `odoo-init --addons` first; `odoo-init --addons --standards recommended` does both in one run. See [A repository of addons](../scaffolding/addons-repository.md) for the files it writes.

## Day to day

| Command | What it does |
| --- | --- |
| `odoo-nix sync --check` | report drift, write nothing; runs no `nix`, `uv` or `npm`, so it works in a no-Nix CI job |
| `odoo-init --sync` (`odoo-nix sync --write`) | write what drifted, retract what a module that turned off left, delete retired files, relock |
| `odoo-nix profile show [--explain]` | the resolved configuration; `--explain` names the layer that set each value |
| `odoo-nix config <key>` | one resolved value: `modules.ci`, `commits.subject-length`, `series`, `profile.name` |
| `odoo-nix gate lint`, `odoo-nix gate test` | the CI gates, run the way CI runs them ([CI](ci.md)) |
| `odoo-nix check manifests\|icons\|submodules` | the lint gate's checks no pre-commit hook makes |
| `odoo-nix ratchet coverage` | the coverage floor only rises |
| `odoo-nix policy --commit-msg-file F` / `--pr` | the commit-msg hook and the `pr-policy` check |
| `odoo-nix ci <step>` | the steps the reusable workflows call |
| `odoo-nix repo apply\|audit\|doctor\|rollout\|targets` | repository settings, the scorecard and the fleet ([Fleet](fleet.md)) |
| `odoo-nix data-path <file>`, `odoo-nix pin-path <input>` | a file the package ships; a locked input's tree |

In an opted-in dev shell `odoo-nix` is on `PATH`, and `nix develop --no-pure-eval .#odoo-nix-lint` is the lint shell. Without the dev shell:

```bash
nix run github:Avunu/odoo-nix#odoo-nix -- sync --check
uv tool install "odoo-nix-tools @ git+https://github.com/Avunu/odoo-nix@<rev>#subdirectory=py/odoo_nix_tools"
```

Use the `<rev>` your `flake.lock` pins for odoo-nix: the tools check that they are the ones the checkout was synced with (see [Versioning](versioning.md#version-skew)).

## Exit codes

Every `odoo-nix` command, and `odoo-init --sync` and `--check`, exits with the table standards-core gives every product:

| Code | Meaning |
| --- | --- |
| `0` | clean, or done |
| `1` | drift (`sync --check`), a failed check or gate step, a rule broken |
| `2` | a configuration it refuses: not opted in, an unknown key, a module that needs another that is off, an addon repository without its addons-mode files |
| `3` | the environment: not a git checkout, an unreadable lock, a missing tool, version skew |

## Read on

- [Profiles](profiles.md): `minimal`, `recommended@2.3`, org profiles and how the layers merge.
- [Modules](modules.md): every module and its keys.
- [Managed files](managed-files.md): what each module writes, how it merges with yours, and where OCA's rules are changed.
- [CI](ci.md): the gates, the callers and the reusable workflows.
- [Versioning](versioning.md): odoo-nix's releases, profile snapshots, version skew and the addons' `<series>.x.y.z`.
- [Fleet](fleet.md): `fleet.json`, `repo apply`, the scorecard and `fleet-audit.yml`.
