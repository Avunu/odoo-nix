---
title: Editors and live reload
description: How the dev server restarts itself on a Python change, and how the shell exposes the environment to Pylance, pyright and the odoo-ls language server.
order: 8
tags: [editor, reload, language-server, odoo-ls]
updated: 2026-10-23
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

## Python analysis

`ide.enable` (the default) makes two things on shell entry. Odoo reads neither; they exist so a static analyser resolves the same names the interpreter does.

| What | Why |
| --- | --- |
| `./.venv`, a symlink to the Nix-built dev environment | The venv layout every editor probes for at the workspace root. |
| `.devenv/state/pythonpath` | A merged `odoo` package whose `addons/` gathers every `addons_path` root. |

The second is not optional. uv2nix installs every module editable through `.pth` files that call `os.path.expandvars`, which only a running interpreter executes. And `odoo.addons` is a namespace Odoo extends from `addons_path` at startup, while most standard addons (`sale`, `portal`, `mail`) live in `odoo/addons`, outside the `odoo` package. Without the mirror, `from odoo.addons.sale.models.sale_order import SaleOrder` is unresolved even for stock Odoo. The mirror links each module in first-root-wins order, as Odoo does, and is rebuilt only when that set changes.

With `ide.vscodeSettings` (the default), a `.vscode/settings.json` is seeded once, never overwritten, pointing Pylance at both and keeping the file watcher and search out of `.devenv` and `.direnv`:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.analysis.extraPaths": [".devenv/state/pythonpath"]
}
```

For another editor, point its language server at the same two paths, for instance a `pyrightconfig.json` with `"venv": ".venv"` and the same `extraPaths`.

## The Odoo language server

`ide.languageServer.enable` (the default; it needs `ide.enable`) adds [odoo-ls](https://github.com/odoo/odoo-ls), a language server that understands `__manifest__.py`, ORM field types and XML view and QWeb references. It puts `odoo_ls_server` on the shell's `PATH` and symlinks a Nix-synthesized `./odools.toml` into place, like `odoo.conf` and `.venv`: gitignored and not edited by hand. It points odoo-ls at the OCB checkout, `addons_path` and the `.venv` interpreter, under one profile named `default`. Every path in it is relative to the file, so its content is the same on every machine.

Any editor's LSP client can run `odoo_ls_server` directly, over stdio, with no initialization options.

VS Code is the exception. The official [`Odoo.odoo`](https://marketplace.visualstudio.com/items?itemName=Odoo.odoo) extension bundles its own `odoo_ls_server` and has no setting to use another, so the Nix-built one never runs inside VS Code. With `ide.vscodeSettings`, two things are seeded once to help it anyway: `.vscode/extensions.json` recommends `Odoo.odoo`, and `.vscode/settings.json` gets `"Odoo.serverConfigPath": "${workspaceFolder}/odools.toml"`, so its bundled server reads the same configuration.

`ide.languageServer.package` defaults to odoo-ls built from odoo-nix's pinned `odoo-ls-src` and `odoo-ls-typeshed` inputs.
