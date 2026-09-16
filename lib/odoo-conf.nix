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
  # section (through 18.0 out of `odoo.tools.config.misc`, where Odoo's parser
  # keeps unknown sections verbatim; on 19.0 by re-reading the loaded file).
  # Values are stringified like the [options] block.
  extraSections ? { },
}:

let
  ini = pkgs.formats.ini { };

  # Odoo's INI parser coerces "True"/"False" back to booleans but never casts
  # numbers, so everything is emitted as a string and read as one.
  toIniValue = v: if builtins.isBool v then (if v then "True" else "False") else toString v;
  toIniSection = builtins.mapAttrs (_n: toIniValue);

  # "No value" for a string option is the key's absence, never the literal
  # "False": Odoo <= 18.0 coerced that to a falsy bool, 19.0 skips the key
  # with a warning. Both then fall back to the option's default -- for db_host
  # / db_password that is the unix socket / no password, which is what the
  # empty value meant all along.
  unset = v: v == null || v == "" || v == "False";

  optionsBlock =
    {
      # --- database connection ---
      db_port = toString odooConf.dbPort;
      db_user = odooConf.dbUser;
    }
    // lib.optionalAttrs (!unset odooConf.dbHost) {
      db_host = odooConf.dbHost;
    }
    // lib.optionalAttrs (!unset odooConf.dbPassword) {
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
      http_interface = odooConf.httpInterface;
      http_port = toString odooConf.httpPort;
      gevent_port = toString odooConf.geventPort;
      workers = toString odooConf.workers;
      log_level = odooConf.logging.level;
      log_db_level = odooConf.logging.dbLevel;
      server_wide_modules = lib.concatStringsSep "," serverWideModules;
    }
    # log_db is a database *name*; "%d" is Odoo's own spelling for "the
    # current request's database" (netsvc.PostgreSQLHandler), so that is what
    # `true` renders as. Absent when off: 18.0's default is False, 19.0's is
    # "" and would warn about a literal False.
    // lib.optionalAttrs (odooConf.logging.db != false) {
      log_db = if odooConf.logging.db == true then "%d" else odooConf.logging.db;
    }
    // lib.optionalAttrs (odooConf.logging.handlers != [ ]) {
      log_handler = lib.concatStringsSep "," odooConf.logging.handlers;
    }
    // lib.optionalAttrs (odooConf.logging.file != null) {
      logfile = odooConf.logging.file;
    }
    # "True", not "all": 18.0 only ever tests the option's truthiness, and
    # 19.0 turned it into a boolean that warns about anything else.
    // lib.optionalAttrs odooConf.withoutDemo {
      without_demo = "True";
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
