# OCI container image builder for Odoo (OCB + OCA) deployments.
#
# A flake-parts perSystem module: when `odoo-nix.containers.enable` is set it
# builds a single all-in-one `odoo` image from the CLI-wrapped production
# package (config.packages.default, defined by devenv.nix) -- `docker exec` a
# running container's `odoo db backup`/`restore`/`migrate` work the same way
# they do outside a container. The entrypoint synthesizes
# /etc/odoo/odoo.conf at startup from env-var defaults, then merges secrets from
# mounted /secrets/* files (printf-based INI; ConfigParser last-wins).
#
# Volume contract:
#   /var/lib/odoo/data   persistent filestore
#   /secrets/db_password, /secrets/admin_passwd, /secrets/*.conf   secrets
# PostgreSQL is external.
#
# The image carries the OCI labels and a HEALTHCHECK on /web/health
# (python-devops-nix CONVENTIONS.md, Containers). Since 2.0.0 it is named
# <registry>/<name>/odoo (1.x's <name>-odoo was the default) and runs as
# uid/gid 1000 (containers.nonRoot; root was the default).
{ inputs, ... }:
{
  # Options live in ./devenv.nix (odoo-nix.containers.*). This module only adds
  # config, gated on enable + containers.enable.
  config.perSystem =
    {
      config,
      pkgs,
      lib,
      ...
    }:
    let
      cfg = config.odoo-nix;
      odooPkg = config.packages.default or null;

      # BLAS and OpenMP pools capped at one thread, as in the dev shell and
      # services.odoo-nix (python-devops-nix lib.python.threadCaps).
      inherit (inputs.python-devops-nix.lib.python) threadCaps;

      # The image is <name>/<role>, the same rule as frappe-nix's
      # modules/containers.nix. containers.registry prefixes it:
      # "ghcr.io/avunu" (or "ghcr.io/avunu/") names it ghcr.io/avunu/<name>/odoo;
      # "" leaves it bare.
      inherit (cfg.containers) nonRoot;
      registry = lib.removeSuffix "/" cfg.containers.registry;
      imageName =
        role: if registry == "" then "${cfg.name}/${role}" else "${registry}/${cfg.name}/${role}";

      # The user the image runs as with containers.nonRoot (the default since
      # 2.0.0); root otherwise. Fixed, so a volume or a bind mount can be owned to match
      # before the first start; the same uid as frappe-nix's images.
      uid = 1000;
      gid = 1000;
      home = "/var/lib/odoo";
      user = if nonRoot then "${toString uid}:${toString gid}" else "0:0";

      # /etc/passwd and /etc/group, so the uid has a name and a home (Python's
      # getpass, wkhtmltopdf's fontconfig cache).
      containerUsers = pkgs.runCommand "odoo-nix-container-users" { } ''
        mkdir -p $out/etc
        cat > $out/etc/passwd <<'EOF'
        root:x:0:0:root:/root:/bin/sh
        odoo:x:${toString uid}:${toString gid}:odoo:${home}:/bin/sh
        nobody:x:65534:65534:nobody:/var/empty:/bin/false
        EOF
        cat > $out/etc/group <<'EOF'
        root:x:0:
        odoo:x:${toString gid}:
        nogroup:x:65534:
        EOF
      '';

      # org.opencontainers.image.* labels. revision is odoo-nix's own commit
      # when the project's flake has it as the `odoo-nix` input, as the
      # scaffold does. containers.labels overrides any of them, for a project
      # that labels its image with its own repository and version.
      version = lib.trim (builtins.readFile ../version.txt);
      revision = (inputs.odoo-nix or { }).rev or null;
      labels = {
        "org.opencontainers.image.title" = imageName "odoo";
        "org.opencontainers.image.source" = "https://github.com/Avunu/odoo-nix";
        "org.opencontainers.image.version" = version;
        "org.opencontainers.image.licenses" = "MIT";
      }
      // lib.optionalAttrs (revision != null) {
        "org.opencontainers.image.revision" = revision;
      }
      // cfg.containers.labels;

      # Odoo's readiness endpoint, needing no database. Bash's /dev/tcp, since
      # the image has no curl; the port is the entrypoint's.
      healthProbe = pkgs.writeShellScript "odoo-healthcheck" ''
        port="''${ODOO_NIX_HTTP_PORT:-''${ODOO_HTTP_PORT:-8069}}"
        exec 3<>"/dev/tcp/127.0.0.1/$port" || exit 1
        printf 'GET /web/health HTTP/1.0\r\nHost: localhost\r\n\r\n' >&3
        IFS= read -r -t 8 status <&3 || exit 1
        [[ $status == "HTTP/1."?" 200 "* ]] || { echo "odoo-healthcheck: $status" >&2; exit 1; }
      '';
      second = 1000000000;

      runtimeDeps = with pkgs; [
        bashInteractive
        coreutils
        gnused
        gnugrep
        findutils
        cacert
        jq
        wkhtmltopdf
        rtlcss
        postgresql # psql client
        # fonts for PDF rendering
        liberation_ttf
        dejavu_fonts
        fontconfig
        freetype
        # native libs
        libxml2
        libxslt
        libsass
        openldap
        cyrus_sasl
        openssl
        libffi
        zlib
      ];

      libraryPath = lib.makeLibraryPath runtimeDeps;
      addonsPath = if odooPkg != null then odooPkg.passthru.addonsPath "${odooPkg}" else "";

      # The entrypoint's variables, ODOO_NIX_<name>; ODOO_<name> through 1.x.
      removedEnv = [
        "DB_HOST"
        "DB_PORT"
        "DB_USER"
        "DB_NAME"
        "HTTP_PORT"
        "GEVENT_PORT"
        "WORKERS"
        "MAX_CRON_THREADS"
        "PROXY_MODE"
        "LIST_DB"
        "WITHOUT_DEMO"
        "LOG_LEVEL"
        "LOG_HANDLER"
        "LOG_DB"
        "LOG_DB_LEVEL"
      ];

      entrypoint = pkgs.writeShellScript "odoo-container-entrypoint" ''
        set -euo pipefail
        CONF=/etc/odoo/odoo.conf

        # Every variable this entrypoint reads is ODOO_NIX_* (python-devops-nix
        # CONVENTIONS.md, Tool-owned variables). The old ODOO_* names, read
        # through 1.x, refuse to start since 2.0.0: ignored, ODOO_DB_HOST
        # would quietly become the default host.
        _old_set=0
        for _new in ${lib.concatStringsSep " " (map (v: "ODOO_NIX_${v}") removedEnv)}; do
          _old="ODOO_''${_new#ODOO_NIX_}"
          if [ -n "''${!_old+x}" ]; then
            echo "odoo-nix: \$$_old is not read since odoo-nix 2.0.0; set \$$_new instead." >&2
            _old_set=1
          fi
        done
        if [ "$_old_set" = 1 ]; then
          exit 64
        fi

        mkdir -p /etc/odoo /var/lib/odoo/data

        {
          echo "[options]"
          echo "addons_path = ${addonsPath}"
          echo "data_dir = /var/lib/odoo/data"
          echo "db_host = ''${ODOO_NIX_DB_HOST:-db}"
          echo "db_port = ''${ODOO_NIX_DB_PORT:-5432}"
          echo "db_user = ''${ODOO_NIX_DB_USER:-odoo}"
          echo "http_interface = 0.0.0.0"
          echo "http_port = ''${ODOO_NIX_HTTP_PORT:-8069}"
          echo "gevent_port = ''${ODOO_NIX_GEVENT_PORT:-8072}"
          echo "workers = ''${ODOO_NIX_WORKERS:-2}"
          echo "max_cron_threads = ''${ODOO_NIX_MAX_CRON_THREADS:-2}"
          echo "proxy_mode = ''${ODOO_NIX_PROXY_MODE:-True}"
          echo "list_db = ''${ODOO_NIX_LIST_DB:-False}"
          echo "without_demo = ''${ODOO_NIX_WITHOUT_DEMO:-False}"
          echo "log_level = ''${ODOO_NIX_LOG_LEVEL:-info}"
          [ -n "''${ODOO_NIX_LOG_HANDLER:-}" ] && echo "log_handler = ''${ODOO_NIX_LOG_HANDLER}"
          # log_db is a database name ("%d" = the request's database); a
          # literal False would be skipped with a warning on 19.0, so it is
          # simply left out when unset.
          [ -n "''${ODOO_NIX_LOG_DB:-}" ] && echo "log_db = ''${ODOO_NIX_LOG_DB}"
          echo "log_db_level = ''${ODOO_NIX_LOG_DB_LEVEL:-warning}"
          [ -n "''${ODOO_NIX_DB_NAME:-}" ] && echo "db_name = ''${ODOO_NIX_DB_NAME}"
          [ -n "''${ODOO_NIX_DB_NAME:-}" ] && echo "dbfilter = ^''${ODOO_NIX_DB_NAME}$"
        } > "$CONF"

        [ -f /secrets/db_password ]  && printf 'db_password = %s\n'  "$(cat /secrets/db_password)"  >> "$CONF"
        [ -f /secrets/admin_passwd ] && printf 'admin_passwd = %s\n' "$(cat /secrets/admin_passwd)" >> "$CONF"
        for f in /secrets/*.conf; do [ -f "$f" ] && cat "$f" >> "$CONF"; done

        chmod 0600 "$CONF"
        export ODOO_RC="$CONF"
        exec "$@"
      '';

      odooImage =
        let
          config = {
            User = user;
            Labels = labels;
            Healthcheck = {
              Test = [
                "CMD"
                "${healthProbe}"
              ];
              Interval = 30 * second;
              Timeout = 10 * second;
              # The first start of a big database loads its registry first.
              StartPeriod = 120 * second;
              Retries = 3;
            };
            Entrypoint = [ "${entrypoint}" ];
            Cmd = [
              "${odooPkg}/bin/odoo"
              "-c"
              "/etc/odoo/odoo.conf"
            ];
            WorkingDir = "/var/lib/odoo";
            ExposedPorts = {
              "8069/tcp" = { };
              "8072/tcp" = { };
            };
            Env = [
              "ODOO_RC=/etc/odoo/odoo.conf"
              "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
              "LANG=C.UTF-8"
              "LD_LIBRARY_PATH=${libraryPath}"
            ]
            # HOME only for the odoo user; root keeps the runtime's default.
            ++ lib.optional nonRoot "HOME=${home}"
            ++ (lib.mapAttrsToList (name: value: "${name}=${value}") threadCaps);
            Volumes = {
              "/var/lib/odoo/data" = { };
            };
          };
        in
        pkgs.dockerTools.buildLayeredImage {
          inherit config;
          name = imageName "odoo";
          tag = "latest";
          contents = [
            odooPkg
            containerUsers
          ]
          ++ runtimeDeps;
          # What the user writes, owned by it with nonRoot: the config the
          # entrypoint renders, the filestore (a fresh named volume takes this
          # ownership) and /tmp.
          enableFakechroot = true;
          fakeRootCommands = ''
            mkdir -p /tmp /etc/odoo /var/lib/odoo/data
            chmod 1777 /tmp
            ${lib.optionalString nonRoot "chown -R ${user} /etc/odoo /var/lib/odoo"}
          '';
          # The image config, readable without a build (tests/containers-eval.nix).
          passthru.imageConfig = config;
        };
    in
    lib.mkIf (cfg.enable && cfg.containers.enable) {
      packages.container-odoo = odooImage;
    };
}
