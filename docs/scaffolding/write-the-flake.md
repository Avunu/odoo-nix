---
title: Write the flake by hand
description: The shape of an odoo-nix project flake and its layout, the options you will change most often, and the variant for a repository of modules that takes OCB as a flake input.
order: 3
tags: [flake, flake-parts, configuration]
updated: 2026-10-21
---

## The project layout

```text
.
├── flake.nix          # the thin wrapper below
├── pyproject.toml     # OCB and the modules as uv path sources; built by uv2nix
├── uv.lock            # committed lock: drives the Nix Python environment
├── modules.txt        # the modules to install (any installable module)
├── odoo/              # OCB (git submodule, branch = series)
├── modules/           # module repositories (git submodules)
│   ├── account-financial-reporting/
│   └── …
├── custom/            # your own modules
└── odoo.conf          # symlink into the Nix store, recreated on shell entry
```

`.devenv/state/` holds the development PostgreSQL cluster and Odoo's filestore. Nothing mutable is tracked.

## The flake

```nix
{
  inputs = {
    self.submodules = true;                  # submodule contents enter the flake source tree
    odoo-nix.url = "github:Avunu/odoo-nix/release-1";
    nixpkgs.follows = "odoo-nix/nixpkgs";    # flake-parts takes perSystem pkgs from `nixpkgs`
  };

  outputs = { self, odoo-nix, ... }@inputs:
    odoo-nix.lib.mkFlake { inherit inputs; } ({ ... }: {
      imports = [ odoo-nix.flakeModules.default ];
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" ];
      perSystem = { pkgs, ... }: {
        odoo-nix = {
          enable = true;
          name = "acme";
          workspaceRoot = ./.;
          odooSeries = "18.0";
          python = pkgs.python311;
          settings.dbName = "acme";
        };
      };
    });
}
```

`odoo-nix.lib.mkFlake` is `flake-parts.lib.mkFlake` with odoo-nix's own inputs (devenv, uv2nix and the rest) merged into yours, so you declare only `odoo-nix` and `nixpkgs.follows`. `self.submodules = true` is what lets Nix read OCB and the module repositories, and it is also why a fresh clone needs its submodules checked out before the flake can be evaluated (see [A fresh clone](../development/README.md#a-fresh-clone)).

The scaffolder writes `github:Avunu/odoo-nix`, which follows `main`. `release-1` follows every 1.x release and nothing that breaks it; see [Upgrading odoo-nix](../development/upgrading.md#which-odoo-nix-to-follow).

## Options you will change most

| Option                         | What it does                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------- |
| `name`                         | The project's identity: names its environments, packages, container image and ports. |
| `odooSeries`, `python`         | The series picks the OCB and OCA branch and catalog; `python` defaults to its preset. |
| `settings.*`                   | odoo.conf's `[options]`: `dbName`, `adminPasswd`, `workers`, `logging.*`, `extra`.   |
| `devguard.egress.allowHosts`   | Hosts the development guard rails let Odoo reach.                                     |
| `postgres.extensions`          | PostgreSQL extensions built into the dev server, such as PostGIS.                     |
| `restore.*`                    | How `odoo db restore` fetches from production.                                        |
| `containers.enable`            | Build the OCI image.                                                                  |

Every option is in [Dev shell options](../reference/dev-shell-options.md), and secrets are declared at the top level under `odoo-nix.secrets` ([Secrets](../development/secrets.md)).

## A repository of modules

An application project keeps OCB as the `odoo/` submodule: it is the thing being deployed. A repository that is itself mounted as an addons path, a library of modules other odoo-nix projects add under `modules/`, should not. Every consumer with `self.submodules = true` would recurse into that gitlink and fetch a second copy of OCB. Such a repository needs OCB only for its own dev shell and checks, so it takes it as a plain source input and sets `coreSource`:

```nix
{
  inputs = {
    odoo-nix.url = "github:Avunu/odoo-nix/release-1";
    nixpkgs.follows = "odoo-nix/nixpkgs";
    ocb = {
      url = "github:OCA/OCB/18.0";
      flake = false;
    };
  };

  outputs = { self, odoo-nix, ... }@inputs:
    odoo-nix.lib.mkFlake { inherit inputs; } ({ inputs, ... }: {
      imports = [ odoo-nix.flakeModules.default ];
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" ];
      perSystem = { pkgs, ... }: {
        odoo-nix = {
          enable = true;
          name = "my-addons";
          workspaceRoot = ./.;
          coreSource = inputs.ocb;      # no self.submodules, no odoo/ submodule
          layout.customDir = ".";       # the repository root is the addons directory
        };
      };
    });
}
```

With `coreSource` set:

- The dev shell keeps `odoo/` (`layout.coreSrc`) as a symlink to the store path, so add `/odoo` to `.gitignore`. `odoo-bin`, the scripts and the editor mirror find OCB where the submodule layout has it, and `pyproject.toml` and `uv.lock` are unchanged (`odoo` stays the path source `odoo/`). For the length of a `uv lock` (from `odoo project update` or `odoo module add`), the scripts point it at a writable shadow of the tree, because setuptools writes `odoo.egg-info` next to it and the store is read-only.
- The Python environment builds the `odoo` wheel from the store path.
- `addons_path`, in the dev `odoo.conf`, in `builtOdoo` and in the checks, carries the two core roots as absolute store paths, and `builtOdoo` links the tree instead of copying it.

Bump OCB with `nix flake update ocb`; `odoo project update` only pulls git submodules. Consumers can mount a repository laid out this way straight from its default branch.
