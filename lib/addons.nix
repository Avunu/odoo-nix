# addons_path synthesis for Odoo projects — the odoo-nix keystone.
#
# Auto-derives Odoo's `addons_path` from the folders actually present in the
# workspace, so it can never drift out of sync with the submodules on disk
# (the failure mode of a hand-maintained odoo.conf).
#
# An "addons root" is any directory that contains at least one immediate child
# holding an `__manifest__.py` — i.e. a directory Odoo can scan for modules.
# Each OCA repo under modules/<repo> (layout.externalDir) is itself one such root (the repo dir
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
  # Module repositories from outside the workspace (modules/devenv.nix
  # `externalSources`), [ { name; src; } ] with `exclude` already applied to
  # src: absolute roots in the OCA slot, after the ones on disk, in list order.
  externalSources ? [ ],
}:

let
  inherit (builtins) readDir attrNames pathExists;

  # True if `dir` has any immediate subdirectory containing __manifest__.py.
  hasModule =
    dir:
    pathExists dir
    && lib.any (
      child: (readDir dir).${child} == "directory" && pathExists (dir + "/${child}/__manifest__.py")
    ) (attrNames (readDir dir));

  externalRoot = workspaceRoot + "/${layout.externalDir}";

  # OCA repo dirs under layout.externalDir that actually contain modules, sorted for
  # deterministic output (readDir is already sorted, but be explicit).
  externalRepos =
    if pathExists externalRoot then
      lib.sort (a: b: a < b) (
        lib.filter (
          name: (readDir externalRoot).${name} == "directory" && hasModule (externalRoot + "/${name}")
        ) (attrNames (readDir externalRoot))
      )
    else
      [ ];

  hasCustom = pathExists (workspaceRoot + "/${layout.customDir}");

  # An externalSources entry whose name is also a directory on disk under
  # layout.externalDir would be mounted where a submodule already is.
  externalNames = map (e: e.name) externalSources;
  clashing = lib.intersectLists externalNames externalRepos;
  duplicateNames = lib.filter (n: lib.count (m: m == n) externalNames > 1) (lib.unique externalNames);

  # Whether Odoo would install the module in DIR. `installable` is a Python
  # literal in __manifest__.py, so it is matched as text.
  isInstallable =
    dir:
    builtins.match ".*['\"]installable['\"][[:space:]]*:[[:space:]]*False.*" (
      builtins.replaceStrings [ "\n" ] [ " " ] (builtins.readFile (dir + "/__manifest__.py"))
    ) == null;

  # Every addons root but core, in addons_path order and labelled for the
  # error: each on-disk repository, each external source and the custom
  # directory.
  roots =
    map (r: {
      label = "${layout.externalDir}/${r}";
      dir = externalRoot + "/${r}";
      external = false;
    }) externalRepos
    ++ map (e: {
      label = "externalSources.${e.name}";
      dir = e.src;
      external = true;
    }) externalSources
    ++ lib.optional hasCustom {
      label = layout.customDir;
      dir = workspaceRoot + "/${layout.customDir}";
      external = false;
    };
  # Odoo takes the first copy of a module on addons_path, installable or
  # not, and ignores the rest. So a name in two roots is an error when more
  # than one copy is installable, or when the first is not and a later one
  # is (it would shadow it). Only names an external source takes part in: a
  # project's own submodules and custom/ are left as they always were. Names
  # are compared first, manifests read only for a name found twice.
  rootsOf = lib.foldl' (
    acc: root: lib.foldl' (a: m: a // { ${m} = (a.${m} or [ ]) ++ [ root ]; }) acc (addonDirs' root.dir)
  ) { } roots;
  addonDirs' = dir: if pathExists dir then addonDirs dir else [ ];
  installableHere = m: r: isInstallable (r.dir + "/${m}");
  conflicting =
    m: rs:
    let
      installable = lib.filter (installableHere m) rs;
    in
    lib.length installable > 1 || (installable != [ ] && !installableHere m (lib.head rs));
  duplicates = lib.filterAttrs conflicting (
    lib.filterAttrs (_: rs: lib.length rs > 1 && lib.any (r: r.external) rs) rootsOf
  );
  checked =
    if clashing != [ ] then
      throw "odoo-nix: externalSources ${lib.concatStringsSep ", " clashing}: ${layout.externalDir}/ already holds a repository of that name on disk. Rename the entry, or remove the submodule."
    else if duplicateNames != [ ] then
      throw "odoo-nix: externalSources names ${lib.concatStringsSep ", " duplicateNames} more than once."
    else if duplicates != { } then
      throw ''
        odoo-nix: a module is in more than one addons root, and Odoo loads only the first copy on addons_path:
        ${lib.concatStringsSep "\n" (
          lib.mapAttrsToList (
            m: rs:
            "  ${m}: ${
                lib.concatMapStringsSep ", " (
                  r: r.label + lib.optionalString (!installableHere m r) " (not installable)"
                ) rs
              }"
          ) duplicates
        )}
        Keep one: add the module to `exclude` of the externalSources entry it should not come from.''
    else
      true;

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

  # externalSources, absolute: after the on-disk repositories, before custom.
  externalEntries = map (e: toString e.src) externalSources;
  # componentsRel up to and including the on-disk repositories (core first
  # when it is in the workspace), and the rest.
  beforeExternal = lib.length externalRepos + (if coreSource == null then 2 else 0);
  relOca = lib.take beforeExternal componentsRel;
  relRest = lib.drop beforeExternal componentsRel;

  addonsPathList =
    assert checked;
    coreEntries ++ map rel relOca ++ externalEntries ++ map rel relRest ++ componentsAbs;

  # The directories that can be JavaScript targets (python-devops-nix
  # docs/conventions.md, JavaScript), as [ { key; src; } ] with keys relative
  # to the workspace: each module repository and the custom directory as
  # roots (a workspace whose members are its addons), and every addon in
  # them. Core OCB never: its own package.json is Odoo's tooling, not a
  # build Odoo needs.
  addonDirs =
    dir:
    lib.filter (
      child: (readDir dir).${child} == "directory" && pathExists (dir + "/${child}/__manifest__.py")
    ) (attrNames (readDir dir));
  join = key: child: if key == "." then child else "${key}/${child}";
  rootAndAddons =
    key: dir:
    [
      {
        inherit key;
        src = dir;
      }
    ]
    ++ map (child: {
      key = join key child;
      src = dir + "/${child}";
    }) (addonDirs dir);
  customKey = if layout.customDir == "." || layout.customDir == "" then "." else layout.customDir;
  nodeCandidates =
    lib.concatMap (
      repo: rootAndAddons "${layout.externalDir}/${repo}" (externalRoot + "/${repo}")
    ) externalRepos
    ++ lib.optionals hasCustom (rootAndAddons customKey (workspaceRoot + "/${layout.customDir}"));
in
{
  # Discovered OCA repo dir names (e.g. [ "account-financial-tools" … ]).
  inherit externalRepos hasModule;

  # The JavaScript target candidates: [ { key; src; } ] (lib/node.nix).
  inherit nodeCandidates;

  # The ordered list of "./relative" addons_path entries.
  inherit addonsPathList;

  # Comma-separated relative addons_path for odoo.conf (dev shell, CWD = root).
  addonsPath = lib.concatStringsSep "," addonsPathList;

  # Absolute addons_path against an arbitrary root — for builds, the NixOS
  # module, and containers, where CWD is not the workspace root. Mirrors
  # frappe-nix/lib/bench.nix's `appsPath root`.
  addonsPathFor =
    root:
    assert checked;
    lib.concatStringsSep "," (
      coreEntries
      ++ map (c: "${root}/${c}") relOca
      ++ externalEntries
      ++ map (c: "${root}/${c}") relRest
      ++ componentsAbs
    );
}
