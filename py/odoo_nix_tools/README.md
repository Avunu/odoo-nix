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
| `policy`, `ci` | core | commit and pull-request policy; the CI and release steps |
| `repo` | core | apply, audit, roll out and doctor a fleet of repositories |
| `data-path`, `pin-path` | core | a packaged data file; a locked flake input's tree |
| `gate lint\|test` | odoo-nix | the lint and test gates CI runs |
| `check manifests\|icons\|submodules` | odoo-nix | addon manifests, icons, submodule state |
| `ratchet coverage` | odoo-nix | the coverage floor |

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | clean |
| 1 | drift (`--check`), or a failed policy, guard or repository step |
| 2 | invalid configuration or argument |
| 3 | environment: not a checkout, not git, unreadable lock, fetch failure, version skew, a bug |

## Development

The tests are `unittest` suites under `tests/`; the Nix build runs them
(`nix build .#checks.<system>.standards-unit`). By hand, from this directory, with the
core on the path:

```
PYTHONPATH=. uv run --no-project --with-editable <python-devops-nix>/standards \
  python -m unittest discover -s tests
```
