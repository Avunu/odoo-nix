---
title: Modules
description: Every module of odoo-nix's standards, the keys each takes in [tool.odoo-nix] or a profile, their defaults, and the rules between modules.
order: 2
tags: [standards, modules, configuration, reference]
updated: 2026-11-04
---

A module is one switch, `<module>.enable`, and the keys that tune it. Set them in a profile or in your table, as a subtable or as dotted keys:

```toml
[tool.odoo-nix]
schema = 1
profile = "recommended"
commits.enable = true

[tool.odoo-nix.python-lint]
extra-select = ["PLR"]
```

`odoo-nix config modules.<module>` prints the effective switch, after the [module rules](profiles.md#how-the-layers-merge); `odoo-nix config <module>.<key>` prints a key. The defaults below are the schema's: `recommended@2.3` sets the same values and turns on the modules marked **rec**.

## Repository keys

These belong to the repository's table alone; a profile that sets one is refused. Both a profile and the table carry `schema = 1`, and the profile's own keys (`name`, `description`, `extends`, `requires-odoo-nix`, `[[retire]]`, `[[extra-files]]`) are refused in the table.

| Key | Meaning |
| --- | --- |
| `profile` | `minimal`, `recommended`, `recommended@<minor>`, `github:<owner>/<repo>[/<ref>]` or `./<dir>` ([Profiles](profiles.md)) |
| `shape` | `"project"` or `"addons"`, when the files show both |
| `series` | the Odoo series (`"18.0"`), overriding `.odoo-series` and the other sources |
| `integration-branch` | the branch pull requests target; `--standards` writes it when `origin/HEAD` names another branch than the default (`develop` under `develop+series`, `main` for a project) |
| `repo` | `<owner>/<name>`, for a checkout whose remote is not `origin` |
| `retire-keep` | paths the retire rules must leave alone |
| `[[tool.odoo-nix.untested]]` | `addon = "<name>"` and `reason = "…"` (at least 10 characters), both required: an installable addon the test gate does not install. The coverage ratchet refuses a new entry in a pull request |

## Modules and keys

| Module | rec | What it manages | Keys (default) |
| --- | --- | --- | --- |
| `dev-shell` | on | the `flake.nix` inputs block, `.envrc`, the `.gitignore` block. Required: `enable = false` is exit 2 | `odoo-nix-url` (`""`: `github:Avunu/odoo-nix/release-<major>`; keep it a `github:` URL, since the CI workflows that install odoo-nix-tools read a `github` lock node only: [CI](ci.md#the-reusable-workflows)) |
| `editorconfig` | on | `.editorconfig`: OCA's sections for the series, plus 2-space Nix and shell | — |
| `python-lint` | on | ruff with OCA's per-series rules in `.ruff.toml`, the locked ruff in `tools/.venv` | `extra-select` (`[]`), `ignore` (`[]`), `per-file-ignores` (`{}`), `extend-exclude` (`[]`) |
| `pylint-odoo` | on | pylint-odoo with OCA's `.pylintrc` and `.pylintrc-mandatory` | `optional-run` (`true`: the optional checks run as an advisory hook) |
| `addon-manifest` | on | the manifest rules | `author` (`""`: none required), `licenses-allowed` (`[]`: `[org.license]` when set, else OCA's list), `website` (`""`: none checked; a template with `{repo}`, `{repo_name}`) |
| `js-xml` | on | prettier and eslint for JavaScript and XML, locked in `package.json` and `package-lock.json` | `exclude` (`[]`: path prefixes both skip, such as `static/dist/`) |
| `ide` | off | `.vscode/settings.json` and `.vscode/extensions.json`, merged ([Editors](../development/editors.md#the-ide-module)). Needs `python-lint` and `js-xml` | `agents` (`false`: `AGENTS.md`, `CLAUDE.md` and Claude Code's hooks, [Agents](agents.md)) |
| `tests` | on | the test gate: Odoo's tests with coverage, checklog-odoo, the coverage floor | `initial-floor` (`0`: `fail_under`, written once), `goal` (`80`, recorded for reference: no report shows it yet, and it is never a gate), `checklog` (`true`) |
| `workflow-lint` | on | actionlint and zizmor over `.github` | — |
| `shell-lint` | on | shellcheck, when the repository has shell scripts | — |
| `nix-lint` | on | nixfmt, statix and deadnix, when it has Nix files | — |
| `hygiene` | on | OCA's pre-commit-hooks checks, check-json and check-yaml, the forbidden-file rules, `.git-blame-ignore-revs` | `forbid-contributing` (`true`: keep OCA's rule against a `CONTRIBUTING.md`) |
| `commits` | off | `committed.toml` and the pull-request policy | `convention` (`"conventional"` or `"odoo"`), `scopes` (`"addons"`: the addon names, or `"any"`), `extra-scopes` (`[]`), `extra-types` (`[]`), `allow-stacked` (`true`), `pr-allowed-bases` (`[]`), `subject-length` (`100`) |
| `releases` | off | the post-merge bump of each addon's version and the series branch's fast-forward. Addon repositories only. Needs `commits` and `ci` | `branching` (`"develop+series"` or `"trunk"`), `version-scheme` (`"odoo-series"` or `"semver"`), `tag-prefix` (`"v"` or `""`; the prefix of release tags, which means nothing under `odoo-series`: that flow makes no tags), `tool` (standards-core's key: `"none"` turns the module off like `enable = false`; odoo-nix reads no other value) |
| `packaging` | off | a whool `pyproject.toml` per addon (the `whool-init` hook). Addon repositories only | — |
| `dependabot` | on | `.github/dependabot.yml`, GitHub Actions and the Nix inputs, one entry per target branch | `schedule` (`"weekly"`), `cooldown-days` (`7`), `target-branches` (`[]`: the integration branch), `auto-merge` (`true`), `auto-merge-policy` (`"decision-table"` or `"all"`), `update-branches` (`false`) |
| `ci` | on | the CI callers ([CI](ci.md)) | `runs-on` (`["ubuntu-latest"]`), `test-timeout-minutes` (`60`), `project-update` (`"0 6 * * 1"`, a project's scheduled `odoo project update`; `""` for none), `github-app` (`{ app-id = "", private-key = "" }`: the names of the Actions variable and secret, never their values), `schedules` (`{}`: a cron per workflow, `ci` for one) |
| `repo-policy` | off | rulesets and repository settings, applied by `odoo-nix repo apply` ([Fleet](fleet.md)). Needs `ci` | `required-approvals` (`1`), `require-code-owner-review` (`false`), `required-checks` (`"gates"`), `release-bypass` (`"github-actions"`; the CI App as `"integration:<numeric id>"`), `secret-scanning` (`true`), `merge-methods` (`["squash"]`), `require-thread-resolution` (`true`), `delete-branch-on-merge` (`true`), `manage-default-branch` (`true`), `manage-features` (`true`) |
| `readme` | off | a README per addon, and optionally a table of the addons in the root `README.md` | `required` (`true`), `addons-table` (`false`) |
| `icons` | off | `static/description/icon.png` per addon, checked by `odoo-nix check icons` | `min-size` (`128`), `max-bytes` (`102400`), `src-icon` (`"assets/addon-icon.png"`, relative to the org profile) |

The `[org]` table (`publisher`, `email`, `copyright-holder`, `license`, `github-owner`, `docs-url`, `dev-docs-url`, `support-url`, `repo-url`) fills the placeholders the templates and hooks use; the built-in profiles leave each `""` except `dev-docs-url` (`https://github.com/Avunu/odoo-nix/tree/main/docs/standards`, both) and `repo-url` (`https://github.com/{repo}`, `recommended@2.3`). A rule that needs a value that is empty is skipped.

## Shape and module

Some modules only mean something in one shape. With the module on in the other, sync gives a notice and the module does nothing:

| Module | project | addons |
| --- | --- | --- |
| `releases` | notice: a project has no series branch | the develop+series flow |
| `packaging` | notice | one whool `pyproject.toml` per addon |
| `check submodules` (lint gate) | every `.gitmodules` entry on `branch = <series>` | n/a |

A project keeps its addons under `layout.customDir` (`custom` by default): the lint hooks, the test gate and `check manifests` read them there, and never `odoo/` or `modules/`.
