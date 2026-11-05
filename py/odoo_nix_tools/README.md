# odoo-nix-tools

odoo-nix's standards tools: the `odoo-nix <command>` CLI (import name `odoo_nix_tools`),
built on python-devops-nix's `standards-core`. It keeps the managed files, profiles, CI
gates and release steps of two shapes of Odoo repository in line: a **project** (an
odoo-nix workspace, `[tool.odoo-nix]` in the root `pyproject.toml`) and an **addon
repository** in addons mode (`[tool.odoo-nix]` in `nix/pyproject.toml`). The design
contract is [DESIGN.md](DESIGN.md); the user documentation is
[docs/standards](../../docs/standards/).

## Install

- With Nix: `nix run github:Avunu/odoo-nix#odoo-nix -- --help`. In an opted-in dev shell
  `odoo-nix` is on `PATH`, and `odoo-init` carries the package (`lib/standards/package.nix`).
- Without Nix (CI jobs), at the odoo-nix revision the checkout's `flake.lock` pins:

  ```
  uv tool install "odoo-nix-tools @ git+https://github.com/Avunu/odoo-nix@<rev>#subdirectory=py/odoo_nix_tools"
  ```

Every file the commands read at run time (series data, profiles, schemas, templates,
manifest fragments) lives under `odoo_nix_tools/data/` and is read through
`importlib.resources`, so both installs see the same files.

## Commands

| Command | From | What |
| --- | --- | --- |
| `sync` | core | write or check the managed files (`odoo-init --sync` runs it) |
| `config`, `profile` | core | the resolved configuration; show, list and validate profiles |
| `data-path`, `pin-path` | core | a packaged data file; a locked flake input's tree |
| `policy`, `ci` | core | commit and pull-request policy (with odoo-nix's rule: no version moved by hand under `develop+series`); the CI, Dependabot and release steps (`ci bump` raises each changed addon's `<series>.x.y.z`) |
| `repo` | core | apply, audit, roll out and doctor a fleet of repositories (`targets`, `apply`, `audit`, `doctor`, `rollout`), with odoo-nix's parts: a fleet entry's shape and integration branch, the release ruleset on the series branch only, audit rows A12 (an addon repository's series and Dependabot branches) and A13 (a project's submodules on its series), and the CI App the release flow needs (`repo doctor`). `.github/workflows/fleet-audit.yml` runs `repo audit --all` from an org profile repository |
| `gate lint\|test` | odoo-nix | the lint and test gates CI runs, step by step, with a JSON report (`.odoo-nix/gate/<gate>.json`) |
| `check manifests\|icons\|submodules` | odoo-nix | what no hook checks: manifest website and series version, addon icons (`--fix` adds the org's), submodule branches |
| `ratchet coverage` | odoo-nix | the coverage floor only rises (`--base`), and `--raise` lifts it to the measured total |

`odoo-nix config shape`, `config series` and `profile show` read what discovery finds:
the shape (`project` or `addons`), the Odoo series and the addons, from the tracked files
(`odoo_nix_tools/discover.py`). The built-in profiles are `minimal` (the dev shell only)
and `recommended` (`recommended@2.3`); `odoo-nix profile list` shows them.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | clean |
| 1 | drift (`--check`), or a failed policy, guard or repository step |
| 2 | invalid configuration or argument |
| 3 | environment: not a checkout, not git, unreadable lock, fetch failure, version skew, a bug |

## Development

The tests are `unittest` suites under `tests/`; the Nix build runs them
(`nix build .#checks.<system>.standards-unit`), and `standards-conformance` checks the
product against the core's contract. Some suites read odoo-nix files outside the package
(`tests/fixtures/standards-*`, `version.txt`, `committed.toml`, `lib/odoo-presets.json`,
`lib/odoo_nix_cli/testrun.py`): from the working
tree they are found two directories up, in the Nix build through `$ODOO_NIX_TOOLS_REPO`.
By hand, from this directory, with the dev lock (`uv.lock`, standards-core at the
commit `pyproject.toml` pins):

```
uv run --locked python -m unittest discover -s tests
```

and against a local copy of the core instead:

```
PYTHONPATH=. uv run --no-project --with-editable <python-devops-nix>/standards \
  python -m unittest discover -s tests
```

The fixtures' locks (`tests/fixtures/standards-locks/<fixture>/<profile>/`) and the
fixtures the package ships (`odoo_nix_tools/data/fixtures/{project,addons}.json`) are
generated: after a change to the series data, `data/tool-pins.json` or the tools groups,
run `nix run .#relock-standards-fixtures` from the odoo-nix tree (network), and
`nix build .#checks.<system>.standards-fixtures-{project,addons}` syncs each fixture
under every profile with those locks. After a change to a fixture tree alone,
`python3 scripts/gen_fixture_data.py` regenerates the shipped copies
(`test_fixtures_render` compares them).

The core is pinned in three places that name one commit: flake.lock's
`python-devops-nix`, `standards-core @ git+…@<sha>` above, and every
`Avunu/python-devops-nix/…@<sha>` in `.github/**`. `nix run .#bump-base -- <tag|sha>`
moves them, and this directory's `uv.lock`, together (`checks.standards-core-pins`).
