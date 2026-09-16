# Pure evaluation assertions over lib/addons.nix and lib/odoo-conf.nix.
#
# `pairs` is { name = { expected; actual; }; }; flake.nix turns each into its
# own derivation (mkEvalCheck) that compares the two as JSON, so a failing
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

  sampleConf = {
    dbHost = "127.0.0.1";
    dbPort = 5432;
    dbUser = "odoo";
    dbPassword = "False";
    dbName = "odoo_dev";
    dataDir = "./.devenv/state/odoo";
    adminPasswd = "admin";
    httpInterface = "127.0.0.1";
    httpPort = 8069;
    geventPort = 8072;
    workers = 0;
    logging = {
      level = "info";
      handlers = [ "werkzeug:WARNING" ];
      db = false;
      dbLevel = "warning";
      file = null;
    };
    withoutDemo = true;
    extra = {
      proxy_mode = true;
      limit_time_real = 1200;
    };
  };
  full = import ../lib/odoo-conf.nix {
    inherit pkgs lib;
    addonsPath = "./odoo/odoo/addons,./odoo/addons,./custom";
    odooConf = sampleConf;
    serverWideModules = [
      "base"
      "rpc"
      "web"
      "dev_mailcatch"
    ];
    extraSections.dev_mailcatch = {
      enabled = true;
      host = "127.0.0.1";
      port = 2525;
    };
  };
  minimal = import ../lib/odoo-conf.nix {
    inherit pkgs lib;
    addonsPath = "./custom";
    odooConf = sampleConf // {
      dbHost = "";
      dbName = null;
      withoutDemo = false;
      logging = sampleConf.logging // {
        handlers = [ ];
      };
      extra = { };
    };
  };
  # sampleConf has log_db off; two more renderings pin the other spellings
  logDbNamed = import ../lib/odoo-conf.nix {
    inherit pkgs lib;
    addonsPath = "./custom";
    odooConf = sampleConf // {
      logging = sampleConf.logging // {
        db = "audit";
      };
    };
  };
  logDbCurrent = import ../lib/odoo-conf.nix {
    inherit pkgs lib;
    addonsPath = "./custom";
    odooConf = sampleConf // {
      logging = sampleConf.logging // {
        db = true;
      };
    };
  };
in
{
  rendered = full.odooConfFile;

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

    # ---- lib/odoo-conf.nix ----
    odoo-conf-booleans = {
      expected = {
        proxy_mode = "True";
        limit_time_real = "1200";
      };
      actual = {
        inherit (full.optionsBlock) proxy_mode limit_time_real;
      };
    };
    # log_db: absent when off (19.0 warns about a literal False), "%d" for
    # `true`, the name otherwise
    odoo-conf-log-db = {
      expected = [
        false
        "%d"
        "audit"
      ];
      actual = [
        (full.optionsBlock ? log_db)
        logDbCurrent.optionsBlock.log_db
        logDbNamed.optionsBlock.log_db
      ];
    };
    # "False"/"" db_host + db_password are left out (socket, no password);
    # a real host is emitted
    odoo-conf-db-unset = {
      expected = [
        false
        false
        "127.0.0.1"
      ];
      actual = [
        (minimal.optionsBlock ? db_host)
        (minimal.optionsBlock ? db_password)
        full.optionsBlock.db_host
      ];
    };
    odoo-conf-http-interface = {
      expected = "127.0.0.1";
      actual = full.optionsBlock.http_interface;
    };
    odoo-conf-server-wide = {
      expected = "base,rpc,web,dev_mailcatch";
      actual = full.optionsBlock.server_wide_modules;
    };
    odoo-conf-default-server-wide = {
      expected = "base,web";
      actual = minimal.optionsBlock.server_wide_modules;
    };
    odoo-conf-optional-keys = {
      expected = {
        without_demo = "True";
        log_handler = "werkzeug:WARNING";
        db_name = "odoo_dev";
      };
      actual = {
        inherit (full.optionsBlock) without_demo log_handler db_name;
      };
    };
    odoo-conf-optional-keys-absent = {
      expected = [
        false
        false
        false
      ];
      actual = [
        (minimal.optionsBlock ? without_demo)
        (minimal.optionsBlock ? log_handler)
        (minimal.optionsBlock ? db_name)
      ];
    };
  };
}
