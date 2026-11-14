---
title: Editors and live reload
description: How the dev server restarts itself on a Python change, how the shell exposes the environment to an editor and the odoo-ls language server, and what the standards' ide module sets in VS Code.
order: 8
tags: [editor, reload, language-server, odoo-ls, vscode]
updated: 2026-11-04
---

## Live reload

Edit a `.py` file anywhere on `addons_path` and the dev server restarts itself in place, through `os.execve`, so the PID, the working directory and the open HTTP socket all survive. There is nothing to run.

This is Odoo's own `--dev=reload` watcher, which `devMode = "all"` already asks for. Odoo only starts it if it can import a filesystem watcher, and it declares neither `inotify` nor `watchdog` as a dependency, so `--dev=all` alone logs `Code autoreload feature is disabled` once and never reloads. `watch.python` (on by default) closes that gap: a new project's `pyproject.toml` has `watchdog` in `[dependency-groups].dev`, and for an older project the dev process falls back to nixpkgs' `watchdog`. Look for this line at start-up:

```text
AutoReload watcher running with watchdog
```

What it covers:

- **Python**: every `addons_path` root is watched recursively, `odoo/odoo/addons`, `odoo/addons`, each `modules/<REPO>` and `custom/`. A change restarts the server; a syntax error is logged and the restart skipped until you fix it.
- **XML, QWeb and assets** need no restart: `--dev=xml` re-reads views, templates and JS and SCSS bundles from disk. Reload the browser.
- **Odoo's framework code** (`odoo/odoo/*.py`, such as `models.py` or `http.py`) is not an addons root and is not watched. Restart `devenv up` for those.
- **`settings.options.workers` must be 0**, the default. The watcher only runs on the threaded server, and the shell warns if you set workers or a `devMode` without `reload` while `watch.python` is on.

### Inotify queue overflow

Under a burst of file changes (`vite build --watch` rebuilding, `npm install`, a `git checkout` or a Python bytecode recompile) the log can fill with:

```text
WARNING ? watchdog.observers.inotify: Inotify queue overflowed; reconciling recursive watches below b'.../modules/<REPO>'
```

This is the kernel's per-instance event queue (`fs.inotify.max_queued_events`, 16384 by default) filling before the watcher reads it, not the watch-count limit (`max_user_watches`). `watchdog` recovers by rescanning, so nothing breaks; at worst one reload is spurious or missed.

Odoo watches every `addons_path` root recursively, `node_modules` and `__pycache__` included, and has no way to exclude them. Two ways to cut the noise:

- **Raise the queue limit.** On NixOS: `boot.kernel.sysctl."fs.inotify.max_queued_events" = 524288;`. Elsewhere: `sudo sysctl fs.inotify.max_queued_events=524288`, persisted in `/etc/sysctl.d/`. The dev server prints a one-line hint at start-up while the limit is under 65536.
- **Watch less.** `devMode = "xml,qweb"` (or `watch.python = false`) drops the watcher; Python edits then need a restart of `devenv up`.

## Python analysis

`ide.enable` (the dev-shell option, on by default) makes two things on shell entry. Odoo reads neither; they exist so a static analyser resolves the same names the interpreter does.

| What | Why |
| --- | --- |
| `./.venv`, a symlink to the Nix-built dev environment | The venv layout every editor probes for at the workspace root. |
| `.devenv/state/pythonpath` | A merged `odoo` package whose `addons/` gathers every `addons_path` root. |

The second is not optional. uv2nix installs every module editable through `.pth` files that call `os.path.expandvars`, which only a running interpreter executes. And `odoo.addons` is a namespace Odoo extends from `addons_path` at startup, while most standard addons (`sale`, `portal`, `mail`) live in `odoo/addons`, outside the `odoo` package. Without the mirror, `from odoo.addons.sale.models.sale_order import SaleOrder` is unresolved even for stock Odoo. The mirror links each module in first-root-wins order, as Odoo does, and is rebuilt only when that set changes.

With `ide.vscodeSettings` (the default), a missing `.vscode/settings.json` is seeded once, never overwritten, pointing the editor at both and keeping the file watcher and search out of `.devenv` and `.direnv`:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.analysis.extraPaths": [".devenv/state/pythonpath"],
  "files.watcherExclude": { "**/.devenv/**": true, "**/.direnv/**": true },
  "search.exclude": { "**/.devenv/**": true, "**/.direnv/**": true }
}
```

A missing `.vscode/extensions.json` is seeded the same way, recommending `Odoo.odoo`. For another editor, point its language server at the same two paths, for instance a `pyrightconfig.json` with `"venv": ".venv"` and the same `extraPaths`.

## The Odoo language server

`ide.languageServer.enable` (the default; it needs `ide.enable`) adds [odoo-ls](https://github.com/odoo/odoo-ls), a language server that understands `__manifest__.py`, ORM field types and XML view and QWeb references. It puts `odoo_ls_server` on the shell's `PATH` and symlinks a Nix-synthesized `./odools.toml` into place, like `odoo.conf` and `.venv`: gitignored and not edited by hand. It points odoo-ls at the OCB checkout, `addons_path` and the `.venv` interpreter, under one profile named `default`. Every path in it is relative to the file, so its content is the same on every machine.

The file also carries a diagnostic filter for the OCB checkout and the external (OCA) directory. Both sit inside the workspace, and odoo-ls reports problems for every file in it, so without the filter the Problems panel fills with upstream findings nobody in the project can fix. The filter needs odoo-ls 1.5 or later, which expands `${workspaceFolder}` in its paths; an older server ignores it.

Any editor's LSP client can run `odoo_ls_server` directly, over stdio, with no initialization options.

VS Code is the exception. The official [`Odoo.odoo`](https://marketplace.visualstudio.com/items?itemName=Odoo.odoo) extension bundles its own `odoo_ls_server` and has no setting to use another, so the Nix-built one never runs inside VS Code. Its server still reads the generated `./odools.toml`: it finds the file by walking up from the workspace folder. With `ide.vscodeSettings`, `.vscode/extensions.json` is seeded once to recommend `Odoo.odoo`.

Leave `Odoo.serverConfigPath` unset. The extension passes its value to the server without expanding variables, so `"${workspaceFolder}/odools.toml"` names a file that does not exist, and the server loads no configuration and indexes nothing. Its log then shows `Config file not found: ${workspaceFolder}/odools.toml`. Remove the setting from a `.vscode/settings.json` seeded by an earlier odoo-nix; with the standards' [`ide` module](#the-ide-module) on, sync removes it and keeps it out.

`ide.languageServer.package` defaults to odoo-ls built from odoo-nix's pinned `odoo-ls-src` and `odoo-ls-typeshed` inputs.

## The `ide` module

A repository on odoo-nix's [standards](../standards/README.md) can turn on the `ide` module (`ide.enable = true` in `[tool.odoo-nix]`; `recommended` leaves it off: editor settings are a team's taste). Sync then merges a set of keys into `.vscode/settings.json` and `.vscode/extensions.json`, the seed's files or your own. It owns those keys and nothing else: your other settings, their order, comments, the indent, inline arrays and a missing final newline all stay as they are.

| Setting | Value | Why |
| --- | --- | --- |
| `python.languageServer` | `"None"` | Odoo LS is the Python language server; Pylance alongside it reports the ORM's dynamic names as errors |
| `ty.diagnosticMode`, `ty.disableLanguageServices` | `"off"`, `true` | ty is off for addon code too |
| `ruff.path` | `["${workspaceFolder}/tools/.venv/bin/ruff"]` | the ruff the pre-commit hooks lock in `tools/uv.lock`, so the editor and the hooks agree |
| `[python]` | ruff as the formatter, format on save | |
| `[xml]`, `[javascript]` | prettier as the formatter, format on save | |
| `prettier.requireConfig`, `prettier.prettierPath` | `true`, `"./node_modules/prettier"` | the prettier `package-lock.json` locks, with the rendered `prettier.config.cjs` |
| `files.watcherExclude`, `search.exclude` | `.odoo-nix`, `tools/.venv`, `node_modules` | beside the seed's `.devenv` and `.direnv` |

`.vscode/extensions.json` gains `charliermarsh.ruff`, `esbenp.prettier-vscode` and `dbaeumer.vscode-eslint`, and they leave `unwantedRecommendations`.

The dev shell seeds only a missing file, and `odoo-init --standards` usually runs sync before the shell is ever entered. So when sync creates `.vscode/settings.json` or `.vscode/extensions.json`, it writes the seed's keys and the `Odoo.odoo` recommendation into it as well. From then on those are your keys, as if the shell had seeded them: sync does not check them, and turning `ide` off does not remove them. A file that already exists, seeded or your own, gets only the module's keys. `Odoo.serverConfigPath` is deleted wherever it is set (see above); `Odoo.selectedProfile` and every `python-envs.*` setting are never touched, and a `python-envs.*` setting gets a notice, since it overrides the interpreter. The module needs `python-lint` and `js-xml` on, which put ruff in `tools/.venv` and prettier in `node_modules`; the dev shell links both into the checkout. prettier itself skips `.vscode/`, so the files keep the layout you gave them.

Turning `ide` off takes back only the keys it wrote and that still have its values: a key you changed stays, and the seed's keys are never the module's to remove.
