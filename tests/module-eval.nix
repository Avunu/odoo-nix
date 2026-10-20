# Evaluation-level assertions over services.odoo-nix (modules/nixos.nix):
# what the module hands systemd, PostgreSQL and nginx, without building or
# booting anything. Same `pairs` shape as eval.nix; flake.nix turns each into
# a named mkEvalCheck.
#
# Mostly the contracts shared with frappe-nix through python-devops-nix
# (PLAN.md, Phase 6): the journald vocabulary (APP_SERVICE/APP_SITE on every
# unit, SyslogIdentifier=odoo-<role>, roles from lib.journald.roles), the
# hardening baseline on every unit odoo-nix defines, init as the service user
# with LoadCredential, the socket directory, nginx's logs, the migrate.*
# options and the PostgreSQL log settings. The VM tests (module-nginx,
# module-odoo-<major>) assert the same on a running system.
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

  pinned = eval { services.odoo-nix.dbName = "acme"; };
  multi = eval { services.odoo-nix.dbFilter = "^%d$"; };
  toFile = eval {
    services.odoo-nix = {
      dbName = "acme";
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
  module-log-fields-web = {
    expected = [ "APP_SERVICE=web" ] ++ site;
    actual = fields pinned "odoo";
  };
  module-log-fields-migrate = {
    expected = [ "APP_SERVICE=migrate" ] ++ site;
    actual = fields pinned "odoo-migrate";
  };
  module-log-fields-init = {
    expected = [ "APP_SERVICE=init" ] ++ site;
    actual = fields pinned "odoo-init";
  };
  module-log-fields-db = {
    expected = {
      postgresql = [ "APP_SERVICE=db" ] ++ site;
      postgresql-setup = [ "APP_SERVICE=db" ] ++ site;
    };
    actual = {
      postgresql = fields pinned "postgresql";
      postgresql-setup = fields pinned "postgresql-setup";
    };
  };
  module-log-fields-nginx = {
    expected = [ "APP_SERVICE=nginx" ] ++ site;
    actual = fields pinned "nginx";
  };
  # No pinned database, no one site: APP_SITE is left out, not guessed.
  module-log-fields-multi-db = {
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
  module-syslog-identifiers = {
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
  module-log-roles = {
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
  module-journald = {
    expected = {
      env = [ ];
      toFileWarns = true;
      defaultWarns = false;
      onWarns = true;
      offWarns = true;
      fileQuiet = [ ];
    };
    actual = {
      env = lib.filter (u: (pinned.systemd.services.${u}.environment.ODOO_NIX_JOURNALD or null) != null) (
        odooUnits
      );
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
  module-hardening = {
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

  # Production secrets (CONVENTIONS.md): init runs as the service user, and
  # the secret files reach it through LoadCredential, not by reading them.
  module-init-credentials = {
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
  module-socket = {
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
  module-migrate-options = {
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
  module-environment-files = {
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

  module-postgresql-logging = {
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

  module-nginx-access-log = {
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
  module-nginx-socket = {
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
}
