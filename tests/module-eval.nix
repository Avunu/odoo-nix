# Evaluation-level assertions over services.odoo-nix (modules/nixos.nix):
# what the module hands systemd, PostgreSQL and nginx, without building or
# booting anything. Same `pairs` shape as eval.nix; flake.nix turns each into
# a named check (lib.checks.mk's `eval`).
#
# Mostly the contracts shared with frappe-nix through python-devops-nix
# (PLAN.md, Phase 6): the journald vocabulary (APP_SERVICE/APP_SITE on every
# unit, SyslogIdentifier=odoo-<role>, roles from lib.journald.roles), the
# hardening baseline on every unit odoo-nix defines, init as the service user
# with LoadCredential, the socket directory, nginx's logs, the migrate.*
# options and the PostgreSQL log settings. The VM tests (nginx,
# service-<major>) assert the same on a running system.
{
  pkgs,
  # inputs.python-devops-nix.lib
  base,
  odooModule,
}:
let
  inherit (pkgs) lib;

  # Only `name`, passthru.addonsPath and passthru.builtOdoo (migrate's
  # assertion) are read; nothing below forces a path to it, so it is never
  # built.
  fakePackage = pkgs.runCommand "odoo-nix-eval-package" {
    passthru = {
      addonsPath = p: "${p}/addons";
      builtOdoo = null;
    };
  } "mkdir $out";

  eval =
    config:
    (import "${pkgs.path}/nixos/lib/eval-config.nix" {
      inherit (pkgs.stdenv.hostPlatform) system;
      modules = [
        odooModule
        {
          # Read by `warnings` below, which would otherwise warn about it.
          system.stateVersion = lib.trivial.release;
          services.odoo-nix = {
            enable = true;
            package = fakePackage;
            database.createLocally = true;
            nginx = {
              enable = true;
              domain = "odoo.example.com";
            };
          };
        }
        config
      ];
    }).config;

  pinned = eval {
    services.odoo-nix = {
      dbName = "acme";
      hardening.enable = true;
    };
  };
  # The default: no hardening (opt-in through 1.x).
  plain = eval { services.odoo-nix.dbName = "acme"; };
  multi = eval { services.odoo-nix.dbFilter = "^%d$"; };
  toFile = eval {
    services.odoo-nix = {
      dbName = "acme";
      hardening.enable = true;
      logging.file = "/var/log/odoo/odoo.log";
    };
  };
  withEnvFiles = eval {
    services.odoo-nix = {
      dbName = "acme";
      environmentFiles = [ "/run/agenix/odoo-backup" ];
    };
  };
  secrets = eval {
    services.odoo-nix = {
      dbName = "acme";
      database.passwordFile = "/run/agenix/odoo-db";
      adminPasswordFile = "/run/agenix/odoo-admin";
    };
  };
  socket = eval {
    services.odoo-nix = {
      dbName = "acme";
      nginx = {
        domain = lib.mkForce "";
        socketPath = "/run/odoo/nginx.sock";
      };
    };
  };
  # Evaluated for its assertions only: a socket straight in /run.
  badSocket = eval { services.odoo-nix.nginx.socketPath = "/run/nginx.sock"; };
  journaldOn = eval {
    services.odoo-nix = {
      dbName = "acme";
      logging.journald = true;
    };
  };
  journaldOff = eval {
    services.odoo-nix = {
      dbName = "acme";
      logging.journald = false;
    };
  };
  fileQuiet = eval {
    services.odoo-nix = {
      dbName = "acme";
      logging = {
        file = "/var/log/odoo/odoo.log";
        journald = false;
      };
    };
  };
  tuned = eval {
    services.odoo-nix = {
      dbName = "acme";
      logging.accessLog = false;
      database.slowQueryMs = 250;
    };
  };
  # The old path, an alias that warns through 1.x.
  renamedSlow = eval {
    services.odoo-nix = {
      dbName = "acme";
      logging.slowQueryMs = 125;
    };
  };

  # settings (NixOS RFC 42), rendered as the module renders odoo-base.conf.
  odooIni = import ../lib/odoo-ini.nix { inherit pkgs lib; };
  conf =
    cfg:
    (odooIni.generate "odoo-base.conf" (removeAttrs cfg.services.odoo-nix.settings [ "_module" ])).text;
  hasLine = cfg: line: lib.elem line (lib.splitString "\n" (conf cfg));
  overridden = eval {
    services.odoo-nix = {
      dbName = "acme";
      settings.options = {
        workers = 6;
        proxy_mode = false;
        dbfilter = "^acme-.*$";
        db_host = null;
      };
    };
  };
  sectioned = eval {
    services.odoo-nix = {
      dbName = "acme";
      settings.queue_job.channels = "root:2";
    };
  };
  # 1.0's flat form: an alias for settings.options that warns through 1.x,
  # and wins over a computed key, as `//` did.
  flat = eval {
    services.odoo-nix = {
      dbName = "acme";
      settings = {
        limit_time_cpu = 600;
        workers = 8;
        addons_path = "/srv/addons";
      };
    };
  };
  atoms = eval {
    services.odoo-nix = {
      dbName = "acme";
      withoutDemo = true;
      logging.handlers = [
        "odoo.sql_db:DEBUG"
        "werkzeug:WARNING"
      ];
      settings.options = {
        server_wide_modules = [
          "base"
          "web"
          "queue_job"
        ];
        unaccent = true;
      };
    };
  };
  nonIni = eval {
    services.odoo-nix = {
      dbName = "acme";
      settings.options.limit_time_cpu = {
        soft = 60;
      };
    };
  };

  fields = cfg: unit: cfg.systemd.services.${unit}.serviceConfig.LogExtraFields;
  site = [ "APP_SITE=acme" ];
  odooUnits = [
    "odoo"
    "odoo-migrate"
    "odoo-init"
  ];
  sc = cfg: unit: cfg.systemd.services.${unit}.serviceConfig;
  role =
    cfg: unit:
    lib.removePrefix "APP_SERVICE=" (lib.findFirst (lib.hasPrefix "APP_SERVICE=") "" (fields cfg unit));
  warns = cfg: infix: lib.any (lib.hasInfix infix) cfg.warnings;
  failed = cfg: map (a: a.message) (lib.filter (a: !a.assertion) cfg.assertions);
in
{
  service-log-fields-web = {
    expected = [ "APP_SERVICE=web" ] ++ site;
    actual = fields pinned "odoo";
  };
  service-log-fields-migrate = {
    expected = [ "APP_SERVICE=migrate" ] ++ site;
    actual = fields pinned "odoo-migrate";
  };
  service-log-fields-init = {
    expected = [ "APP_SERVICE=init" ] ++ site;
    actual = fields pinned "odoo-init";
  };
  service-log-fields-db = {
    expected = {
      postgresql = [ "APP_SERVICE=db" ] ++ site;
      postgresql-setup = [ "APP_SERVICE=db" ] ++ site;
    };
    actual = {
      postgresql = fields pinned "postgresql";
      postgresql-setup = fields pinned "postgresql-setup";
    };
  };
  service-log-fields-nginx = {
    expected = [ "APP_SERVICE=nginx" ] ++ site;
    actual = fields pinned "nginx";
  };
  # No pinned database, no one site: APP_SITE is left out, not guessed.
  service-log-fields-multi-db = {
    expected = {
      odoo = [ "APP_SERVICE=web" ];
      nginx = [ "APP_SERVICE=nginx" ];
    };
    actual = {
      odoo = fields multi "odoo";
      nginx = fields multi "nginx";
    };
  };
  # SyslogIdentifier=odoo-<role> (CONVENTIONS.md, Journald vocabulary).
  service-syslog-identifiers = {
    expected = {
      odoo = "odoo-web";
      odoo-migrate = "odoo-migrate";
      odoo-init = "odoo-init";
    };
    actual = lib.genAttrs odooUnits (u: (sc pinned u).SyslogIdentifier);
  };

  # Every role a unit carries is one of python-devops-nix's written list --
  # the same assertion frappe-nix's tests/logging-fields.nix makes -- and the
  # identifier is the product's prefix and that role.
  service-log-roles = {
    expected = {
      known = true;
      identifiers = true;
    };
    actual = {
      known = lib.all (u: lib.elem (role pinned u) base.journald.roles) (
        odooUnits
        ++ [
          "postgresql"
          "postgresql-setup"
          "nginx"
        ]
      );
      identifiers = lib.all (u: (sc pinned u).SyslogIdentifier == "odoo-${role pinned u}") odooUnits;
    };
  };

  # Journald formatting is always on (the odoo_journald graft); nothing sets
  # the old switch. logging.journald is a deprecated no-op that warns, except
  # where `false` silences the logging.file warning it always did.
  service-journald = {
    expected = {
      env = [ ];
      toFileWarns = true;
      defaultWarns = false;
      onWarns = true;
      offWarns = true;
      fileQuiet = [ ];
    };
    actual = {
      env = lib.filter (u: pinned.systemd.services.${u}.environment ? ODOO_NIX_JOURNALD) odooUnits;
      toFileWarns = warns toFile "logging.file is set";
      defaultWarns = warns pinned "services.odoo-nix";
      onWarns = warns journaldOn "logging.journald has no effect";
      offWarns = warns journaldOff "no longer turns that off";
      fileQuiet = lib.filter (lib.hasInfix "services.odoo-nix") fileQuiet.warnings;
    };
  };

  # python-devops-nix's sandboxing baseline on every unit odoo-nix defines,
  # with no UMask anywhere (odoo-nix#51: nginx reads the filestore through
  # the group), the state directory writable, and W+X memory only where Odoo
  # runs (wkhtmltopdf, rtlcss).
  service-hardening = {
    expected = {
      baseline = lib.genAttrs odooUnits (_: {
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        CapabilityBoundingSet = "";
        SystemCallFilter = [
          "@system-service"
          "~@privileged"
        ];
        umask = false;
        writable = true;
      });
      jit = {
        odoo = false;
        odoo-migrate = false;
        odoo-init = true;
      };
      families = [ "AF_UNIX" ];
      logDir = true;
    };
    actual = {
      baseline = lib.genAttrs odooUnits (
        u:
        let
          c = sc pinned u;
        in
        {
          inherit (c)
            NoNewPrivileges
            ProtectSystem
            ProtectHome
            PrivateTmp
            CapabilityBoundingSet
            SystemCallFilter
            ;
          umask = c ? UMask;
          writable = lib.elem "/var/lib/odoo" c.ReadWritePaths;
        }
      );
      jit = lib.genAttrs odooUnits (u: (sc pinned u).MemoryDenyWriteExecute);
      families = (sc pinned "odoo-init").RestrictAddressFamilies;
      logDir = lib.elem "/var/log/odoo" (sc toFile "odoo").ReadWritePaths;
    };
  };

  # hardening.enable defaults to false through 1.x: then the units carry no
  # sandboxing key at all, while init still runs as the service user.
  service-hardening-default = {
    expected = {
      enable = false;
      keys = lib.genAttrs odooUnits (_: [ ]);
      initUser = "odoo";
    };
    actual = {
      enable = plain.services.odoo-nix.hardening.enable;
      keys = lib.genAttrs odooUnits (
        u:
        lib.filter (k: (sc plain u) ? ${k}) (
          lib.attrNames base.nixos.hardening.baseline
          ++ [
            "ReadWritePaths"
            "RestrictAddressFamilies"
          ]
        )
      );
      initUser = (sc plain "odoo-init").User;
    };
  };

  # Production secrets (CONVENTIONS.md): init runs as the service user, and
  # the secret files reach it through LoadCredential, not by reading them.
  service-init-credentials = {
    expected = {
      user = "odoo";
      credentials = [
        "db_password:/run/agenix/odoo-db"
        "admin_passwd:/run/agenix/odoo-admin"
      ];
      none = [ ];
    };
    actual = {
      user = (sc secrets "odoo-init").User;
      credentials = (sc secrets "odoo-init").LoadCredential;
      none = (sc pinned "odoo-init").LoadCredential;
    };
  };

  # nginx's socket in its own 0770 directory (lib.nixos.unixSocket), and the
  # assertion for one that is not.
  service-socket = {
    expected = {
      rule = true;
      refused = true;
    };
    actual = {
      rule = lib.elem "d /run/odoo 0770 odoo odoo -" socket.systemd.tmpfiles.rules;
      refused = lib.any (lib.hasPrefix "services.odoo-nix.nginx.socketPath must be an absolute path inside its own directory") (
        failed badSocket
      );
    };
  };

  # The migrate.* options: python-devops-nix's four, with their defaults,
  # beside odoo-nix's own full and timeout.
  service-migrate-options = {
    expected = {
      enable = true;
      snapshot = true;
      rollbackOnFailure = true;
      snapshotRetention = 3;
      full = false;
      timeout = "infinity";
    };
    actual = pinned.services.odoo-nix.migrate;
  };

  # services.odoo-nix.environmentFiles reaches the units that run Odoo (the
  # auto_backup cron lives in the odoo process), and is empty by default.
  service-environment-files = {
    expected = {
      odoo = [ "/run/agenix/odoo-backup" ];
      odoo-migrate = [ "/run/agenix/odoo-backup" ];
      default = [ ];
    };
    actual = {
      odoo = withEnvFiles.systemd.services.odoo.serviceConfig.EnvironmentFile;
      odoo-migrate = withEnvFiles.systemd.services.odoo-migrate.serviceConfig.EnvironmentFile;
      default = pinned.systemd.services.odoo.serviceConfig.EnvironmentFile;
    };
  };

  service-postgresql-logging = {
    expected = {
      prefix = "%d %u ";
      defaultSlow = null;
      slow = 250;
      renamed = 125;
      renamedWarns = true;
    };
    actual = {
      prefix = pinned.services.postgresql.settings.log_line_prefix;
      defaultSlow = pinned.services.postgresql.settings.log_min_duration_statement or null;
      slow = tuned.services.postgresql.settings.log_min_duration_statement;
      renamed = renamedSlow.services.postgresql.settings.log_min_duration_statement;
      renamedWarns = warns renamedSlow "has been renamed to `services.odoo-nix.database.slowQueryMs'";
    };
  };

  service-nginx-access-log = {
    expected = {
      format = true;
      journal = true;
      off = true;
    };
    actual = {
      format = lib.hasInfix base.nixos.nginx.journalJsonFormat pinned.services.nginx.commonHttpConfig;
      journal = lib.hasInfix "access_log syslog:server=unix:/dev/log,tag=nginx_access,nohostname journal_json;" pinned.services.nginx.commonHttpConfig;
      off = lib.hasInfix "access_log off;" tuned.services.nginx.commonHttpConfig;
    };
  };

  # The error log over syslog, so it keeps its severity; the real-IP block and
  # the socket headers only on a unix-socket listener.
  service-nginx-socket = {
    expected = {
      errorLog = "syslog:server=unix:/dev/log,tag=nginx,nohostname error";
      realIp = true;
      tcpRealIp = false;
      headers = true;
    };
    actual = {
      errorLog = pinned.services.nginx.logError;
      realIp = lib.hasInfix base.nixos.nginx.cloudflareRealIp socket.services.nginx.virtualHosts.odoo.extraConfig;
      tcpRealIp =
        lib.hasInfix "real_ip_header"
          pinned.services.nginx.virtualHosts."odoo.example.com".extraConfig;
      headers =
        lib.hasInfix base.nixos.nginx.socketProxyHeaders
          socket.services.nginx.virtualHosts.odoo.locations."/".extraConfig;
    };
  };

  # A host's settings.options wins over a computed (mkDefault) key, without
  # mkForce; null drops the key.
  service-settings-override = {
    expected = {
      workers = true;
      proxy = true;
      dbfilter = true;
      noHost = true;
      effective = 6;
    };
    actual = {
      workers = hasLine overridden "workers=6";
      proxy = hasLine overridden "proxy_mode=False";
      dbfilter = hasLine overridden "dbfilter=^acme-.*$";
      noHost = !(lib.hasInfix "db_host" (conf overridden));
      effective = overridden.services.odoo-nix.settings.options.workers;
    };
  };

  # Any attribute beside `options` is a section of its own.
  service-settings-section = {
    expected = true;
    actual = lib.hasInfix "[queue_job]\nchannels=root:2\n" (conf sectioned);
  };

  service-settings-flat-alias = {
    expected = {
      limit = 600;
      workers = 8;
      addons = "/srv/addons";
      rendered = true;
      warns = true;
      once = 1;
      noFlat = false;
    };
    actual = {
      limit = flat.services.odoo-nix.settings.options.limit_time_cpu;
      inherit (flat.services.odoo-nix.settings.options) workers;
      addons = flat.services.odoo-nix.settings.options.addons_path;
      rendered = hasLine flat "limit_time_cpu=600";
      warns = warns flat "settings.limit_time_cpu -> settings.options.limit_time_cpu";
      once = lib.length (lib.filter (lib.hasInfix "settings.options.<key>") flat.warnings);
      noFlat = flat.services.odoo-nix.settings ? limit_time_cpu;
    };
  };

  # Bools as Odoo's True/False, lists comma-separated, ints as text.
  service-settings-atoms = {
    expected = [
      true
      true
      true
      true
      true
      true
    ];
    actual = map (hasLine atoms) [
      "server_wide_modules=base,web,queue_job"
      "log_handler=odoo.sql_db:DEBUG,werkzeug:WARNING"
      "unaccent=True"
      "without_demo=True"
      "list_db=False"
      "http_port=8069"
    ];
  };

  # A value pkgs.formats.ini cannot hold is a type error.
  service-settings-non-ini = {
    expected = false;
    actual = (builtins.tryEval (builtins.deepSeq (conf nonIni) true)).success;
  };
}
