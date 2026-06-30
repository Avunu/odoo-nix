# odoo-nix

Reusable Nix infrastructure for [Odoo](https://www.odoo.com/) projects built on the
**[Odoo Community Backports (OCB)](https://github.com/OCA/OCB)** distribution and
**[OCA](https://odoo-community.org/) modules** — the open alternative to Odoo Enterprise.

`odoo-nix` packages everything needed to develop and ship an Odoo + OCA project
declaratively, so a consuming project's flake stays a thin wrapper instead of a hand-rolled
monolith. From a small top-level source tree it provides:

- a **`gum`-based scaffolder** (`nix run github:Avunu/odoo-nix`) that picks OCA modules from a
  bundled catalog, resolves their transitive **dependency repos**, and wires them in as git
  submodules;
- **auto-synthesized `addons_path`** — derived from the folders actually present, so it can
  never drift out of sync with your submodules;
- a Nix-synthesized **`odoo.conf`** (declared in your flake, symlinked into place);
- a **devenv** development shell (PostgreSQL + Odoo + Mailpit) with a reproducible Python
  environment via [uv2nix](https://github.com/pyproject-nix/uv2nix);
- a `builtOdoo` package — the assembled, deployable Odoo tree;
- a single-instance **NixOS module** (`services.odoo-nix`) with secret-safe config synthesis;
- an **OCI container** image (`dockerTools`);
- portable **dev scripts** (`provision-db`, `odoo-add-module`, `odoo-update`, …).

It is consumed as a [flake-parts](https://flake.parts/) module.

## Requirements

- Nix with flakes enabled, and [direnv](https://direnv.net/) for the dev shell.
- A project laid out top-level (the scaffolder writes this for you):

```
.
├── flake.nix          # your thin wrapper (see Quick start)
├── pyproject.toml      # Odoo core deps + scoped OCA deps; built by uv2nix
├── uv.lock             # committed lock — drives the Nix Python env
├── modules.txt         # OCA modules to install (any installable module)
├── odoo/               # OCB source (git submodule, branch = series)
├── modules/            # OCA module-repo submodules
│   ├── account-financial-reporting/
│   └── …
├── custom/             # your own Odoo modules
└── odoo.conf           # symlink into the Nix store (synthesized)
```

`.devenv/state/` holds the dev PostgreSQL cluster **and** Odoo's filestore — nothing mutable
is tracked.

## Create a new project

`nix run github:Avunu/odoo-nix` scaffolds a fresh project — the odoo-nix equivalent of a
manual Odoo bootstrap. It selects an Odoo series (which fixes the Python version from a
preset), lets you pick OCA modules, resolves their dependency repos, writes the wrapper
flake, adds OCB + the resolved repos as shallow git submodules, generates `pyproject.toml`
from `odoo/requirements.txt` + the modules' Python deps, and runs `uv lock`:

```sh
nix run github:Avunu/odoo-nix                    # interactive (gum picker)
# or fully non-interactive:
nix run github:Avunu/odoo-nix -- \
  --series 18.0 --modules account_financial_report,repair_order_group \
  --name acme --db acme acme
cd acme && direnv allow && devenv up             # then `provision-db` in another shell
```

Series presets are curated in `lib/odoo-presets.json`:

| Series | Python | OCB / OCA branch |
| --- | --- | --- |
| `18.0` | python311 | `18.0` |
| `17.0` | python311 | `17.0` |
| `16.0` | python310 | `16.0` |

18.0 is the default and the series the bundled OCA catalog is richest for.

### The module picker

The interactive picker lists **all installable modules** for the series (fuzzy search via
`gum filter --no-fuzzy`, so typing a repo or module name does prefix matching, not loose
subsequence matching). Modules flagged `application` in their manifest are marked with a ★
and sorted first, but every installable module is selectable — most useful OCA modules
(localizations, feature modules) are *not* applications.

Picking a module resolves the **transitive closure of OCA repos** it needs (via each
module's `depends`) and adds only the new repos as submodules. The set of modules you chose
is recorded in `modules.txt`, which drives both installation (`provision-db`) and the scoped
Python-dependency aggregation.

## Quick start

A consuming `flake.nix` is just configuration:

```nix
{
  inputs = {
    self.submodules = true;                  # submodule contents enter the flake source tree
    odoo-nix.url = "github:Avunu/odoo-nix";
    nixpkgs.follows = "odoo-nix/nixpkgs";
  };

  outputs = { self, odoo-nix, ... }@inputs:
    odoo-nix.lib.mkFlake { inherit inputs; } ({ ... }: {
      imports = [ odoo-nix.flakeModules.default ];
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      perSystem = { pkgs, ... }: {
        odoo-nix = {
          enable = true;
          projectName = "acme";
          workspaceRoot = ./.;
          odooSeries = "18.0";
          python = pkgs.python311;
          odooConf.dbName = "acme";
          odooConf.adminPasswd = "change-me";  # dev only
        };
      };
    });
}
```

```sh
direnv allow            # or: nix develop --no-pure-eval
devenv up               # PostgreSQL + Odoo + Mailpit
provision-db            # (another shell) create the DB + install modules.txt
# → http://localhost:8069   (Mailpit UI: http://localhost:8025)
```

## Flake outputs

| Output | Description |
| --- | --- |
| `flakeModules.default` | the flake-parts module (devenv shell + containers + the `odoo-nix` option namespace) |
| `nixosModules.default` | the standalone `services.odoo-nix` NixOS module |
| `lib.mkFlake` | `flake-parts.lib.mkFlake` wrapper that merges odoo-nix's own inputs |
| `lib.overrides` | composable Python native-build overlays (psycopg2, python-ldap, lxml, libsass) |
| `lib.addons` | the `addons_path` synthesis function, for testing / advanced use |
| `packages.<sys>.odoo-init` / `.default` | the scaffolder executable |
| `apps.<sys>.odoo-init` / `.default` | `nix run` entry point |

A consuming project additionally gets `packages.<sys>.{odooConf, odooPythonEnv, odooDevEnv,
builtOdoo, default}` from the flake-parts module.

## Options — `perSystem.odoo-nix`

| Option | Default | Description |
| --- | --- | --- |
| `enable` | `false` | enable the dev shell + packages |
| `projectName` | — | identifier for env / package / container names |
| `workspaceRoot` | — | project root (where `pyproject.toml`, `odoo.conf`, `odoo/` live) |
| `odooSeries` | `"18.0"` | Odoo series — the OCB/OCA branch + catalog filter (does **not** select a nixpkgs package) |
| `python` | `pkgs.python311` | interpreter (match the series) |
| `nodejs` | `pkgs.nodejs_22` | Node.js (for `rtlcss` / asset tooling) |
| `pythonOverrides` | `_: _: {}` | uv2nix package-set overlay for native-build overrides |
| `layout.coreSrc` | `"odoo"` | path of the OCB source submodule |
| `layout.externalDir` | `"modules"` | directory holding OCA module-repo submodules |
| `layout.customDir` | `"custom"` | directory holding your own modules |
| `layout.extraAddons` | `[ ]` | extra `addons_path` entries appended verbatim |
| `odooConf.dbHost/dbPort/dbUser/dbPassword/dbName` | `127.0.0.1` / `5432` / `odoo` / `False` / `odoo_dev` | DB connection |
| `odooConf.dataDir` | `"./.devenv/state/odoo"` | Odoo filestore (gitignored under `.devenv`) |
| `odooConf.adminPasswd` | `"admin"` | DB-manager master password (dev) |
| `odooConf.httpPort/geventPort` | `8069` / `8072` | HTTP + websocket/longpolling ports |
| `odooConf.workers` | `0` | worker processes (0 = threaded dev mode) |
| `odooConf.devMode` | `"all"` | `--dev` flag for the dev process |
| `odooConf.extra` | `{ }` | arbitrary extra `[options]` keys merged last |
| `extraDevPackages` / `extraLibraryPaths` / `extraScripts` / `extraEnv` | `[]` / `[]` / `{}` / `{}` | dev-shell extras |
| `containers.enable` / `containers.registry` | `false` / `""` | build the OCI image |

## Development shell

`devenv up` starts:

- **PostgreSQL** (state under `.devenv/state`; Odoo connects via `odoo.conf`),
- **odoo** — `odoo-bin -c odoo.conf --dev=all` (threaded; serves HTTP + websockets),
- **mailpit** — SMTP sink + web UI.

On shell entry it initializes git submodules, symlinks the synthesized `odoo.conf` into
place, and ensures the filestore + `custom/` directories exist.

### Dev scripts

| Command | Action |
| --- | --- |
| `provision-db [db]` | create the DB + install everything in `modules.txt` |
| `odoo-init-db [db]` | create + initialize a DB (`-i base`) |
| `odoo-upgrade <m[,m2]> [db]` | upgrade module(s) (`-u`) |
| `odoo-shell [db]` | Odoo Python REPL |
| `odoo-add-module [module …]` | pick more OCA modules → resolve + add repos → record in `modules.txt` → re-lock |
| `odoo-add-bundle [name …]` | add a curated bundle of OCA modules (from `data/oca-bundles.json`) |
| `odoo-update` | pull submodules, re-aggregate OCA Python deps, `uv lock` |

After `odoo-add-module` / `odoo-add-bundle`, run `direnv reload` so the Nix engine re-derives
`addons_path` and rebuilds the Python env.

### Bundles

`odoo-add-bundle` adds a named set of OCA "must-have" modules in one step — it expands the
bundle to its module list and runs the same resolve → add-repos → record → re-lock flow as
`odoo-add-module`. Bundles are defined in the hand-maintained `data/oca-bundles.json`:

```json
{
  "base":  { "label": "Base — OCA must-have foundation modules", "modules": ["queue_job", "…"] },
  "sales": { "label": "Sales — OCA sales workflow",              "modules": ["sale_cancel_reason", "…"] }
}
```

```sh
odoo-add-bundle                    # interactive picker (name — label — module count)
odoo-add-bundle base sales         # by name; modules are unioned across bundles
```

Add or edit a bundle by editing `oca-bundles.json` — no code changes needed.

## Python environment

The project's `pyproject.toml` + `uv.lock` are the single Python manifest, built reproducibly
by **uv2nix** (no pip, no `.venv`). Dependency resolution is **fully declarative — uv does all
of it**, with no custom aggregation:

- OCA modules are modern **[whool](https://github.com/sbidoul/whool)** packages
  (`odoo-addon-<module>`). Each module's build metadata declares its full dependency graph
  from `__manifest__.py`: `odoo-addon-<dep>` for OCA depends, `odoo` for core depends, and
  `external_dependencies.python` as real PyPI requirements.
- **OCB itself** resolves as an `odoo` path dependency — its `setup.py` carries Odoo's own
  requirements, so uv resolves those too (replacing any `requirements.txt` translation).

`lib/oca_sources.py` generates two managed blocks (regenerated by `odoo-add-module` /
`odoo-add-bundle` / `odoo-update`):

- `[project].dependencies` — `odoo` + the modules from `modules.txt` as `odoo-addon-<name>`
  (the install roots);
- `[tool.uv.sources]` — `odoo` (the OCB submodule) + **every** local module as an editable
  path source. uv then resolves the transitive closure of the roots against these local
  sources and pulls only the genuine external deps from PyPI.

This is a pure enumeration of available local modules — no dependency *logic*. uv resolves the
graph; adding a module or changing its manifest deps is picked up automatically.

The dev environment installs the modules **editable** (live source) and `odoo` as a wheel
(its vendored `pep517_odoo` backend needs `setup/` on `PYTHONPATH` during the build, handled in
`lib/python.nix`); Odoo is still **run from source** via `odoo-bin` + `addons_path`, so module
loading and OCB edits work exactly as before — the editable installs just feed uv's resolution.
`lib/overrides.nix` supplies native-build overrides (psycopg2, python-ldap) and a
`[tool.uv.extra-build-dependencies]` block grants `setuptools` to sdist-only legacy deps. For a
genuine version conflict, use `[tool.uv] override-dependencies`.

## `addons_path` synthesis

`lib/addons.nix` enumerates `modules/*`, keeps only directories that actually contain an Odoo
module (an immediate child with `__manifest__.py`), prepends the two core OCB addon dirs, and
appends `custom/` — emitting an ordered, relative `addons_path` that is regenerated on every
evaluation. Adding or removing a submodule changes the path automatically; there is no
hand-maintained list to drift.

## `odoo.conf` synthesis

`lib/odoo-conf.nix` renders the `[options]` block from your declarative `odooConf.*` settings
plus the derived `addons_path` (via `pkgs.formats.ini`) to a read-only `/nix/store` file. The
dev shell symlinks it to `./odoo.conf`; `--dev` stays a CLI flag so the same file is
prod-usable.

## Production — `services.odoo-nix`

A standalone NixOS module (imported separately from the flake-parts module). One Odoo instance
per deployment; multi-tenancy via `dbfilter`. A base `odoo.conf` (no secrets) is written to the
store; an `odoo-init` oneshot copies it to a `0600` runtime file and **appends** `db_password`
/ `admin_passwd` from secret files — so secret *values* never enter `/nix/store`.

```nix
# In a nixosConfiguration:
{
  imports = [ odoo-nix.nixosModules.default ];
  services.odoo-nix = {
    enable = true;
    package = projectFlake.packages.x86_64-linux.default;  # builtOdoo
    dbName = "acme";
    database.createLocally = true;                          # local PG, socket peer auth
    adminPasswordFile = "/run/secrets/odoo-admin";
    workers = 4;
    nginx = { enable = true; domain = "erp.example.com"; }; # proxy_mode + /websocket → 8072
  };
}
```

Key options: `package`, `stateDir`, `http.{port,longpollingPort,interface}`, `workers`,
`maxCronThreads`, `dbName`/`dbFilter`/`listDb`, `database.{createLocally,host,port,user,
passwordFile}`, `adminPasswordFile`, `settings` (extra `[options]`), `update` (modules to `-u`
on deploy), `autoInit`, `nginx.{enable,domain}`.

## Production — OCI containers

Set `odoo-nix.containers.enable = true` to get `packages.<sys>.container-odoo`, an all-in-one
image (`dockerTools.buildLayeredImage`) running `odoo-bin` with HTTP workers + gevent + cron.
The entrypoint synthesizes `/etc/odoo/odoo.conf` from env-var defaults and merges secrets from
mounted files:

- `/var/lib/odoo/data` — persistent filestore (volume),
- `/secrets/db_password`, `/secrets/admin_passwd`, `/secrets/*.conf` — secrets,
- PostgreSQL is external.

## Library

### `lib.mkFlake`

Wraps `flake-parts.lib.mkFlake`, merging odoo-nix's own inputs (devenv, uv2nix, …) so the
consumer only declares `odoo-nix` + `nixpkgs.follows`.

### `lib.overrides`

Composable `final: prev:` Python overlays for packages needing system libraries
(`psycopg2`, `python-ldap`, `lxml`, `libsass`). psycopg2 + python-ldap are wired by default;
pass more via `pythonOverrides`.

### `lib.addons`

The `addons_path` synthesis used internally; importable for `nix eval` testing.

## The OCA catalog

`data/oca-modules.json` is the bundled catalog (every OCA module across the cloned repos, with
`repo`, `version`, `application`, `installable`, `depends`, `summary`, …) that powers the
picker and dependency resolver. It is generated by the vendored `data/extract_manifests.py`
from repos cloned by `data/clone-oca-repos.sh`. The shipped catalog is richest for 18.0; to
enrich another series, clone the OCA repos at that branch and re-run the extractor.

`data/oca-bundles.json` is a separate, **hand-maintained** file defining the named module
bundles used by `odoo-add-bundle` (see [Bundles](#bundles)).

## Repository layout

```
flake.nix                    # inputs; flakeModules / nixosModules / lib / packages
modules/
  flake-module.nix           # imports devenv.flakeModule + devenv.nix + containers.nix
  devenv.nix                 # perSystem.odoo-nix options + dev shell
  containers.nix             # dockerTools OCI image
  nixos.nix                  # services.odoo-nix
lib/
  addons.nix                 # addons_path synthesis (the keystone)
  odoo-conf.nix              # odoo.conf INI synthesis
  python.nix                 # uv2nix Python env
  odoo.nix                   # builtOdoo assembly
  overrides.nix              # native-build Python overlays
  scripts.nix                # dev-shell scripts
  oca-lib.sh                 # OCA repo resolver + module picker (shell)
  oca_sources.py             # generate uv path-sources (deps + sources blocks)
  uv_build_deps.py           # sdist build-dep sync
  init.nix / odoo-init.sh    # the scaffolder
  odoo-presets.json          # series → python / branch
data/
  oca-modules.json           # vendored OCA catalog (+ generator scripts)
  oca-bundles.json           # hand-maintained "must-have" module bundles
templates/project/           # scaffolder template (thin flake + pyproject + README)
```

## License

See repository.
