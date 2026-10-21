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
git clone <this-repo> && cd @PROJECT_NAME@
direnv allow          # checks out the submodules, then loads the dev shell
devenv up             # start postgres + odoo + mailpit
odoo db provision     # (another shell) create the DB + install modules.txt
```

Nix reads the submodules while it evaluates `flake.nix`, so a fresh clone needs
them checked out first; `.envrc` does that with odoo-nix's own tool, as partial
clones. Without direnv, run `nix run github:Avunu/odoo-nix#bootstrap` before
`nix develop --no-pure-eval`.

Open the server address the shell banner prints; Mailpit's web UI is there too.
Every port is a base plus an offset hashed from the project's name (Odoo HTTP
10000, websockets 11000, PostgreSQL 12000, Mailpit SMTP 13000 and web UI 14000,
each plus the offset), so several projects run at once. Set `odoo-nix.ports.offset`,
or `ODOO_NIX_PORT_OFFSET=<0..899>` for one shell, to pick another offset.

## Live code reload

The dev server runs with `--dev=all`, so edits are picked up without restarting it:

- **`.py`** anywhere on the `addons_path` (`custom/`, `modules/<repo>`, `odoo/addons`) —
  the server restarts itself in place. Watch the log for
  `autoreload: python code updated`. A syntax error is logged and the restart skipped
  until you fix it.
- **XML views, QWeb templates, JS/SCSS assets** — no restart at all; just reload the
  browser.

Odoo's watcher needs the `watchdog` package, which is pinned in
`[dependency-groups].dev`. `AutoReload watcher running with watchdog` at start-up means
it is live. Odoo's own framework code (`odoo/odoo/*.py`) is *not* watched — restart
`devenv up` for those.

## Managing OCA modules

```sh
odoo module add                       # interactive picker, resolves dep repos
odoo module add account_financial_report   # or by module name
odoo module add https://example.com/owner/repo.git   # any third-party repo, any git host
odoo module add owner/repo 17.0 my-repo              # GitHub shorthand, explicit branch + path
odoo module add-bundle                # add a curated bundle (base, oca-accounting, …)
odoo module add-bundle base sales     # or by bundle name
```

`odoo module add` / `odoo module add-bundle` add the required repos as submodules,
record the modules in `modules.txt`, refresh the Python deps, and re-lock. Run
`direnv reload` afterwards so the Nix engine re-derives `addons_path` and rebuilds
the env. For a git URL, branch and submodule path are prompted for when omitted
interactively (branch defaults to the project's Odoo series, else the repo's
detected default branch; path defaults to a slug of the repo name) and default
sensibly when run non-interactively.

## Common commands

| Command                     | Action                                          |
| ---------------------------- | ------------------------------------------------ |
| `odoo db provision [db]`     | Create DB + install all `modules.txt`, or migrate it if it already exists |
| `odoo db migrate [db]`       | Update the modules whose code or version changed, with progress + a summary table |
| `odoo db upgrade <m> [db]`   | Upgrade specific module(s)                      |
| `odoo db backup [db]`        | Back up a database (schema + filestore)         |
| `odoo db restore <db> <zip>` | Restore a database from a backup                |
| `odoo module add-bundle [n]` | Add a curated OCA module bundle                 |
| `odoo shell [db]`            | Odoo Python REPL                                |
| `odoo project update`        | Pull submodules + refresh deps + re-lock, then migrate |
