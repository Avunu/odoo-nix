---
title: Repository layout
description: Where things live in the odoo-nix repository, the flake checks and what CI runs, how the pinned test fixtures, odoo-ls lock and OCA catalog are refreshed, and how these pages are checked.
order: 5
tags: [contributing, layout, checks, ci]
updated: 2026-10-28
---

## Layout

```text
flake.nix                    # inputs; flakeModules, nixosModules, lib, packages, apps, checks
modules/
  flake-module.nix           # imports devenv's flake module, secrets.nix, devenv.nix, containers.nix
  devenv.nix                 # the perSystem.odoo-nix options and the dev shell
  containers.nix             # the OCI image, its shared parts from python-devops-nix's lib.containers
  nixos.nix                  # services.odoo-nix
  secrets.nix                # odoo-nix.secrets: python-devops-nix's lib.secrets.mkModule
lib/
  addons.nix                 # addons_path synthesis
  odoo-ini.nix               # odoo.conf's INI dialect, for the dev shell and the NixOS module
  python.nix                 # the uv2nix Python environments
  odoo.nix                   # builtOdoo, the assembled tree
  raw-odoo.nix               # runs a tree's odoo-bin, or `python -m odoo` without one
  cli.nix                    # wraps builtOdoo, or the live checkout, in the odoo command
  cli-package.nix            # the odoo_nix_cli package
  cli-scripts.nix            # the workspace configuration `odoo module`, `odoo project update|relock` and `nix run .#relock` read
  cli-module.nix             # odoo_nix_cli as a Python module, for odoo-init and the relock app
  relock.nix                 # a project's `nix run .#relock`
  odoo_nix_cli/              # the odoo command (Python: click and rich)
    commands/                #   db, module, project, shell, test
    workspace/               #   module add, add-bundle, remove; project update, relock (relock.py: also nix run .#relock; lock.py: the lock, shared with nix run .#relock-fixtures)
    init/                    #   odoo-init, the scaffolder
    oca.py                   #   the OCA catalog and bundles
    migrate_plan.py          #   what odoo db migrate updates
    backups.py, backup_layout.py  # the remote backup store and its naming
  init.nix                   # packages the scaffolder
  oca_sources.py             # the managed blocks of pyproject.toml
  odoo-presets.json          # series → Python and branch
  devguard/odoo_devguard/    # the Odoo guards over python-devops-nix's core; dev environments only
  devguard.nix               # builds it with a project's settings baked in
  journald/odoo_journald/    # journald-native log lines for Odoo
  journald.nix               # grafts it into every environment
  odoo-ls.nix, odoo-ls-Cargo.lock  # odoo-ls, with a vendored lock (upstream commits none)
  overrides.nix              # lib.overrides
  build-deps.nix             # odoo-nix-build-deps
  shell-tools.nix            # odoo-nix-sources, -bootstrap, -db-nocow, -banner
  bootstrap.sh               # odoo-nix-bootstrap
  bootstrap-lock.nix         # the odoo-nix a project's flake.lock pins, read without evaluating it
  pr_policy.py               # the pr-policy check
data/
  oca-modules.json           # the vendored OCA catalog
  oca-bundles.json           # the hand-maintained bundles
  oca-repos.txt              # the OCA repositories the catalog is built from
  sync-oca-repos.sh, extract_manifests.py  # refresh the catalog
templates/project/           # what a new project is laid down from
tests/                       # the flake checks, their scripts and fixtures
docs/                        # these pages
```

## Checks

`nix flake check -L` runs everything. odoo-nix is a library, so its checks do what a project does: they build a real Odoo from a pinned OCB tree (`ocb-18`, `ocb-19` and `ocb-20`, `flake = false` inputs in the shape of [A repository of modules](../scaffolding/write-the-flake.md#a-repository-of-modules)) through `coreSource`, with the same library calls the flake-parts module makes. Checks are one derivation per assertion, so a failure names itself.

```bash
nix flake check -L                               # everything
nix build -L .#checks.x86_64-linux.<NAME>        # one check
```

| Checks | What they cover |
| --- | --- |
| `addons-*`, `odoo-ini-*`, `odoo-ini-render` | `lib/addons.nix` on synthetic trees and `lib/odoo-ini.nix`'s rendering. |
| `fixture-requires-python-<18\|19\|20>`, `built-odoo-addons-path-<18\|19\|20>`, `built-odoo-version-<18\|19\|20>`, `lock-audit-<18\|19\|20>`, `lock-fresh-<18\|19\|20>`, `build-deps-<18\|19\|20>` | Per series, without running Odoo: the fixture's `requires-python`, `builtOdoo`'s passthru, the fixture lock against the pinned OCB, the managed build-dependency block. |
| `lock-audit-*` | The stale-lock audit. |
| `built-odoo-<18\|19\|20>`, `odoo-init-<18\|19\|20>`, `odoo-test-<18\|19\|20>` | The assembled package, `-i base` against an in-sandbox PostgreSQL with no guard rails in production, and the fixture addon's Odoo tests including the guard rails. |
| `built-odoo-no-odoo-bin-<18\|19\|20>`, `raw-odoo` | The assembled package from an OCB tree without `odoo-bin`, and `lib/raw-odoo.nix` with stand-in trees. |
| `cli-lifecycle-<18\|19\|20>`, `cli-migrate-<18\|19\|20>`, `cli-project-backup-<18\|19\|20>`, `cli-remote-restore-<18\|19\|20>` | The `odoo` command end to end: provision, backup, drop and restore; migrations from build to build, including rollback; project backups; restores from a directory store. |
| `devguard-core`, `devguard`, `devguard-baked` | The guard rails, the shared core and odoo-nix's side, without Odoo or a network. |
| `backups`, `backup-layout` | The backup fetch layer and odoo-nix's naming. |
| `journald-formatter` | The `odoo_journald` graft. |
| `scaffold`, `odoo-init-unit` | `odoo-init` offline: every flag and exit code, and its pieces. |
| `odoo-module-cli`, `odoo-module-unit` | `odoo module add`, `add-bundle` and `remove` offline, and their pieces. |
| `relock`, `relock-stale-lock` | A project's `nix run .#relock` offline over a stale lock, and that it evaluates where the dev shell does not. |
| `sources`, `bootstrap`, `bootstrap-lock-*` | Shell entry's submodule checkout and the fresh-clone bootstrap. |
| `db-nocow` | The btrfs NOCOW handling (Linux). |
| `secrets-*`, `restore-*`, `settings-*`, `rename-*`, `identity-*`, `ports-*`, `mailpit-*`, `watch-*`, `ci-mode`, `tree`, `python-default-*`, `container-name*` | The flake-parts module's options, evaluated. |
| `service-*`, `nginx`, `service-<18\|19\|20>` | `services.odoo-nix`, evaluated, and in NixOS VMs (KVM) with a stub and with the real Odoo: migrations on deploy, rollback leaving Odoo down, nginx, X-Sendfile, the journal, hardening. |
| `nix-lint`, `shared-config`, `pr-policy`, `workflows` | `nixfmt-rs`, statix and deadnix; the shared editor and lint configuration; the pull-request policy; actionlint and zizmor. |

Everything that runs Odoo or a VM is Linux-only. `nix develop` gives a shell for working on odoo-nix itself, with `uv`, `nixfmt-rs` and `odoo-nix-relock-fixtures`; `nix fmt` formats the Nix files.

The fixtures are the smallest project-shaped workspace: a hand-written `pyproject.toml`, a committed `uv.lock` and one custom addon, with no `odoo/` in the tree. The build gets OCB from the `ocb-*` input through `coreSource`, and the tests run in `odooTestEnv`, so they run in the sandbox.

## What CI runs

The `check` workflow runs two jobs on every pull request and every push to `main`. `lint` runs every hook in `.pre-commit-config.yaml` over the whole tree with [prek](https://prek.j178.dev), with no Nix involved: the same command a developer's commit runs, so a hook that would rewrite a file fails the job. `flake` runs `nix flake check -L` and builds the scaffolder (`nix build .#default`). When a job fails, `report` comments every job's result on the pull request, with each failed check and the end of its build log, and edits that comment once the checks pass. `autofix` runs `nix fmt` and the hooks over a pull request's branch and pushes what they rewrite as a `style:` commit, then dispatches `check` and `pr-policy` on it, because a push made with the workflow's token starts no workflow: pull before you push again. A fork's branch is not the workflow's to push to, so there the `lint` log has the diff. `pr-policy` checks that the title and every commit are [conventional commits](https://www.conventionalcommits.org/) under `committed.toml`'s types and scopes, and refuses `!` and `BREAKING CHANGE`: a major release is a deliberate `Release-As: <N>.0.0` footer. Dependabot's pull requests skip only the 100-character subject limit. `release` runs release-please and moves the `release-N` branch. Dependabot's pull requests merge automatically once the required checks pass, except action updates and the OCB pins, which a person reviews.

## Re-locking

The weekly Dependabot pull request bumps `ocb-18`, `ocb-19` and `ocb-20`. `uv.lock` does not record OCB's revision, only what uv derived from it, so a bump is stale only when OCB's `install_requires` or its series changed. Then `lock-fresh-<MAJOR>` fails and prints the fix:

```bash
nix run .#relock-fixtures   # or: nix run .#relock-fixtures -- --upgrade
git add tests/fixtures/*/uv.lock tests/fixtures/*/pyproject.toml
```

It runs `uv lock` in each fixture with the series' interpreter, then syncs the build-dependency block, with the same code a project's `odoo project relock` locks with (`lib/odoo_nix_cli/workspace/lock.py`), including the lock-time shadow of the store path, except that any failed step fails it. It is odoo-nix's own: a project re-locks with [`odoo project relock` or its own `nix run .#relock`](../development/locks.md#re-locking-a-project).

odoo-ls does not commit a `Cargo.lock` upstream, so odoo-nix vendors one at `lib/odoo-ls-Cargo.lock`. A bump of `odoo-ls-src` needs it refreshed, or `nix build .#odoo-ls` fails:

```bash
nix run .#relock-odoo-ls
git add lib/odoo-ls-Cargo.lock
```

## The OCA catalog

`data/oca-modules.json` is the bundled catalog behind the module picker and the dependency resolver: one record per repository, module and series, with `repo`, `version`, `application`, `installable`, `depends`, `summary` and more. It covers 18.0, 19.0 and 20.0. Refreshing it is two commands:

```bash
data/sync-oca-repos.sh              # or: data/sync-oca-repos.sh 19.0
data/extract_manifests.py           # rewrites data/oca-modules.json
```

`sync-oca-repos.sh` keeps one bare mirror per repository of `data/oca-repos.txt` under the gitignored `data/.cache/`, fetching each series as a shallow branch and skipping repositories without it. A re-run moves each branch to OCA's current head. `extract_manifests.py` reads the manifests straight out of the git objects, with no working trees, and skips a manifest whose `version` disagrees with its branch. Both scripts carry their own series list (20.0, 19.0 and 18.0): keep them in step with `lib/odoo-presets.json` when a series is added or dropped.

`data/oca-bundles.json` is maintained by hand; add or edit a bundle there with no code change. `odoo module add <GIT_URL>` bypasses the catalog entirely.

## Building these pages

The documentation site is built from the shared workspace [Avunu/site-docs](https://github.com/Avunu/site-docs), where odoo-nix is a registered project; there is no site in this repository. The pages are plain Markdown that reads the same on GitHub: callouts are GitHub alerts, and links between pages are relative file links.

Every pull request that touches `docs/` runs the `Docs` workflow, which builds the workspace with the pull request's pages in place of odoo-nix's and checks them strictly, links included. To check locally, follow the site-docs README and run its check with `--only odoo-nix --source odoo-nix=<THIS_CHECKOUT>`.
