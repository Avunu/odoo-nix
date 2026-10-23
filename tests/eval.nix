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
