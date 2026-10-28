# devenv shell module for Odoo (OCB) + OCA projects.
# Defines the perSystem.odoo-nix option namespace and wires the dev shell:
# PostgreSQL + a single odoo-bin process + mailpit, a Nix-synthesized odoo.conf
# symlinked into place, and the OCA management scripts.
topLevel@{
  lib,
  flake-parts-lib,
  inputs,
  ...
}:
let
  inherit (lib) mkOption mkEnableOption types;
  inherit (flake-parts-lib) mkPerSystemOption;
  # Series -> interpreter, the same file odoo-init scaffolds from.
  presets = builtins.fromJSON (builtins.readFile ../lib/odoo-presets.json);

  # A removed option (mkRemovedOptionModule reports through `assertions`,
  # which perSystem has none of): defining it fails the shell's evaluation
  # with the message, through `removals`, below. The names 1.x renamed and
  # kept as aliases went in 2.0.0; each is refused naming its replacement
  # (docs/development/upgrading.md, "1.x to 2.0").
  removed =
    path: instead:
    { options, ... }:
    let
      opt = lib.getAttrFromPath path options;
    in
    {
      options = lib.setAttrByPath path (mkOption {
        type = types.anything;
        visible = false;
        description = "Removed: ${instead}";
      });
      config.odoo-nix.removals = lib.optional opt.isDefined "The option `${lib.showOption path}' defined in ${lib.showFiles opt.files} has been removed. ${instead}";
    };

  # The dev shell's `settings` before 2.0.0 was a typed camelCase tree
  # (settings.dbName, settings.logging.level, ...); it is odoo.conf by section
  # now (NixOS RFC 42, python-devops-nix docs/conventions.md, Framework config
  # blocks). A top-level key of the old tree is refused with where it went:
  # left alone, `settings.logging = { ... }` would quietly become a
  # [logging] section Odoo never reads.
  removedSettings = {
    dbHost = "settings.options.db_host";
    dbUser = "settings.options.db_user";
    dbPassword = "settings.options.db_password";
    dbName = "dbName (top level, beside `name`)";
    dataDir = "settings.options.data_dir";
    adminPasswd = "settings.options.admin_passwd";
    logging = "settings.options.{log_level,log_handler,log_db,log_db_level,logfile} (log_db = true is \"%d\")";
    httpInterface = "settings.options.http_interface";
    workers = "settings.options.workers";
    devMode = "devMode (top level: it is odoo-bin's --dev flag, not an odoo.conf key)";
    extra = "settings.options.<key>, each key as Odoo spells it";
    withoutDemo = "settings.options.without_demo";
    httpPort = "ports.http";
    geventPort = "ports.gevent";
    dbPort = "ports.db";
  };
in
{
  options.perSystem = mkPerSystemOption (
    { pkgs, config, ... }:
    {
      imports = [
        (removed [ "odoo-nix" "mailcatch" ]
          "The mail guard is devguard.mail.enable, and the catcher's host and ports are mailpit.{host,port,httpPort}."
        )
        (removed [ "odoo-nix" "devguard" "crons" ]
          "The job denylist is devguard.jobs.{enable,extraBlocked} (python-devops-nix docs/conventions.md, Job denylist)."
        )
        (removed [ "odoo-nix" "dev" ] "dev.autoReload is watch.python.")
        (removed [ "odoo-nix" "projectName" ] "The project's identity is `name`.")
        (removed [
          "odoo-nix"
          "restore"
          "attachments"
        ] "It is restore.files: \"mirror\" is true, \"none\" false.")
        # One image name since 2.0.0, <name>/odoo, so the switch that opted
        # into it through 1.x is gone rather than left a no-op to remove later.
        (removed [ "odoo-nix" "containers" "roleImageNames" ]
          "The image is always <registry>/<name>/odoo now; remove the option, and point what pulls or runs it at that name."
        )
        # The 1.x `odooConf` block, whose options became the camelCase
        # `settings` tree, which is odoo.conf by section now (see
        # removedSettings).
        (removed [ "odoo-nix" "odooConf" ]
          "Set odoo.conf's keys in settings.options.<key>, as Odoo spells them, the database in dbName and the ports in ports.*."
        )
      ]
      # The catcher is a service, not a guard: its settings left devguard.mail
      # for the mailpit tree.
      ++ map (name: removed [ "odoo-nix" "devguard" "mail" name ] "It is mailpit.${name}.") [
        "host"
        "port"
        "httpPort"
      ];

      options.odoo-nix = {
        enable = mkEnableOption "Odoo + OCA devenv shell";

        removals = mkOption {
          type = types.listOf types.str;
          default = [ ];
          internal = true;
          description = "Removed options in use: evaluating the shell's config fails with all of them.";
        };

        tui = mkOption {
          type = types.nullOr types.package;
          default = null;
          internal = true;
          description = "The program `odoo ui` runs (python-devops-nix's lib.tui.script), for the checks.";
        };

        name = mkOption {
          type = types.str;
          description = ''
            The project's identity: a slug that names its Python environments,
            packages, container image and dev-shell banner, and devenv's own
            top-level `name` (by default). Was `projectName`.
          '';
          example = "avunu-accounting";
        };

        workspaceRoot = mkOption {
          type = types.path;
          description = "Workspace root (where pyproject.toml, odoo.conf and the layout directories live).";
        };

        coreSource = mkOption {
          type = types.nullOr types.path;
          default = null;
          example = lib.literalExpression "inputs.ocb";
          description = ''
            OCB source tree from outside the workspace — typically a non-flake input
            (`inputs.ocb = { url = "github:OCA/OCB/18.0"; flake = false; }`) — instead of
            the `layout.coreSrc` git submodule.

            When set, `<coreSrc>` in the workspace is a symlink to this tree that the
            dev shell creates and refreshes (add it to `.gitignore`), the Python
            environment builds the `odoo` wheel from it, and the addons_path,
            `builtOdoo` and every check resolve the core roots there. The repository
            then carries no OCB submodule, so `self.submodules = true` is unnecessary
            and a project that mounts this repository as a submodule never fetches
            OCB through it. Bump the pin with `nix flake update <input>` rather than
            `odoo-update`.
          '';
        };

        odooSeries = mkOption {
          type = types.str;
          default = "18.0";
          description = "Odoo major series — the OCB/OCA git branch and the OCA catalog filter.";
        };

        python = mkOption {
          type = types.package;
          default =
            let
              series = config.odoo-nix.odooSeries;
            in
            pkgs.${
              presets.${series}.python or (throw ''
                odoo-nix: no preset for odooSeries "${series}" in lib/odoo-presets.json; set odoo-nix.python.
              '')
            };
          defaultText = lib.literalMD ''
            the series' interpreter from `lib/odoo-presets.json`
            (`pkgs.python311` for 18.0, `pkgs.python312` for 19.0, `pkgs.python314` for 20.0)
          '';
          description = "Python interpreter (should match the series' `requires-python`).";
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
            C-extension dependency (e.g. python-snappy) without writing a Nix
            override. psycopg2, python-ldap, lxml, pycups, python-magic, pyvips
            and cairocffi need no entry: python-devops-nix's lib.python.overrides
            fixes them.
          '';
          example = lib.literalExpression "{ python-snappy = [ pkgs.snappy ]; }";
        };

        dbName = mkOption {
          type = types.nullOr types.str;
          default = "odoo_dev";
          example = "acme";
          description = ''
            The development database: odoo.conf's `db_name` (in
            `settings.options`), the database the shell's PostgreSQL creates,
            and the `odoo` command's default. `null` leaves `db_name` out of
            odoo.conf and creates no database.
          '';
        };

        devMode = mkOption {
          type = types.str;
          default = "all";
          example = "reload,xml";
          description = ''
            The dev server's `--dev` flag: odoo-bin's command line only, not
            an odoo.conf key. `watch.python` needs `all` or `reload` in it.
          '';
        };

        settings = mkOption {
          type =
            let
              odooIni = import ../lib/odoo-ini.nix { inherit pkgs lib; };
            in
            types.submodule {
              freeformType = odooIni.type;
              options.options = mkOption {
                type = types.attrsOf odooIni.atomType;
                default = { };
                description = ''
                  odoo.conf's `[options]` section, in Odoo's own key spelling.
                  Holds every key the shell computes (most at `mkDefault`, so
                  a value here wins); set any other key here too.
                '';
              };
            };
          default = { };
          description = ''
            The dev shell's odoo.conf, as Nix (NixOS RFC 42), the same shape
            as `services.odoo-nix.settings`: one attribute per INI section, in
            Odoo's own key spelling. `options` is `[options]`; any other
            attribute is a section of its own, for a server-wide module that
            reads one. Rendered by lib/odoo-ini.nix: `true`/`false` as
            `True`/`False`, a list as one comma-separated value, `null` as no
            key at all.

            The shell sets what it computes into `options`, so this shows the
            effective file. A plain value here wins over `admin_passwd`,
            `data_dir`, `db_host`, `db_user`, `http_interface`, `log_level`,
            `log_db_level`, `server_wide_modules` and `workers`. The shell's
            own keys are set at normal priority and conflict with a second
            value: `addons_path` (from `layout` and `coreSource`),
            `http_port`, `gevent_port` and `db_port` (from `ports`), and
            `db_name` (from `dbName`).
          '';
          example = lib.literalExpression ''
            {
              options = {
                log_level = "debug";
                log_handler = [ "werkzeug:WARNING" ];
                without_demo = true;
                limit_time_real = 1200;
              };
              queue_job.channels = "root:2";
            }
          '';
        };

        postgres = {
          extensions = mkOption {
            type = types.functionTo (types.listOf types.package);
            default = _: [ ];
            example = lib.literalExpression "ps: [ ps.postgis ]";
            description = ''
              PostgreSQL extensions to build into the dev server, as a
              function of the server's extension package set
              (`pkgs.postgresql_16.pkgs`).

              Only makes the extension *available*; nothing creates it in a
              database. The dev DB role is a superuser, so a module whose
              `pre_init_hook` runs `CREATE EXTENSION` itself (OCA's
              `base_geoengine` for PostGIS) needs nothing more. Without the
              matching entry here, installing such a module fails with
              `extension "…" is not available` and the install is rolled
              back — the server ships only what it is built with.
            '';
          };

          noCow = mkOption {
            type = types.bool;
            default = true;
            description = ''
              On btrfs, keep the datadir off copy-on-write (`chattr +C`).

              PostgreSQL rewrites pages in place; copy-on-write turns every
              such write into a new extent — compressed first, on the
              compressed mounts btrfs desktops usually have — and every fsync
              into a filesystem transaction that other programs' saves wait
              behind. See python-devops-nix's lib.dbNocow (strategy "parent").

              The attribute only reaches files created after it is set, so
              shell entry arranges it for a datadir that does not exist yet.
              One that already holds a cluster is reported, not touched: stop
              `devenv up` and run `odoo-nix-db-nocow migrate "$PGDATA"` to
              copy it across once. A no-op on any other filesystem.
            '';
          };
        };

        # What the shell does when a file changes.
        watch = {
          python = mkOption {
            type = types.bool;
            default = true;
            description = ''
              Restart the server on a Python change: make Odoo's
              `--dev=reload` watcher functional.

              Odoo only starts its filesystem watcher if it can import
              `inotify` or `watchdog`, and neither is a declared Odoo
              dependency -- so `--dev=all` alone logs "Code autoreload feature
              is disabled" and silently never reloads. This ensures `watchdog`
              is importable by the dev server; Odoo then restarts itself in
              place (`os.execve`, preserving PID, CWD and the open HTTP
              socket) on any `.py` change under an addons_path root.

              XML views, QWeb templates and asset bundles do not need this --
              `--dev=xml` already re-reads them from disk per request.

              Requires `settings.options.workers = 0` (the default) and a
              `devMode` with `reload` (or `all`): the shell warns
              otherwise. Was `dev.autoReload`.
            '';
          };
        };

        # The mail catcher as a service. The mail guard (devguard.mail)
        # redirects Odoo's mail to it.
        mailpit = {
          enable = mkOption {
            type = types.bool;
            default = true;
            description = ''
              Run Mailpit beside the server, which starts after it. On whether
              or not the mail guard is: with the guard off, a database's own
              `ir.mail_server` records decide where mail goes.
            '';
          };
          host = mkOption {
            type = types.str;
            default = "127.0.0.1";
            description = "Host the catcher's SMTP listener is bound to. Was `devguard.mail.host`.";
          };
          port = mkOption {
            type = types.port;
            default = config.odoo-nix.ports.smtp;
            defaultText = lib.literalExpression "config.odoo-nix.ports.smtp";
            description = "The catcher's SMTP port, which the mail guard redirects to. Was `devguard.mail.port`.";
          };
          httpPort = mkOption {
            type = types.port;
            default = config.odoo-nix.ports.mailUi;
            defaultText = lib.literalExpression "config.odoo-nix.ports.mailUi";
            description = "Mailpit's web UI port. Was `devguard.mail.httpPort`.";
          };
        };

        # One offset for every TCP port the shell binds, so several projects
        # (and linked worktrees of one, with worktreeSalt) run at once:
        # python-devops-nix's lib.ports (docs/conventions.md, Ports). The offset is
        # a hash of the project's name; ODOO_NIX_PORT_OFFSET picks one by hand
        # for a shell, over `ports.offset`. The bases are clear of
        # frappe-nix's (8000, 3306, 9000, 19000-21000 + offset), so a bench and
        # a project never meet.
        ports = inputs.python-devops-nix.lib.ports.options {
          cfg = config.odoo-nix.ports;
          inherit (config.odoo-nix) name;
          label = "odoo-nix";
          variable = "ODOO_NIX_PORT_OFFSET";
          bases = {
            http = 10000;
            gevent = 11000;
            db = 12000;
            smtp = 13000;
            mailUi = 14000;
          };
          descriptions = {
            http = "Odoo's HTTP port (http_port)";
            gevent = "Odoo's websocket/longpolling port (gevent_port)";
            db = "PostgreSQL's port (db_port)";
            smtp = "Mailpit's SMTP port (`mailpit.port`'s default)";
            mailUi = "Mailpit's web UI port (`mailpit.httpPort`'s default)";
          };
          baseService = "http";
        };

        # Guard rails for the development environment: stop a database restored
        # from production (with its live credentials) from reaching the outside
        # world. Implemented by lib/devguard/odoo_devguard, grafted into the dev
        # virtualenv only -- never the production one, see lib/python.nix.
        devguard = {
          enable = mkOption {
            type = types.bool;
            default = true;
            description = ''
              Install the dev guard rails: every interpreter started from the dev
              environment (server, `odoo shell`, `odoo db ...`, scripts) refuses
              to reach beyond this machine, sends all mail to Mailpit, skips
              denylisted crons, and refuses to open remote `fs.storage` records.
              See odoo-nix's docs/development/guard-rails.md.

              Turning it off is a persistent decision about the whole project, not
              a per-command one (`ODOO_DEVGUARD_ENABLED=0` is that): `odoo db
              restore` refuses to run while it is off unless
              `ODOO_NIX_RESTORE_ALLOW_UNGUARDED=1` (or `restore.requireDevguard
              = false`).
            '';
          };

          egress = {
            enable = mkOption {
              type = types.bool;
              default = true;
              description = ''
                Refuse every non-loopback `connect()` made by Odoo's Python
                (requests, httpx, aiohttp/s3fs, paramiko, urllib, smtplib, ...).
                The catch-all: the other guards exist for readable errors, this
                one for completeness. PostgreSQL (libpq, in C) is not affected.
              '';
            };
            allowHosts = mkOption {
              type = types.listOf types.str;
              default = [ ];
              example = [
                "api.stripe.com"
                "*.example.com"
                "10.0.0.0/8"
              ];
              description = ''
                Destinations the guard lets through: hostnames (`*.` for a
                subdomain wildcard), IP literals or CIDRs. Loopback, Unix sockets
                and the mail catcher are always allowed. A hostname is matched
                against the name a connection was resolved from, so it works for
                clients that resolve first and connect by address (nearly all).
                `ODOO_DEVGUARD_EGRESS_ALLOW_HOSTS=a,b` replaces this list for one
                command.
              '';
            };
          };

          mail = {
            enable = mkOption {
              type = types.bool;
              default = true;
              description = ''
                Redirect ALL outgoing email to the local Mailpit catcher, whatever
                `ir.mail_server` record or from-filter a mail names, and block
                IMAP/POP3. Replaces the former `mailcatch` option and the
                `dev_mailcatch` server-wide addon.
              '';
            };
          };

          # The job denylist (python-devops-nix docs/conventions.md, Job denylist):
          # Odoo's crons. Formerly devguard.crons.*.
          jobs = {
            enable = mkOption {
              type = types.bool;
              default = true;
              description = ''
                Skip scheduled actions on the denylist (auto_backup, currency-rate
                providers, bank-statement pulls, EDI output sync, fetchmail,
                publisher warranty, web push) even if something switched them
                back on. Neutralization already deactivates every cron.
              '';
            };
            extraBlocked = mkOption {
              type = types.listOf types.str;
              default = [ ];
              example = [ "my_module.ir_cron_sync_erp" ];
              description = "More cron external ids (`<module>.<name>`) to skip, exact match.";
            };
          };

          objectstore.enable = mkOption {
            type = types.bool;
            default = true;
            description = ''
              Refuse to open an `fs.storage` that is not a local filesystem
              (S3, SFTP, ...), so attachments and backups cannot reach a
              production bucket. `odoo db restore` points restored storages at
              local disk.
            '';
          };

          backups.enable = mkOption {
            type = types.bool;
            default = true;
            description = "Skip `auto_backup` jobs that write to a remote destination, and their retention pass.";
          };

          webhooks.enable = mkOption {
            type = types.bool;
            default = true;
            description = "Make outbound webhook server actions do nothing.";
          };

          iap.enable = mkOption {
            type = types.bool;
            default = true;
            description = "Make Odoo IAP calls (SMS, partner autocomplete, ...) fail with a readable error.";
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

          languageServer = {
            enable = mkOption {
              type = types.bool;
              default = true;
              description = ''
                Run odoo-ls (the Odoo-aware Rust language server) alongside
                Pylance/pyright. Puts `odoo_ls_server` on the dev shell PATH
                and symlinks a Nix-synthesized `./odools.toml` into place
                from this workspace's OCB checkout, addons_path and `.venv`
                interpreter -- all as relative paths (odoo-ls resolves them
                against odools.toml's own location, not CWD), so the file's
                content is identical across machines and checkout locations.

                VS Code's `Odoo.odoo` extension bundles its own copy of this
                server and never reads this one -- see `vscodeSettings`,
                which is all VS Code gets from this option (a
                `Odoo.serverConfigPath` setting pointing at the generated
                `odools.toml`, plus an extension recommendation). This
                option's binary is for every other editor's LSP client and
                for `odoo_ls_server` from the CLI.

                `odools.toml` is a store symlink like `odoo.conf` and
                `.venv` -- add it to `.gitignore`, do not hand-edit or
                commit it (its target is a specific store path that goes
                stale the moment addons_path or coreSrc changes). Only takes
                effect when `ide.enable` is also true: the generated
                `python_path` points at `.venv`, which only `ide.enable`
                creates.
              '';
            };

            package = mkOption {
              type = types.package;
              default = import ../lib/odoo-ls.nix {
                inherit pkgs lib;
                src = inputs.odoo-ls-src;
                typeshedSrc = inputs.odoo-ls-typeshed;
              };
              description = "The odoo_ls_server package to use.";
            };
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

        # `odoo db restore` / `odoo project restore` from the remote backup
        # store. The credentials are the backup-access secret
        # (odoo-nix.secrets, modules/secrets.nix), decrypted per command.
        restore = {
          enable = mkOption {
            type = types.bool;
            default = topLevel.config.odoo-nix.secrets.backupAccess.enable;
            defaultText = lib.literalExpression "odoo-nix.secrets.backupAccess.enable";
            description = ''
              Offer `setup-backup-access` and let the `odoo` CLI decrypt the
              backup-access secret for remote restores.
            '';
          };

          prefix = mkOption {
            type = types.str;
            default = "";
            description = ''
              Path prefix inside the bucket, used when the secret's
              `BACKUPS_PREFIX` is unset.
            '';
          };

          sourceDatabase = mkOption {
            type = types.str;
            default = "";
            description = ''
              Database folder to restore from (production's database name).
              Defaults to the name of the database being restored.
            '';
          };

          files = mkOption {
            type = types.bool;
            default = false;
            description = ''
              Also download the attachments held in an object store
              (`fs_attachment`) when restoring from the remote store
              (`--files`/`--no-files` per command). Either way the restored
              database's remote `fs.storage` records are pointed at a local
              directory, so the copy can never write to production; with this
              on, the bucket contents are mirrored there first (the
              backup-access credentials need read access to that bucket).

              Was `restore.attachments = "mirror"`.
            '';
          };

          neutralize = mkOption {
            type = types.bool;
            default = true;
            description = "Neutralize (no outgoing mail, crons off) databases restored from the remote store.";
          };

          migrate = mkOption {
            type = types.bool;
            default = true;
            description = ''
              Run `odoo db migrate` on a database once it is restored, so a
              backup taken by older code is brought up to the checkout's
              modules (`--no-migrate` per command). No snapshot is taken first:
              the backup just restored is one.
            '';
          };

          requireDevguard = mkOption {
            type = types.bool;
            default = true;
            description = ''
              Refuse to restore while `devguard.enable` is false, because
              nothing would then stop the restored database from mailing
              customers, writing to production storage or running its crons.
              `ODOO_NIX_RESTORE_ALLOW_UNGUARDED=1` overrides it per command.
              Turn this off only for a project whose databases hold nothing
              that can reach the outside.
            '';
          };
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
            example = "ghcr.io/avunu";
            description = "Registry prefix for the image name: \"ghcr.io/avunu\" names the image ghcr.io/avunu/<name>/odoo. A trailing slash is dropped; empty leaves the name bare.";
          };
          nonRoot = mkOption {
            type = types.bool;
            default = true;
            description = "Run the image as odoo (uid/gid 1000) instead of root, with /etc/odoo and /var/lib/odoo owned by it. The default since 2.0.0 (root through 1.x). A filestore volume a root image wrote is owned by root and needs a one-time chown first: see docs/production/container.md, Running as non-root. `false` runs it as root.";
          };
          labels = mkOption {
            type = types.attrsOf types.str;
            default = { };
            example = lib.literalExpression ''
              {
                "org.opencontainers.image.source" = "https://github.com/acme/odoo";
                "org.opencontainers.image.revision" = self.rev or "dirty";
              }
            '';
            description = "Image labels, over the org.opencontainers.image.* ones the image gets (title, source, version, licenses, and revision when the project's flake has odoo-nix as the `odoo-nix` input). Those describe odoo-nix; set source, version and revision here to describe the project instead.";
          };
        };
      };
    }
  );

  config = {
    perSystem =
      {
        config,
        options,
        pkgs,
        lib,
        ...
      }:
      let
        # Every read of cfg goes through the removed options' error first
        # (perSystem has no `assertions` option to collect them).
        cfg =
          if config.odoo-nix.removals != [ ] then
            throw ''
              odoo-nix: ${lib.concatStringsSep "\n" config.odoo-nix.removals}
              See odoo-nix's docs/development/upgrading.md, "1.x to 2.0".''
          else
            config.odoo-nix;

        # The 1.x camelCase tree's keys in a `settings` definition
        # (removedSettings), with where they are written.
        settingsRemovals = lib.concatMap (
          d:
          lib.optionals (builtins.isAttrs d.value && !(d.value ? _type)) (
            map (
              k:
              "settings.${k} (in ${toString d.file}) is the 1.x camelCase settings tree; it is ${removedSettings.${k}} now."
            ) (lib.filter (k: removedSettings ? ${k}) (lib.attrNames d.value))
          )
        ) options.odoo-nix.settings.definitionsWithLocations;

        # odoo.conf's INI dialect, shared with the NixOS module.
        odooIni = import ../lib/odoo-ini.nix { inherit pkgs lib; };

        # python-devops-nix's Python pieces: the BLAS thread caps, rich for
        # the banner, and (in lib/python.nix) the package fixes and the
        # stale-lock audit.
        pythonLib = inputs.python-devops-nix.lib.python;
        inherit (pythonLib) threadCaps;

        # The guard rails, with this project's settings baked in. Only the dev and
        # test environments get it (lib/python.nix), never the production one.
        # Settings are read at run time with `ODOO_DEVGUARD_*` winning, so the
        # shell's environment can re-point or disable a guard for one command.
        dg = cfg.devguard;
        devguardPkg = import ../lib/devguard.nix {
          inherit pkgs;
          base = inputs.python-devops-nix.lib;
          settings = {
            enabled = dg.enable;
            guards = {
              egress = {
                enable = dg.egress.enable;
                allow_hosts = dg.egress.allowHosts;
              };
              mail = {
                enable = dg.mail.enable;
                inherit (cfg.mailpit) host port;
                http_port = cfg.mailpit.httpPort;
              };
              jobs = {
                enable = dg.jobs.enable;
                extra_blocked = dg.jobs.extraBlocked;
              };
              objectstore.enable = dg.objectstore.enable;
              backups.enable = dg.backups.enable;
              webhooks.enable = dg.webhooks.enable;
              iap.enable = dg.iap.enable;
            };
          };
        };

        pythonEnvs = import ../lib/python.nix {
          inherit pkgs lib;
          inherit (cfg)
            python
            workspaceRoot
            coreSource
            ;
          projectName = cfg.name;
          devguard = if dg.enable then devguardPkg else null;
          # In every environment, the production one included: inert unless
          # stderr is the journal (python-devops-nix docs/conventions.md, Journald
          # enablement).
          journald = import ../lib/journald.nix {
            inherit pkgs;
            base = inputs.python-devops-nix.lib;
          };
          inherit pythonLib;
          inherit (inputs) pyproject-nix pyproject-build-systems uv2nix;
          inherit (cfg) pythonLibraries;
          extraOverrides = cfg.pythonOverrides;
        };

        # Pure-Python, no propagated dependencies -- safe to drop on PYTHONPATH
        # of the uv2nix-built venv without dragging in a conflicting transitive.
        watchdogFallback = "${cfg.python.pkgs.watchdog}/${cfg.python.sitePackages}";

        addons = import ../lib/addons.nix {
          inherit lib;
          inherit (cfg) workspaceRoot layout coreSource;
        };

        # The dev odoo.conf: `settings` as the config below fills it in. The
        # name and the text alone make its store path.
        odooConfFile = odooIni.generate "odoo.conf" (removeAttrs cfg.settings [ "_module" ]);

        # Secrets + remote restore (see modules/secrets.nix): the
        # python-devops-nix toolkit (docs/library.md, Secrets and backups),
        # with odoo-nix's names.
        secretsCfg = topLevel.config.odoo-nix.secrets;
        secretsTools = inputs.python-devops-nix.lib.secrets.tools {
          inherit pkgs;
          cfg = secretsCfg;
          label = "odoo-nix";
          restoreCommand = "odoo db restore";
          bucketExample = "my-odoo-backups";
          # setup-backup-access's check that the credentials reach the
          # backups: one folder per database (lib/odoo_nix_cli/backup_layout.py).
          verifyListing = ''
            local listing
            listing="$("$FETCH" folders)" || return
            printf 'bucket reachable; %s database folder(s) under the prefix\n' \
              "$(printf '%s\n' "$listing" | grep -c . || true)"
          '';
        };

        rcloneBin = lib.getExe pkgs.rclone;

        # The backup fetch layer as a command (`odoo-nix-backup-fetch
        # {list,folders,fetch}`), with odoo-nix's layout: what
        # `setup-backup-access` tests the credentials with before encrypting
        # them. The `odoo` CLI imports the same module in-process (lib/cli.nix).
        backupFetch = inputs.python-devops-nix.lib.backups.fetch {
          inherit pkgs;
          label = "odoo-nix";
          envPrefix = "ODOO";
          layout = ../lib/odoo_nix_cli/backup_layout.py;
        };

        # Run a command with the backup-access secret in its environment. The
        # `odoo` CLI re-executes itself through this when the credentials are
        # absent: decryption happens per command, never at shell entry (see
        # loadSecrets in python-devops-nix's lib.secrets.tools for why).
        withBackupAccess = pkgs.writeShellScript "odoo-nix-with-backup-access" ''
          ${secretsTools.loadSecrets config.agenix-shell.installationScript}
          export ODOO_NIX_SECRETS_LOADED=1
          exec "$@"
        '';

        restoreEnabled = cfg.restore.enable && secretsTools.enabled;

        cliScripts = import ../lib/cli-scripts.nix {
          inherit lib pkgs;
          sourcesBin = lib.getExe sources;
          buildDeps = import ../lib/build-deps.nix {
            inherit pkgs;
            base = inputs.python-devops-nix.lib;
          };
          python = "${pythonEnvs.devPythonEnv}/bin/python";
          inherit (cfg) odooSeries layout coreSource;
          ocaDataset = ../data/oca-modules.json;
          bundlesFile = ../data/oca-bundles.json;
        };

        builtOdoo = import ../lib/odoo.nix {
          inherit pkgs lib;
          inherit (cfg)
            workspaceRoot
            layout
            odooSeries
            coreSource
            ;
          projectName = cfg.name;
          inherit (pythonEnvs) odooPythonEnv;
        };

        # The `odoo` CLI: db/module/project subcommands + odoo-bin passthrough
        # (lib/cli.nix). The dev variant's passthrough target is the live
        # workspace checkout through the editable dev env -- the same
        # $REPO_ROOT/<coreSrc>/odoo-bin the old lib/scripts.nix preamble ran,
        # not the Nix-assembled builtOdoo snapshot, so `odoo shell`/`odoo
        # server`/etc keep seeing live source edits. The production variant
        # (packages.default, consumed by services.odoo-nix / the container
        # builder) passes through to builtOdoo's own wrapper instead, and has
        # no workspace scripts wired in -- there is no git checkout to pull or
        # modules.txt to add to in an assembled /nix/store deployment.
        # A tree without odoo-bin runs as `python -m odoo` (lib/raw-odoo.nix).
        # The `odoo` process under `devenv up` runs this too.
        devRawOdooBin = pkgs.writeShellScript "odoo-nix-dev-odoo-bin" ''
          set -euo pipefail
          cd "''${REPO_ROOT:-$PWD}"
          tree="''${REPO_ROOT:-$PWD}/${cfg.layout.coreSrc}"
          ${import ../lib/raw-odoo.nix {
            inherit pkgs;
            python = "${pythonEnvs.devPythonEnv}/bin/python";
          }}
        '';

        odooCliDev = import ../lib/cli.nix {
          inherit pkgs lib;
          inherit (cfg) python;
          inherit cliScripts;
          name = "${cfg.name}-odoo-cli-dev";
          rawOdooBin = devRawOdooBin;
          targetPythonEnv = pythonEnvs.devPythonEnv;
          inherit rcloneBin;
          base = inputs.python-devops-nix.lib;
          withSecrets = if restoreEnabled then withBackupAccess else null;
          tui = tuiRun;
        };

        odooCliProd = import ../lib/cli.nix {
          inherit pkgs lib;
          inherit (cfg) python;
          name = "${cfg.name}-odoo-cli";
          rawOdooBin = "${builtOdoo}/bin/odoo";
          mirrorTree = builtOdoo;
          targetPythonEnv = pythonEnvs.odooPythonEnv;
          cliScripts = null;
          base = inputs.python-devops-nix.lib;
        };

        # python-devops-nix's shell pieces (docs/library.md, Development
        # shell), configured in
        # lib/shell-tools.nix: odoo-nix-sources (submodule checkout on entry),
        # odoo-nix-db-nocow (the postgres.noCow option) and odoo-nix-banner,
        # on the project's interpreter so the shell carries no second one.
        shellTools = import ../lib/shell-tools.nix {
          inherit pkgs;
          base = inputs.python-devops-nix.lib;
          inherit (cfg) python;
        };
        inherit (shellTools) sources dbNocow;

        # CI mode (python-devops-nix docs/conventions.md, CI mode): ODOO_NIX_CI set to anything but
        # "", 0 or false skips the interactive steps, turns process-compose's
        # TUI off and prints a one-line banner.
        ciMode = inputs.python-devops-nix.lib.ciMode {
          label = "odoo-nix";
          envPrefix = "ODOO";
        };

        # The welcome banner's spec: rendered with rich by odoo-nix-banner,
        # never hand-aligned `echo` lines.
        bannerSpec = {
          title = "${cfg.name} — Odoo ${cfg.odooSeries} (OCB + OCA) dev environment";
          commands =
            map
              (c: {
                command = builtins.elemAt c 0;
                description = builtins.elemAt c 1;
              })
              [
                [
                  "devenv up"
                  "start postgres + odoo + mailpit"
                ]
                [
                  "odoo db provision"
                  "create DB + install modules.txt"
                ]
                [
                  "odoo db migrate"
                  "update changed modules, with progress"
                ]
                [
                  "odoo module add"
                  "pick + wire in more OCA modules"
                ]
                [
                  "odoo module add-bundle"
                  "add a curated OCA module bundle"
                ]
                [
                  "odoo project update"
                  "pull submodules + refresh deps"
                ]
                [
                  "odoo test <mod> [db]"
                  "run a module's tests"
                ]
                [
                  "odoo shell"
                  "Odoo REPL"
                ]
                [
                  "odoo ui"
                  "the menu: stack, commands, OCA store (or just: odoo)"
                ]
              ];
          urls = [
            {
              label = "Odoo server";
              url = "http://127.0.0.1:${toString cfg.ports.http}";
            }
          ];
          facts = [
            {
              label = "addons_path entries";
              value = toString (builtins.length addons.addonsPathList);
            }
          ];
          guard = {
            inherit (cfg.devguard) enable;
            egress = {
              inherit (cfg.devguard.egress) enable;
              allow = cfg.devguard.egress.allowHosts;
            };
            mail = {
              inherit (cfg.devguard.mail) enable;
              url = "http://127.0.0.1:${toString cfg.mailpit.httpPort}";
            };
          };
        };

        # The menu (`odoo ui`, and a bare `odoo` at a terminal):
        # python-devops-nix's lib.tui, with lib/odoo_nix_cli/tui.py as its
        # store. It runs on its own interpreter (textual, on the project's
        # Python), isolated from the dev environment, and changes nothing
        # itself: every action is an `odoo …` command line it shows first.
        tuiBase = inputs.python-devops-nix.lib.tui;
        cliPackage = import ../lib/cli-package.nix {
          inherit pkgs;
          base = inputs.python-devops-nix.lib;
        };

        tuiCommand = tuiBase.command {
          inherit pkgs;
          inherit (cfg) python;
          name = "odoo-nix-tui";
          plugins = [
            {
              name = "odoo_nix_cli";
              path = "${cliPackage}/odoo_nix_cli";
            }
          ];
        };

        # The Commands tab: the `odoo` command line's own tree, built here
        # from its click group, and the odoo-bin subcommands it passes
        # through (their arguments are odoo-bin's, so each is one line).
        cliCatalog = tuiBase.commands {
          inherit pkgs;
          name = "odoo-nix-commands";
          python = inputs.python-devops-nix.lib.python.rich {
            inherit (cfg) python;
            extraPackages = ps: [ ps.click ];
          };
          target = "odoo_nix_cli.commands:cli";
          cli = "odoo";
          source = "odoo-nix";
          interactive = [
            "shell"
            "ui"
          ];
          pythonPath = [ cliPackage ];
        };
        odooBinCatalog = pkgs.writeText "odoo-bin-commands.json" (
          builtins.toJSON {
            name = "odoo";
            source = "odoo-bin";
            help = "odoo-bin's own subcommands, which `odoo` passes through.";
            commands =
              map
                (c: {
                  name = builtins.elemAt c 0;
                  path = [ (builtins.elemAt c 0) ];
                  short = builtins.elemAt c 1;
                  raw = true;
                  interactive = builtins.elemAt c 2;
                })
                [
                  [
                    "server"
                    "run the server in the foreground (devenv up runs it for you)"
                    true
                  ]
                  [
                    "scaffold"
                    "create a module skeleton: scaffold <name> <directory>"
                    false
                  ]
                  [
                    "populate"
                    "fill a database with generated test data"
                    false
                  ]
                  [
                    "neutralize"
                    "neutralize a database (crons, mail servers, payment providers)"
                    false
                  ]
                  [
                    "cloc"
                    "count the lines of code of the installed modules"
                    false
                  ]
                  [
                    "upgrade_code"
                    "rewrite module source for this series' API"
                    false
                  ]
                  [
                    "tsconfig"
                    "write a tsconfig.json for the addons' JavaScript"
                    false
                  ]
                  [
                    "obfuscate"
                    "obfuscate (or unobfuscate) a database's data"
                    false
                  ]
                ];
          }
        );

        tuiRun = tuiBase.script {
          inherit pkgs;
          tui = tuiCommand;
          name = "odoo-nix-ui";
          spec = {
            product = "odoo-nix";
            cli = "odoo";
            root = "@root@";
            banner = bannerSpec;
            site = {
              label = "Odoo";
              url = "http://127.0.0.1:${toString cfg.ports.http}";
              process = "odoo";
            };
            stack.actions = [
              {
                label = "Update changed modules";
                argv = [
                  "odoo"
                  "db"
                  "migrate"
                ];
                help = "odoo db migrate: upgrade what changed since the last run";
              }
              {
                label = "Pull and refresh the project";
                argv = [
                  "odoo"
                  "project"
                  "update"
                ];
                help = "odoo project update: submodules on their branch, deps re-locked, then migrate";
                after = "rebuild";
              }
            ];
            actions = [
              {
                label = "Provision the database";
                argv = [
                  "odoo"
                  "db"
                  "provision"
                ];
                help = "create it and install modules.txt, or migrate it if it exists";
              }
              {
                label = "Update changed modules";
                argv = [
                  "odoo"
                  "db"
                  "migrate"
                ];
              }
              {
                label = "Odoo shell";
                argv = [
                  "odoo"
                  "shell"
                ];
                interactive = true;
              }
              {
                label = "Pull and refresh the project";
                argv = [
                  "odoo"
                  "project"
                  "update"
                ];
                after = "rebuild";
              }
            ];
            commands = [
              { file = "${cliCatalog}"; }
              { file = "${odooBinCatalog}"; }
            ];
            plugin = {
              module = "odoo_nix_cli.tui";
              config = {
                series = cfg.odooSeries;
                ocaDataset = "${../data/oca-modules.json}";
                ocaBundles = "${../data/oca-bundles.json}";
                inherit (cfg.layout) externalDir customDir;
              };
            };
          };
          vars.root = "\${REPO_ROOT:-$PWD}";
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
          builtins.toJSON (
            {
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
            # VS Code's own Odoo.odoo extension bundles its own odoo_ls_server
            # binary and never reads cfg.ide.languageServer.package -- this
            # setting is the one thing it *does* pick up from this module.
            // lib.optionalAttrs (cfg.ide.enable && cfg.ide.languageServer.enable) {
              "Odoo.serverConfigPath" = "\${workspaceFolder}/odools.toml";
            }
          )
        );

        # Recommends the Odoo.odoo VS Code extension (the odoo-ls client) --
        # seeded once, like vscodeSettingsFile, so VS Code prompts the
        # developer to install it without odoo-nix ever calling any
        # extension-management API itself.
        vscodeExtensionsFile = pkgs.writeText "odoo-nix-vscode-extensions.json" (
          builtins.toJSON { recommendations = [ "Odoo.odoo" ]; }
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

        # odools.toml for odoo-ls (see ide.languageServer.enable): Nix-pure,
        # symlinked into place like odoo.conf, not regenerated by bash --
        # odoo-ls resolves a relative path against the directory of the
        # specific file that value's text came from (fill_or_canonicalize in
        # server/src/core/config.rs), using the literal discovered path
        # rather than a canonicalized one, so a symlinked odools.toml at the
        # workspace root resolves relative paths against the workspace root
        # itself -- exactly like odoo.conf's relative addons_path, and safe
        # for both auto-discovery (walking up from a workspace folder) and
        # an explicit --config-path/Odoo.serverConfigPath. The profile is
        # always named "default": odoo-ls falls back to that name whenever a
        # client never answers its Odoo-specific `workspace/configuration`
        # request, which covers every non-VS-Code client.
        odoolsTomlFile = pkgs.writeText "odoo-nix-odools.toml" ''
          [[config]]
          name = "default"
          odoo_path = "./${cfg.layout.coreSrc}"
          python_path = "./.venv/bin/python3"
          addons_paths = [
          ${lib.concatMapStringsSep ",\n" (p: "  \"${p}\"") addons.addonsPathList}
          ]
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
      lib.mkMerge [
        { odoo-nix.removals = settingsRemovals; }

        # odoo.conf's [options] from the shell's own options. Under
        # config.odoo-nix.enable, not cfg.enable: settingsRemovals reads
        # these definitions, and cfg waits for it.
        (lib.mkIf config.odoo-nix.enable {
          odoo-nix.settings.options = lib.mkMerge [
            # The shell's: odoo.conf has to agree with what it runs. The
            # ports are the ports tree's (PostgreSQL listens on ports.db, the
            # banner and ODOO_NIX_HTTP_PORT name ports.http), the addons the
            # layout's, and db_name dbName's. Normal priority, so a second
            # value is a conflict, not a silent override: change `ports.*`,
            # `layout` or `dbName`, or use mkForce.
            (
              {
                addons_path = addons.addonsPath;
                http_port = cfg.ports.http;
                gevent_port = cfg.ports.gevent;
                db_port = cfg.ports.db;
              }
              // lib.optionalAttrs (cfg.dbName != null) { db_name = cfg.dbName; }
            )
            # Everything else is a default a project may override.
            (lib.mapAttrs (_: lib.mkDefault) {
              db_host = "127.0.0.1";
              # The role the shell's PostgreSQL creates (initialScript reads
              # it back from here).
              db_user = "odoo";
              # Relative to the workspace root, gitignored under .devenv; the
              # shell creates it.
              data_dir = "./.devenv/state/odoo";
              # The database manager's master password, for a dev instance.
              admin_passwd = "admin";
              # Loopback: a dev instance with `admin` as its master password
              # has no business on the LAN, and 20.0 makes this its own
              # default (19.0 warns whenever the key is absent).
              http_interface = "127.0.0.1";
              # Threaded: watch.python's reloader runs on that server only.
              workers = 0;
              log_level = "info";
              log_db_level = "warning";
              # Setting the key at all replaces Odoo's own default, so the
              # series' full default set is reproduced: 19.0 added `rpc`
              # (DEFAULT_SERVER_WIDE_MODULES = base,rpc,web) and would
              # otherwise lose XML-RPC/JSON-RPC entirely.
              server_wide_modules = [
                "base"
              ]
              ++ lib.optional (lib.versionAtLeast cfg.odooSeries "19.0") "rpc"
              ++ [ "web" ];
            })
          ];
        })

        (lib.mkIf cfg.enable { odoo-nix.tui = tuiRun; })

        (lib.mkIf cfg.enable {
          packages.odooPythonEnv = pythonEnvs.odooPythonEnv;
          packages.odooDevEnv = pythonEnvs.devPythonEnv;
          packages.odooTestEnv = pythonEnvs.testPythonEnv;
          packages.odooConf = odooConfFile;
          # builtOdoo (lib/odoo.nix) is the un-wrapped assembled tree, still
          # available directly for anything that specifically wants it (e.g.
          # tests/series.nix asserts against it). `default`/`package` -- what
          # services.odoo-nix and the container builder actually consume -- is
          # the CLI-wrapped production build: `${pkg}/bin/odoo` handles
          # db/module/project subcommands and passes anything else straight to
          # the real odoo-bin (`passthru.builtOdoo`'s bin/odoo, which the
          # wrapper execs via $ODOO_NIX_RAW_ODOO).
          packages.builtOdoo = builtOdoo;
          packages.odooCli = odooCliDev;
          packages.default = odooCliProd;
          packages.odoo-ls = cfg.ide.languageServer.package;

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

              # devenv's "Name of the project": the shell and the product agree
              # (python-devops-nix docs/conventions.md, Identity options).
              name = lib.mkDefault cfg.name;

              packages =
                with pkgs;
                [
                  pythonEnvs.devPythonEnv
                  # hiPrio: OCB itself ships a console-script entry point named
                  # `odoo` (installed by uv2nix into devPythonEnv), colliding
                  # with this CLI's own `bin/odoo`. devenv orders `packages` by
                  # meta.priority precisely for this -- "packages wrapped with
                  # lib.hiPrio shadow other packages that ship a program with
                  # the same name" (devenv's own top-level.nix) -- rather than
                  # relying on list order, which the two already silently
                  # collided on once (OCB's script winning, shadowing this one)
                  # before this was diagnosed.
                  (lib.hiPrio odooCliDev)

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
                ++ lib.optional (cfg.ide.enable && cfg.ide.languageServer.enable) cfg.ide.languageServer.package
                ++ secretsTools.packages
                ++ lib.optional restoreEnabled pkgs.rclone
                # For the one-off `odoo-nix-db-nocow migrate` shell entry asks for.
                ++ lib.optional (cfg.postgres.noCow && pkgs.stdenv.hostPlatform.isLinux) dbNocow
                ++ cfg.extraDevPackages;

              env = {
                REPO_ROOT = config.devenv.root;
                ODOO_RC = config.devenv.root + "/odoo.conf";
                PYTHONPATH = config.devenv.root + "/${cfg.layout.coreSrc}";

                # NOTE: PGHOST/PGPORT/PGUSER are provided by devenv's postgres
                # service — do not set them here (it causes an option conflict).
                # Odoo connects via odoo.conf (db_host/db_port/db_user), not PG*.

                ODOO_NIX_HTTP_PORT = toString cfg.ports.http;
                ODOO_NIX_GEVENT_PORT = toString cfg.ports.gevent;
                # Single source of truth: the same values are baked into the
                # devguard's settings (lib/devguard.nix), so Odoo and Mailpit can
                # never drift apart.
                MAILPIT_SMTP_HOST = cfg.mailpit.host;
                MAILPIT_SMTP_PORT = toString cfg.mailpit.port;
                MAILPIT_HTTP_PORT = toString cfg.mailpit.httpPort;

                # The Nix-time devguard switch, read by `odoo db restore`: unlike
                # $ODOO_DEVGUARD_ENABLED (per command) this is a property of the
                # project, and its mere presence says "this is a dev shell".
                ODOO_NIX_DEVGUARD = if cfg.devguard.enable then "1" else "0";

                UV_PROJECT_ENVIRONMENT = config.env.DEVENV_STATE + "/uv-env";
                LD_LIBRARY_PATH = libraryPath;
              }
              // threadCaps
              // {
                ODOO_NIX_RESTORE_PREFIX = cfg.restore.prefix;
                ODOO_NIX_RESTORE_SOURCE_DB = cfg.restore.sourceDatabase;
                ODOO_NIX_RESTORE_FILES = if cfg.restore.files then "1" else "0";
                ODOO_NIX_RESTORE_NEUTRALIZE = if cfg.restore.neutralize then "1" else "0";
                ODOO_NIX_RESTORE_MIGRATE = if cfg.restore.migrate then "1" else "0";
                ODOO_NIX_RESTORE_REQUIRE_DEVGUARD = if cfg.restore.requireDevguard then "1" else "0";
              }
              // cfg.extraEnv;

              # Both of these fail silently in Odoo -- a disabled watcher is one
              # INFO line in a very noisy log -- which is exactly how the dev
              # server shipped with reload requested but never running.
              warnings =
                let
                  devFeatures = lib.splitString "," cfg.devMode;
                  workers = cfg.settings.options.workers or 0;
                in
                lib.optional (cfg.watch.python && toString workers != "0") ''
                  odoo-nix: watch.python is on but settings.options.workers = ${toString workers}.
                  Odoo's reload watcher only runs on the threaded server; set workers = 0 for it to take effect.
                ''
                ++
                  lib.optional (cfg.watch.python && !lib.elem "all" devFeatures && !lib.elem "reload" devFeatures)
                    ''
                      odoo-nix: watch.python is on but devMode = "${cfg.devMode}" requests
                      neither "all" nor "reload", so Odoo will not start a file watcher.
                    ''
                ++ lib.optional (cfg.devguard.enable && cfg.devguard.mail.enable && !cfg.mailpit.enable) ''
                  odoo-nix: the mail guard is on but mailpit.enable is false: mail is redirected to
                  ${cfg.mailpit.host}:${toString cfg.mailpit.port}, where nothing listens, so sending fails.
                '';

              services.postgres = {
                enable = true;
                package = pkgs.postgresql_16;
                # devenv wraps the server in `withPackages` whenever this is
                # non-null, even for an empty list; keep the plain package unless
                # something is actually requested.
                extensions =
                  if cfg.postgres.extensions pkgs.postgresql_16.pkgs == [ ] then null else cfg.postgres.extensions;
                listen_addresses = "127.0.0.1";
                port = cfg.ports.db;
                initialDatabases = lib.optional (cfg.dbName != null) {
                  name = cfg.dbName;
                };
                # Odoo's DB role needs CREATEDB to create/drop databases from the UI.
                initialScript = ''
                  CREATE ROLE ${cfg.settings.options.db_user} WITH LOGIN CREATEDB SUPERUSER;
                '';
              };
              # NOTE: no services.redis — Odoo uses filesystem/DB sessions.

              processes = {
                # Single threaded dev server: serves HTTP + websocket (gevent_port)
                # in-process when workers = 0.
                odoo.exec = ''
                  ${lib.optionalString cfg.watch.python ''
                    # A project that pins watchdog in [dependency-groups].dev wins;
                    # otherwise fill it in from nixpkgs so Odoo's --dev=reload
                    # watcher has something to import. PYTHONPATH precedes
                    # site-packages, hence the probe rather than an unconditional
                    # prepend. os.execve carries this across every reload.
                    if ! ${pythonEnvs.devPythonEnv}/bin/python -c 'import watchdog' 2>/dev/null; then
                      export PYTHONPATH="${watchdogFallback}''${PYTHONPATH:+:$PYTHONPATH}"
                    fi
                  ''}
                  exec ${devRawOdooBin} \
                    -c "$REPO_ROOT/odoo.conf" \
                    --dev=${cfg.devMode}
                '';

                mailpit = lib.mkIf cfg.mailpit.enable {
                  exec = ''
                    exec ${pkgs.mailpit}/bin/mailpit \
                      --smtp "$MAILPIT_SMTP_HOST:$MAILPIT_SMTP_PORT" \
                      --listen "127.0.0.1:$MAILPIT_HTTP_PORT" \
                      --database "$DEVENV_STATE/mailpit.db"
                  '';
                };
              };

              # Cross-manager ordering. `process.managers.process-compose.settings`
              # would be ignored outright: devenv 2.0+ defaults
              # process.manager.implementation to "native", and that block only
              # applies under process-compose. `processes.<n>.after` is honoured by
              # the native manager and translated back into process-compose's
              # depends_on (@started -> process_started) for older CLIs.
              processes.odoo.after = [
                "devenv:processes:postgres@started"
              ]
              # The catcher before the server, mail guard or not, so a server
              # never sends to a catcher that is not up yet.
              ++ lib.optional cfg.mailpit.enable "devenv:processes:mailpit@started";

              enterShell = ''
                ${ciMode.exports}
                ${lib.optionalString (cfg.postgres.noCow && pkgs.stdenv.hostPlatform.isLinux) ''
                  # Before `devenv up` runs initdb: the btrfs NOCOW attribute only
                  # reaches files created after it is set (python-devops-nix's
                  # lib.dbNocow, strategy "parent").
                  ${lib.getExe dbNocow} prepare "''${PGDATA:-$DEVENV_STATE/postgres}" || true
                ''}
                ${lib.optionalString (cfg.coreSource != null) ''
                  # OCB comes from a flake input: keep <coreSrc> a symlink to it so
                  # odoo-bin, the scripts and the IDE mirror all find it where the
                  # submodule layout would have it (`uv lock` goes through a
                  # writable shadow of it, see lib/odoo_nix_cli/workspace/lock.py). A real directory
                  # there is a leftover submodule checkout — never clobber it silently.
                  if [ "$(readlink "${cfg.layout.coreSrc}" 2>/dev/null)" != "${toString cfg.coreSource}" ]; then
                    if [ -e "${cfg.layout.coreSrc}" ] && [ ! -L "${cfg.layout.coreSrc}" ]; then
                      echo "odoo-nix: ${cfg.layout.coreSrc}/ exists but coreSource is set; remove the" >&2
                      echo "          checkout (git submodule deinit / rm -rf) so it can become a symlink." >&2
                    else
                      ln -sfn "${toString cfg.coreSource}" "${cfg.layout.coreSrc}"
                    fi
                  fi
                ''}
                # Check out the git submodules this clone has never had -- a
                # fresh clone's, on its first entry -- scoped to just those
                # paths, so an already-initialized submodule is never touched
                # here even if its checked-out commit differs from what the
                # superproject's index records. That divergent state is exactly
                # what `odoo project update` leaves things in until the new
                # pointers are committed; a blanket `git submodule update` would
                # silently reset it back on every shell entry. Nor is one that
                # was set up and has since been removed or deinitialized brought
                # back: submodules should only ever move via an explicit `odoo
                # project update`. python-devops-nix's lib.sources; skipped in CI
                # mode, where the job checks out what it needs.
                ${ciMode.unlessCi ''
                  ${lib.getExe sources} enter --treeless ${lib.escapeShellArg cfg.layout.coreSrc} "$DEVENV_ROOT" || true
                ''}

                # Symlink the Nix-synthesized odoo.conf into place (read-only store
                # target; odoo-bin -c consumes it, never rewrites it).
                if [ "$(readlink odoo.conf 2>/dev/null)" != "${odooConfFile}" ]; then
                  ln -sfn "${odooConfFile}" odoo.conf
                fi

                # Ensure the filestore + custom-addons dirs exist.
                mkdir -p ${
                  lib.escapeShellArgs (
                    lib.optional (cfg.settings.options.data_dir or null != null) cfg.settings.options.data_dir
                    ++ [ cfg.layout.customDir ]
                  )
                }

                ${lib.optionalString cfg.ide.enable ideSetup}

                ${lib.optionalString (cfg.ide.enable && cfg.ide.languageServer.enable) ''
                  # Symlink the Nix-synthesized odools.toml into place, same as
                  # odoo.conf above.
                  if [ "$(readlink odools.toml 2>/dev/null)" != "${odoolsTomlFile}" ]; then
                    ln -sfn "${odoolsTomlFile}" odools.toml
                  fi
                ''}

                ${lib.optionalString (cfg.ide.enable && cfg.ide.vscodeSettings) ''
                  # Seeded once; a project's own settings are never overwritten.
                  if [ ! -e "$DEVENV_ROOT/.vscode/settings.json" ]; then
                    mkdir -p "$DEVENV_ROOT/.vscode"
                    install -m 644 "${vscodeSettingsFile}" "$DEVENV_ROOT/.vscode/settings.json"
                  fi
                ''}

                ${lib.optionalString (cfg.ide.enable && cfg.ide.languageServer.enable && cfg.ide.vscodeSettings) ''
                  # Prompts VS Code to offer installing Odoo.odoo (the odoo-ls
                  # client). Seeded once, same as settings.json above.
                  if [ ! -e "$DEVENV_ROOT/.vscode/extensions.json" ]; then
                    mkdir -p "$DEVENV_ROOT/.vscode"
                    install -m 644 "${vscodeExtensionsFile}" "$DEVENV_ROOT/.vscode/extensions.json"
                  fi
                ''}

                ${ciMode.banner {
                  inherit (cfg) name;
                  details = "Odoo ${cfg.odooSeries}, http ${toString cfg.ports.http}";
                  interactive = inputs.python-devops-nix.lib.banner.script {
                    inherit pkgs;
                    inherit (shellTools) banner;
                    spec = bannerSpec;
                  };
                }}
              '';

              # odoo-nix's own site-maintenance commands are the `odoo` CLI
              # package above now (db/module/project subcommands), not devenv
              # scripts -- this option remains solely for a consumer's own
              # custom scripts.
              scripts =
                secretsTools.scripts {
                  # setup-backup-access only when remote restores are on.
                  fetch = if cfg.restore.enable then lib.getExe backupFetch else null;
                }
                // cfg.extraScripts;
            };
        })
      ];
  };
}
