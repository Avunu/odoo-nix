# Standalone NixOS module: services.odoo-nix
#
# Production systemd runtime for an odoo-nix project. Single Odoo instance per
# deployment (multi-tenancy via dbfilter). A single odoo.service runs the
# assembled builtOdoo package via `odoo-bin`, forking --workers=N HTTP workers
# plus the gevent/websocket process itself (no separate longpolling unit).
#
# Config synthesis: a base odoo.conf (no secrets) is written to the Nix store
# via pkgs.formats.ini; an odoo-init oneshot, running as the service user,
# copies it to a 0600 runtime file and appends db_password / admin_passwd
# from the secret files systemd hands it (LoadCredential; ConfigParser
# last-wins), so secret *values* never enter /nix/store.
#
# Schema follows code: odoo-migrate runs `odoo db migrate` before every start
# of odoo.service and updates exactly the modules whose code or version
# changed, behind a verified snapshot, rolling back on failure -- and
# odoo.service does not start on a failed migration (see migrateScript).
#
# Logging goes to journald, not files: every unit this module defines or
# enables carries APP_SERVICE/APP_SITE journal fields (LogExtraFields), and
# Odoo's records reach the journal with their real syslog priority (the
# odoo_journald graft, lib/journald.nix) -- what a log shipper reading the
# journal (Vector -> Loki, `journalctl -p warning`) filters on.
#
# Every unit this module defines runs under python-devops-nix's systemd
# sandboxing baseline (lib.nixos.hardening; CONVENTIONS.md, Unit hardening),
# with what it legitimately needs named next to it. There is no UMask: Odoo
# writes the filestore that nginx serves through the service group
# (nginx.xSendfile, odoo-nix#51); backups and snapshots get their modes where
# they are written.
#
# python-devops-nix's library arrives as the module argument `odooNixBase`:
# flake.nixosModules.default sets it, so import that, not this file alone.
{
  config,
  lib,
  pkgs,
  odooNixBase,
  ...
}:

let
  inherit (lib)
    mkOption
    mkEnableOption
    mkIf
    types
    optionalString
    ;
  cfg = config.services.odoo-nix;

  inherit (cfg) dbName;
  socketAuth = cfg.database.createLocally && cfg.database.passwordFile == null;

  # The journal-field contract shared with frappe-nix and wordpress-nix
  # (python-devops-nix lib.journald.fields; CONVENTIONS.md, Journald
  # vocabulary): APP_SERVICE names the role, APP_SITE the site the unit
  # serves, and a unit this module defines has SyslogIdentifier=odoo-<role>.
  # With no pinned dbName (multi-database via dbFilter) no one site is
  # served, so APP_SITE is left out rather than guessed. LogExtraFields
  # applies to everything journald attributes to the unit's cgroup --
  # stdout/stderr and syslog alike -- so nginx's access log (syslog, below)
  # carries them too. The upstream units (db, nginx) keep their identifiers.
  journalFields =
    role:
    odooNixBase.journald.fields {
      prefix = "odoo";
      inherit role;
      site = dbName;
    };

  # What the units that run Odoo may write, under ProtectSystem=strict: the
  # state directory (the runtime odoo.conf, data_dir: filestore, sessions,
  # backups), data_dir if `settings` moved it, and logging.file's directory.
  # A host adds its own with systemd.services.<unit>.serviceConfig.ReadWritePaths.
  odooWritePaths = [
    cfg.stateDir
  ]
  ++ lib.optional (cfg.settings ? data_dir) (toString cfg.settings.data_dir)
  ++ lib.optional (cfg.logging.file != null) (builtins.dirOf cfg.logging.file);

  # The sandbox for odoo.service and odoo-migrate, which run the same Odoo
  # code. Odoo shells out to wkhtmltopdf for PDF reports (QtWebKit's JIT) and
  # to rtlcss, a Node program (V8's JIT), when it compiles a right-to-left
  # asset bundle, so both need W+X memory. odoo-migrate gets the same: a
  # module's install or migration hook may render a report, and a refused
  # JIT there would fail the deploy and keep Odoo down.
  odooHardening = odooNixBase.nixos.hardening {
    readWritePaths = odooWritePaths;
    profiles = [
      "wkhtmltopdf"
      "jit"
    ];
  };

  # nginx serves the public side over a unix socket; Odoo itself stays on
  # loopback TCP. Verified against the Odoo 18.0 source this module builds:
  # ThreadedWSGIServerReloadable.__init__ hands (host, port) straight to
  # werkzeug.serving.ThreadedWSGIServer, bypassing run_simple/make_server where
  # werkzeug's own `unix://` support lives; PreforkServer builds AF_INET and
  # binds a 2-tuple; and server_bind's socket-activation branch hardcodes
  # AF_INET in socket.fromfd. (19.x adds http_socket_activation but still passes
  # AF_INET explicitly, which CPython does not verify against the real fd.)
  nginxSocket = cfg.nginx.socketPath != "";

  # nginx's listen socket in its own directory (lib.nixos.unixSocket): 0770,
  # since nginx -- a member of cfg.group, not the owner -- creates the socket
  # in it, and nginx chmods the socket itself to 0666, so the directory is
  # the gate.
  sockets = odooNixBase.nixos.unixSocket {
    inherit (cfg) user group;
    sockets = [
      {
        option = "services.odoo-nix.nginx.socketPath";
        path = cfg.nginx.socketPath;
        peerCreates = true;
        example = "/run/odoo/nginx.sock";
      }
    ];
  };

  # The vhost only needs a name to key it; with a single server block on the
  # socket it is the default server, so server_name never has to match.
  vhostName = if cfg.nginx.domain != "" then cfg.nginx.domain else "odoo";

  # recommendedProxySettings hardcodes `X-Forwarded-Proto $scheme`, and NixOS
  # emits its include AFTER a location's extraConfig, so the wrong scheme cannot
  # be overridden from there — Odoo's proxy_mode would then build http URLs and
  # drop the Secure flag on session cookies. Opt each location out and set the
  # whole header block explicitly (lib.nixos.nginx.socketProxyHeaders).
  socketProxyHeaders = optionalString nginxSocket odooNixBase.nixos.nginx.socketProxyHeaders;

  xSendfile = cfg.nginx.enable && cfg.nginx.xSendfile;

  # Base [options] (no secrets). addons_path is the assembled package's absolute
  # path; data_dir + the conf live under the stateful directory.
  baseOptions = {
    addons_path = cfg.package.passthru.addonsPath "${cfg.package}";
    data_dir = "${cfg.stateDir}/data";
    db_user = cfg.database.user;
    http_interface = cfg.http.interface;
    http_port = toString cfg.http.port;
    gevent_port = toString cfg.http.longpollingPort;
    workers = toString cfg.workers;
    max_cron_threads = toString cfg.maxCronThreads;
    proxy_mode = if cfg.nginx.enable then "True" else "False";
    list_db = if cfg.listDb then "True" else "False";
    log_level = cfg.logging.level;
    log_db_level = cfg.logging.dbLevel;
  }
  // lib.optionalAttrs xSendfile { x_sendfile = "True"; }
  # Socket auth means no db_host/db_port at all: absent keys fall back to
  # Odoo's defaults (the unix socket) on every series, where the old literal
  # "False" was coerced to a falsy bool by 18.0 and is skipped with a warning
  # by 19.0.
  // lib.optionalAttrs (!socketAuth) {
    db_host = cfg.database.host;
    db_port = toString cfg.database.port;
  }
  # log_db is a database *name*; "%d" is Odoo's spelling for "the current
  # request's database", so that is what `true` renders as. Absent when off.
  // lib.optionalAttrs (cfg.logging.db != false) {
    log_db = if cfg.logging.db == true then "%d" else cfg.logging.db;
  }
  // lib.optionalAttrs (dbName != null) {
    db_name = dbName;
    dbfilter = "^${dbName}$";
  }
  // lib.optionalAttrs (cfg.dbFilter != "") {
    dbfilter = cfg.dbFilter;
  }
  # "True", not "all": 18.0 only tests the option's truthiness, 19.0 made
  # it a boolean that warns about anything else.
  // lib.optionalAttrs cfg.withoutDemo {
    without_demo = "True";
  }
  // lib.optionalAttrs (cfg.logging.handlers != [ ]) {
    log_handler = lib.concatStringsSep "," cfg.logging.handlers;
  }
  // lib.optionalAttrs (cfg.logging.file != null) {
    logfile = cfg.logging.file;
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
  // odooNixBase.python.threadCaps
  // cfg.extraEnv;

  # The `odoo` an operator runs from a root shell (`odoo db backup`, `odoo db
  # migrate`, `odoo shell`). Run straight from the package it would have
  # neither the service's tools (pg_dump, psql, wkhtmltopdf are not on a root
  # shell's PATH) nor its secrets, and would write the filestore and backups
  # as root. So, as root, it runs as a transient unit with the service's
  # user, working directory, PATH, environment and EnvironmentFile= --
  # systemd parses those files, exactly as for odoo.service. Anyone else
  # (the service user itself, say) gets the PATH and environment in place.
  adminCli = pkgs.writeShellScriptBin "odoo" ''
    set -euo pipefail
    if [ "$(id -u)" = 0 ] && [ ${lib.escapeShellArg cfg.user} != root ]; then
      if [ -t 0 ] && [ -t 1 ]; then io=--pty; else io=--pipe; fi
      exec ${config.systemd.package}/bin/systemd-run --quiet --wait --collect "$io" \
        --uid=${lib.escapeShellArg cfg.user} --gid=${lib.escapeShellArg cfg.group} \
        --working-directory=${lib.escapeShellArg cfg.stateDir} \
        --setenv=PATH=${lib.makeBinPath runtimePath} \
        ${
          lib.concatStringsSep " " (
            lib.mapAttrsToList (k: v: "--setenv=${lib.escapeShellArg "${k}=${v}"}") serviceEnv
            ++ map (f: "--property=${lib.escapeShellArg "EnvironmentFile=${f}"}") cfg.environmentFiles
          )
        } \
        -- ${cfg.package}/bin/odoo "$@"
    fi
    export PATH=${lib.makeBinPath runtimePath}:$PATH
    ${lib.concatStringsSep "
" (
      lib.mapAttrsToList (k: v: "export ${k}=${lib.escapeShellArg v}") serviceEnv
    )}
    exec ${cfg.package}/bin/odoo "$@"
  '';

  # The secret files, as systemd credentials: systemd reads them (as root,
  # wherever the host keeps them) and hands odoo-init private copies under
  # $CREDENTIALS_DIRECTORY, so init runs as the service user with no
  # capabilities (python-devops-nix CONVENTIONS.md, Production secrets).
  credentials =
    lib.optional (cfg.database.passwordFile != null) {
      name = "db_password";
      file = cfg.database.passwordFile;
    }
    ++ lib.optional (cfg.adminPasswordFile != null) {
      name = "admin_passwd";
      file = cfg.adminPasswordFile;
    };

  # As the service user, into the state directory it owns (tmpfiles creates
  # it, and data/, before any unit starts). The runtime conf is written to a
  # private temporary file and renamed into place, so Odoo never reads a
  # half-written one. umask is the script's own, not the unit's: nothing else
  # is created here.
  mkInitScript = pkgs.writeShellScript "odoo-nix-init" ''
    set -euo pipefail
    umask 077
    tmp=${runtimeConf}.tmp
    cat ${baseConf} > "$tmp"
    ${lib.concatMapStrings (c: ''
      printf '${c.name} = %s\n' "$(cat "$CREDENTIALS_DIRECTORY/${c.name}")" >> "$tmp"
    '') credentials}
    chmod 0600 "$tmp"
    mv -f "$tmp" ${runtimeConf}
  '';

  mg = cfg.migrate;

  # Nothing else brings the schema along with the code: Odoo creates columns,
  # loads views and runs migration scripts only for modules being installed or
  # updated, so a deploy that ships new module code -- or a database restored
  # from somewhere else -- leaves the schema behind the code without a word.
  # (queue_job then refused to run anything: "database schema is outdated, -u
  # queue_job required", while every job sat in `pending`.)
  #
  # `odoo db migrate` decides what to update (content checksums stored in the
  # database, plus manifest-version drift), snapshots first, and rolls back on
  # failure. `--if-needed` makes the common case -- a restart of a build that
  # already migrated this database -- one query. The marker is in the
  # database, so restoring a dump from elsewhere is itself what triggers the
  # next migration.
  migrateArgs = lib.escapeShellArgs (
    [
      "-c"
      runtimeConf
      "db"
      "migrate"
    ]
    ++ (if dbName != null then [ dbName ] else [ "--all" ])
    ++ [ "--if-needed" ]
    ++ lib.optional mg.full "--full"
    ++ lib.optionals (cfg.update != [ ]) [
      "--also"
      (lib.concatStringsSep "," cfg.update)
    ]
    ++ (
      if mg.snapshot then
        [
          "--snapshot"
          "dump"
          "--keep"
          (toString mg.snapshotRetention)
        ]
        ++ lib.optional mg.rollbackOnFailure "--rollback"
      else
        [
          "--snapshot"
          "none"
        ]
    )
    ++ lib.optional cfg.autoInit "--provision-if-empty"
  );
in
{
  # logging.slowQueryMs -> database.slowQueryMs (python-devops-nix
  # CONVENTIONS.md, Database logging; frappe-nix's name). The old path warns,
  # through 1.x; removed in 2.0.0.
  imports = [
    (lib.mkRenamedOptionModule
      [ "services" "odoo-nix" "logging" "slowQueryMs" ]
      [ "services" "odoo-nix" "database" "slowQueryMs" ]
    )
  ];

  options.services.odoo-nix = {
    enable = mkEnableOption "Odoo (OCB + OCA) production service";

    package = mkOption {
      type = types.package;
      description = "The assembled Odoo package (builtOdoo) from the project flake.";
      example = lib.literalExpression "projectFlake.packages.x86_64-linux.default";
    };

    adminCli = mkOption {
      type = types.bool;
      default = true;
      description = ''
        Install an `odoo` command for operators. From a root shell it runs as
        the service user with the service's PATH, environment and
        `environmentFiles`, so `odoo db backup|restore|migrate` behave as
        they do under odoo.service.
      '';
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

    logging = {
      level = mkOption {
        type = types.enum [
          "info"
          "debug_rpc"
          "warn"
          "test"
          "critical"
          "runbot"
          "debug_sql"
          "error"
          "debug"
          "debug_rpc_answer"
          "notset"
        ];
        default = "info";
        description = "Root/default logging verbosity (log_level).";
      };
      handlers = mkOption {
        type = types.listOf (types.strMatching "^[A-Za-z0-9_.]*:[A-Z]+$");
        default = [ ];
        example = [
          "odoo.addons.my_module:DEBUG"
          "werkzeug:WARNING"
        ];
        description = ''
          Per-logger level overrides (log_handler), as "logger:LEVEL" pairs.
          An empty prefix targets the root logger. The root logger already
          defaults to INFO regardless of this list, so entries here only
          need to cover the loggers you want to override.
        '';
      };
      db = mkOption {
        type = types.either types.bool types.str;
        default = false;
        description = ''
          Mirror log records into the database (log_db). `true` (or "%d")
          logs to whichever database is active for each request; a string
          pins logging to that database name.
        '';
      };
      dbLevel = mkOption {
        type = types.enum [
          "debug"
          "info"
          "warning"
          "error"
          "critical"
        ];
        default = "warning";
        description = "Minimum level mirrored to the database (log_db_level).";
      };
      journald = mkOption {
        type = types.nullOr types.bool;
        default = null;
        description = ''
          Deprecated, and without effect: Odoo logs to the journal natively
          whenever stderr is the journal stream, as `<N>logger [db] message`
          (the odoo_journald graft in the project's Python environment;
          python-devops-nix CONVENTIONS.md, Journald enablement). Accepted,
          with a warning, through 1.x. `false` still silences the warning
          about `logging.file`.
        '';
      };
      file = mkOption {
        type = types.nullOr types.path;
        default = null;
        description = ''
          Write logs to this file (logfile) instead of stderr/journald.
          Leave it null under systemd: the journal already timestamps,
          rotates and ships the log, with priorities.
          Odoo's file and stderr log handlers are mutually exclusive, so
          setting this stops Odoo's own log records from reaching
          `journalctl -u odoo` (uncaught tracebacks printed before logging
          initializes still do). The containing directory is created
          automatically, owned by `user`:`group`.
        '';
      };
      rotate = mkOption {
        type = types.bool;
        default = false;
        description = ''
          Rotate `logging.file` via `services.logrotate`. Odoo has no
          internal log rotation (removed upstream); its `WatchedFileHandler`
          instead detects when logrotate has renamed/recreated the file and
          reopens it automatically, so no reload/signal is needed. Requires
          `logging.file` to be set.
        '';
      };
      accessLog = mkOption {
        type = types.bool;
        default = true;
        description = ''
          Send nginx's request log to the journal as one JSON object per
          request (SYSLOG_IDENTIFIER=nginx_access): time, site (Host), method,
          uri, status, bytes, request_time, upstream_time, remote_addr,
          user_agent, referer. `false` turns the access log off. Only with
          `nginx.enable`.
        '';
      };
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

    withoutDemo = mkOption {
      type = types.bool;
      default = false;
      description = "Skip loading demo data for every installed module (`without_demo = True`).";
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
      extensions = mkOption {
        type = types.functionTo (types.listOf types.package);
        default = _: [ ];
        example = lib.literalExpression "ps: [ ps.postgis ]";
        description = ''
          PostgreSQL extensions to build into the local server
          (`services.postgresql.extensions`). Only meaningful with
          `createLocally`; a remote server ships whatever it was built with.
        '';
      };
      slowQueryMs = mkOption {
        type = types.nullOr types.ints.unsigned;
        default = null;
        example = 500;
        description = ''
          Log every statement that runs at least this many milliseconds
          (PostgreSQL's `log_min_duration_statement`); `0` logs all of them.
          Only with `database.createLocally`.
        '';
      };
      ensureExtensions = mkOption {
        type = types.listOf types.str;
        default = [ ];
        example = [
          "postgis"
          "postgis_topology"
        ];
        description = ''
          Extensions to `CREATE EXTENSION IF NOT EXISTS` in `dbName` after the
          local server comes up. Unlike the dev shell, the Odoo role here is
          not a superuser, so a module that expects to create an untrusted
          extension itself (OCA's `base_geoengine`, whose `pre_init_hook`
          creates `postgis` and `postgis_topology`) needs them created here,
          as the `postgres` superuser, first. Requires `createLocally` and a
          pinned `dbName`.
        '';
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
      description = ''
        Modules to update on every deploy even when their code is unchanged
        (passed to the migration as `--also`). Rarely needed: migrate.* already
        updates every module whose code or version changed. Requires a pinned
        dbName.
      '';
    };

    autoInit = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Install `base` into the pinned database when it has no Odoo schema yet
        (first boot). Without it, an uninitialised database is left alone and
        odoo.service starts anyway, so a database can be restored into it.
      '';
    };

    # python-devops-nix's shared migrate.{enable,snapshot,rollbackOnFailure,
    # snapshotRetention} (CONVENTIONS.md, Migrate on deploy), plus odoo-nix's
    # own full and timeout. odoo-migrate.service runs before every start of
    # odoo.service and updates the modules whose code changed (content
    # checksums recorded in the database, the same ones OCA
    # module_auto_update uses) or whose manifest version is ahead of the
    # database; the first run on a database with no recorded checksums updates
    # everything once. The snapshot is the database alone: attachments are
    # content-addressed and only ever added, so a migration never needs the
    # filestore rolled back. Requires the CLI package (the project flake's
    # `packages.default`).
    migrate =
      odooNixBase.nixos.migrate.options {
        what = "`odoo db migrate` (odoo-migrate.service, before every start of odoo.service, which does not start if it fails)";
        dumpTool = "pg_dump, custom format";
        where = "per database, under `<data_dir>/backups/<db>/premigrate/`";
      }
      // {
        full = mkOption {
          type = types.bool;
          default = false;
          description = "Update every installed module (`-u all`) on each new build instead of only the changed ones.";
        };
        timeout = mkOption {
          type = types.str;
          default = "infinity";
          example = "30min";
          description = ''
            TimeoutStartSec for odoo-migrate.service. A first migration of a large
            database updates every module and can take many minutes; killing it
            part-way leaves a half-updated schema for the rollback to undo.
          '';
        };
      };

    nginx = {
      enable = mkEnableOption "an nginx reverse proxy for Odoo";
      domain = mkOption {
        type = types.str;
        default = "";
        description = "Server name (FQDN) for the nginx virtualHost. Not required when socketPath is set.";
      };
      clientMaxBodySize = mkOption {
        type = types.str;
        default = "64m";
        description = ''
          `client_max_body_size` for the Odoo vhost. NixOS's nginx default is
          10m, which is below what Odoo itself accepts (128 MiB) and below the
          25 MiB a Cloudflare Email Routing message can weigh when a Worker
          pushes it to the `mail_cloudflare` inbound webhook. Scoped to this
          vhost so other sites on the same host keep their own limit.
        '';
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
          that 0770 and owned by the service user and group (nginx, in the
          group, creates the socket there), which is the real gate.
        '';
      };
      xSendfile = mkOption {
        type = types.bool;
        default = false;
        description = ''
          Let nginx send filestore attachments instead of an Odoo worker.
          Sets Odoo's `x_sendfile`: a download (`/web/content`, `/web/image`)
          is still authorized by Odoo, which answers with an empty body and
          `X-Accel-Redirect: /web/filestore/<db>/<path>`; nginx serves that
          file from `<stateDir>/data/filestore` through an `internal`
          location, keeping Odoo's own headers (Content-Type,
          Content-Disposition, Content-Security-Policy, caching). A request
          for `/web/filestore/` from outside is a 404.

          nginx joins the service's group to read the filestore, which Odoo
          creates group-readable; sessions and the runtime odoo.conf stay
          private to the service user.

          Off by default: with it on, anything that talks to Odoo's port
          directly rather than through this nginx gets those empty bodies.
        '';
      };
    };

    extraEnv = mkOption {
      type = types.attrsOf types.str;
      default = { };
    };

    environmentFiles = mkOption {
      type = types.listOf types.path;
      default = [ ];
      example = lib.literalExpression "[ config.age.secrets.odoo-backup.path ]";
      description = ''
        Files of `KEY=value` lines handed to the `odoo` and `odoo-migrate`
        units as systemd `EnvironmentFile=`s, so secrets never enter the Nix
        store. This is how an `fs.storage` configured with
        `eval_options_from_env` (e.g. the `auto_backup_fs_storage` module's
        `odoo_backup` storage) gets its `BACKUPS_URL`, `BACKUPS_ACCESS_KEY`,
        `BACKUPS_SECRET_KEY`, `BACKUPS_BUCKET` and `BACKUPS_PREFIX`.

        With agenix, point it at the same ciphertext the developers decrypt for
        `odoo db restore`, exported by the project flake:

            age.secrets.odoo-backup.file =
              inputs.myproject.lib.secrets.files.odoo_backup_access;
            services.odoo-nix.environmentFiles = [ config.age.secrets.odoo-backup.path ];

        (The host's key must be in the project's `odoo-nix.secrets.hostRecipients`.)
      '';
    };
  };

  config = mkIf cfg.enable {
    environment.systemPackages = lib.optional cfg.adminCli adminCli;

    # Warnings, not assertions: a configuration that sets these must keep
    # evaluating.
    warnings =
      lib.optional (cfg.logging.journald != false && cfg.logging.file != null) ''
        services.odoo-nix.logging.file is set, so Odoo logs to ${cfg.logging.file}:
        `journalctl -u odoo` sees only output from before Odoo's logging starts,
        and without per-record priorities. Leave logging.file null to log to the
        journal, or set logging.journald = false to keep the file and silence
        this warning.
      ''
      ++
        lib.optional
          (cfg.logging.journald == true || (cfg.logging.journald == false && cfg.logging.file == null))
          ''
            services.odoo-nix.logging.journald has no effect: Odoo logs to the journal
            natively whenever stderr is the journal stream (python-devops-nix
            CONVENTIONS.md, Journald enablement)${
              lib.optionalString (cfg.logging.journald == false) ", and `false` no longer turns that off"
            }. Remove it; it is accepted through odoo-nix 1.x.
          '';

    assertions = [
      {
        assertion = cfg.update == [ ] || cfg.dbName != null;
        message = "services.odoo-nix.update requires a pinned dbName.";
      }
      {
        assertion = !cfg.autoInit || cfg.dbName != null;
        message = "services.odoo-nix.autoInit requires a pinned dbName.";
      }
      {
        # The raw builtOdoo tree has only odoo-bin, not `odoo db migrate`.
        assertion = !mg.enable || cfg.package.passthru ? builtOdoo;
        message =
          "services.odoo-nix.migrate needs the odoo CLI package -- set package to the project flake's"
          + " `packages.default` (lib/cli.nix), not the raw builtOdoo tree, or set migrate.enable = false.";
      }
      {
        assertion = !cfg.nginx.enable || cfg.nginx.domain != "" || nginxSocket;
        message = "services.odoo-nix.nginx.enable requires nginx.domain (or nginx.socketPath, which needs no server name).";
      }
      {
        assertion = !cfg.logging.rotate || cfg.logging.file != null;
        message = "services.odoo-nix.logging.rotate requires logging.file to be set.";
      }
      {
        assertion = cfg.database.ensureExtensions == [ ] || (cfg.database.createLocally && dbName != null);
        message = "services.odoo-nix.database.ensureExtensions requires database.createLocally and a pinned dbName.";
      }
    ]
    # nginx chmods its listen socket to 0666, so the directory around it is
    # what keeps it private.
    ++ sockets.assertions;

    users.users = lib.mkMerge [
      (mkIf (cfg.user == "odoo") {
        odoo = {
          isSystemUser = true;
          inherit (cfg) group;
          home = cfg.stateDir;
        };
      })
      # nginx needs group membership to traverse the 0750 socket directory,
      # and the 0750 state directory down to the filestore for x_sendfile.
      (mkIf (cfg.nginx.enable && (nginxSocket || xSendfile)) {
        nginx.extraGroups = [ cfg.group ];
      })
    ];
    users.groups = mkIf (cfg.group == "odoo") { odoo = { }; };

    systemd.tmpfiles.rules = [
      "d ${cfg.stateDir} 0750 ${cfg.user} ${cfg.group} -"
      "d ${cfg.stateDir}/data 0750 ${cfg.user} ${cfg.group} -"
      # Backups and pre-migrate snapshots (`odoo db backup|migrate`, and OCA
      # auto_backup's default folder) are whole databases. nginx joins
      # cfg.group for the socket and the filestore, so this directory, unlike
      # data/, is owner-only. `d` also tightens one that already exists.
      "d ${cfg.stateDir}/data/backups 0700 ${cfg.user} ${cfg.group} -"
    ]
    # 0770, not 0750: nginx *creates* its listen socket in here and is only a
    # group member (added to cfg.group below), so it needs group write on the
    # directory, not just traversal. The directory is the access gate because
    # nginx chmods the socket itself to 0666.
    ++ sockets.tmpfiles
    # Odoo's own os.makedirs() fallback for logfile's parent dir silently
    # reverts to stderr logging on PermissionError under a non-root user, so
    # pre-create it with the right owner.
    ++ lib.optional (
      cfg.logging.file != null
    ) "d ${builtins.dirOf cfg.logging.file} 0750 ${cfg.user} ${cfg.group} -";

    systemd.services.odoo-init = {
      description = "Initialize Odoo runtime config for ${cfg.package.name}";
      wantedBy = [ "multi-user.target" ];
      before = [ "odoo.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        User = cfg.user;
        Group = cfg.group;
        ExecStart = mkInitScript;
        LoadCredential = map (c: "${c.name}:${c.file}") credentials;
      }
      # It writes the runtime conf into the state directory and opens no
      # socket of its own.
      // odooNixBase.nixos.hardening {
        readWritePaths = [ cfg.stateDir ];
        addressFamilies = [ "AF_UNIX" ];
      }
      // journalFields "init";
    };

    # A oneshot WITHOUT RemainAfterExit: it goes back to inactive when it
    # finishes, so odoo.service's Requires= starts it again on every start of
    # odoo.service -- a deploy (switch-to-configuration stops odoo.service
    # when its unit changes and starts it again), a reboot, `nomad job
    # restart`, a restart after restoring a dump. With odoo.service stopped
    # while it runs, no worker, cron or queue_job runner touches the database
    # mid-update. A no-op start costs one query (--if-needed).
    systemd.services.odoo-migrate = mkIf mg.enable {
      description = "Migrate the Odoo database to ${cfg.package.name}";
      after = [
        "network.target"
        "odoo-init.service"
      ]
      ++ lib.optional cfg.database.createLocally "postgresql.target";
      requires = [
        "odoo-init.service"
      ]
      ++ lib.optional cfg.database.createLocally "postgresql.target";
      path = runtimePath;
      environment = serviceEnv;
      serviceConfig = {
        Type = "oneshot";
        User = cfg.user;
        Group = cfg.group;
        WorkingDirectory = cfg.stateDir;
        TimeoutStartSec = mg.timeout;
        EnvironmentFile = cfg.environmentFiles;
        ExecStart = "${cfg.package}/bin/odoo ${migrateArgs}";
      }
      // odooHardening
      // journalFields "migrate";
    };

    systemd.services.odoo = {
      description = "Odoo (OCB + OCA) server";
      wantedBy = [ "multi-user.target" ];
      after = [
        "network.target"
        "odoo-init.service"
      ]
      # postgresql.target, not .service: ensureUsers/ensureDatabases run in
      # postgresql-setup.service, which only the target orders after (nixpkgs
      # postgresql.md: "run this service after postgresql.target"). The
      # migration (or autoInit's `-i base`) would otherwise race the role
      # creation.
      ++ lib.optional cfg.database.createLocally "postgresql.target"
      ++ lib.optional mg.enable "odoo-migrate.service";
      # Requires, not only After: new code must never serve a schema it was
      # not migrated to. A failed migration has been rolled back to the old
      # schema, and the new code on top of it fails in ways nothing reports
      # (a paused job runner, a missing column on one screen) -- so Odoo stays
      # down instead, and the failure is the unit's.
      requires = [
        "odoo-init.service"
      ]
      ++ lib.optional cfg.database.createLocally "postgresql.target"
      ++ lib.optional mg.enable "odoo-migrate.service";

      path = runtimePath;
      environment = serviceEnv;

      serviceConfig = {
        User = cfg.user;
        Group = cfg.group;
        WorkingDirectory = cfg.stateDir;
        EnvironmentFile = cfg.environmentFiles;
        # Only with migrate disabled: odoo-migrate handles both autoInit
        # (--provision-if-empty) and update (--also) otherwise. The legacy
        # path runs `-i base` once (stamp file) and `odoo db upgrade` on every
        # start, with no change detection and no snapshot.
        ExecStartPre = lib.optional (!mg.enable && (cfg.autoInit || cfg.update != [ ])) (
          pkgs.writeShellScript "odoo-service-start-pre" (
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
              ${cfg.package}/bin/odoo -c ${runtimeConf} db upgrade ${lib.concatStringsSep "," cfg.update} ${toString cfg.dbName}
            ''
          )
        );
        ExecStart = "${cfg.package}/bin/odoo -c ${runtimeConf}";
        Restart = "always";
        RestartSec = "5";
      }
      // odooHardening
      # SyslogIdentifier=odoo-web: otherwise each Exec line's own executable
      # name (ExecStartPre's is a generated script's), which follows the
      # package, not the role -- stable names are what a query can key on.
      // journalFields "web";
    };

    # Odoo has no internal log rotation; its WatchedFileHandler detects when
    # an external tool renames/recreates the log file (by inode) and reopens
    # it, so no reload/signal is needed here — logrotate's default "rename +
    # recreate" behavior is exactly the cooperation contract it expects.
    services.logrotate = mkIf cfg.logging.rotate {
      enable = true;
      settings.${cfg.logging.file} = {
        frequency = "daily";
        rotate = 14;
        compress = true;
        missingok = true;
        notifempty = true;
        create = "0640 ${cfg.user} ${cfg.group}";
      };
    };

    services.postgresql = mkIf cfg.database.createLocally {
      enable = true;
      extensions = cfg.database.extensions;
      ensureDatabases = lib.optional (dbName != null) dbName;
      ensureUsers = [
        {
          name = cfg.database.user;
          # nixpkgs' ensureDBOwnership asserts that the database is named
          # after the role. A project whose dbName differs ("myshop" owned by
          # "odoo") gets the ownership transferred below instead.
          ensureDBOwnership = dbName != null && dbName == cfg.database.user;
          ensureClauses.createdb = true;
        }
      ];
      # journald already stamps time and PID (nixpkgs' default prefix is
      # "[%p] "); what it cannot know is which database and role a line is
      # about. mkDefault: a host that wants its own prefix just sets it.
      settings = {
        log_line_prefix = lib.mkDefault "%d %u ";
      }
      // lib.optionalAttrs (cfg.database.slowQueryMs != null) {
        log_min_duration_statement = cfg.database.slowQueryMs;
      };
    };

    # The upstream units this module turns on serve this instance alone, so
    # they carry its journal fields too (see journalFields), and keep their
    # own SyslogIdentifiers.
    systemd.services.postgresql.serviceConfig.LogExtraFields =
      mkIf cfg.database.createLocally (journalFields "db").LogExtraFields;
    systemd.services.postgresql-setup.serviceConfig.LogExtraFields =
      mkIf cfg.database.createLocally (journalFields "db").LogExtraFields;
    systemd.services.nginx.serviceConfig.LogExtraFields = mkIf cfg.nginx.enable (journalFields "nginx")
    .LogExtraFields;

    # postgresql-setup runs as the postgres superuser and already owns
    # ensureDatabases; append so the database exists before the extensions go
    # into it. `IF NOT EXISTS` keeps it idempotent across restarts, and the
    # Odoo role owning the database is what lets it use them afterwards.
    systemd.services.postgresql-setup.script = mkIf (cfg.database.createLocally && dbName != null) (
      lib.mkAfter (
        lib.optionalString (dbName != cfg.database.user) ''
          psql -tAc 'ALTER DATABASE "${dbName}" OWNER TO "${cfg.database.user}"'
        ''
        + lib.concatMapStrings (ext: ''
          psql -d '${dbName}' -tAc 'CREATE EXTENSION IF NOT EXISTS "${ext}"'
        '') cfg.database.ensureExtensions
      )
    );

    services.nginx = mkIf cfg.nginx.enable {
      enable = true;
      recommendedProxySettings = true;
      recommendedGzipSettings = true;
      # The error log over syslog, so each line keeps its severity (on
      # stderr every line is info). nginx-wide, as logError is; mkDefault, so
      # the host may send it elsewhere.
      logError = lib.mkDefault odooNixBase.nixos.nginx.errorLog;
      # The access log as one JSON object per request, to the journal under
      # SYSLOG_IDENTIFIER=nginx_access (lib.nixos.nginx.accessLog). http-level,
      # so every server block inherits it.
      commonHttpConfig = odooNixBase.nixos.nginx.accessLog cfg.logging.accessLog;
      upstreams.odoo.servers."127.0.0.1:${toString cfg.http.port}" = { };
      upstreams.odoochat.servers."127.0.0.1:${toString cfg.http.longpollingPort}" = { };
      virtualHosts.${vhostName} = {
        listen = lib.optionals nginxSocket [ { addr = "unix:${cfg.nginx.socketPath}"; } ];

        # A unix socket has no peer address, so $remote_addr is meaningless.
        # Trust the socket peer and take the real client IP from Cloudflare's
        # header — the socket is only reachable from the connector beside it.
        extraConfig = ''
          client_max_body_size ${cfg.nginx.clientMaxBodySize};
        ''
        + optionalString nginxSocket odooNixBase.nixos.nginx.cloudflareRealIp;

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
          # Where Odoo's X-Accel-Redirect points (nginx.xSendfile). internal:
          # reachable only through that header, never by a client's request.
          "/web/filestore/" = mkIf xSendfile {
            alias = "${cfg.stateDir}/data/filestore/";
            extraConfig = ''
              internal;
            '';
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
