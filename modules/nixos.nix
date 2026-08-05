# Standalone NixOS module: services.odoo-nix
#
# Production systemd runtime for an odoo-nix project. Single Odoo instance per
# deployment (multi-tenancy via dbfilter). A single odoo.service runs the
# assembled builtOdoo package via `odoo-bin`, forking --workers=N HTTP workers
# plus the gevent/websocket process itself (no separate longpolling unit).
#
# Config synthesis: a base odoo.conf (no secrets) is written to the Nix store
# via pkgs.formats.ini; an odoo-init oneshot copies it to a 0600 runtime file
# and appends db_password / admin_passwd from secret files (ConfigParser
# last-wins), so secret *values* never enter /nix/store.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  inherit (lib) mkOption mkEnableOption mkIf types optionalString;
  cfg = config.services.odoo-nix;

  dbName = cfg.dbName;
  socketAuth = cfg.database.createLocally && cfg.database.passwordFile == null;

  # nginx serves the public side over a unix socket; Odoo itself stays on
  # loopback TCP. Verified against the Odoo 18.0 source this module builds:
  # ThreadedWSGIServerReloadable.__init__ hands (host, port) straight to
  # werkzeug.serving.ThreadedWSGIServer, bypassing run_simple/make_server where
  # werkzeug's own `unix://` support lives; PreforkServer builds AF_INET and
  # binds a 2-tuple; and server_bind's socket-activation branch hardcodes
  # AF_INET in socket.fromfd. (19.x adds http_socket_activation but still passes
  # AF_INET explicitly, which CPython does not verify against the real fd.)
  nginxSocket = cfg.nginx.socketPath != "";
  nginxSocketDir = builtins.dirOf cfg.nginx.socketPath;

  # The vhost only needs a name to key it; with a single server block on the
  # socket it is the default server, so server_name never has to match.
  vhostName = if cfg.nginx.domain != "" then cfg.nginx.domain else "odoo";

  # recommendedProxySettings hardcodes `X-Forwarded-Proto $scheme`, and NixOS
  # emits its include AFTER a location's extraConfig, so the wrong scheme cannot
  # be overridden from there — Odoo's proxy_mode would then build http URLs and
  # drop the Secure flag on session cookies. Opt each location out and set the
  # whole header block explicitly.
  socketProxyHeaders = optionalString nginxSocket ''
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Server $hostname;
  '';

  # Base [options] (no secrets). addons_path is the assembled package's absolute
  # path; data_dir + the conf live under the stateful directory.
  baseOptions =
    {
      addons_path = cfg.package.passthru.addonsPath "${cfg.package}";
      data_dir = "${cfg.stateDir}/data";
      db_host = if socketAuth then "False" else cfg.database.host;
      db_port = if socketAuth then "False" else toString cfg.database.port;
      db_user = cfg.database.user;
      http_interface = cfg.http.interface;
      http_port = toString cfg.http.port;
      gevent_port = toString cfg.http.longpollingPort;
      workers = toString cfg.workers;
      max_cron_threads = toString cfg.maxCronThreads;
      proxy_mode = if cfg.nginx.enable then "True" else "False";
      list_db = if cfg.listDb then "True" else "False";
      log_level = cfg.logLevel;
    }
    // lib.optionalAttrs (dbName != null) {
      db_name = dbName;
      dbfilter = "^${dbName}$";
    }
    // lib.optionalAttrs (cfg.dbFilter != "") {
      dbfilter = cfg.dbFilter;
    }
    // builtins.mapAttrs (
      _n: v: if builtins.isBool v then (if v then "True" else "False") else toString v
    ) cfg.settings;

  baseConf = (pkgs.formats.ini { }).generate "odoo-base.conf" { options = baseOptions; };

  runtimeConf = "${cfg.stateDir}/odoo.conf";

  # Native runtime tools Odoo shells out to (PDF, RTL CSS, psql for restores).
  runtimePath = [
    pkgs.wkhtmltopdf
    pkgs.rtlcss
    pkgs.postgresql
    pkgs.git
    pkgs.gnused
    pkgs.coreutils
  ];

  serviceEnv = {
    ODOO_RC = runtimeConf;
    LANG = "C.UTF-8";
  }
  // cfg.extraEnv;

  mkInitScript = pkgs.writeShellScript "odoo-nix-init" ''
    set -euo pipefail
    umask 077
    mkdir -p "${cfg.stateDir}/data"
    cp ${baseConf} ${runtimeConf}
    chmod 0600 ${runtimeConf}
    ${optionalString (cfg.database.passwordFile != null) ''
      printf 'db_password = %s\n' "$(cat ${cfg.database.passwordFile})" >> ${runtimeConf}
    ''}
    ${optionalString (cfg.adminPasswordFile != null) ''
      printf 'admin_passwd = %s\n' "$(cat ${cfg.adminPasswordFile})" >> ${runtimeConf}
    ''}
    chown ${cfg.user}:${cfg.group} ${runtimeConf} "${cfg.stateDir}/data"
  '';
in
{
  options.services.odoo-nix = {
    enable = mkEnableOption "Odoo (OCB + OCA) production service";

    package = mkOption {
      type = types.package;
      description = "The assembled Odoo package (builtOdoo) from the project flake.";
      example = lib.literalExpression "projectFlake.packages.x86_64-linux.default";
    };

    user = mkOption {
      type = types.str;
      default = "odoo";
    };
    group = mkOption {
      type = types.str;
      default = "odoo";
    };

    stateDir = mkOption {
      type = types.path;
      default = "/var/lib/odoo";
      description = "Stateful directory: holds the runtime odoo.conf + filestore.";
    };

    http = {
      port = mkOption {
        type = types.port;
        default = 8069;
      };
      longpollingPort = mkOption {
        type = types.port;
        default = 8072;
        description = "gevent/websocket port (set as gevent_port).";
      };
      interface = mkOption {
        type = types.str;
        default = "127.0.0.1";
        description = "HTTP bind interface (keep loopback behind nginx).";
      };
    };

    workers = mkOption {
      type = types.int;
      default = 2;
      description = "HTTP worker processes (0 = threaded; >0 enables multiprocess + gevent).";
    };

    maxCronThreads = mkOption {
      type = types.int;
      default = 2;
    };

    logLevel = mkOption {
      type = types.str;
      default = "info";
    };

    dbName = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "Pin to a single database (sets db_name + dbfilter=^name$).";
    };

    dbFilter = mkOption {
      type = types.str;
      default = "";
      description = "Explicit dbfilter regex for multi-tenant deployments (overrides dbName's).";
    };

    listDb = mkOption {
      type = types.bool;
      default = false;
      description = "Allow the database manager / db listing.";
    };

    database = {
      createLocally = mkEnableOption "a local PostgreSQL instance (socket peer auth)";
      host = mkOption {
        type = types.str;
        default = "127.0.0.1";
      };
      port = mkOption {
        type = types.port;
        default = 5432;
      };
      user = mkOption {
        type = types.str;
        default = "odoo";
      };
      passwordFile = mkOption {
        type = types.nullOr types.path;
        default = null;
        description = "File with the DB password (merged into odoo.conf at activation). Null = socket peer auth.";
      };
    };

    adminPasswordFile = mkOption {
      type = types.nullOr types.path;
      default = null;
      description = "File with the database-manager master password (admin_passwd).";
    };

    settings = mkOption {
      type = types.attrsOf (types.either types.str (types.either types.int types.bool));
      default = { };
      description = "Extra [options] keys merged into odoo.conf (no secrets).";
    };

    update = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Modules to upgrade (-u) on (re)start. Use sparingly; requires a pinned dbName.";
    };

    autoInit = mkOption {
      type = types.bool;
      default = false;
      description = "Initialize the pinned database with `-i base` on first boot.";
    };

    nginx = {
      enable = mkEnableOption "an nginx reverse proxy for Odoo";
      domain = mkOption {
        type = types.str;
        default = "";
        description = "Server name (FQDN) for the nginx virtualHost. Not required when socketPath is set.";
      };
      socketPath = mkOption {
        type = types.str;
        default = "";
        example = "/run/odoo/nginx.sock";
        description = ''
          Serve the nginx vhost over this unix socket instead of a TCP port, for
          a co-located reverse proxy or tunnel connector that terminates TLS.
          Odoo itself stays on loopback TCP — its server layer cannot bind a
          unix socket (see the comment in this module).

          Implies the public scheme is https: `X-Forwarded-Proto` is set
          accordingly and the client IP is taken from `CF-Connecting-IP`, since a
          unix socket has no peer address.

          nginx chmods its unix listen sockets to 0666, so the socket file does
          not restrict access. Give it its own directory; this module creates
          that 0750 and owned by the service user, which is the real gate.
        '';
      };
    };

    extraEnv = mkOption {
      type = types.attrsOf types.str;
      default = { };
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.update == [ ] || cfg.dbName != null;
        message = "services.odoo-nix.update requires a pinned dbName.";
      }
      {
        assertion = !cfg.nginx.enable || cfg.nginx.domain != "" || nginxSocket;
        message = "services.odoo-nix.nginx.enable requires nginx.domain (or nginx.socketPath, which needs no server name).";
      }
      {
        # nginx chmods its listen socket to 0666, so the 0750 directory around it
        # is what keeps it private.
        assertion =
          !nginxSocket
          || (lib.hasPrefix "/" cfg.nginx.socketPath && nginxSocketDir != "/run" && nginxSocketDir != "/");
        message =
          "services.odoo-nix.nginx.socketPath must be an absolute path inside its own directory"
          + " (e.g. /run/odoo/nginx.sock), not directly in /run — the directory's 0750 mode is"
          + " what keeps the socket private.";
      }
    ];

    users.users = lib.mkMerge [
      (mkIf (cfg.user == "odoo") {
        odoo = {
          isSystemUser = true;
          group = cfg.group;
          home = cfg.stateDir;
        };
      })
      # nginx needs group membership to traverse the 0750 socket directory.
      (mkIf (cfg.nginx.enable && nginxSocket) {
        nginx.extraGroups = [ cfg.group ];
      })
    ];
    users.groups = mkIf (cfg.group == "odoo") { odoo = { }; };

    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0750 ${cfg.user} ${cfg.group} -"
      "d ${cfg.stateDir}/data 0750 ${cfg.user} ${cfg.group} -"
    ]
    # 0770, not 0750: nginx *creates* its listen socket in here and is only a
    # group member (added to cfg.group below), so it needs group write on the
    # directory, not just traversal. The directory is the access gate because
    # nginx chmods the socket itself to 0666.
    ++ lib.optional nginxSocket "d ${nginxSocketDir} 0770 ${cfg.user} ${cfg.group} -";

    systemd.services.odoo-init = {
      description = "Initialize Odoo runtime config for ${cfg.package.name}";
      wantedBy = [ "multi-user.target" ];
      before = [ "odoo.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = mkInitScript;
      };
    };

    systemd.services.odoo = {
      description = "Odoo (OCB + OCA) server";
      wantedBy = [ "multi-user.target" ];
      after = [
        "network.target"
        "odoo-init.service"
      ]
      ++ lib.optional cfg.database.createLocally "postgresql.service";
      requires = [
        "odoo-init.service"
      ]
      ++ lib.optional cfg.database.createLocally "postgresql.service";

      path = runtimePath;
      environment = serviceEnv;

      serviceConfig = {
        User = cfg.user;
        Group = cfg.group;
        WorkingDirectory = cfg.stateDir;
        ExecStartPre = lib.optional (cfg.autoInit || cfg.update != [ ]) (
          pkgs.writeShellScript "odoo-migrate" (
            ''
              set -euo pipefail
            ''
            + optionalString cfg.autoInit ''
              STAMP="${cfg.stateDir}/.odoo-nix-initialized"
              if [ ! -e "$STAMP" ]; then
                ${cfg.package}/bin/odoo -c ${runtimeConf} -d ${toString cfg.dbName} -i base --stop-after-init
                touch "$STAMP"
              fi
            ''
            + optionalString (cfg.update != [ ]) ''
              ${cfg.package}/bin/odoo -c ${runtimeConf} -d ${toString cfg.dbName} -u ${lib.concatStringsSep "," cfg.update} --stop-after-init
            ''
          )
        );
        ExecStart = "${cfg.package}/bin/odoo -c ${runtimeConf}";
        Restart = "always";
        RestartSec = "5";
      };
    };

    services.postgresql = mkIf cfg.database.createLocally {
      enable = true;
      ensureDatabases = lib.optional (dbName != null) dbName;
      ensureUsers = [
        {
          name = cfg.database.user;
          ensureDBOwnership = dbName != null;
          ensureClauses.createdb = true;
        }
      ];
    };

    services.nginx = mkIf cfg.nginx.enable {
      enable = true;
      recommendedProxySettings = true;
      recommendedGzipSettings = true;
      upstreams.odoo.servers."127.0.0.1:${toString cfg.http.port}" = { };
      upstreams.odoochat.servers."127.0.0.1:${toString cfg.http.longpollingPort}" = { };
      virtualHosts.${vhostName} = {
        listen = lib.optionals nginxSocket [ { addr = "unix:${cfg.nginx.socketPath}"; } ];

        # A unix socket has no peer address, so $remote_addr is meaningless.
        # Trust the socket peer and take the real client IP from Cloudflare's
        # header — the socket is only reachable from the connector beside it.
        extraConfig = optionalString nginxSocket ''
          set_real_ip_from unix:;
          real_ip_header CF-Connecting-IP;
        '';

        # In socket mode this module owns the complete header set (the
        # recommended include is off per location, and its $scheme is wrong here).
        # In TCP mode the previous configuration is reproduced exactly.
        locations = {
          "/" = {
            proxyPass = "http://odoo";
            recommendedProxySettings = !nginxSocket;
            extraConfig =
              if nginxSocket then
                ''
                  ${socketProxyHeaders}
                  proxy_redirect off;
                ''
              else
                ''
                  proxy_redirect off;
                  proxy_set_header X-Forwarded-Host $host;
                  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                  proxy_set_header X-Forwarded-Proto $scheme;
                  proxy_set_header X-Real-IP $remote_addr;
                '';
          };
          "/websocket" = {
            proxyPass = "http://odoochat";
            proxyWebsockets = true;
            recommendedProxySettings = !nginxSocket;
            extraConfig =
              if nginxSocket then
                socketProxyHeaders
              else
                ''
                  proxy_set_header X-Forwarded-Host $host;
                  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                  proxy_set_header X-Forwarded-Proto $scheme;
                '';
          };
          "/longpolling" = {
            proxyPass = "http://odoochat";
            proxyWebsockets = true;
            recommendedProxySettings = !nginxSocket;
            extraConfig = socketProxyHeaders;
          };
          "~* /web/static/" = {
            proxyPass = "http://odoo";
            recommendedProxySettings = !nginxSocket;
            extraConfig = ''
              ${socketProxyHeaders}
              proxy_cache_valid 200 60m;
              proxy_buffering on;
              expires 864000;
            '';
          };
        };
      };
    };
  };
}
