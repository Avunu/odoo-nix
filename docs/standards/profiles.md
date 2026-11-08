---
title: Profiles
description: The built-in profiles minimal and recommended@2.3, an organisation's own profile, the in-repo profile, and the order in which the layers and your table merge.
order: 1
tags: [standards, profiles, configuration]
updated: 2026-11-07
---

A profile is a TOML file that turns [modules](modules.md) on and off and sets their keys. Your `[tool.odoo-nix]` table names one with `profile`, and anything else in the table overrides it.

## The built-in profiles

`odoo-nix profile list` prints them:

| Profile | What it turns on |
| --- | --- |
| `minimal` | `dev-shell` only: the `flake.nix` inputs block, `.envrc` and the `.gitignore` block. Every other module is off. Frozen for all of odoo-nix 2.x |
| `recommended@2.3` | the vendor-neutral set: `dev-shell`, `editorconfig`, `python-lint`, `pylint-odoo`, `addon-manifest`, `js-xml`, `tests`, `workflow-lint`, `shell-lint`, `nix-lint`, `hygiene`, `dependabot` (weekly, a 7-day cooldown, the decision table) and `ci`. Off: `ide`, `commits`, `releases`, `packaging`, `repo-policy`, `readme`, `icons` |

`recommended` alone means the newest snapshot, `recommended@2.3` today. A snapshot never changes once a release ships it: a later minor that changes `recommended` adds `recommended@2.<minor>.toml`, and a table that names `recommended@2.3` keeps exactly what it had. The package's own test (`test_profiles.Frozen`) compares each built-in file's bytes with the digest it records.

`recommended@2.3` leaves `[org]` empty except `dev-docs-url` (`https://github.com/Avunu/odoo-nix/tree/main/docs/standards`, which `minimal` sets too) and `repo-url` (`https://github.com/{repo}`), and every rule that needs an organisation's values is skipped while they are: no required author, no website check, OCA's license list, no `oca-fix-manifest-website` hook. Nothing that needs editor taste (`ide`) or repository admin (`repo-policy`) is on.

## An organisation's profile

An org profile is a repository (or a directory) holding a `profile.toml`:

```toml
schema = 1
name = "avunu"
description = "Avunu's Odoo standards."
extends = "recommended@2.3"
requires-odoo-nix = ">=2.3,<3"

[org]
publisher = "Avunu LLC"
license = "LGPL-3"
github-owner = "Avunu"

[addon-manifest]
author = "Avunu LLC"
website = "https://github.com/{repo}"

[commits]
enable = true

[releases]
enable = true
branching = "develop+series"
```

Avunu's own profile is public at [Avunu/odoo-standards-profile](https://github.com/Avunu/odoo-standards-profile), with the repositories it covers listed in its `fleet.json`.

Beside it, a `templates/` directory may override a managed file's template (the overridable ones are marked in [Managed files](managed-files.md)) or add `[[extra-files]]` of its own, and `[[retire]]` entries delete files the organisation no longer wants. A file in `templates/` that is neither is refused (exit 2), so assets such as the icon `check icons --fix` copies (`icons.src-icon`, default `assets/addon-icon.png`) live beside `templates/`, not in it.

A checkout uses it in one of two ways:

| `profile =` | Where it comes from |
| --- | --- |
| `"github:<owner>/<repo>[/<ref>]"` | a flake input `standards-profile`, which the `flake.nix` inputs block declares and `flake.lock` pins. `odoo-nix repo rollout --profile-to` moves it |
| `"./<dir>"` | a directory of the checkout itself (an in-repo profile) |

Check a profile before you publish it:

```bash
odoo-nix profile validate profile.toml [--templates DIR]
```

It validates the schema, the `extends` and the `requires-odoo-nix` range, then syncs each of odoo-nix's fixture checkouts (a project and an addon repository) under the profile, in throwaway git repositories, so a template that does not render fails here and not in a repository. `--profile-path DIR` on `sync`, `config` and `profile show` reads the profile from a directory instead of its locked input, for the profile's own author.

`--profile-path` changes only where the profile is read from. The first sync of a checkout still locks the `standards-profile` input from the URL in `profile`, so before the profile's repository is published that lock fails (exit 3). To try an unpublished profile on a real checkout, opt in first, which fails at the lock, then lock the input from the profile's clone by hand, put the node's `original` back to the URL the inputs block names, and sync again. A checkout that has not opted in has no `.#odoo-init` of its own, so the first run uses odoo-nix's:

```bash
nix run github:Avunu/odoo-nix#odoo-init -- --standards github:<owner>/<repo>/<ref> --profile-path ../profile   # exits 3 at the lock
nix flake lock --override-input standards-profile "git+file://$(realpath ../profile)"
node='.nodes[.nodes.root.inputs["standards-profile"]].original'
jq "$node = {type: \"github\", owner: \"<owner>\", repo: \"<repo>\", ref: \"<ref>\"}" flake.lock > flake.lock.new
mv flake.lock.new flake.lock
nix run --no-pure-eval .#odoo-init -- --sync --profile-path ../profile
```

A checkout already opted in to another profile refuses `--standards` (exit 2). Set `profile = "github:<owner>/<repo>/<ref>"` in its table instead, and start at the `nix flake lock` line.

Do not commit the result: the lock names a local path.

## How the layers merge

1. The built-in profile (the table's `profile`, or the org profile's `extends`), then the org profile, then your table. Tables merge key by key; a scalar or a list replaces the one below it.
2. Each layer is validated on its own. Both files carry `schema = 1`. Some keys belong to the repository alone and are refused in a profile: `profile`, `shape`, `series`, `integration-branch`, `repo`, `retire-keep` and `[[tool.odoo-nix.untested]]`. The profile's own keys (`name`, `description`, `extends`, `requires-odoo-nix`, `[[retire]]`, `[[extra-files]]`) are refused in the table.
3. The schema's defaults fill what no layer set.
4. odoo-nix derives what follows from the checkout: `shape` and `series`; the integration branch (`develop` under `develop+series`, but `main` for a project that sets none); `dependabot.target-branches = []` becomes the integration branch; `addon-manifest.licenses-allowed = []` becomes `[org.license]` when the license is set.
5. The module rules: `dev-shell` cannot be turned off; a module whose needs are off is exit 2 (`releases` needs `commits` and `ci`, `repo-policy` needs `ci`, `ide` needs `python-lint` and `js-xml`); the GitHub-only modules (`dependabot`, `ci`, `repo-policy`, `releases`, `workflow-lint`) are off for a checkout that is not on GitHub.
6. `requires-odoo-nix` is checked against the running odoo-nix-tools (exit 3 when it is outside the range).

`odoo-nix profile show --explain` prints every value with the layer that set it: `builtin:recommended@2.3`, `org:<source>@<rev>`, `app` (your table) or `default`.

## Changing profile

Edit `profile` in the table and run `odoo-init --sync`. A module the new profile turns off is retracted: the files and the blocks it owned are removed, and only the keys and leaves it wrote come out of a merged file (`tools/pyproject.toml`, `package.json`, `.vscode/*.json`). `minimal` after `recommended` takes a repository back to the dev shell's files alone.
