---
title: CI
description: The gates odoo-nix's standards run, the caller workflows sync writes, the reusable odoo-*.yml workflows they call, the CI App, and the Dependabot decision table.
order: 4
tags: [standards, ci, github-actions, gates, dependabot]
updated: 2026-11-04
---

With `ci` on, sync writes small **caller** workflows into `.github/workflows/`. Each calls a **reusable** workflow of odoo-nix (`Avunu/odoo-nix/.github/workflows/odoo-*.yml`) at the revision your `flake.lock` pins, so CI moves only when odoo-nix does (`odoo-init --sync` rewrites the `uses:` SHAs). Every job is named `ci`, so a gate's check reads `ci / lint`, `ci / test` or `ci / pr-policy`. The required checks are the gates that are on: `lint` with any lint module, `test` with `tests` and an installable addon that is not `untested`, `pr-policy` with `commits` or `releases`. A gate that is off has no caller, so its check never reports; do not require it.

## The gates

A gate is one command that a developer runs the same way CI does.

### `lint`

```bash
nix develop --no-pure-eval .#odoo-nix-lint -c odoo-nix gate lint
```

| Step | What | Module |
| --- | --- | --- |
| `sync-check` | `odoo-nix sync --check` (with `--expect-rev $ODOO_NIX_EXPECT_REV`) | always |
| `prek` | every hook of `.pre-commit-config.yaml`, with `-c` | any hook module |
| `manifests` | `odoo-nix check manifests`: the website template, `<series>.x.y.z` versions, the series branch and `.odoo-series` | `addon-manifest` |
| `icons` | `odoo-nix check icons`: a square `static/description/icon.png` of at least `icons.min-size` pixels and at most `icons.max-bytes` bytes (`--fix` adds a missing one from the org profile's `icons.src-icon`) | `icons` |
| `submodules` | `odoo-nix check submodules`: every `.gitmodules` entry on `branch = <series>` (projects) | `ci` |
| `ratchet` | `odoo-nix ratchet coverage --base <merge-base>`: `fail_under` does not fall, `untested` does not grow | `tests` |

The lint shell is the one the odoo-nix your `flake.lock` pins builds over the checkout's path: it links `tools/.venv`, `tools/.bin` and `node_modules` from the checkout's locks, and never evaluates the checkout's own flake, so a project's submodules are not fetched.

### `test`

```bash
ODOO_NIX_CI=1 nix develop --no-pure-eval -c odoo-nix gate test
```

| Step | What | Module |
| --- | --- | --- |
| `modules` | the installable addons, less `[[tool.odoo-nix.untested]]` | `tests` |
| `postgres` | under `ODOO_NIX_CI`, a throwaway cluster: its data directory is `.odoo-nix/test/pg`, its socket in a temporary directory | `tests` |
| `odoo-test` | `odoo test <modules> --fresh-db --coverage tools/pyproject.toml --log .odoo-nix/test/odoo.log` | `tests` |
| `checklog` | checklog-odoo over that log with `checklog-odoo.cfg` | `tests.checklog` |
| `coverage` | combine, report against `fail_under`, write `coverage.xml` | `tests` |
| `manifestoo` | `check-licenses` and `check-dev-status` (an addon with no `development_status` counts as Beta, as in OCA) | `addon-manifest` |

Outside CI the test gate uses the dev shell's PostgreSQL. `COVERAGE_FILE` is `.odoo-nix/coverage/.coverage` unless you export one.

### What a gate reports

Every step runs, and a step whose module is off is skipped with the reason. `--report` (default `.odoo-nix/gate/<gate>.json`, schema `odoo-nix data-path schema/gate-report.schema.json`) lists each step's status, command, exit code and time; under GitHub Actions a table goes to the job summary and problems become `::error` annotations (`--format github`). The gate exits `1` when a step failed; `2` and `3` only for its own configuration and environment errors and those of the `odoo-nix …` sub-steps. A tool that exits non-zero, coverage under `fail_under` included, is a failed step, exit 1.

### `pr-policy`

`odoo-nix policy --pr` checks a pull request: its base is the integration branch, a `commits.pr-allowed-bases` glob or (with `commits.allow-stacked`) another open PR's head; its title and every commit pass `committed` with the rendered `committed.toml`; under `develop+series` no addon's manifest version was moved by hand (the bump owns it). A Dependabot PR is exempt from the subject length alone. `odoo-nix policy --commit-msg-file F` is the same per-commit check as a commit-msg hook.

## The callers

| Caller | Triggers | Calls |
| --- | --- | --- |
| `ci.yml` (`name: ci`), when the `lint` or the `test` gate is on | push to the integration branch, `pull_request`, `workflow_dispatch`, and `ci.schedules.ci` when set | `odoo-lint.yml`, `odoo-test.yml` (each gate that is on) |
| `pr-policy.yml` (`name: pr-policy`), only with `commits` or `releases` on | `pull_request` (opened, edited, synchronize, reopened), push to the integration branch, `workflow_dispatch` | `odoo-pr-policy.yml` (skipped on the push, which a required check counts as passed) |
| `release.yml` | push to the integration branch, `workflow_run` of `ci` on it, `workflow_dispatch`; concurrency `release`, never cancelled | `odoo-release.yml` ([Versioning](versioning.md#the-addons-release-flow)) |
| `deps.yml` | `pull_request`, push to the integration branch (with `dependabot.update-branches`), the `ci.project-update` schedule (projects), `workflow_dispatch` | `odoo-deps.yml` |

`release.yml` is written only where the checkout has a release branch: an addon repository with `releases` on.

## The reusable workflows

All of them pin every action by SHA, pass inputs through `env:`, clear `$RUNNER_TEMP` on self-hosted runners, and run a fork's pull request on `ubuntu-latest` whatever `ci.runs-on` says. A job that can hold the CI App's private key runs on GitHub-hosted `ubuntu-latest` whatever `ci.runs-on` says, and runs none of the repository's addons or their dependencies: `odoo-release.yml`'s `release`; `odoo-release-please.yml`'s `release-please`, `sync` and `upload` (its `package` job builds the zip and the wheel with no secret and hands them over as an artifact); and `odoo-deps.yml`'s `relock-push`, `automerge` and `update-branches`. Each installs odoo-nix-tools hash-locked before it mints the token (`standards-install` with `hardened: "true"`: from `Avunu/odoo-nix` only, at the full revision `flake.lock` pins, every dependency from that revision's `py/odoo_nix_tools/uv.lock` by hash, with a pinned uv and no uv cache), and none restores a cache a job that ran the repository's code could have saved (`package` uses none). `relock-push` checks out the event's head SHA, applies only an allowlisted patch (`nix/uv.lock` and `nix/pyproject.toml`, regular files: no `flake.lock`, workflow, mode change, symlink or rename), and pushes without force; it and `automerge` compute whether the PR moves a rollout input from the `flake.lock`s through the API, not from `relock-plan`, and `automerge` takes `relock-plan`'s "nothing to relock" only for a PR whose files are `flake.lock` and the relock's. `repackage` runs on `ubuntu-latest` too, and `upload` refuses any tag but the dispatch's `repackage` one. Two jobs still mint the App's token on `ci.runs-on` in the job that runs the repository's code: `odoo-test.yml`'s `test` (the token fetches private submodules before the tests run) and `odoo-deps.yml`'s `project-update` (before `odoo project update`). On a GitHub-hosted runner, `odoo-test.yml` also deletes the preinstalled toolchains it doesn't use and clones submodules at depth 1, because Nix clones each submodule's full history itself.

| Workflow | Inputs | What it runs |
| --- | --- | --- |
| `odoo-lint.yml` | `integration-branch`, `runs-on` | the lint shell of the locked odoo-nix, then `odoo-nix gate lint --format github` |
| `odoo-test.yml` | `integration-branch`, `runs-on`, `test-timeout-minutes`, `client-id`; secret `APP_PRIVATE_KEY` | the checkout with its submodules (the App's token for private ones), a port offset of its own (`ODOO_NIX_PORT_OFFSET`, the first free from a hash of the run, attempt and runner, so jobs sharing a self-hosted host don't meet on the project's hashed ports), `ODOO_NIX_CI=1 nix develop --no-pure-eval -c odoo-nix gate test`, the log and `coverage.xml` as an artifact |
| `odoo-pr-policy.yml` | `integration-branch`, `runs-on` | odoo-nix-tools installed at the locked revision, `committed` from the locked odoo-nix, then the policy |
| `odoo-release.yml` | `integration-branch`, `release-branch` (required), `runs-on`, `client-id`; secret `APP_PRIVATE_KEY` | the bump and the fast-forward, with the App's token |
| `odoo-deps.yml` | `shape` (required), `integration-branch`, `runs-on`, `auto-merge`, `auto-merge-policy`, `update-branches`, `merge-method`, `client-id`; secret `APP_PRIVATE_KEY` | `relock-plan`/`relock-push` (addons), `automerge`, `update-branches`, `project-update` (projects) |

Where a job needs `odoo-nix` itself, it installs odoo-nix-tools at the odoo-nix revision the checkout's `flake.lock` pins (with `uv tool install`, or, in a job that can hold the CI App's key, hash-locked from that revision's `uv.lock`), through python-devops-nix's composite actions (`standards-install`, then `standards-pr-policy`, `standards-release-ff`, `standards-deps-automerge` or `standards-update-branches`); `standards-install` exports `ODOO_NIX_EXPECT_REV` for the skew check. It reads the revision from `flake.lock`'s `odoo-nix` node, which must be locked from a `github:` URL: with `dev-shell.odoo-nix-url` set to a `git+…` URL, `odoo-pr-policy.yml`, `odoo-release.yml`, `odoo-deps.yml` and `fleet-audit.yml` fail (`odoo-lint.yml` and `odoo-test.yml` still run). Nix runs what needs it: the lint shell, the test gate, `committed`, the relock and `odoo project update`.

### The CI App

`ci.github-app` names the Actions variable that holds a GitHub App's client ID and the secret that holds its private key:

```toml
[tool.odoo-nix.ci]
github-app = { app-id = "AVUNU_CI_APP_ID", private-key = "AVUNU_CI_PRIVATE_KEY" }
```

The release flow needs it: the bump commit and the series branch's move are pushed with its token, which the integration ruleset lets past its pull-request rule. `odoo-deps.yml` uses it when it is there, so its pushes, PRs and merges start CI by themselves. Without one (`""`, the default), `GITHUB_TOKEN` pushes raise no event, so the jobs dispatch `ci.yml` and `pr-policy.yml` on the new head instead. A Dependabot run sees only Dependabot secrets: store the private key there too. `odoo-nix repo doctor` lists what is missing ([Fleet](fleet.md#repo-doctor)).

## Dependabot

`.github/dependabot.yml` updates GitHub Actions and the Nix inputs, one entry per `dependabot.target-branches` branch (default: the integration branch), on `dependabot.schedule` with a `cooldown-days` cooldown, except for an addon repository's `ocb` input, which follows the branch tip (a cooldown would lock an odoo/odoo commit that OCB merged, which has no OCB `pyproject.toml`); its `updates` local region takes your own entries (an addon's own `package.json`, say). The locked tools (`tools/uv.lock`, `package-lock.json`) are not configured: they follow the series data.

With `dependabot.auto-merge`, `odoo-deps.yml` gives every Dependabot PR a verdict, `auto` (auto-merge, where every enabled gate is a required check of the integration branch), `review` (labelled `needs-review`), `relock` or `close`. The first rule of the PR's ecosystem that matches decides:

| # | Ecosystem | Matches | Verdict |
| --- | --- | --- | --- |
| 1 | github-actions | odoo-nix's reusable workflows (`$engine`, `Avunu/odoo-nix/*`) | review, sticky: they move with the locked odoo-nix |
| 2 | github-actions | `Avunu/python-devops-nix`, `Avunu/python-devops-nix/*` | review, sticky |
| 3, 4 | github-actions | grouped, or a single named action | auto |
| 5 | nix | `odoo-nix`, `standards-profile` | close: they move with `odoo-nix repo rollout` |
| 6 | nix | any other input (nixpkgs, `ocb`, an `oca-*` source) | relock: `nix run .#relock` on the PR first (addons mode) |
| 7, 8 | npm, uv | the locked tools at `/` and `/tools` | close, sticky |
| 9 | npm | an addon's own `package.json`, minor or patch | auto |
| 10 | submodules | a project's submodule | relock |

No match is `review`. `dependabot.auto-merge-policy = "all"` auto-merges everything a sticky rule does not hold. A nix PR in an addon repository is relocked by `relock-plan` (which runs the PR's code with no write token) and `relock-push` (which applies the patch with the App's token); in a project nothing relocks it here, so its verdict leaves it to a person, and `project-update` (on `ci.project-update`'s schedule) moves every submodule to its branch's tip with `odoo project update`, relocks, and opens `standards/project-update`. With `dependabot.update-branches`, bot PRs that fall behind the integration branch are brought up to date on every push.
