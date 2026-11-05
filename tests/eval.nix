# Pure evaluation assertions over lib/addons.nix and lib/odoo-ini.nix.
#
# `pairs` is { name = { expected; actual; }; }; flake.nix turns each into its
# own derivation (lib.checks.mk's `eval`) that compares the two as JSON, so a failing
# assertion is reported by name instead of aborting the whole evaluation.
# `rendered` is a real odoo.conf for a grep-level check of the INI output.
#
# Nothing here touches an OCB input: addons.nix only ever stringifies
# coreSource, so a fake store path serves, and the tree under
# fixtures/addons-tree is synthetic (manifests only).
{ pkgs, lib }:
let
  addons = import ../lib/addons.nix;
  tree = ./fixtures/addons-tree;
  bare = ./fixtures/addons-tree-bare;
  layout = {
    coreSrc = "odoo";
    externalDir = "modules";
    customDir = "custom";
    extraAddons = [ ];
  };
  fakeCore = "/nix/store/00000000000000000000000000000000-ocb";
  fakeExtra = "/nix/store/00000000000000000000000000000000-odoo-nix-addons";

  submodule = addons {
    inherit lib layout;
    workspaceRoot = tree;
  };
  withExtra = addons {
    inherit lib;
    workspaceRoot = tree;
    layout = layout // {
      extraAddons = [ "vendor/x" ];
    };
  };
  core = addons {
    inherit lib layout;
    workspaceRoot = tree;
    coreSource = fakeCore;
    extraAddonsAbs = [ fakeExtra ];
  };
  empty = addons {
    inherit lib layout;
    workspaceRoot = bare;
  };

  # externalSources: a repository from outside the workspace, with the
  # module custom/ also has filtered out (what `exclude` does), as an
  # absolute root after the on-disk repositories. Its mod_a is not
  # installable, so it is no second copy of alpha-repo's.
  gamma = ./fixtures/external-gamma;
  gammaWithoutMyMod = builtins.path {
    path = gamma;
    name = "gamma-source";
    filter = path: _type: !(dirOf path == toString gamma && baseNameOf path == "my_mod");
  };
  external =
    sources:
    addons {
      inherit lib layout;
      workspaceRoot = tree;
      coreSource = fakeCore;
      externalSources = sources;
    };
  withGamma = external [
    {
      name = "gamma";
      src = gammaWithoutMyMod;
    }
  ];
  fails = v: !(builtins.tryEval (builtins.deepSeq v v)).success;

  # my_mod both in a submodule and in custom/ (a project's own business,
  # left as it always was), and custom/mod_a, which gamma's unported mod_a
  # would shadow from before it on addons_path.
  shadowTree = ./fixtures/addons-tree-shadow;
  onShadowTree =
    sources:
    addons {
      inherit lib layout;
      workspaceRoot = shadowTree;
      externalSources = sources;
    };

  # odoo.conf's INI dialect, shared by the dev shell and the NixOS module.
  odooIni = import ../lib/odoo-ini.nix { inherit pkgs lib; };
  full = {
    options = {
      addons_path = "./odoo/odoo/addons,./odoo/addons,./custom";
      db_host = "127.0.0.1";
      db_password = null;
      log_db = null;
      http_interface = "127.0.0.1";
      server_wide_modules = [
        "base"
        "rpc"
        "web"
        "queue_job"
      ];
      log_handler = [ "werkzeug:WARNING" ];
      without_demo = true;
      proxy_mode = true;
      limit_time_real = 1200;
      list_db = false;
    };
    queue_job = {
      enabled = true;
      host = "127.0.0.1";
      port = 2525;
    };
  };
in
{
  rendered = odooIni.generate "odoo.conf" full;

  pairs = {
    # ---- lib/addons.nix ----
    addons-external-repos = {
      expected = [
        "alpha-repo"
        "beta-repo"
      ];
      actual = submodule.externalRepos;
    };
    # a module must be an immediate child; a missing dir is simply "no"
    addons-has-module = {
      expected = [
        true
        false
        false
      ];
      actual = [
        (submodule.hasModule (tree + "/modules/alpha-repo"))
        (submodule.hasModule (tree + "/modules/nested-only"))
        (submodule.hasModule (tree + "/does-not-exist"))
      ];
    };
    addons-path-list = {
      expected = [
        "./odoo/odoo/addons"
        "./odoo/addons"
        "./modules/alpha-repo"
        "./modules/beta-repo"
        "./custom"
      ];
      actual = submodule.addonsPathList;
    };
    addons-path = {
      expected = "./odoo/odoo/addons,./odoo/addons,./modules/alpha-repo,./modules/beta-repo,./custom";
      actual = submodule.addonsPath;
    };
    addons-path-for = {
      expected = "/srv/odoo/odoo/odoo/addons,/srv/odoo/odoo/addons,/srv/odoo/modules/alpha-repo,/srv/odoo/modules/beta-repo,/srv/odoo/custom";
      actual = submodule.addonsPathFor "/srv/odoo";
    };
    addons-extra-addons-last = {
      expected = "./vendor/x";
      actual = lib.last withExtra.addonsPathList;
    };
    # coreSource: absolute core roots first, workspace components relative,
    # extraAddonsAbs verbatim and last -- in both renderings
    addons-core-source-list = {
      expected = [
        "${fakeCore}/odoo/addons"
        "${fakeCore}/addons"
        "./modules/alpha-repo"
        "./modules/beta-repo"
        "./custom"
        fakeExtra
      ];
      actual = core.addonsPathList;
    };
    addons-core-source-for = {
      expected = "${fakeCore}/odoo/addons,${fakeCore}/addons,/x/modules/alpha-repo,/x/modules/beta-repo,/x/custom,${fakeExtra}";
      actual = core.addonsPathFor "/x";
    };
    addons-external-sources-list = {
      expected = [
        "${fakeCore}/odoo/addons"
        "${fakeCore}/addons"
        "./modules/alpha-repo"
        "./modules/beta-repo"
        (toString gammaWithoutMyMod)
        "./custom"
      ];
      actual = withGamma.addonsPathList;
    };
    addons-external-sources-for = {
      expected = "${fakeCore}/odoo/addons,${fakeCore}/addons,/x/modules/alpha-repo,/x/modules/beta-repo,${gammaWithoutMyMod},/x/custom";
      actual = withGamma.addonsPathFor "/x";
    };
    # my_mod is installable in custom/ and in gamma: Odoo would load the first.
    addons-external-sources-duplicate = {
      expected = true;
      actual =
        fails
          (external [
            {
              name = "gamma";
              src = gamma;
            }
          ]).addonsPathList;
    };
    # A name already on disk under modules/, or given twice.
    addons-external-sources-clash = {
      expected = [
        true
        true
      ];
      actual = [
        (fails
          (external [
            {
              name = "alpha-repo";
              src = gammaWithoutMyMod;
            }
          ]).addonsPathList
        )
        (fails
          (external [
            {
              name = "g";
              src = gammaWithoutMyMod;
            }
            {
              name = "g";
              src = gammaWithoutMyMod;
            }
          ]).addonsPathList
        )
      ];
    };
    addons-submodule-duplicate-unchanged = {
      expected = [
        "./odoo/odoo/addons"
        "./odoo/addons"
        "./modules/r"
        "./custom"
      ];
      actual = (onShadowTree [ ]).addonsPathList;
    };
    # gamma's mod_a is not installable, but it comes first: Odoo would take
    # it and never see custom/mod_a.
    addons-external-sources-shadow = {
      expected = true;
      actual =
        fails
          (onShadowTree [
            {
              name = "gamma";
              src = gammaWithoutMyMod;
            }
          ]).addonsPathList;
    };
    addons-bare-workspace = {
      expected = [
        "./odoo/odoo/addons"
        "./odoo/addons"
      ];
      actual = empty.addonsPathList;
    };

    # ---- lib/odoo-ini.nix ----
    # Odoo's literals for booleans, decimal text for numbers, one
    # comma-separated value for a list.
    odoo-ini-values = {
      expected = [
        "True"
        "False"
        "1200"
        "base,rpc,web,queue_job"
        "x"
      ];
      actual = map odooIni.toIniValue [
        true
        false
        1200
        full.options.server_wide_modules
        "x"
      ];
    };
  };
}
