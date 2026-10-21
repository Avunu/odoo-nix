---
title: Repository layout
description: Where things live in the odoo-nix repository, the flake checks and what CI runs, how the pinned test fixtures, odoo-ls lock and OCA catalog are refreshed, and how these pages are checked.
order: 5
tags: [contributing, layout, checks, ci]
updated: 2026-10-21
---

## Layout

```text
flake.nix                    # inputs; flakeModules, nixosModules, lib, packages, apps, checks
modules/
  flake-module.nix           # imports devenv's flake module, secrets.nix, devenv.nix, containers.nix
  devenv.nix                 # the perSystem.odoo-nix options and the dev shell
  containers.nix             # the OCI image
  nixos.nix                  # services.odoo-nix
  secrets.nix                # odoo-nix.secrets: python-devops-nix's lib.secrets.mkModule
addons/
  dev_mailcatch/             # deprecated no-op stub; the mail guard replaced it
lib/
  addons.nix                 # addons_path synthesis
  odoo-conf.nix              # odoo.conf synthesis
  python.nix                 # the uv2nix Python environments
  odoo.nix                   # builtOdoo, the assembled tree
  cli.nix                    # wraps builtOdoo, or the live checkout, in the odoo command
  cli-package.nix            # the odoo_nix_cli package
  cli-scripts.nix            # the workspace configuration `odoo module` reads, and `project update`'s script
  odoo_nix_cli/              # the odoo command (Python: click and rich)
    commands/                #   db, module, project, shell, test
    workspace/               #   module add, add-bundle, remove
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
  core-shadow.sh             # the writable lock-time shadow of a store-resident OCB (coreSource)
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

`nix flake check -L` runs everything. odoo-nix is a library, so its checks do what a project does: they build a real Odoo from a pinned OCB tree (`ocb-18` and `ocb-19`, `flake = false` inputs in the shape of [A repository of modules](../scaffolding/write-the-flake.md#a-repository-of-modules)) through `coreSource`, with the same library calls the flake-parts module makes. Checks are one derivation per assertion, so a failure names itself.

```bash
nix flake check -L                               # everything
nix build -L .#checks.x86_64-linux.<NAME>        # one check
```

| Checks | What they cover |
| --- | --- |
| `eval-addons-*`, `eval-odoo-conf-*`, `odoo-conf-render` | `lib/addons.nix` on synthetic trees and `lib/odoo-conf.nix`'s rendering. |
| `eval-*-<18\|19>`, `lock-fresh-<18\|19>`, `build-deps-<18\|19>` | Per series, without running Odoo: the fixture's `requires-python`, `builtOdoo`'s passthru, the fixture lock against the pinned OCB, the managed build-dependency block. |
| `eval-lock-audit-*` | The stale-lock audit. |
| `builtOdoo-<18\|19>`, `odoo-init-<18\|19>`, `odoo-test-<18\|19>` | The assembled package, `-i base` against an in-sandbox PostgreSQL with no guard rails in production, and the fixture addon's Odoo tests including the guard rails. |
| `cli-lifecycle-<18\|19>`, `cli-migrate-<18\|19>`, `cli-project-backup-<18\|19>`, `cli-remote-restore-<18\|19>` | The `odoo` command end to end: provision, backup, drop and restore; migrations from build to build, including rollback; project backups; restores from a directory store. |
| `devguard-core`, `devguard`, `devguard-baked` | The guard rails, the shared core and odoo-nix's side, without Odoo or a network. |
| `backups`, `backup-layout` | The backup fetch layer and odoo-nix's naming. |
| `journald-formatter` | The `odoo_journald` graft. |
| `scaffold`, `odoo-init-unit` | `odoo-init` offline: every flag and exit code, and its pieces. |
| `module-cli`, `module-unit` | `odoo module add`, `add-bundle` and `remove` offline, and their pieces. |
| `sources`, `bootstrap`, `eval-bootstrap-lock-*` | Shell entry's submodule checkout and the fresh-clone bootstrap. |
| `db-nocow` | The btrfs NOCOW handling (Linux). |
| `eval-secrets-*`, `eval-restore-*`, `eval-rename-*`, `eval-identity-*`, `eval-ports-*`, `eval-mailpit-*`, `eval-watch-*`, `eval-ci-mode`, `eval-tree`, `eval-python-default-*`, `eval-container-name*` | The flake-parts module's options, evaluated. |
| `eval-module-*`, `module-nginx`, `module-odoo-<18\|19>` | `services.odoo-nix`, evaluated, and in NixOS VMs (KVM) with a stub and with the real Odoo: migrations on deploy, rollback leaving Odoo down, nginx, X-Sendfile, the journal, hardening. |
| `nix-lint`, `shared-config`, `pr-policy`, `workflows` | `nixfmt-rs`, statix and deadnix; the shared editor and lint configuration; the pull-request policy; actionlint and zizmor. |

Everything that runs Odoo or a VM is Linux-only. `nix develop` gives a shell for working on odoo-nix itself, with `uv`, `nixfmt-rs` and `odoo-nix-relock`; `nix fmt` formats the Nix files.

The fixtures are the smallest project-shaped workspace: a hand-written `pyproject.toml`, a committed `uv.lock` and one custom addon, with no `odoo/` in the tree. The build gets OCB from the `ocb-*` input through `coreSource`, and the tests run in `odooTestEnv`, so they run in the sandbox.

## What CI runs

The `check` workflow runs `nix flake check -L` and builds the scaffolder (`nix build .#default`) on every pull request and every push to `main`. `pr-policy` checks that the title and every commit are [conventional commits](https://www.conventionalcommits.org/) under `committed.toml`'s types and scopes, and refuses `!` and `BREAKING CHANGE`: a major release is a deliberate `Release-As: <N>.0.0` footer. Dependabot's pull requests skip only the 100-character subject limit. `release` runs release-please and moves the `release-N` branch. Dependabot's pull requests merge automatically once the required checks pass, except action updates and the OCB pins, which a person reviews.

## Re-locking

The weekly Dependabot pull request bumps `ocb-18` and `ocb-19`. `uv.lock` does not record OCB's revision, only what uv derived from it, so a bump is stale only when OCB's `install_requires` or its series changed. Then `lock-fresh-<MAJOR>` fails and prints the fix:

```bash
nix run .#relock            # or: nix run .#relock -- --upgrade
git add tests/fixtures/*/uv.lock tests/fixtures/*/pyproject.toml
```

It runs `uv lock` in each fixture with the series' interpreter, then syncs the build-dependency block, the same tail `odoo project update` runs in a project.

odoo-ls does not commit a `Cargo.lock` upstream, so odoo-nix vendors one at `lib/odoo-ls-Cargo.lock`. A bump of `odoo-ls-src` needs it refreshed, or `nix build .#odoo-ls` fails:

```bash
nix run .#relock-odoo-ls
git add lib/odoo-ls-Cargo.lock
```

## The OCA catalog

`data/oca-modules.json` is the bundled catalog behind the module picker and the dependency resolver: one record per repository, module and series, with `repo`, `version`, `application`, `installable`, `depends`, `summary` and more. It covers 18.0 and 19.0. Refreshing it is two commands:

```bash
data/sync-oca-repos.sh              # or: data/sync-oca-repos.sh 19.0
data/extract_manifests.py           # rewrites data/oca-modules.json
```

`sync-oca-repos.sh` keeps one bare mirror per repository of `data/oca-repos.txt` under the gitignored `data/.cache/`, fetching each series as a shallow branch and skipping repositories without it. `extract_manifests.py` reads the manifests straight out of the git objects, with no working trees, and skips a manifest whose `version` disagrees with its branch. Both scripts carry their own series list (19.0 and 18.0): keep them in step with `lib/odoo-presets.json` when a series is added or dropped.

`data/oca-bundles.json` is maintained by hand; add or edit a bundle there with no code change. `odoo module add <GIT_URL>` bypasses the catalog entirely.

## Building these pages

The documentation site is built from the shared workspace [Avunu/site-docs](https://github.com/Avunu/site-docs), where odoo-nix is a registered project; there is no site in this repository. The pages are plain Markdown that reads the same on GitHub: callouts are GitHub alerts, and links between pages are relative file links.

Every pull request that touches `docs/` runs the `Docs` workflow, which builds the workspace with the pull request's pages in place of odoo-nix's and checks them strictly, links included. To check locally, follow the site-docs README and run its check with `--only odoo-nix --source odoo-nix=<THIS_CHECKOUT>`.
