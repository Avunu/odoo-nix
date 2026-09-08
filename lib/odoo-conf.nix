# odoo.conf (INI) synthesis from declarative Nix options + the derived addons_path.
#
# Produces a read-only /nix/store odoo.conf that the dev shell symlinks into
# place (./odoo.conf) and `odoo-bin -c odoo.conf` consumes. The single
# synthesized value that matters most is `addons_path` (from lib/addons.nix).
#
# Booleans are emitted as Odoo's literal "True"/"False" strings; everything is
# stringified so pkgs.formats.ini never sees a raw bool/int (which it would
# render lowercase, breaking Odoo's parser).
#
# Usage:
#   import ./lib/odoo-conf.nix { inherit pkgs lib; odooConf = cfg.odooConf;
#                                addonsPath = addons.addonsPath; }

{
  pkgs,
  lib,
  odooConf,
  addonsPath,
  # Modules imported at server start, before any registry is built. "base" and
  # "web" are always loaded by Odoo; they are listed explicitly because setting
  # the key at all replaces Odoo's own default.
  serverWideModules ? [
    "base"
    "web"
  ],
  # Extra INI sections beside [options], for modules that read their own
  # section out of `odoo.tools.config.misc` (Odoo's parser keeps unknown
  # sections verbatim). Values are stringified like the [options] block.
  extraSections ? { },
}:

let
  ini = pkgs.formats.ini { };

  # Odoo's INI parser coerces "True"/"False" back to booleans but never casts
  # numbers, so everything is emitted as a string and read as one.
  toIniValue = v: if builtins.isBool v then (if v then "True" else "False") else toString v;
  toIniSection = builtins.mapAttrs (_n: toIniValue);

  optionsBlock =
    {
      # --- database connection ---
      db_host = odooConf.dbHost;
      db_port = toString odooConf.dbPort;
      db_user = odooConf.dbUser;
      db_password = odooConf.dbPassword;
    }
    // lib.optionalAttrs (odooConf.dbName != null) {
      db_name = odooConf.dbName;
    }
    // {
      # --- storage + the synthesized addons routing ---
      data_dir = odooConf.dataDir;
      addons_path = addonsPath;

      # --- runtime ---
      admin_passwd = odooConf.adminPasswd;
      http_port = toString odooConf.httpPort;
      gevent_port = toString odooConf.geventPort;
      workers = toString odooConf.workers;
      log_level = odooConf.logging.level;
      log_db = toIniValue odooConf.logging.db;
      log_db_level = odooConf.logging.dbLevel;
      server_wide_modules = lib.concatStringsSep "," serverWideModules;
    }
    // lib.optionalAttrs (odooConf.logging.handlers != [ ]) {
      log_handler = lib.concatStringsSep "," odooConf.logging.handlers;
    }
    // lib.optionalAttrs (odooConf.logging.file != null) {
      logfile = odooConf.logging.file;
    }
    // lib.optionalAttrs odooConf.withoutDemo {
      without_demo = "all";
    }
    # Escape hatch: arbitrary extra [options] keys win last. Values stringified
    # so callers may pass ints/bools.
    // toIniSection odooConf.extra;

  odooConfFile = ini.generate "odoo.conf" (
    {
      options = optionsBlock;
    }
    // builtins.mapAttrs (_n: toIniSection) extraSections
  );
in
{
  inherit odooConfFile optionsBlock;
}
