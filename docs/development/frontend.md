---
title: Addon frontends
description: How an addon ships JavaScript that needs packages, a bundler or a compiler. Covers the package.json contract, which package manager installs it, what Nix builds into the deployed tree, the shell's install, build and watch, and two Vite recipes.
order: 8
tags: [javascript, node, pnpm, vite, assets]
updated: 2026-10-29
---

Odoo ships its own JavaScript ready for the browser, with OWL and no build step. It has no convention for package managers or bundlers. odoo-nix adds one, the same rule frappe-nix follows (python-devops-nix's [JavaScript conventions](https://github.com/Avunu/python-devops-nix/blob/main/docs/conventions.md#javascript)).

An addon with a `package.json` at its root is a JavaScript target. If that `package.json` has a `build` script, Nix runs it and deploys the result, so whatever Odoo serves comes from your own build. Use this for a custom frontend: a shopfloor-style single-page app, a widget written in TypeScript, or a library from npm bundled for an asset bundle.

## The contract

1. **`package.json` at the addon's root.** Without one, odoo-nix does nothing with the addon. A module repository can have one at its own root instead, as a workspace whose members are its addons: see [Workspaces](#workspaces).
2. **A lockfile picks the package manager.**

   | Lockfile | Manager |
   | --- | --- |
   | `pnpm-lock.yaml` | pnpm |
   | `yarn.lock` (yarn 1) | yarn |
   | `package-lock.json` | npm |

   A `packageManager` field (`"pnpm@10.4.1"`) or `devEngines.packageManager` (`{ "name": "pnpm", "version": "12.10.1" }`) in `package.json` takes precedence, and must agree with the lockfile. Its major version selects the nixpkgs package: `pnpm_10`, `pnpm_11` or `pnpm_12`, yarn 1, or the npm that ships with Node.js. Each of these stops evaluation with an error that says how to fix it:
   - two lockfiles in one folder;
   - a manager that disagrees with the lockfile;
   - a yarn berry lock;
   - a bun lock.
3. **The lockfile is required** if the addon has dependencies. Nothing else records which versions to install.
4. **Nix builds only if there is a `build` script.** It installs offline from the lockfile with `--ignore-scripts`, runs `<manager> run build` in the addon, and deploys the addon's tree as the build left it, without `node_modules`. An addon with a `package.json` but no build script (for example, one that only uses ESLint) is deployed as it is.
5. **A `watch` script is optional.** Under `devenv up`, it runs as the `node-watch` process.

The build output goes in **`static/dist/`**. Odoo serves everything under an addon's `static/`. From 17.0 on, Odoo treats any `.js` file under `static/src/` as an ES module of its own (`@odoo-module`) and transpiles it, so bundler output must stay out of there.

```gitignore
node_modules/
static/dist/
```

Nix always rebuilds `static/dist/`, so it doesn't need to be committed. Commit it only if the addon is also installed somewhere without odoo-nix.

## What Nix builds

`builtOdoo` copies each addon from the workspace, then lays its build on top. That is the package `services.odoo-nix` and the container image run. The install uses the hashes recorded in the lockfile, so there are no hashes to keep up to date:
- **npm:** nixpkgs' `importNpmLock`.
- **yarn 1:** one fetch per tarball in `yarn.lock`.
- **pnpm:** [pnpm2nix-nzbr](https://github.com/FliegendeWurst/pnpm2nix-nzbr).

The node_modules derivation takes only `package.json`, the lockfile and the manager's settings (`.npmrc`, `pnpm-workspace.yaml` and the like), so editing code doesn't reinstall anything.

A whool-packaged addon (one with its own `pyproject.toml`) is also installed as a wheel. Odoo looks in the wheel first, so the wheel is built from the built tree as well.

A package that genuinely needs its install script (a native addon compiled with node-gyp, say) gets it through `nodeOverrides`:

```nix
odoo-nix.nodeOverrides."custom/acme_ui".postInstall = "npm rebuild sharp";
```

`nodeExcludes = [ "<path>" ]` leaves an addon out entirely: Nix doesn't build it and the shell doesn't install it.

## In the shell

| What | When |
| --- | --- |
| `odoo-nix-node install` | On shell entry: each addon's frozen install (`npm ci`, `yarn install --frozen-lockfile`, `pnpm install --frozen-lockfile`). It is skipped when nothing it reads has changed, and in CI mode. A failure is reported, but the shell still opens. |
| `odoo module build [addon …]` | Runs the build scripts in the working tree, either all of them or the named addons (by name or by path). Nix runs the same scripts into `builtOdoo`. |
| `node-watch` | Under `devenv up`, when some addon has a `watch` script (`watch.node`). Each line of output is prefixed with the addon's path. With `--dev=all`, Odoo serves the rebuilt files without a restart. |
| `odoo-nix-node list` | The addons with a `package.json`, their manager, lockfile and scripts. |

Inside the shell, a pnpm whose version differs from the one `devEngines` names keeps running instead of downloading another (`pnpm_config_pm_on_fail=ignore`), so the shell and Nix build with the same pnpm.

## Workspaces

A module repository can be one workspace: a `package.json` and lockfile at its root, with the addons as members (`pnpm-workspace.yaml`'s `packages`, or `workspaces` in `package.json` for yarn and npm). The members have no lockfile of their own and are installed once, at the root. If the root has a `build` script, that script builds everything. If it doesn't, each member's `build` script runs. Either way the whole repository is built as one tree, and the members' outputs land in their own `static/dist/`.

## Two recipes

Most bundlers work. These use [Vite](https://vite.dev).

### A library for an Odoo asset bundle

Use this for a widget or a dependency that Odoo's own JavaScript calls. Build it as a classic script with a fixed file name, because Odoo's bundler adds its own cache-busting.

```js
// vite.config.js
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "static/dist",
    emptyOutDir: true,
    lib: {
      entry: "frontend/main.ts",
      name: "AcmeScanner", // the global the bundle defines
      formats: ["iife"],
      fileName: () => "acme_scanner.js",
    },
  },
});
```

```python
# __manifest__.py
"assets": {
    "web.assets_backend": [
        "acme_scanner/static/dist/acme_scanner.js",
        "acme_scanner/static/src/**/*",  # your OWL code, which calls window.AcmeScanner
    ],
},
```

### A standalone single-page app

This is the shopfloor shape: an app with its own page, served by a controller.

```js
// vite.config.js
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  base: "/acme_shopfloor/static/dist/",
  build: { outDir: "static/dist", emptyOutDir: true, manifest: true },
});
```

A controller route renders a QWeb template that loads the entry file. With `manifest: true`, it reads `static/dist/.vite/manifest.json` to find the hashed file names. The app calls Odoo over JSON-RPC, or over the REST API an addon such as `base_rest` provides.

## Troubleshooting

- **`… has dependencies and no lockfile`.** Run `npm install`, `yarn` or `pnpm install` in the addon, then commit the lockfile.
- **`… names pnpm 12.10.1 (devEngines.packageManager), but its lockfile is yarn.lock`.** Regenerate the lock with the manager you named, or change the field.
- **`… nixpkgs has no pnpm_7`.** The pinned nixpkgs has `pnpm_10` through `pnpm_12`. Move the addon to one of them.
- **A build that works in the shell but not in Nix.** Nix has no network and runs no install scripts. A package that downloads a binary on install needs `nodeOverrides`. A build step that fetches anything needs to stop doing that.
