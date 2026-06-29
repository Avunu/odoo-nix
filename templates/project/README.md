# @PROJECT_NAME@

An Odoo @SERIES@ project built on the **Odoo Community Backports (OCB)**
distribution + **OCA** modules, managed declaratively with
[odoo-nix](https://github.com/Avunu/odoo-nix).

## Layout

| Path            | Contents                                            |
| --------------- | --------------------------------------------------- |
| `odoo/`         | OCB source (git submodule, branch `@SERIES@`)       |
| `apps/`         | OCA repos (git submodules)                          |
| `custom/`       | This project's own addons                           |
| `pyproject.toml`| Python deps (Odoo core + OCA), locked in `uv.lock`  |
| `oca-apps.txt`  | Selected OCA application modules to install         |
| `odoo.conf`     | Symlink into the Nix store (synthesized; `addons_path` auto-derived) |
| `.devenv/state/`| postgres cluster + Odoo filestore (gitignored)      |

## Quick start

```sh
git clone --recurse-submodules <this-repo> && cd @PROJECT_NAME@
direnv allow          # or: nix develop --no-pure-eval
devenv up             # start postgres + odoo + mailpit
provision-db          # (another shell) create the DB + install oca-apps.txt
```

Open <http://localhost:8069>. Mailpit UI is at <http://localhost:8025>.

## Managing OCA apps

```sh
odoo-add-app                       # interactive picker, resolves dep repos
odoo-add-app account_financial_report   # or by module name
```

`odoo-add-app` adds the required OCA repos as submodules, records the app in
`oca-apps.txt`, refreshes the Python deps, and re-locks. Run `direnv reload`
afterwards so the Nix engine re-derives `addons_path` and rebuilds the env.

## Common commands

| Command               | Action                                       |
| --------------------- | -------------------------------------------- |
| `provision-db [db]`   | Create DB + install all `oca-apps.txt`       |
| `odoo-init-db [db]`   | Create + initialize a DB (base only)         |
| `odoo-upgrade <m>`    | Upgrade module(s)                            |
| `odoo-shell [db]`     | Odoo Python REPL                             |
| `odoo-update`         | Pull submodules + refresh deps + re-lock     |
