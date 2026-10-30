# The addons' JavaScript (lib/node.nix over python-devops-nix's lib.node),
# against tests/fixtures/node-project: a consumer-shaped workspace whose
# custom addons install with npm and yarn, one has a package.json for tooling
# and no build, one has none, one has dependencies and no lockfile; and a
# module repository whose root is a pnpm workspace of two addons.
#
#   pairs  -- { name = { expected; actual; }; } for lib.checks.mk's `eval`
#   built  -- the assembled tree (lib/odoo.nix), checked file by file: what
#             each build wrote, no node_modules, the untouched addons as they
#             were, and odoo-nix-node over a copy of the workspace
#
# No OCB: lib/odoo.nix only links coreSource, so a fake store path serves.
{
  pkgs,
  lib,
  inputs,
  scriptCheck,
}:
let
  base = inputs.python-devops-nix.lib;
  workspaceRoot = ./fixtures/node-project;
  layout = {
    coreSrc = "odoo";
    externalDir = "modules";
    customDir = "custom";
    extraAddons = [ ];
  };
  fakeCore = "/nix/store/00000000000000000000000000000000-ocb";

  nodeFor =
    excludes:
    import ../lib/node.nix {
      inherit
        pkgs
        lib
        base
        workspaceRoot
        layout
        excludes
        ;
      nodejs = pkgs.nodejs_22;
      inherit (inputs) pnpm2nix;
    };
  node = nodeFor [ "custom/lockless_ui" ];
  everything = nodeFor [ ];

  builtOdoo = import ../lib/odoo.nix {
    inherit
      pkgs
      lib
      workspaceRoot
      layout
      ;
    projectName = "odoo-nix-node-fixture";
    odooSeries = "18.0";
    coreSource = fakeCore;
    odooPythonEnv = pkgs.python3;
    nodeBuilds = node.builds;
  };

  attempt =
    x:
    let
      r = builtins.tryEval (builtins.deepSeq x x);
    in
    if r.success then r.value else "error";
in
{
  pairs = {
    node-targets = {
      expected = [
        "custom/lint_only"
        "custom/npm_ui"
        "custom/yarn_ui"
        "modules/frontends"
      ];
      actual = lib.sort (a: b: a < b) (map (t: t.key) node.targets);
    };
    # The repository's lock installs its addons; they have none of their own.
    node-workspace-members = {
      expected = [
        {
          key = "modules/frontends/kiosk_ui";
          root = "modules/frontends";
        }
        {
          key = "modules/frontends/pos_ui";
          root = "modules/frontends";
        }
      ];
      actual = node.covered;
    };
    # Only what has a build script, its own or its members': not lint_only.
    node-builds = {
      expected = [
        "custom/npm_ui"
        "custom/yarn_ui"
        "modules/frontends"
      ];
      actual = lib.attrNames node.builds;
    };
    node-managers = {
      expected = [
        "pnpm"
        "yarn"
      ];
      actual = lib.sort (a: b: a < b) (map lib.getName node.managers);
    };
    # Dependencies and no lockfile: refused once Nix has to build it.
    node-lockless-refused = {
      expected = "error";
      actual = attempt everything.builds."custom/lockless_ui".drvPath;
    };
    node-lockless-listed = {
      expected = [ "custom/lockless_ui" ];
      actual = map (t: t.key) everything.lockless;
    };
    node-excludes = {
      expected = [ ];
      actual = map (t: t.key) node.lockless;
    };
    node-watch = {
      expected = false;
      actual = node.hasWatch;
    };
  };

  built = scriptCheck "node-built" { tools = [ pkgs.diffutils ]; } ''
    t=${builtOdoo}
    for a in custom/npm_ui custom/yarn_ui modules/frontends/pos_ui modules/frontends/kiosk_ui; do
      name=''${a##*/}
      [ "$(cat "$t/$a/static/dist/$name.js")" = "window.$name = true;" ] \
        || { echo "$a: static/dist/$name.js is missing or wrong" >&2; exit 1; }
    done
    if find "$t" -name node_modules | grep -q .; then
      echo "node_modules in the assembled tree:" >&2
      find "$t" -name node_modules >&2
      exit 1
    fi
    diff -r ${workspaceRoot}/custom/lint_only "$t/custom/lint_only"
    diff -r ${workspaceRoot}/custom/plain "$t/custom/plain"
    [ -f "$t/custom/npm_ui/__manifest__.py" ]

    # odoo-nix-node over a copy of the workspace: the targets it lists.
    cp -r ${workspaceRoot} ws
    chmod -R u+w ws
    cd ws
    ${lib.getExe node.command} list > list.txt
    grep -q '^custom/npm_ui	npm	package-lock.json	build$' list.txt
    grep -q '^modules/frontends	pnpm	pnpm-lock.yaml	-$' list.txt
  '';
}
