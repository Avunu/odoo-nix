---
title: Python dependencies and locks
description: How pyproject.toml and uv.lock carry a project's Python dependencies into Nix through uv2nix, the managed blocks odoo-nix writes, what a stale lock looks like, and how to give a C extension its libraries.
order: 7
tags: [python, uv, uv2nix, locks]
updated: 2026-10-28
---

The project's `pyproject.toml` and `uv.lock` are its single Python manifest, built by [uv2nix](https://github.com/pyproject-nix/uv2nix). Dependency resolution is uv's alone; odoo-nix only lists what is on disk.

## Where dependencies come from

- OCA modules are [whool](https://github.com/sbidoul/whool) packages, `odoo-addon-<MODULE>`. Each one's build metadata declares its dependencies from `__manifest__.py`: `odoo-addon-<DEP>` for an OCA dependency, `odoo` for a core one, and `external_dependencies.python` as ordinary PyPI requirements.
- OCB itself is the `odoo` path dependency. Its `setup.py` carries Odoo's own requirements, so uv resolves those too.

## The managed blocks

`lib/oca_sources.py` writes two blocks of `pyproject.toml`, between `# >>> odoo-nix: … >>>` markers. `odoo project relock` regenerates them, and so do `odoo module add`, `add-bundle`, `remove` and `odoo project update`, which re-lock the same way; do not edit them by hand.

- `[project].dependencies`: `odoo` and every module in `modules.txt` as `odoo-addon-<NAME>`, the install roots.
- `[tool.uv.sources]`: `odoo` (the OCB submodule) and every local module, as editable path sources.

uv then resolves the closure of the roots against those local sources and fetches only the genuine external dependencies from PyPI. Adding a module or changing a manifest's dependencies is picked up by the next lock.

A module that is not packaged (a plain addons repository with no per-module `pyproject.toml` or `setup.py`, which Odoo allows) cannot be a uv source. It stays on `addons_path` only and is folded into the install set instead: walking from the roots, its `external_dependencies.python` become direct requirements and its packaged `depends` become `odoo-addon-<DEP>` roots.

The rest of `pyproject.toml` is yours. `[dependency-groups].dev` holds development and test tools (`debugpy`, `ruff`, `watchdog`, `freezegun`, `websocket-client` in a new project); they reach the dev and test environments and never production.

## The environments

| Environment | Package | Contents |
| --- | --- | --- |
| production | `odooPythonEnv` | Real wheels for `odoo` and every module. No dev group, no guard rails. |
| development | `odooDevEnv` | Every local module installed editable against the checkout, plus the dev group and the [guard rails](guard-rails.md). Odoo itself runs from the checkout's `odoo-bin`, or [without one](commands.md) from its `odoo` package. |
| test | `odooTestEnv` | The production wheels plus the dev group and the guard rails, with no checkout needed, for sandboxed runs. |

The package set is uv2nix's, then python-devops-nix's shared package fixes (`lib.python.overrides`: psycopg2, python-ldap, lxml, pycups, python-magic, pyvips and cairocffi), then odoo-nix's own (the OCB build, `lxml_html_clean`), then the project's `pythonOverrides`.

## Build dependencies of old sdists

Some legacy packages that only ship an sdist do not declare `setuptools` as a build dependency. A managed `[tool.uv.extra-build-dependencies]` block grants it to them. `odoo-nix-build-deps update` (python-devops-nix's `lib.python.buildDeps`) derives the block from `uv.lock` after each lock, and `odoo-nix-build-deps check` fails when it is out of date. `odoo project relock`, `odoo project update` and `odoo module …` run it for you.

## Re-locking a project

```bash
odoo project relock                            # after editing modules.txt or pyproject.toml by hand
odoo project relock --upgrade-package lxml     # arguments go to uv lock
nix run .#relock                               # the same, outside the shell
nix run .#relock -- --upgrade-package lxml
```

`odoo project relock` is the project's one re-lock command. It rewrites the managed blocks from `modules.txt` and what is on disk, runs `uv lock`, syncs the build-dependency block and locks again. It pulls nothing and moves no submodule. `odoo project update` runs the same code after pulling, and `odoo module add`, `add-bundle` and `remove` after changing the workspace. Commit `pyproject.toml` and `uv.lock` afterwards, then `direnv reload`.

`nix run .#relock` is the same re-lock as a flake app, for when the shell does not start. It runs the same code with the same configuration, from the project root, and evaluates nothing that reads `uv.lock`, so it works when the lock is too stale for the shell to evaluate (see [A stale lock is an evaluation error](#a-stale-lock-is-an-evaluation-error)). First it does what shell entry would have done in a clone whose shell never started: it checks out the submodules the clone has never had, and makes the `odoo/` link to `coreSource`. That matters after a pull that brings a new module repository: `git pull` does not check it out, and a module that is not on disk is left out of the lock.

A failed `uv lock` exits with uv's status here. `odoo module …` and `odoo project update` report the failed lock and carry on: fix `pyproject.toml`, then run `odoo project relock`. In odoo-nix's own repository, `nix run .#relock-fixtures` re-locks its test fixtures (see [Re-locking](../reference/layout.md#re-locking)).

## A stale lock is an evaluation error

Every environment goes through python-devops-nix's stale-lock audit. A dependency that `pyproject.toml` declares and `uv.lock` lacks, such as a module added to `modules.txt` without re-locking, fails evaluation with a message that names it:

```text
odoo-nix: uv.lock does not cover every declared dependency, so the Python
environment cannot be resolved.
```

uv2nix alone would build the environment without it, and Odoo would fail later on a missing import. The `odoo` command is not available until the shell starts, so re-lock from the project root with `nix run .#relock`, commit `pyproject.toml` and `uv.lock`, and re-enter the shell. For a genuine version conflict, use `[tool.uv] override-dependencies`.

## C extensions that need a library

When a module pulls in a C extension that needs system headers, expose the library declaratively instead of writing an override. `pythonLibraries` maps a Python package to nixpkgs libraries whose `.dev` headers and pkg-config are added to its build:

```nix
odoo-nix.pythonLibraries = {
  python-snappy = [ pkgs.snappy ];
};
```

The shared fixes above need no entry. `python-magic`, for one, is pointed at nixpkgs' libmagic, so it works outside the dev shell too. For anything more, `pythonOverrides` takes a uv2nix overlay, and `lib.overrides` has the shared fixes one by one as overlays for a flake that builds its own package set.
