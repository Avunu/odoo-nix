---
title: Versioning
description: How odoo-nix and odoo-nix-tools are released and pinned, the frozen profile snapshots, the version-skew checks, how a release reaches your repositories, and the addons' <series>.x.y.z release flow.
order: 5
tags: [standards, versioning, releases, skew]
updated: 2026-11-04
---

## odoo-nix's own releases

odoo-nix and odoo-nix-tools are one release with one version: `version.txt`, `py/odoo_nix_tools/pyproject.toml` and `odoo_nix_tools.__version__` move together (the `standards-version` check holds them equal). release-please opens the release pull request on `main` from the conventional commits since the last tag: `fix:` makes a patch, `feat:` a minor, and a major is only a `Release-As: <N>.0.0` footer (pr-policy refuses `!` and `BREAKING CHANGE`). On the release pull request, a `fixtures` job re-renders the standards fixtures for the new version (odoo-nix-tools' dev lock, and on a major the fixtures' `release-<major>` URLs) and pushes them to the PR's branch, so every commit on `main`, the release's included, keeps its checks green. After the merge it tags `vX.Y.Z` and fast-forwards **`release-<major>`** (`release-2` for every 2.x) to the tag.

A checkout follows that branch: the `dev-shell` inputs block writes `odoo-nix.url = "github:Avunu/odoo-nix/release-2";` (`dev-shell.odoo-nix-url` overrides it), and `flake.lock` pins the commit. The caller workflows name the same commit and its version: `uses: Avunu/odoo-nix/.github/workflows/odoo-lint.yml@<sha> # v2.3.0`.

## Profile snapshots

A built-in profile never changes once a release ships it (see [Profiles](profiles.md#the-built-in-profiles)): `minimal` is frozen for 2.x, and `recommended@2.3` is the first `recommended` snapshot. A minor that changes `recommended` adds `recommended@2.<minor>.toml`, so a checkout that names a snapshot keeps its rules across odoo-nix upgrades, and one that names plain `recommended` moves to the newest on its next sync.

An org profile states the odoo-nix it needs with `requires-odoo-nix = ">=2.3,<3"`; a checkout whose odoo-nix-tools falls outside the range is exit 3.

## Version skew

The files in a checkout, its `flake.lock` and the tools that check them must name one odoo-nix. `sync --check` (and so the lint gate) reports each disagreement as exit 3:

1. **The tools**: `--expect-rev` (`$ODOO_NIX_EXPECT_REV`; in CI the lint gate's `odoo-lint.yml` exports it from its own step reading `flake.lock`, and `standards-install` exports it in the jobs that install with uv) must be the odoo-nix revision `flake.lock` pins.
2. **The callers**: every `uses:` of an `odoo-*.yml` workflow must name the locked revision and the running version.
3. **The core**: the standards-core the tools run must be the python-devops-nix commit the locked odoo-nix pins.

`ODOO_NIX_ALLOW_SKEW=1` turns the three off, for odoo-nix's own tests and fixtures. Locally `odoo-init --sync` runs from the odoo-nix the lock pins (after phase A locks the flake it re-executes there when that is another release), so a sync never writes files for a different odoo-nix than the lock's.

## How a release reaches a repository

Dependabot never moves `odoo-nix` or `standards-profile` (the decision table closes those PRs). A release reaches a checkout through:

```bash
odoo-nix repo rollout --to v2.3.0 --repo Avunu/edi-addons      # or --all --fleet fleet.json
odoo-nix repo rollout --profile-to latest --all --fleet fleet.json
```

For each repository, in a temporary clone of its integration branch: `nix flake update odoo-nix` (or `standards-profile`), `nix run --no-pure-eval .#relock`, `nix run --no-pure-eval .#odoo-init -- --sync`, then a commit `chore(deps): odoo-nix v2.3.0`, a push of `standards/odoo-nix-v2.3.0`, a pull request and, unless `--no-auto-merge`, auto-merge. It runs with your own `gh` token (scope `workflow`): the bump rewrites caller workflows, which `GITHUB_TOKEN` cannot push. `--dry-run` prints the plan.

## odoo-nix's pin of standards-core

odoo-nix reaches the engine three ways: `flake.lock`'s `python-devops-nix` node, the `standards-core @ git+https://github.com/Avunu/python-devops-nix@<sha>#subdirectory=standards` dependency of odoo-nix-tools (what `uv tool install` resolves), and every `Avunu/python-devops-nix/…@<sha>` in `.github/**`. They name one commit, which is on python-devops-nix's `main` or a `v*` tag. `nix run .#bump-base -- <tag|sha> [COMMENT]` moves all three at once, and the dev lock (`py/odoo_nix_tools/uv.lock`) with them; the `standards-core-pins` flake check compares them offline, and check.yml's `standards-core-pins` job adds the reachability. Dependabot is told to leave them alone.

## The addons' release flow

Under `releases` (addon repositories), each addon carries its own version, `<series>.x.y.z` (`releases.version-scheme = "odoo-series"`), raised from the conventional commits that touch it:

| Commit | Raises | `18.0.1.2.3` becomes |
| --- | --- | --- |
| `fix:`, `perf:` | z | `18.0.1.2.4` |
| `feat:` | y, z to 0 | `18.0.1.3.0` |
| `!` or `BREAKING CHANGE` | x, y and z to 0 | `18.0.2.0.0` |

A change only under `tests/`, `README.md`/`README.rst`, `readme/`, `i18n/`, `i18n_extra/` or `static/description/` raises nothing. A `Release-As` footer is refused (each addon's version moves in `ci bump`), and odoo-series makes no tags. The version prefix must be the series (`17.0.1.0.0` in an 18.0 repository is a `check manifests` problem).

`releases.branching = "develop+series"` (the default) is a post-merge-bump flow:

1. Pull requests target **`develop`**. pr-policy refuses a pull request that moves a manifest's version by hand.
2. After each merge, `release.yml` runs `odoo-release.yml`: `odoo-nix ci bump --base origin/<series> --push` writes the new versions into the manifests and pushes one `chore(release): bump <addons>` commit to `develop` with the CI App's token (the integration ruleset lets the App past its pull-request rule).
3. `odoo-nix ci fast-forward --release-branch <series> --wait-checks 900` moves the **series branch** (`18.0`, the one `.odoo-series` names) to that commit once its required checks are green. Still pending, the next run (the `workflow_run` of ci) retries; a bump push that loses a race to a newer merge is not a failure, because the run for the new head bumps.

Nothing but the release automation moves the series branch: with `repo-policy` on, its ruleset is the series alone (`refs/heads/18.0`), so a maintenance branch of another series, such as Dependabot's second target `17.0`, still merges pull requests. The `trunk` branching has no release branch and no flow: pull requests target `main` and versions are yours.

A project has no series branch: its release branch is `""`, so neither `release.yml` nor a release ruleset is rendered, and its integration ruleset lets no actor bypass it.
