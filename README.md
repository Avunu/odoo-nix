# odoo-nix

Reusable Nix infrastructure for [Odoo](https://www.odoo.com/) projects built on the **[Odoo Community Backports (OCB)](https://github.com/OCA/OCB)** distribution and **[OCA](https://odoo-community.org/) modules** — the open alternative to Odoo Enterprise.

`odoo-nix` packages everything needed to develop and ship an Odoo + OCA project declaratively, so a consuming project's flake stays a thin wrapper instead of a hand-rolled monolith. From a small top-level source tree it provides:

-   a **`gum`\-based scaffolder** (`nix run github:Avunu/odoo-nix`) that optionally picks OCA bundles or modules from a bundled catalog, resolves their transitive **dependency repos**, and wires them in as git submodules — decline both and you get plain Odoo core
-   **auto-synthesized `addons_path`** — derived from the folders actually present, so it can never drift out of sync with your submodules
-   a Nix-synthesized **`odoo.conf`** (declared in your flake, symlinked into place)
-   a **devenv** development shell (PostgreSQL + Odoo + Mailpit) with a reproducible Python environment via [uv2nix](https://github.com/pyproject-nix/uv2nix)
-   a `builtOdoo` package — the assembled, deployable Odoo tree
-   a single-instance **NixOS module** (`services.odoo-nix`) with secret-safe config synthesis
-   an **OCI container** image (`dockerTools`)
-   portable **dev scripts** (`provision-db`, `odoo-add-module`, `odoo-update`, …)

It is consumed as a [flake-parts](https://flake.parts/) module.

## Requirements

-   Nix with flakes enabled, and [direnv](https://direnv.net/) for the dev shell.
-   A project laid out top-level (the scaffolder writes this for you):

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

`.devenv/state/` holds the dev PostgreSQL cluster **and** Odoo's filestore — nothing mutable is tracked.

## Create a new project

`nix run github:Avunu/odoo-nix` scaffolds a fresh project — the odoo-nix equivalent of a manual Odoo bootstrap. It selects an Odoo series (which fixes the Python version from a preset), _optionally_ lets you add OCA software, resolves the dependency repos, writes the wrapper flake, adds OCB + the resolved repos as shallow git submodules, generates `pyproject.toml` and runs `uv lock`:

```sh
nix run github:Avunu/odoo-nix                    # interactive (gum prompts)
# or fully non-interactive:
nix run github:Avunu/odoo-nix -- \
  --series 18.0 --bundles base \
  --modules account_financial_report,repair_order_group \
  --name acme --db acme acme
cd acme && direnv allow && devenv up             # then `provision-db` in another shell
```

**OCA software is entirely opt-in.** The scaffolder asks two independent, skippable questions — "add curated bundles?" then "add individual modules?" — each defaulting to _no_. Decline both (or pass neither `--bundles` nor `--modules`) and you get a plain Odoo core project; answer both and the two selections are unioned and de-duplicated. Modules can always be added later with `odoo-add-module` / `odoo-add-bundle`.

Series presets are curated in `lib/odoo-presets.json`:

| Series | Python | OCB / OCA branch |
| --- | --- | --- |
| 18.0 | python311 | 18.0 |
| 19.0 | python312 | 19.0 |

18.0 is the default for `odoo-nix.odooSeries` and the series the bundled OCA catalog is richest for; 19.0 is fully supported and catalogued, but OCA's port to it is still in progress, so fewer modules exist there.

### The module picker

The interactive picker lists **all installable modules** for the series (fuzzy search via `gum filter --no-fuzzy`, so typing a repo or module name does prefix matching, not loose subsequence matching). Modules flagged `application` in their manifest are marked with a ★ and sorted first, but every installable module is selectable — most useful OCA modules (localizations, feature modules) are _not_ applications.

Picking a module resolves the **transitive closure of OCA repos** it needs (via each module's `depends`) and adds only the new repos as submodules. The set of modules you chose is recorded in `modules.txt`, which drives both installation (`provision-db`) and the scoped Python-dependency aggregation.

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
| flakeModules.default | the flake-parts module (devenv shell + containers + the odoo-nix option namespace) |
| nixosModules.default | the standalone services.odoo-nix NixOS module |
| lib.mkFlake | flake-parts.lib.mkFlake wrapper that merges odoo-nix's own inputs |
| lib.overrides | composable Python native-build overlays (psycopg2, python-ldap, lxml, libsass) |
| lib.addons | the addons_path synthesis function, for testing / advanced use |
| packages.<sys>.odoo-init / .default | the scaffolder executable |
| apps.<sys>.odoo-init / .default | nix run entry point |

A consuming project additionally gets `packages.<sys>.{odooConf, odooPythonEnv, odooDevEnv, builtOdoo, default}` from the flake-parts module.

## Options — `perSystem.odoo-nix`

| Option | Default | Description |
| --- | --- | --- |
| enable | false | enable the dev shell + packages |
| projectName | — | identifier for env / package / container names |
| workspaceRoot | — | project root (where pyproject.toml, odoo.conf, odoo/ live) |
| odooSeries | "18.0" | Odoo series — the OCB/OCA branch + catalog filter (does not select a nixpkgs package) |
| python | pkgs.python311 | interpreter (match the series) |
| nodejs | pkgs.nodejs_22 | Node.js (for rtlcss / asset tooling) |
| pythonOverrides | _: _: {} | uv2nix package-set overlay for native-build overrides |
| pythonLibraries | { } | per-package native libs to expose to a Python build, e.g. { python-snappy = [ pkgs.snappy ]; } (merged with built-ins; pycups is built in) |
| layout.coreSrc | "odoo" | path of the OCB source submodule |
| layout.externalDir | "modules" | directory holding OCA module-repo submodules |
| layout.customDir | "custom" | directory holding your own modules |
| layout.extraAddons | [ ] | extra addons_path entries appended verbatim |
| mailcatch.enable | true | redirect all outgoing email to the local Mailpit catcher |
| mailcatch.host / mailcatch.port | "127.0.0.1" / 1025 | catcher SMTP endpoint (drives Mailpit and Odoo) |
| mailcatch.httpPort | 8025 | Mailpit web UI port |
| odooConf.dbHost/dbPort/dbUser/dbPassword/dbName | 127.0.0.1 / 5432 / odoo / False / odoo_dev | DB connection |
| odooConf.dataDir | "./.devenv/state/odoo" | Odoo filestore (gitignored under .devenv) |
| odooConf.adminPasswd | "admin" | DB-manager master password (dev) |
| odooConf.httpPort/geventPort | 8069 / 8072 | HTTP + websocket/longpolling ports |
| odooConf.workers | 0 | worker processes (0 = threaded dev mode) |
| odooConf.devMode | "all" | --dev flag for the dev process |
| odooConf.logging.level | "info" | root logging verbosity (log_level) |
| odooConf.logging.handlers | [ ] | per-logger level overrides, e.g. [ "werkzeug:WARNING" ] (log_handler) |
| odooConf.logging.db/dbLevel | false / "warning" | mirror logs into a database (log_db/log_db_level) |
| odooConf.logging.file | null | write logs to this file instead of stderr (logfile) |
| dev.autoReload | true | make Odoo's --dev=reload watcher functional (see Live code reload) |
| odooConf.extra | { } | arbitrary extra [options] keys merged last |
| odooConf.withoutDemo | false | skip demo data for every module (without_demo = all) |
| postgres.extensions | _: [ ] | extensions built into the dev PostgreSQL, e.g. ps: [ ps.postgis ] (base_geoengine) |
| ide.enable | true | expose the env to editors: ./.venv symlink + merged odoo analysis root |
| ide.vscodeSettings | true | seed .vscode/settings.json when absent (never overwrites) |
| extraDevPackages / extraLibraryPaths / extraScripts / extraEnv | [] / [] / {} / {} | dev-shell extras |
| containers.enable / containers.registry | false / "" | build the OCI image |

## Development shell

`devenv up` starts:

-   **PostgreSQL** (state under `.devenv/state`; Odoo connects via `odoo.conf`),
-   **odoo** — `odoo-bin -c odoo.conf --dev=all` (threaded; serves HTTP + websockets),
-   **mailpit** — SMTP sink + web UI.

On shell entry it initializes git submodules, symlinks the synthesized `odoo.conf` into place, ensures the filestore + `custom/` directories exist, and refreshes the editor integration below.

### Live code reload

Edit a `.py` file anywhere on the `addons_path` and the dev server restarts itself — in place, via `os.execve`, so the PID, the CWD and the open HTTP socket all survive. Nothing to run, no `devenv up` restart.

This is Odoo's own `--dev=reload` watcher, which `devMode = "all"` already requests. The catch it hides: Odoo only starts the watcher if it can `import` a filesystem watcher, and it declares neither `inotify` nor `watchdog` as a dependency — so `--dev=all` on its own logs one INFO line (`Code autoreload feature is disabled`) in a very noisy log and then never reloads. `dev.autoReload` (on by default) closes that: the scaffolded `pyproject.toml` pins `watchdog` in `[dependency-groups].dev`, and for projects that predate it the dev process falls back to the nixpkgs `watchdog` on `PYTHONPATH`. Look for this line at start-up:

```
AutoReload watcher running with watchdog
```

What it does and does not cover:

-   **Python** — every `addons_path` root is watched recursively: `odoo/odoo/addons`, `odoo/addons`, each `modules/<repo>`, and `custom/`. A change restarts the server; a syntax error is logged and the restart is skipped until you fix it.
-   **XML, QWeb, assets** — no restart needed at all. `--dev=xml` drops the ORM cache on `ir.ui.view` / `ir.asset` / `ir.qweb`, so views, templates and JS/SCSS bundles are re-read from disk. Just reload the browser.
-   **Odoo framework code** (`odoo/odoo/*.py` — `models.py`, `fields.py`, `http.py`) is _not_ an addons root, so it is not watched. Restart the process for those.
-   **`workers` must be 0** (the default). The watcher only runs on the threaded server; the dev shell warns if you set workers and leave `autoReload` on.

Python packages are installed editable against `$REPO_ROOT`, so module _source_ was always live — only the restart trigger was missing.

### Editor / language-server integration

`ide.enable` (the default) produces two derived artifacts. Neither is read at runtime — the server and the scripts import from the store env directly — they exist so a static analyser resolves the same names the interpreter does.

| Artifact | Purpose |
| --- | --- |
| ./.venv → the Nix-built dev env | the venv layout every editor probes for at the workspace root |
| .devenv/state/pythonpath | a merged odoo package whose addons/ aggregates every addons_path root |

The second one is not optional dressing. Two things hide Odoo's imports from an analyser, and both need a real directory to look at:

1.  uv2nix installs every OCA/custom module **editable**, through `.pth` files whose body is `sys.path.append(os.path.expandvars(…))`. Only a running interpreter executes those.
2.  `odoo.addons` is a `pkgutil` namespace that Odoo extends from `addons_path` at startup — and the bulk of the standard addons (`sale`, `portal`, `mail`, …) live in `<coreSrc>/addons`, _outside_ the `odoo` package. Nothing static can see them either.

So without it, `from odoo.addons.sale.models.sale_order import SaleOrder` is unresolved even for stock Odoo. The mirror links each module in first-root-wins order — the same precedence Odoo applies — and is rebuilt only when that set changes.

With `ide.vscodeSettings`, a `.vscode/settings.json` is seeded (once, never overwritten) pointing Pylance at both:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.analysis.extraPaths": [".devenv/state/pythonpath"]
}
```

For a non-VS Code editor, point your language server at the same two paths — e.g. a `pyrightconfig.json` with `"venv": ".venv"` and the same `extraPaths`.

### Outgoing mail catch-all

With `mailcatch.enable` (the default), **every** outgoing email is redirected to Mailpit — nothing can reach a real recipient from a dev environment. Open the catcher at [http://localhost:8025](http://localhost:8025).

Setting `smtp_server` in `odoo.conf` is _not_ enough on its own: Odoo only falls back to it when no `ir.mail_server` record matches, so a single row in that table — or a `mail.mail` carrying an explicit `mail_server_id` — sends for real. So odoo-nix ships an addon, `addons/dev_mailcatch`, that patches `ir.mail_server.connect` and `ir.mail_server._find_mail_server` to always dial the catcher.

It is loaded as a **server-wide module**, not installed into any database:

```ini
[options]
server_wide_modules = base,web,dev_mailcatch

[dev_mailcatch]
enabled = True
host = 127.0.0.1
port = 1025
```

Odoo runs the manifest's `post_load` hook at server start, so the redirection covers every database on the server — including ones created later — with no `-i` step, and applies to the HTTP server, `odoo-shell`, and `--stop-after-init` runs (`-i`/`-u`) alike. The addon is served directly from the Nix store; it is never copied or symlinked into your workspace, so it stays out of `custom/`, `modules.txt`, and your git tree. A startup log line names the target:

```
WARNING dev_mailcatch ACTIVE — ALL outgoing email is redirected to 127.0.0.1:1025.
```

`ODOO_MAILCATCH_ENABLED` / `_HOST` / `_PORT` override `odoo.conf` for one-off runs. The catch-all is **dev-shell only** — `services.odoo-nix` and the container builder never load it.

### Dev scripts

| Command | Action |
| --- | --- |
| provision-db [db] | create the DB + install everything in modules.txt |
| odoo-init-db [db] | create + initialize a DB (-i base) |
| odoo-upgrade <m[,m2]> [db] | upgrade module(s) (-u) |
| odoo-shell [db] | Odoo Python REPL |
| odoo-add-module [module …] | pick more OCA modules → resolve + add repos → record in modules.txt → re-lock |
| odoo-add-bundle [name …] | add a curated bundle of OCA modules (from data/oca-bundles.json) |
| odoo-update | pull submodules, re-aggregate OCA Python deps, uv lock |

After `odoo-add-module` / `odoo-add-bundle`, run `direnv reload` so the Nix engine re-derives `addons_path` and rebuilds the Python env.

### Bundles

`odoo-add-bundle` adds a named set of OCA "must-have" modules in one step — it expands the bundle to its module list and runs the same resolve → add-repos → record → re-lock flow as `odoo-add-module`. Bundles are defined in the hand-maintained `data/oca-bundles.json`:

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

The same picker and expansion are available at scaffold time (`--bundles`, or the first interactive prompt) — both callers share the `oca_pick_bundles` / `oca_expand_bundles` helpers in `lib/oca-lib.sh`. Bundles are series-blind lists, so expansion is scoped to the project's series: a member with no in-series catalog record is reported and dropped rather than recorded in `modules.txt` and left to fail at `provision-db`.

## Python environment

The project's `pyproject.toml` + `uv.lock` are the single Python manifest, built reproducibly by **uv2nix** (no pip, no `.venv`). Dependency resolution is **fully declarative — uv does all of it**, with no custom aggregation:

-   OCA modules are modern **[whool](https://github.com/sbidoul/whool)** packages (`odoo-addon-<module>`). Each module's build metadata declares its full dependency graph from `__manifest__.py`: `odoo-addon-<dep>` for OCA depends, `odoo` for core depends, and `external_dependencies.python` as real PyPI requirements.
-   **OCB itself** resolves as an `odoo` path dependency — its `setup.py` carries Odoo's own requirements, so uv resolves those too (replacing any `requirements.txt` translation).

`lib/oca_sources.py` generates two managed blocks (regenerated by `odoo-add-module` / `odoo-add-bundle` / `odoo-update`):

-   `[project].dependencies` — `odoo` + the modules from `modules.txt` as `odoo-addon-<name>` (the install roots);
-   `[tool.uv.sources]` — `odoo` (the OCB submodule) + **every** local module as an editable path source. uv then resolves the transitive closure of the roots against these local sources and pulls only the genuine external deps from PyPI.

This is a pure enumeration of available local modules — no dependency _logic_. uv resolves the graph; adding a module or changing its manifest deps is picked up automatically.

The dev environment installs the modules **editable** (live source) and `odoo` as a wheel (its vendored `pep517_odoo` backend needs `setup/` on `PYTHONPATH` during the build, handled in `lib/python.nix`); Odoo is still **run from source** via `odoo-bin` + `addons_path`, so module loading and OCB edits work exactly as before — the editable installs just feed uv's resolution. `lib/overrides.nix` supplies native-build overrides (psycopg2, python-ldap) and a `[tool.uv.extra-build-dependencies]` block grants `setuptools` to sdist-only legacy deps. For a genuine version conflict, use `[tool.uv] override-dependencies`.

When a module pulls a C-extension dep that needs system headers (e.g. `pycups` → `cups/http.h`), expose the library declaratively rather than writing an override — the `pythonLibraries` option maps a Python package to nixpkgs libraries whose `.dev` headers + pkg-config are added to its build:

```nix
odoo-nix.pythonLibraries = {
  python-snappy = [ pkgs.snappy ];   # pycups is built in
};
```

## `addons_path` synthesis

`lib/addons.nix` enumerates `modules/*`, keeps only directories that actually contain an Odoo module (an immediate child with `__manifest__.py`), prepends the two core OCB addon dirs, and appends `custom/` — emitting an ordered, relative `addons_path` that is regenerated on every evaluation. Adding or removing a submodule changes the path automatically; there is no hand-maintained list to drift.

Entries stay workspace-relative so the file is identical across machines and containers. Absolute roots (`extraAddonsAbs`) are appended last, verbatim — that is how odoo-nix's own store-resident addons, such as `dev_mailcatch`, join the path without being vendored into the consumer's tree.

## `odoo.conf` synthesis

`lib/odoo-conf.nix` renders the `[options]` block from your declarative `odooConf.*` settings plus the derived `addons_path` (via `pkgs.formats.ini`) to a read-only `/nix/store` file. The dev shell symlinks it to `./odoo.conf`; `--dev` stays a CLI flag so the same file is prod-usable.

Beside `[options]` it can emit arbitrary extra sections (`extraSections`) for modules that read their own INI section out of `odoo.tools.config.misc` — Odoo's parser keeps unknown sections verbatim. `dev_mailcatch` uses this; OCA modules like `queue_job` follow the same convention.

## Production — `services.odoo-nix`

A standalone NixOS module (imported separately from the flake-parts module). One Odoo instance per deployment; multi-tenancy via `dbfilter`. A base `odoo.conf` (no secrets) is written to the store; an `odoo-init` oneshot copies it to a `0600` runtime file and **appends** `db_password` / `admin_passwd` from secret files — so secret _values_ never enter `/nix/store`.

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

Key options: `package`, `stateDir`, `http.{port,longpollingPort,interface}`, `workers`, `maxCronThreads`, `dbName`/`dbFilter`/`listDb`/`withoutDemo`, `database.{createLocally,host,port,user,passwordFile,extensions,ensureExtensions}`, `adminPasswordFile`, `settings` (extra `[options]`), `update` (modules to `-u` on deploy), `autoInit`, `nginx.{enable,domain}`, `logging.{level,handlers,db,dbLevel,file,rotate}` (`rotate` wires up `services.logrotate` against `logging.file`; Odoo's own `WatchedFileHandler` picks up the rotated file automatically, no reload needed).

PostGIS (OCA `base_geoengine`): `database.extensions = ps: [ ps.postgis ];` builds it into the local server and `database.ensureExtensions = [ "postgis" "postgis_topology" ];` creates both in `dbName` as the `postgres` superuser. The module's `pre_init_hook` tries to create them itself, which only works for a superuser — the dev shell's role is one, the production role is not.

## Production — OCI containers

Set `odoo-nix.containers.enable = true` to get `packages.<sys>.container-odoo`, an all-in-one image (`dockerTools.buildLayeredImage`) running `odoo-bin` with HTTP workers + gevent + cron. The entrypoint synthesizes `/etc/odoo/odoo.conf` from env-var defaults and merges secrets from mounted files:

-   `/var/lib/odoo/data` — persistent filestore (volume),
-   `/secrets/db_password`, `/secrets/admin_passwd`, `/secrets/*.conf` — secrets,
-   PostgreSQL is external.

## Library

### `lib.mkFlake`

Wraps `flake-parts.lib.mkFlake`, merging odoo-nix's own inputs (devenv, uv2nix, …) so the consumer only declares `odoo-nix` + `nixpkgs.follows`.

### `lib.overrides`

Composable `final: prev:` Python overlays for packages needing system libraries (`psycopg2`, `python-ldap`, `lxml`, `libsass`). psycopg2 + python-ldap are wired by default; pass more via `pythonOverrides`.

### `lib.addons`

The `addons_path` synthesis used internally; importable for `nix eval` testing.

## The OCA catalog

`data/oca-modules.json` is the bundled catalog (every OCA module across the cloned repos, with `repo`, `version`, `application`, `installable`, `depends`, `summary`, …) that powers the picker and dependency resolver. It covers **19.0 and 18.0** — one record per (repo, module, series).

Refreshing it is two commands. `sync-oca-repos.sh` keeps one bare mirror per OCA repo under the gitignored `data/.cache/`, fetching each series as a shallow branch (repos without that branch are skipped); `extract_manifests.py` then reads the manifests straight out of the git objects — no working trees:

```sh
data/sync-oca-repos.sh              # or: data/sync-oca-repos.sh 19.0
data/extract_manifests.py           # rewrites data/oca-modules.json
```

Both default to the series list in `lib/odoo-presets.json`; keep the three in sync when a series is added or dropped. A manifest whose `version` disagrees with the branch it was read from is skipped, since every consumer filters on the version prefix.

`data/oca-bundles.json` is a separate, **hand-maintained** file defining the named module bundles used by `odoo-add-bundle` (see [Bundles](#bundles)).

## Repository layout

```
flake.nix                    # inputs; flakeModules / nixosModules / lib / packages
modules/
  flake-module.nix           # imports devenv.flakeModule + devenv.nix + containers.nix
  devenv.nix                 # perSystem.odoo-nix options + dev shell
  containers.nix             # dockerTools OCI image
  nixos.nix                  # services.odoo-nix
addons/
  dev_mailcatch/             # server-wide outgoing-mail catch-all (dev shell only)
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
  oca-modules.json           # vendored OCA catalog (+ sync/extract scripts)
  oca-bundles.json           # hand-maintained "must-have" module bundles
templates/project/           # scaffolder template (thin flake + pyproject + README)
```

## License

See repository.
