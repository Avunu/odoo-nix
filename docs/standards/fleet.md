---
title: Fleet
description: An organisation's fleet.json, and the repo commands over it, apply, audit, doctor, rollout and targets, with odoo-nix's scorecard rows and the scheduled fleet-audit.yml.
order: 6
tags: [standards, fleet, repo-policy, audit, github]
updated: 2026-11-04
---

An organisation keeps the list of its repositories in its profile repository, as `fleet.json`. The `odoo-nix repo …` commands take that list (`--all --fleet fleet.json`) or one or more `<owner>/<repo>`.

## `fleet.json`

```json
{
  "schema": 1,
  "profile": "github:Avunu/odoo-standards-profile",
  "repos": [
    { "repo": "Avunu/edi-addons", "shape": "addons", "branches": ["develop", "18.0"], "private": false },
    { "repo": "Avunu/millrun", "shape": "project", "branches": ["main"], "private": true }
  ]
}
```

| Key | Meaning |
| --- | --- |
| `repo` | `<owner>/<name>` (required) |
| `shape` | `"project"` or `"addons"` (required): a repository that has not opted in yet is read with it |
| `branches` | the branches that matter (required): the integration branch first, then an addon repository's series branch |
| `private` | `true` keeps `repo apply --phase full` off the repository (required) |
| `integration_branch` | when it is not `branches[0]` |
| `profile` | this repository's profile, over the file's `profile` |
| `documentation` | an `https://` URL |

`odoo-nix repo targets --all --fleet fleet.json` prints each repository's branches, integration branch, opt-in state, profile and privacy.

## `repo apply`

Sets a repository's settings, labels and rulesets from the rendered `repo-policy` (module `repo-policy`; a repository with it off is skipped with a notice). It reads what the repository has and writes only what differs; a ruleset it does not know is listed, never deleted. `--dry-run` reads and prints a JSON diff per repository. It needs an admin token.

- **`--phase provisional`** works on a repository that has not opted in: the integration ruleset, from the fleet entry's shape and integration branch and the fleet's profile, and the default branch moved to the integration branch.
- **`--phase full`** needs the repository's own table, and adds the rest: the required checks (`ci / lint`, `ci / test`, `ci / pr-policy`, the gates that are on) and, under `develop+series`, the release ruleset.

odoo-nix's rulesets: an addon repository's release ruleset protects its series branch alone (`refs/heads/18.0`, from `.odoo-series`), not every `*.0`, so a maintenance branch such as `17.0` still takes pull requests; its bypass actor is `repo-policy.release-bypass`, which must name the CI App by its numeric id (`"integration:123456"`) for the bump to be pushed. A project has no release branch, so its integration ruleset has no bypass actor at all.

## `repo audit`

The scorecard: for each repository, a shallow clone of its integration branch, and rows that each read `green`, `amber`, `red`, `n/a` (the module is off) or `unknown` (the token cannot read it).

| Row | Module | Green when |
| --- | --- | --- |
| A1 | `repo-policy` | the default branch is the integration branch |
| A2 | `releases` | the release branch equals the integration head, or is behind it only by commits whose checks are pending |
| A3 | `repo-policy` | the settings and rulesets match the rendering |
| A4 | always | the managed files are present and `sync --check` is clean, with the odoo-nix-tools the checkout's `flake.lock` pins (`uv tool run`; `--against latest`: the latest release's) |
| A5 | `ci` | the gates are green on the integration branch |
| A9 | always | no file a retire rule names is left |
| A10 | `dependabot` | the last nix bump merged with its relock; odoo-nix and the profile current |
| A11 | `releases` | a release tag exists (tags flow only; n/a under odoo-series) |
| A12 | `releases` | (addon repositories) the fleet entry's `branches` list the series `.odoo-series` names; Dependabot targets the integration branch and no branch the release ruleset protects |
| A13 | `ci` | (projects) every submodule's `.gitmodules` entry has `branch = <series>` |

A12 and A13 are odoo-nix's; the rest are standards-core's. `--format md|json`, `--out FILE`, and `--issue --issue-repo <owner/repo>` keeps one `scorecard: <repo>` issue per repository there. Exit 1 when any row is amber or red.

## `repo doctor`

Read-only, no admin needed: for the checkout in the current directory, or `<owner>/<repo>`, the repository settings the enabled modules rely on, each `ok`, `missing` or `unknown`, with where to change it. Beside the core's rows (Actions may create pull requests, auto-merge allowed, every gate a required check, the labels, a private profile's fetch token), odoo-nix adds, for an addon repository under `develop+series`:

- the Actions variable `ci.github-app.app-id` names (the App's client ID) and the Actions secret `ci.github-app.private-key` names, on the repository or shared from the organisation; a blank name is its own `missing` row;
- `repo-policy.release-bypass` as `integration:<numeric id>`: the App's id from its settings page, not the client ID the variable holds.

A project with `ci.project-update` set and no CI App gets a notice: its `standards/project-update` pull requests are opened with `GITHUB_TOKEN`, so their CI is dispatched rather than triggered.

## `repo rollout`

Moves repositories to an odoo-nix release (`--to vX.Y.Z`) or an org profile release (`--profile-to <ref>|latest`), one pull request each. See [Versioning](versioning.md#how-a-release-reaches-a-repository).

## The scheduled audit

odoo-nix ships the reusable `fleet-audit.yml`. The profile repository, whose `flake.lock` pins odoo-nix, calls it:

```yaml
on:
  schedule: [{ cron: "0 5 * * 1" }]
  workflow_dispatch:
permissions: {}
jobs:
  audit:
    uses: Avunu/odoo-nix/.github/workflows/fleet-audit.yml@<sha> # v2.3.0
    permissions:
      contents: read
      issues: write
    with:
      issue-repo: ${{ github.repository }}
    secrets:
      AUDIT_TOKEN: ${{ secrets.AUDIT_TOKEN }}
```

Inputs: `fleet` (default `fleet.json`), `issue-repo` (default none), `against` (`pinned` or `latest`), `runs-on`. It installs the odoo-nix-tools the profile repository pins (python-devops-nix's `standards-install`) and runs `odoo-nix repo audit --all` through `standards-fleet-audit`: the scorecard goes to the job summary and, with `issue-repo`, to the issues, and the job fails when any row is amber or red. `AUDIT_TOKEN` is a read-only token over the fleet (Administration, Contents, Actions and Variables read; Secrets read for the doctor rows); without it the rows that need it read `unknown`.
