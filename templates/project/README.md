# @PROJECT_NAME@

An Odoo @SERIES@ project built on the **Odoo Community Backports (OCB)**
distribution + **OCA** modules, managed declaratively with
[odoo-nix](https://github.com/Avunu/odoo-nix).

## Layout

| Path            | Contents                                            |
| --------------- | --------------------------------------------------- |
| `odoo/`         | OCB source (git submodule, branch `@SERIES@`)       |
| `modules/`      | OCA module repos (git submodules)                   |
| `custom/`       | This project's own modules                          |
| `pyproject.toml`| Python deps (Odoo core + OCA), locked in `uv.lock`  |
| `modules.txt`   | OCA modules to install (any installable module)     |
| `odoo.conf`     | Symlink into the Nix store (synthesized; `addons_path` auto-derived) |
| `.devenv/state/`| postgres cluster + Odoo filestore (gitignored)      |

## Quick start

```sh
git clone --recurse-submodules <this-repo> && cd @PROJECT_NAME@
direnv allow          # or: nix develop --no-pure-eval
devenv up             # start postgres + odoo + mailpit
provision-db          # (another shell) create the DB + install modules.txt
```

Open <http://localhost:8069>. Mailpit UI is at <http://localhost:8025>.

## Managing OCA modules

```sh
odoo-add-module                       # interactive picker, resolves dep repos
odoo-add-module account_financial_report   # or by module name
```

`odoo-add-module` adds the required OCA repos as submodules, records the module
in `modules.txt`, refreshes the Python deps, and re-locks. Run `direnv reload`
afterwards so the Nix engine re-derives `addons_path` and rebuilds the env.

## Common commands

| Command               | Action                                       |
| --------------------- | -------------------------------------------- |
| `provision-db [db]`   | Create DB + install all `modules.txt`        |
| `odoo-init-db [db]`   | Create + initialize a DB (base only)         |
| `odoo-upgrade <m>`    | Upgrade module(s)                            |
| `odoo-shell [db]`     | Odoo Python REPL                             |
| `odoo-update`         | Pull submodules + refresh deps + re-lock     |
