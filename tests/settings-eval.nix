# Evaluation-level assertions over the dev shell's `settings` (NixOS RFC 42;
# python-devops-nix CONVENTIONS.md, Framework config blocks): odoo.conf by
# section, in Odoo's spelling, with the keys the shell computes set into it.
# A consumer's flake is evaluated through lib.mkFlake and nothing is built.
# Same `pairs` shape as eval.nix; flake.nix turns each into a named check
# (lib.checks.mk's `eval`).
{
  pkgs,
  lib,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;
  inherit (inputs.python-devops-nix.lib) ports;

  perSystem =
    odoo-nix:
    (mkFlake
      {
        inputs.self = {
          outPath = ../.;
          inherit inputs;
        };
      }
      {
        debug = true;
        systems = [ system ];
        imports = [ ../modules/flake-module.nix ];
        perSystem.odoo-nix = {
          enable = true;
          name = "acme";
          workspaceRoot = ./fixtures/19.0;
          coreSource = inputs.ocb-19;
          odooSeries = "19.0";
        }
        // odoo-nix;
      }
    ).allSystems.${system}.config;

  options = config: config.odoo-nix.settings.options;
  shell = config: config.devenv.shells.default;
  # Whether evaluating the dev odoo.conf succeeds.
  evaluates = odoo-nix: (builtins.tryEval (perSystem odoo-nix).packages.odooConf.outPath).success;

  offset = ports.offsetFor "acme";
  defaults = perSystem { };
in
{
  # Every key the shell computes, readable from `settings`.
  settings-defaults = {
    expected = {
      addons_path = defaults.odoo-nix.settings.options.addons_path;
      admin_passwd = "admin";
      data_dir = "./.devenv/state/odoo";
      db_host = "127.0.0.1";
      db_name = "odoo_dev";
      db_port = 12000 + offset;
      db_user = "odoo";
      gevent_port = 11000 + offset;
      http_interface = "127.0.0.1";
      http_port = 10000 + offset;
      log_db_level = "warning";
      log_level = "info";
      server_wide_modules = [
        "base"
        "rpc"
        "web"
      ];
      workers = 0;
    };
    actual = options defaults;
  };

  # The rendered dev odoo.conf, byte for byte: the same text names the same
  # store path (lib/odoo-ini.nix renders through pkgs.writeText).
  settings-rendered = {
    expected =
      (pkgs.writeText "odoo.conf" ''
        [options]
        addons_path=${defaults.odoo-nix.settings.options.addons_path}
        admin_passwd=admin
        data_dir=./.devenv/state/odoo
        db_host=127.0.0.1
        db_name=odoo_dev
        db_port=${toString (12000 + offset)}
        db_user=odoo
        gevent_port=${toString (11000 + offset)}
        http_interface=127.0.0.1
        http_port=${toString (10000 + offset)}
        log_db_level=warning
        log_level=info
        server_wide_modules=base,rpc,web
        workers=0
      '').outPath;
    actual = defaults.packages.odooConf.outPath;
  };

  # 18.0's default server-wide modules have no `rpc`.
  settings-server-wide-18 = {
    expected = [
      "base"
      "web"
    ];
    actual =
      (options (perSystem {
        odooSeries = "18.0";
        workspaceRoot = ./fixtures/18.0;
        coreSource = inputs.ocb-18;
      })).server_wide_modules;
  };

  # A plain value wins over a computed default, without mkForce; null takes
  # the key out of odoo.conf; a new key is added; the shell follows what it
  # reads back (the role it creates, the directory it makes, the warning).
  settings-override =
    let
      config = perSystem {
        settings.options = {
          workers = 2;
          db_user = "me";
          db_host = null;
          data_dir = "./var/data";
          log_handler = [
            "werkzeug:WARNING"
            "odoo.sql_db:INFO"
          ];
          without_demo = true;
          limit_time_real = 1200;
        };
      };
    in
    {
      expected = {
        workers = 2;
        db_user = "me";
        db_host = null;
        data_dir = "./var/data";
        limit_time_real = 1200;
        role = true;
        dataDir = true;
        warning = true;
        text =
          (pkgs.writeText "odoo.conf" ''
            [options]
            addons_path=${config.odoo-nix.settings.options.addons_path}
            admin_passwd=admin
            data_dir=./var/data
            db_name=odoo_dev
            db_port=${toString (12000 + offset)}
            db_user=me
            gevent_port=${toString (11000 + offset)}
            http_interface=127.0.0.1
            http_port=${toString (10000 + offset)}
            limit_time_real=1200
            log_db_level=warning
            log_handler=werkzeug:WARNING,odoo.sql_db:INFO
            log_level=info
            server_wide_modules=base,rpc,web
            without_demo=True
            workers=2
          '').outPath;
      };
      actual = {
        inherit (options config)
          workers
          db_user
          db_host
          data_dir
          limit_time_real
          ;
        role = lib.hasInfix "CREATE ROLE me " (shell config).services.postgres.initialScript;
        dataDir = lib.hasInfix "./var/data" (shell config).enterShell;
        warning = lib.any (lib.hasInfix "settings.options.workers = 2") (shell config).warnings;
        text = config.packages.odooConf.outPath;
      };
    };

  # Any attribute beside `options` is an INI section of its own.
  settings-sections =
    let
      config = perSystem {
        settings.queue_job = {
          channels = "root:2";
          jobrunner = true;
        };
      };
    in
    {
      expected = {
        channels = "root:2";
        jobrunner = true;
        log_level = "info";
      };
      actual = {
        inherit (config.odoo-nix.settings.queue_job) channels jobrunner;
        inherit (options config) log_level;
      };
    };

  # The ports are the ports tree's: odoo.conf, PostgreSQL and the shell's env
  # move together, and a second value in settings is a conflict.
  settings-ports =
    let
      config = perSystem {
        ports = lib.mapAttrs (_: lib.mkForce) {
          http = 8169;
          gevent = 8172;
          db = 5442;
        };
      };
    in
    {
      expected = {
        conf = {
          http_port = 8169;
          gevent_port = 8172;
          db_port = 5442;
        };
        pg = 5442;
        env = "8169";
        conflict = false;
      };
      actual = {
        conf = { inherit (options config) http_port gevent_port db_port; };
        pg = (shell config).services.postgres.port;
        env = (shell config).env.ODOO_NIX_HTTP_PORT;
        conflict = evaluates { settings.options.http_port = 8069; };
      };
    };

  # dbName is db_name, and the database the shell's PostgreSQL creates; null
  # leaves both out.
  settings-db-name =
    let
      named = perSystem { dbName = "shop"; };
      none = perSystem { dbName = null; };
    in
    {
      expected = {
        named = {
          conf = "shop";
          pg = [ { name = "shop"; } ];
        };
        none = {
          conf = false;
          pg = [ ];
        };
        conflict = false;
      };
      actual = {
        named = {
          conf = (options named).db_name;
          pg = map (d: { inherit (d) name; }) (shell named).services.postgres.initialDatabases;
        };
        none = {
          conf = (options none) ? db_name;
          pg = (shell none).services.postgres.initialDatabases;
        };
        conflict = evaluates { settings.options.db_name = "other"; };
      };
    };

  # devMode is odoo-bin's --dev flag, not an odoo.conf key.
  settings-dev-mode =
    let
      config = perSystem { devMode = "xml"; };
    in
    {
      expected = {
        flag = true;
        conf = false;
        warning = true;
      };
      actual = {
        flag = lib.hasInfix "--dev=xml" (shell config).processes.odoo.exec;
        conf = (options config) ? dev_mode;
        warning = lib.any (lib.hasInfix ''devMode = "xml"'') (shell config).warnings;
      };
    };

  # 1.x's camelCase tree and its odooConf alias are refused, naming where
  # each key went; the shell does not evaluate.
  settings-removed =
    let
      old = {
        settings = {
          dbName = "x";
          logging.level = "debug";
          httpPort = 8069;
        };
        odooConf.workers = 1;
      };
      removals = (perSystem old).odoo-nix.removals;
    in
    {
      expected = {
        count = 4;
        dbName = true;
        logging = true;
        port = true;
        odooConf = true;
        evaluates = false;
      };
      actual = {
        count = builtins.length removals;
        dbName = lib.any (lib.hasInfix "settings.dbName (in") removals;
        logging = lib.any (lib.hasInfix "settings.options.{log_level,") removals;
        port = lib.any (lib.hasInfix "it is ports.http now") removals;
        odooConf = lib.any (lib.hasInfix "`odoo-nix.odooConf'") removals;
        evaluates = evaluates old;
      };
    };
}
