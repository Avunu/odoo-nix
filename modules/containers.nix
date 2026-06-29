# OCI container image builder for Odoo (OCB + OCA) deployments.
#
# A flake-parts perSystem module: when `odoo-nix.containers.enable` is set it
# builds a single all-in-one `odoo` image from the assembled builtOdoo package
# (config.packages.builtOdoo, defined by devenv.nix). The entrypoint synthesizes
# /etc/odoo/odoo.conf at startup from env-var defaults, then merges secrets from
# mounted /secrets/* files (printf-based INI; ConfigParser last-wins).
#
# Volume contract:
#   /var/lib/odoo/data   persistent filestore
#   /secrets/db_password, /secrets/admin_passwd, /secrets/*.conf   secrets
# PostgreSQL is external.
{
  lib,
  flake-parts-lib,
  ...
}:
let
  inherit (flake-parts-lib) mkPerSystemOption;
in
{
  # Options live in ./devenv.nix (odoo-nix.containers.*). This module only adds
  # config, gated on enable + containers.enable.
  config.perSystem =
    { config, pkgs, lib, ... }:
    let
      cfg = config.odoo-nix;
      builtOdoo = config.packages.builtOdoo or null;

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
      addonsPath = if builtOdoo != null then builtOdoo.passthru.addonsPath "${builtOdoo}" else "";

      entrypoint = pkgs.writeShellScript "odoo-container-entrypoint" ''
        set -euo pipefail
        CONF=/etc/odoo/odoo.conf
        mkdir -p /etc/odoo /var/lib/odoo/data

        {
          echo "[options]"
          echo "addons_path = ${addonsPath}"
          echo "data_dir = /var/lib/odoo/data"
          echo "db_host = ''${ODOO_DB_HOST:-db}"
          echo "db_port = ''${ODOO_DB_PORT:-5432}"
          echo "db_user = ''${ODOO_DB_USER:-odoo}"
          echo "http_interface = 0.0.0.0"
          echo "http_port = ''${ODOO_HTTP_PORT:-8069}"
          echo "gevent_port = ''${ODOO_GEVENT_PORT:-8072}"
          echo "workers = ''${ODOO_WORKERS:-2}"
          echo "max_cron_threads = ''${ODOO_MAX_CRON_THREADS:-2}"
          echo "proxy_mode = ''${ODOO_PROXY_MODE:-True}"
          echo "list_db = ''${ODOO_LIST_DB:-False}"
          [ -n "''${ODOO_DB_NAME:-}" ] && echo "db_name = ''${ODOO_DB_NAME}"
          [ -n "''${ODOO_DB_NAME:-}" ] && echo "dbfilter = ^''${ODOO_DB_NAME}$"
        } > "$CONF"

        [ -f /secrets/db_password ]  && printf 'db_password = %s\n'  "$(cat /secrets/db_password)"  >> "$CONF"
        [ -f /secrets/admin_passwd ] && printf 'admin_passwd = %s\n' "$(cat /secrets/admin_passwd)" >> "$CONF"
        for f in /secrets/*.conf; do [ -f "$f" ] && cat "$f" >> "$CONF"; done

        chmod 0600 "$CONF"
        export ODOO_RC="$CONF"
        exec "$@"
      '';

      odooImage = pkgs.dockerTools.buildLayeredImage {
        name = "${cfg.registry or ""}${cfg.projectName}-odoo";
        tag = "latest";
        contents = [ builtOdoo ] ++ runtimeDeps;
        config = {
          Entrypoint = [ "${entrypoint}" ];
          Cmd = [ "${builtOdoo}/bin/odoo" "-c" "/etc/odoo/odoo.conf" ];
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
          ];
          Volumes = {
            "/var/lib/odoo/data" = { };
          };
        };
      };
    in
    lib.mkIf (cfg.enable && cfg.containers.enable) {
      packages.container-odoo = odooImage;
    };
}
