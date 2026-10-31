# The addons' JavaScript: python-devops-nix's lib.node (docs/conventions.md,
# JavaScript) over the workspace's addons. Odoo itself ships browser-ready JS
# and has no build step; an addon that needs packages, a bundler or a
# compiler says so with a package.json at its root (or at its repository's,
# as a workspace whose members are addons), and its `build` script writes
# what Odoo serves, by this project's convention under static/dist/
# (docs/development/frontend.md).
#
#   targets   the addons (and repository roots) with a package.json, as
#             [ { key; path; } ] for the shell's command
#   builds    { <key> = the target's tree after its build; } for every target
#             with a build script of its own or in a member: builtOdoo lays
#             each over the copied tree, and lib/python.nix builds a
#             whool-packaged addon's wheel from it
#   command   odoo-nix-node {list,install,build,watch}
#   managers  the package managers some target installs with, for the shell
#   hasWatch  whether any target has a watch script
#
# A target with dependencies and no lockfile is an evaluation error once it
# has to be built: nothing says which versions the build would get.
{
  pkgs,
  lib,
  base,
  workspaceRoot,
  layout,
  nodejs,
  # pnpm2nix-nzbr's source (odoo-nix's `pnpm2nix` input).
  pnpm2nix,
  # Keys (`custom/acme_ui`) to leave alone, neither built nor installed.
  excludes ? [ ],
  # { <key> = attrs merged into that target's node_modules derivation; }.
  overrides ? { },
  python ? pkgs.python3,
  ciVar ? "ODOO_NIX_CI",
}:

let
  label = "odoo-nix";
  inherit (base) node;

  addons = import ./addons.nix { inherit lib workspaceRoot layout; };

  found = node.discover {
    inherit label;
    candidates = lib.filter (c: !lib.elem c.key excludes) addons.nodeCandidates;
  };

  # A lockless target builds too: with nothing to install (a build script
  # that needs only node), or, with dependencies, to fail evaluation with the
  # fix (lib.node.modules) rather than ship the addon unbuilt.
  buildable = lib.filter node.builds (found.targets ++ found.lockless);

  buildOf =
    target:
    node.build {
      inherit
        pkgs
        label
        nodejs
        target
        ;
      nodeModules = node.modules {
        inherit
          pkgs
          label
          nodejs
          target
          pnpm2nix
          ;
        overrides = overrides.${target.key} or { };
      };
    };

  everyTarget = found.targets ++ found.lockless;
  managerOf =
    target:
    node.managerPackage {
      inherit
        pkgs
        label
        nodejs
        target
        ;
    };

  targetsFile = pkgs.writeText "odoo-nix-node-targets.json" (
    builtins.toJSON (
      map (t: {
        inherit (t) key;
        path = t.key;
      }) everyTarget
    )
  );
in
{
  inherit (found) targets covered lockless;

  builds = lib.listToAttrs (map (t: lib.nameValuePair t.key (buildOf t)) buildable);

  command = node.command {
    inherit
      pkgs
      label
      python
      ciVar
      ;
    targets = targetsFile;
  };

  # npm comes with node, which the shell has anyway.
  managers = lib.unique (map managerOf (lib.filter (t: t.manager != "npm") everyTarget));

  hasWatch = lib.any (t: t.hasWatch) everyTarget;
  hasTargets = everyTarget != [ ];
}
