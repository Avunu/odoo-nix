# Evaluation-level assertions over services.odoo-nix (modules/nixos.nix):
# what the module hands systemd, PostgreSQL and nginx, without building or
# booting anything. Same `pairs` shape as eval.nix; flake.nix turns each into
# a named mkEvalCheck.
#
# Mostly the journald contract shared with frappe-nix and wordpress-nix:
# APP_SERVICE/APP_SITE on every unit, stable SyslogIdentifiers, the switch
# that turns on priority-prefixed output, nginx's JSON access log and the
# PostgreSQL log settings. The VM tests (module-nginx, module-odoo-<major>)
# assert the same fields actually reach the journal.
{
  pkgs,
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
  tuned = eval {
    services.odoo-nix = {
      dbName = "acme";
      logging = {
        accessLog = false;
        slowQueryMs = 250;
      };
    };
  };

  fields = cfg: unit: cfg.systemd.services.${unit}.serviceConfig.LogExtraFields;
  site = [ "APP_SITE=acme" ];
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
  module-syslog-identifiers = {
    expected = {
      odoo = "odoo";
      odoo-migrate = "odoo-migrate";
      odoo-init = "odoo-init";
    };
    actual = lib.genAttrs [ "odoo" "odoo-migrate" "odoo-init" ] (
      u: pinned.systemd.services.${u}.serviceConfig.SyslogIdentifier
    );
  };

  # The switch the CLI reads (lib/odoo_nix_cli/journald.py): on by default,
  # off -- with a warning, not an error -- once logging.file takes the
  # records away from stderr.
  module-journald-env = {
    expected = {
      odoo = "1";
      odoo-migrate = "1";
      toFile = null;
      toFileWarns = true;
      defaultWarns = false;
    };
    actual = {
      odoo = pinned.systemd.services.odoo.environment.ODOO_NIX_JOURNALD or null;
      odoo-migrate = pinned.systemd.services.odoo-migrate.environment.ODOO_NIX_JOURNALD or null;
      toFile = toFile.systemd.services.odoo.environment.ODOO_NIX_JOURNALD or null;
      toFileWarns = lib.any (lib.hasInfix "logging.file is set") toFile.warnings;
      defaultWarns = lib.any (lib.hasInfix "services.odoo-nix") pinned.warnings;
    };
  };

  module-postgresql-logging = {
    expected = {
      prefix = "%d %u ";
      defaultSlow = null;
      slow = 250;
    };
    actual = {
      prefix = pinned.services.postgresql.settings.log_line_prefix;
      defaultSlow = pinned.services.postgresql.settings.log_min_duration_statement or null;
      slow = tuned.services.postgresql.settings.log_min_duration_statement;
    };
  };

  module-nginx-access-log = {
    expected = {
      format = true;
      journal = true;
      off = true;
    };
    actual = {
      format = lib.hasInfix "log_format journal_json escape=json '{\"time\":\"$time_iso8601\",\"site\":\"$host\"" pinned.services.nginx.commonHttpConfig;
      journal = lib.hasInfix "access_log syslog:server=unix:/dev/log,tag=nginx_access,nohostname journal_json;" pinned.services.nginx.commonHttpConfig;
      off = lib.hasInfix "access_log off;" tuned.services.nginx.commonHttpConfig;
    };
  };
}
