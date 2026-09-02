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

        mailcatch = {
          enable =
            mkOption {
              type = types.bool;
              default = true;
              description = ''
                Redirect ALL outgoing email to the local Mailpit catcher.

                Ships odoo-nix's `dev_mailcatch` addon from the Nix store and
                loads it as a server-wide module, so the redirection covers
                every database on the dev server without installing anything
                into any of them — and cannot be defeated by an
                `ir.mail_server` record. Dev-shell only: the NixOS module and
                container builder never load it.
              '';
            };
          host = mkOption {
            type = types.str;
            default = "127.0.0.1";
            description = "Host the catcher's SMTP listener is bound to.";
          };
          port = mkOption {
            type = types.port;
            default = 1025;
            description = "Catcher SMTP port — drives both Mailpit and Odoo.";
          };
          httpPort = mkOption {
            type = types.port;
            default = 8025;
            description = "Mailpit web UI port.";
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

        testBrowser = mkOption {
          type = types.nullOr types.package;
          default = pkgs.chromium;
          description = ''
            Browser used by Odoo's HttpCase browser tours.

            Odoo drives a headless Chrome over the devtools protocol and looks
            for `google-chrome`, `chromium`, `chromium-browser` or
            `google-chrome-stable` on PATH. Without one it *skips* every tour
            rather than failing, so an undeclared system browser turns tours
            into tests that quietly do not run.

            Declared here for the same reason wkhtmltopdf is: a binary Odoo
            shells out to at runtime. Set to `null` to rely on a system browser
            (or to drop the closure on projects that run no tours).
          '';
        };

        ide = {
          enable = mkOption {
            type = types.bool;
            default = true;
            description = ''
              Expose the environment to editors / language servers.

              Creates two derived artifacts on shell entry, neither of which
              Odoo itself reads:

              - `./.venv` — a symlink to the Nix-built dev env, the venv
                layout every editor probes for at the workspace root.
              - `$DEVENV_STATE/pythonpath` — a merged `odoo` package tree
                whose `addons/` aggregates every addons_path root. Odoo builds
                `odoo.addons` at runtime as a pkgutil namespace, and uv2nix's
                editable installs hook it through `.pth` files that call
                `os.path.expandvars`. A static analyser does neither, so
                without this even `from odoo.addons.sale import …` is
                unresolved.
            '';
          };

          vscodeSettings = mkOption {
            type = types.bool;
            default = true;
            description = ''
              Seed `.vscode/settings.json` with the interpreter path and the
              analysis roots above, when the file does not already exist.
              Never overwrites an existing file.
            '';
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

        # odoo-nix's own addons, served straight from the store — never copied
        # or symlinked into the consumer's workspace. The addons_path entry is
        # the parent directory, so future odoo-nix addons come along for free.
        #
        # builtins.path (rather than a bare `../addons`) gives this its own
        # store path, hashed over the addons alone. A bare path would be a
        # subpath of the whole flake source, so every unrelated odoo-nix edit
        # would change addons_path, rewrite odoo.conf and force a restart.
        odooNixAddons = builtins.path {
          path = ../addons;
          name = "odoo-nix-addons";
        };

        addons = import ../lib/addons.nix {
          inherit lib;
          inherit (cfg) workspaceRoot layout;
          extraAddonsAbs = lib.optional cfg.mailcatch.enable odooNixAddons;
        };

        confSynth = import ../lib/odoo-conf.nix {
          inherit pkgs lib;
          inherit (cfg) odooConf;
          addonsPath = addons.addonsPath;
          serverWideModules = [
            "base"
            "web"
          ] ++ lib.optional cfg.mailcatch.enable "dev_mailcatch";
          extraSections = lib.optionalAttrs cfg.mailcatch.enable {
            dev_mailcatch = {
              enabled = true;
              inherit (cfg.mailcatch) host port;
            };
          };
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

        # ── Editor / language-server integration ──────────────────────────
        # Everything below is derived, gitignored and invisible to Odoo: the
        # server and the scripts import from the /nix/store env directly. It
        # exists so a static analyser resolves the same names the interpreter
        # does.
        #
        # Two things defeat analysers here, and both need a real directory to
        # look at:
        #
        #   1. uv2nix installs every OCA/custom module *editable*, via .pth
        #      files whose body is `sys.path.append(os.path.expandvars(...))`.
        #      Only a running interpreter executes those.
        #   2. `odoo.addons` is a pkgutil namespace that Odoo extends from
        #      addons_path at startup — and the bulk of the standard addons
        #      (sale, portal, mail, …) live in <coreSrc>/addons, *outside* the
        #      `odoo` package. Nothing static can see them either.
        #
        # So `pythonpathRoot` mirrors the `odoo` package with an `addons/`
        # directory that aggregates every addons_path root, first root wins —
        # the same precedence Odoo applies. One entry on
        # `python.analysis.extraPaths` then resolves core, OCA and custom
        # modules alike.
        pythonpathRoot = "$DEVENV_STATE/pythonpath";

        vscodeSettingsFile = pkgs.writeText "odoo-nix-vscode-settings.json" (
          builtins.toJSON {
            "python.defaultInterpreterPath" = "\${workspaceFolder}/.venv/bin/python";
            "python.analysis.extraPaths" = [ ".devenv/state/pythonpath" ];
            # The mirror re-exports ~2k module directories; keep the watcher
            # and the search index off it (VS Code excludes neither by
            # default, though Pylance already skips dot-directories).
            "files.watcherExclude" = {
              "**/.devenv/**" = true;
              "**/.direnv/**" = true;
            };
            "search.exclude" = {
              "**/.devenv/**" = true;
              "**/.direnv/**" = true;
            };
          }
        );

        # Anchored on $DEVENV_ROOT, not $PWD: these paths have to be the
        # workspace's regardless of where `nix develop` was invoked from.
        ideSetup = ''
          # $DEVENV_ROOT/.venv → the Nix-built dev env. Editors locate an
          # interpreter by probing the workspace root for a venv layout; ours
          # lives in the store, so link it into view. Named `.venv` because
          # that is the one name every editor checks without configuration.
          if [ -e "$DEVENV_ROOT/.venv" ] && [ ! -L "$DEVENV_ROOT/.venv" ]; then
            echo "⚠  ./.venv exists and is not a symlink — leaving it alone." >&2
            echo "   Remove it to let odoo-nix link the Nix-built dev env there." >&2
          elif [ "$(readlink "$DEVENV_ROOT/.venv" 2>/dev/null)" != "${pythonEnvs.devPythonEnv}" ]; then
            ln -sfn "${pythonEnvs.devPythonEnv}" "$DEVENV_ROOT/.venv"
          fi

          # The merged `odoo` tree. Rebuilding means ~2k symlinks, so collect
          # the wanted module set first (pure bash, no forks) and rebuild only
          # when it differs from the last run's stamp.
          _pp="${pythonpathRoot}"
          _targets=()
          declare -A _seen=()
          for _root in ${lib.concatStringsSep " " (map (p: "\"${p}\"") addons.addonsPathList)}; do
            case "$_root" in
              /*) _abs="$_root" ;;
              *) _abs="$DEVENV_ROOT/''${_root#./}" ;;
            esac
            for _mod in "$_abs"/*/; do
              [ -f "$_mod/__manifest__.py" ] || continue
              _mod="''${_mod%/}"
              _name="''${_mod##*/}"
              # First root wins, as in Odoo's own module resolution.
              [ -n "''${_seen[$_name]:-}" ] && continue
              _seen["$_name"]=1
              _targets+=("$_mod")
            done
          done

          # No trailing newline on either side: `$(...)` strips them, so the
          # stamp has to be written the same way or it never compares equal.
          _want=$(printf '%s\n' ''${_targets[@]+"''${_targets[@]}"})
          if [ ''${#_targets[@]} -gt 0 ] && [ "$_want" != "$(cat "$_pp/.stamp" 2>/dev/null)" ]; then
            rm -rf "$_pp"
            mkdir -p "$_pp/odoo/addons"
            # Everything the `odoo` package itself provides (fields.py, api.py,
            # tools/, …). `addons` is rebuilt below; `__pycache__` is noise.
            for _e in "$DEVENV_ROOT/${cfg.layout.coreSrc}"/odoo/*; do
              case "''${_e##*/}" in
                addons | __pycache__) continue ;;
              esac
              ln -s "$_e" "$_pp/odoo/''${_e##*/}"
            done
            # One `ln` per batch rather than per module: each link is named
            # after its target's basename, which *is* the module name.
            #
            # No __init__.py under addons/ — leaving it an implicit namespace
            # package is what lets a static analyser merge the roots, which is
            # the same thing pkgutil.extend_path does at runtime.
            printf '%s\0' "''${_targets[@]}" | xargs -0 ln -s -t "$_pp/odoo/addons" --
            printf '%s' "$_want" > "$_pp/.stamp"
            echo "  language-server paths refreshed (''${#_targets[@]} modules)"
          fi
          unset _pp _want _targets _seen _root _abs _mod _name _e
        '';

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
          { config, lib, ... }:
          {
            # devenv's dotenv integration is loaded by the devenv CLI and
            # asserts against being combined with the flake integration
            # (`nix develop`, as opposed to `devenv shell`) — enabling it
            # unconditionally breaks every flake-based consumer of this
            # module. `mkDefault` keeps `.env` loading for `devenv shell`
            # while a flake-integrated shell falls back to off, and a
            # consumer can still override either way.
            dotenv.enable = lib.mkDefault (!config.devenv.flakesIntegration);

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
              ++ lib.optional (cfg.testBrowser != null) cfg.testBrowser
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
                # Single source of truth: the same values are baked into
                # odoo.conf's [dev_mailcatch] section, so Odoo and Mailpit can
                # never drift apart.
                MAILPIT_SMTP_HOST = cfg.mailcatch.host;
                MAILPIT_SMTP_PORT = toString cfg.mailcatch.port;
                MAILPIT_HTTP_PORT = toString cfg.mailcatch.httpPort;

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
                  --smtp ''${MAILPIT_SMTP_HOST:-127.0.0.1}:''${MAILPIT_SMTP_PORT:-1025} \
                  --listen 127.0.0.1:''${MAILPIT_HTTP_PORT:-8025} \
                  --database "$DEVENV_STATE/mailpit.db"
              '';
            };

            process.managers.process-compose.settings.processes = {
              odoo.depends_on = {
                postgres.condition = "process_started";
              }
              // lib.optionalAttrs cfg.mailcatch.enable {
                mailpit.condition = "process_started";
              };
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

              ${lib.optionalString cfg.ide.enable ideSetup}

              ${lib.optionalString (cfg.ide.enable && cfg.ide.vscodeSettings) ''
                # Seeded once; a project's own settings are never overwritten.
                if [ ! -e "$DEVENV_ROOT/.vscode/settings.json" ]; then
                  mkdir -p "$DEVENV_ROOT/.vscode"
                  install -m 644 "${vscodeSettingsFile}" "$DEVENV_ROOT/.vscode/settings.json"
                fi
              ''}

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
              ${lib.optionalString cfg.mailcatch.enable ''
                echo "  mail: ALL outgoing email → Mailpit (http://127.0.0.1:${toString cfg.mailcatch.httpPort})"
              ''}
              echo ""
            '';

            scripts = scripts // cfg.extraScripts;
          };
      };
  };
}
