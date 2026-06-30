# devenv shell module for Odoo (OCB) + OCA projects.
# Defines the perSystem.odoo-nix option namespace and wires the dev shell:
# PostgreSQL + a single odoo-bin process + mailpit, a Nix-synthesized odoo.conf
# symlinked into place, and the OCA management scripts.
{
  lib,
  flake-parts-lib,
  inputs,
  ...
}:
let
  inherit (lib) mkOption mkEnableOption types;
  inherit (flake-parts-lib) mkPerSystemOption;
in
{
  options.perSystem = mkPerSystemOption (
    { config, pkgs, ... }:
    {
      options.odoo-nix = {
        enable = mkEnableOption "Odoo + OCA devenv shell";

        projectName = mkOption {
          type = types.str;
          description = "Project identifier used for env/package/container names.";
          example = "avunu-accounting";
        };

        workspaceRoot = mkOption {
          type = types.path;
          description = "Workspace root (where pyproject.toml, odoo.conf and src/ live).";
        };

        odooSeries = mkOption {
          type = types.str;
          default = "18.0";
          description = "Odoo major series — the OCB/OCA git branch and the OCA catalog filter.";
        };

        python = mkOption {
          type = types.package;
          default = pkgs.python311;
          description = "Python interpreter (should match the series; 3.11 for 18.0).";
        };

        nodejs = mkOption {
          type = types.package;
          default = pkgs.nodejs_22;
          description = "Node.js package (for rtlcss / asset tooling).";
        };

        pythonOverrides = mkOption {
          type = types.functionTo (types.functionTo types.attrs);
          default = _final: _prev: { };
          description = "uv2nix Python package-set overlay for native-build overrides.";
        };

        pythonLibraries = mkOption {
          type = types.attrsOf (types.listOf types.package);
          default = { };
          description = ''
            Native libraries to expose to a Python package's build, keyed by
            package name. Each library's headers (its `.dev` output) and
            pkg-config are added to the build — the declarative way to satisfy a
            C-extension dependency (e.g. pycups) without writing a Nix override.
            Merged with odoo-nix's built-in set (which already covers pycups).
          '';
          example = lib.literalExpression ''{ python-snappy = [ pkgs.snappy ]; }'';
        };

        odooConf = {
          dbHost = mkOption {
            type = types.str;
            default = "127.0.0.1";
            description = "PostgreSQL host (empty string = unix socket).";
          };
          dbPort = mkOption {
            type = types.port;
            default = 5432;
          };
          dbUser = mkOption {
            type = types.str;
            default = "odoo";
          };
          dbPassword = mkOption {
            type = types.str;
            default = "False";
            description = "DB password as an INI literal (\"False\" = none, for dev).";
          };
          dbName = mkOption {
            type = types.nullOr types.str;
            default = "odoo_dev";
            description = "Default database name (null to omit db_name from odoo.conf).";
          };
          dataDir = mkOption {
            type = types.str;
            default = "./.devenv/state/odoo";
            description = "Odoo filestore data_dir (relative to the workspace root; gitignored under .devenv).";
          };
          adminPasswd = mkOption {
            type = types.str;
            default = "admin";
            description = "Database manager master password (dev only).";
          };
          logLevel = mkOption {
            type = types.str;
            default = "info";
          };
          httpPort = mkOption {
            type = types.port;
            default = 8069;
          };
          geventPort = mkOption {
            type = types.port;
            default = 8072;
          };
          workers = mkOption {
            type = types.int;
            default = 0;
            description = "Worker processes (0 = threaded dev mode).";
          };
          devMode = mkOption {
            type = types.str;
            default = "all";
            description = "Value for the dev process's --dev flag (CLI only, not in odoo.conf).";
          };
          extra = mkOption {
            type = types.attrsOf (types.either types.str (types.either types.int types.bool));
            default = { };
            description = "Arbitrary extra [options] keys merged last into odoo.conf.";
          };
        };

        layout = {
          coreSrc = mkOption {
            type = types.str;
            default = "odoo";
            description = "Path (relative to root) of the OCB source submodule.";
          };
          externalDir = mkOption {
            type = types.str;
            default = "modules";
            description = "Directory holding OCA module-repo submodules.";
          };
          customDir = mkOption {
            type = types.str;
            default = "custom";
            description = "Directory holding the project's own addons.";
          };
          extraAddons = mkOption {
            type = types.listOf types.str;
            default = [ ];
            description = "Extra addons_path entries appended verbatim (relative paths).";
          };
        };

        extraDevPackages = mkOption {
          type = types.listOf types.package;
          default = [ ];
          description = "Additional packages for the dev shell.";
        };

        extraLibraryPaths = mkOption {
          type = types.listOf types.package;
          default = [ ];
          description = "Additional packages added to LD_LIBRARY_PATH.";
        };

        extraScripts = mkOption {
          type = types.attrsOf types.anything;
          default = { };
          description = "Additional devenv scripts merged with the standard set.";
        };

        extraEnv = mkOption {
          type = types.attrsOf types.str;
          default = { };
          description = "Additional environment variables for the dev shell.";
        };

        containers = {
          enable = mkEnableOption "OCI container builds";
          registry = mkOption {
            type = types.str;
            default = "";
            description = "Container registry URL prefix.";
          };
        };
      };
    }
  );

  config = {
    perSystem =
      { config, pkgs, lib, ... }:
      let
        cfg = config.odoo-nix;

        overrides = import ../lib/overrides.nix;

        # Odoo always needs these native builds; wire them as defaults.
        builtinOverrides = lib.composeManyExtensions [
          (overrides.psycopg2 { inherit pkgs; })
          (overrides.python-ldap { inherit pkgs; })
        ];

        # Built-in native-library exposures (merged with the user's). Add common
        # C-extension deps here so they work out of the box.
        builtinPythonLibraries = {
          pycups = [ pkgs.cups ];
        };

        pythonEnvs = import ../lib/python.nix {
          inherit pkgs lib;
          inherit (cfg) python workspaceRoot projectName;
          pyproject-nix = inputs.pyproject-nix;
          pyproject-build-systems = inputs.pyproject-build-systems;
          uv2nix = inputs.uv2nix;
          pythonLibraries = builtinPythonLibraries // cfg.pythonLibraries;
          extraOverrides = lib.composeManyExtensions [
            builtinOverrides
            cfg.pythonOverrides
          ];
        };

        addons = import ../lib/addons.nix {
          inherit lib;
          inherit (cfg) workspaceRoot layout;
        };

        confSynth = import ../lib/odoo-conf.nix {
          inherit pkgs lib;
          inherit (cfg) odooConf;
          addonsPath = addons.addonsPath;
        };

        scripts = import ../lib/scripts.nix {
          inherit lib pkgs;
          python = "${pythonEnvs.devPythonEnv}/bin/python";
          inherit (cfg) odooSeries layout;
          dbName = if cfg.odooConf.dbName != null then cfg.odooConf.dbName else "odoo_dev";
          ocaDataset = ../data/oca-modules.json;
          ocaLib = ../lib/oca-lib.sh;
          bundlesFile = ../data/oca-bundles.json;
        };

        builtOdoo = import ../lib/odoo.nix {
          inherit pkgs lib;
          inherit (cfg) workspaceRoot layout projectName odooSeries;
          odooPythonEnv = pythonEnvs.odooPythonEnv;
        };

        libraryPath = lib.makeLibraryPath (
          [
            pkgs.stdenv.cc.cc.lib
            pkgs.libxml2
            pkgs.libxslt
            pkgs.libsass
            pkgs.libffi
            pkgs.openldap
            pkgs.cyrus_sasl
            pkgs.openssl
            pkgs.zlib
            pkgs.postgresql_16.lib
            pkgs.file.out
          ]
          ++ cfg.extraLibraryPaths
        );
      in
      lib.mkIf cfg.enable {
        packages.odooPythonEnv = pythonEnvs.odooPythonEnv;
        packages.odooDevEnv = pythonEnvs.devPythonEnv;
        packages.odooConf = confSynth.odooConfFile;
        packages.builtOdoo = builtOdoo;
        packages.default = builtOdoo;

        devenv.shells.default =
          { config, ... }:
          {
            dotenv.enable = true;

            packages =
              with pkgs;
              [
                pythonEnvs.devPythonEnv

                # Odoo runtime / asset tooling
                cfg.nodejs
                rtlcss
                wkhtmltopdf

                # DB client + native libs
                postgresql_16
                libsass
                libxml2
                libxslt

                # Tooling
                uv
                gum
                gawk
                mailpit
                curl
                file
                git
                gnused
                jq
                just
              ]
              ++ cfg.extraDevPackages;

            env =
              {
                REPO_ROOT = config.devenv.root;
                ODOO_RC = config.devenv.root + "/odoo.conf";
                PYTHONPATH = config.devenv.root + "/${cfg.layout.coreSrc}";

                # NOTE: PGHOST/PGPORT/PGUSER are provided by devenv's postgres
                # service — do not set them here (it causes an option conflict).
                # Odoo connects via odoo.conf (db_host/db_port/db_user), not PG*.

                ODOO_HTTP_PORT = toString cfg.odooConf.httpPort;
                ODOO_GEVENT_PORT = toString cfg.odooConf.geventPort;
                MAILPIT_SMTP_PORT = "1025";
                MAILPIT_HTTP_PORT = "8025";

                UV_PROJECT_ENVIRONMENT = config.env.DEVENV_STATE + "/uv-env";
                LD_LIBRARY_PATH = libraryPath;
              }
              // cfg.extraEnv;

            services.postgres = {
              enable = true;
              package = pkgs.postgresql_16;
              listen_addresses = "127.0.0.1";
              port = cfg.odooConf.dbPort;
              initialDatabases = lib.optional (cfg.odooConf.dbName != null) {
                name = cfg.odooConf.dbName;
              };
              # Odoo's DB role needs CREATEDB to create/drop databases from the UI.
              initialScript = ''
                CREATE ROLE ${cfg.odooConf.dbUser} WITH LOGIN CREATEDB SUPERUSER;
              '';
            };
            # NOTE: no services.redis — Odoo uses filesystem/DB sessions.

            processes = {
              # Single threaded dev server: serves HTTP + websocket (gevent_port)
              # in-process when workers = 0.
              odoo.exec = ''
                exec ${pythonEnvs.devPythonEnv}/bin/python \
                  "$REPO_ROOT/${cfg.layout.coreSrc}/odoo-bin" \
                  -c "$REPO_ROOT/odoo.conf" \
                  --dev=${cfg.odooConf.devMode}
              '';

              mailpit.exec = ''
                exec ${pkgs.mailpit}/bin/mailpit \
                  --smtp 127.0.0.1:''${MAILPIT_SMTP_PORT:-1025} \
                  --listen 127.0.0.1:''${MAILPIT_HTTP_PORT:-8025} \
                  --database "$DEVENV_STATE/mailpit.db"
              '';
            };

            process.managers.process-compose.settings.processes = {
              odoo.depends_on.postgres.condition = "process_started";
            };

            enterShell = ''
              # Initialize git submodules (src/odoo + src/external/*) if needed.
              if git submodule status 2>/dev/null | grep -q '^-'; then
                echo "Initializing git submodules…"
                git submodule update --init --recursive
              fi

              # Symlink the Nix-synthesized odoo.conf into place (read-only store
              # target; odoo-bin -c consumes it, never rewrites it).
              if [ "$(readlink odoo.conf 2>/dev/null)" != "${confSynth.odooConfFile}" ]; then
                ln -sfn "${confSynth.odooConfFile}" odoo.conf
              fi

              # Ensure the filestore + custom-addons dirs exist.
              mkdir -p "${cfg.odooConf.dataDir}" "${cfg.layout.customDir}"

              echo ""
              echo "╔════════════════════════════════════════════════════════════╗"
              echo "║  ${cfg.projectName} — Odoo ${cfg.odooSeries} (OCB + OCA) dev environment"
              echo "╠════════════════════════════════════════════════════════════╣"
              echo "║  devenv up           start postgres + odoo + mailpit       ║"
              echo "║  provision-db        create DB + install modules.txt       ║"
              echo "║  odoo-add-module     pick + wire in more OCA modules       ║"
              echo "║  odoo-add-bundle     add a curated OCA module bundle       ║"
              echo "║  odoo-update         pull submodules + refresh deps        ║"
              echo "║  odoo-shell          Odoo REPL                             ║"
              echo "╚════════════════════════════════════════════════════════════╝"
              echo "  addons_path entries: ${toString (builtins.length addons.addonsPathList)}  (http: ${toString cfg.odooConf.httpPort})"
              echo ""
            '';

            scripts = scripts // cfg.extraScripts;
          };
      };
  };
}
