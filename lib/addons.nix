# addons_path synthesis for Odoo projects — the odoo-nix keystone.
#
# Auto-derives Odoo's `addons_path` from the folders actually present in the
# workspace, so it can never drift out of sync with the submodules on disk
# (the failure mode of a hand-maintained odoo.conf).
#
# An "addons root" is any directory that contains at least one immediate child
# holding an `__manifest__.py` — i.e. a directory Odoo can scan for modules.
# Each OCA repo under src/external/<repo> is itself one such root (the repo dir
# holds many module subdirs), so it contributes ONE addons_path entry.
#
# Path ordering is load-bearing for Odoo (first match wins):
#   core base addons -> core UI addons -> OCA externals -> custom -> extras
#
# Usage:
#   import ./lib/addons.nix {
#     inherit lib;
#     workspaceRoot = ./.;
#     layout = { coreSrc = "odoo"; externalDir = "modules";
#                customDir = "custom"; extraAddons = [ ]; };
#   }

{
  lib,
  workspaceRoot,
  layout,
}:

let
  inherit (builtins) readDir attrNames pathExists;

  # True if `dir` has any immediate subdirectory containing __manifest__.py.
  hasModule =
    dir:
    pathExists dir
    && lib.any (
      child:
      (readDir dir).${child} == "directory" && pathExists (dir + "/${child}/__manifest__.py")
    ) (attrNames (readDir dir));

  externalRoot = workspaceRoot + "/${layout.externalDir}";

  # OCA repo dirs under src/external that actually contain modules, sorted for
  # deterministic output (readDir is already sorted, but be explicit).
  externalRepos =
    if pathExists externalRoot then
      lib.sort (a: b: a < b) (
        lib.filter (
          name:
          (readDir externalRoot).${name} == "directory" && hasModule (externalRoot + "/${name}")
        ) (attrNames (readDir externalRoot))
      )
    else
      [ ];

  hasCustom = pathExists (workspaceRoot + "/${layout.customDir}");

  # The ordered list of addons-path components, as paths relative to the
  # workspace root (no leading "./").
  componentsRel =
    [
      "${layout.coreSrc}/odoo/addons" # core kernel: base, web, …
      "${layout.coreSrc}/addons" # core UI: account, sale, …
    ]
    ++ map (r: "${layout.externalDir}/${r}") externalRepos
    ++ lib.optional hasCustom layout.customDir
    ++ layout.extraAddons;

  # Emit "./relative" entries: odoo.conf addons_path entries are resolved from
  # the CWD where `odoo-bin -c odoo.conf` runs (= workspace root). Relative
  # paths keep the file identical across machines and containers, and let it be
  # store-symlinked without baking a /nix/store or $HOME prefix.
  rel = p: "./" + p;
  addonsPathList = map rel componentsRel;
in
{
  # Discovered OCA repo dir names (e.g. [ "account-financial-tools" … ]).
  inherit externalRepos hasModule;

  # The ordered list of "./relative" addons_path entries.
  inherit addonsPathList;

  # Comma-separated relative addons_path for odoo.conf (dev shell, CWD = root).
  addonsPath = lib.concatStringsSep "," addonsPathList;

  # Absolute addons_path against an arbitrary root — for builds, the NixOS
  # module, and containers, where CWD is not the workspace root. Mirrors
  # frappe-nix/lib/bench.nix's `appsPath root`.
  addonsPathFor = root: lib.concatStringsSep "," (map (c: "${root}/${c}") componentsRel);
}
