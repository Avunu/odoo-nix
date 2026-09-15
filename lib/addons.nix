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
#     extraAddonsAbs = [ ];
#   }

{
  lib,
  workspaceRoot,
  layout,
  # OCB from outside the workspace (a non-flake input) instead of the
  # `layout.coreSrc` submodule: the two core roots are then emitted as absolute
  # store paths, since a workspace-relative entry could never reach them.
  coreSource ? null,
  # Absolute addons roots (typically /nix/store paths) appended last, verbatim.
  # Kept separate from layout.extraAddons because those are workspace-relative
  # and get a "./" prefix — which would mangle an absolute path.
  extraAddonsAbs ? [ ],
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

  # The two OCB roots, always first: core kernel (base, web, …) then core UI
  # (account, sale, …). Workspace-relative for the submodule layout, absolute
  # when OCB comes from `coreSource`.
  coreRel = [
    "${layout.coreSrc}/odoo/addons"
    "${layout.coreSrc}/addons"
  ];
  coreAbs = map (sub: "${toString coreSource}/${sub}") [
    "odoo/addons"
    "addons"
  ];

  # The ordered list of workspace-relative addons-path components (no leading
  # "./"), core included unless it lives outside the workspace.
  componentsRel =
    lib.optionals (coreSource == null) coreRel
    ++ map (r: "${layout.externalDir}/${r}") externalRepos
    ++ lib.optional hasCustom layout.customDir
    ++ layout.extraAddons;

  # Absolute core roots, prepended to both renderings when coreSource is set.
  coreEntries = lib.optionals (coreSource != null) coreAbs;

  # Emit "./relative" entries: odoo.conf addons_path entries are resolved from
  # the CWD where `odoo-bin -c odoo.conf` runs (= workspace root). Relative
  # paths keep the file identical across machines and containers, and let it be
  # store-symlinked without baking a /nix/store or $HOME prefix.
  rel = p: "./" + p;

  # Absolute roots are already resolvable from any CWD, so they bypass `rel`
  # and are shared verbatim by both the relative and the absolute renderings.
  componentsAbs = map toString extraAddonsAbs;

  addonsPathList = coreEntries ++ map rel componentsRel ++ componentsAbs;
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
  addonsPathFor =
    root:
    lib.concatStringsSep "," (coreEntries ++ map (c: "${root}/${c}") componentsRel ++ componentsAbs);
}
