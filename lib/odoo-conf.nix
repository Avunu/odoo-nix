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
}:

let
  ini = pkgs.formats.ini { };

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
      log_level = odooConf.logLevel;
    }
    # Escape hatch: arbitrary extra [options] keys win last. Values stringified
    # so callers may pass ints/bools.
    // builtins.mapAttrs (_n: v: if builtins.isBool v then (if v then "True" else "False") else toString v) odooConf.extra;

  odooConfFile = ini.generate "odoo.conf" {
    options = optionsBlock;
  };
in
{
  inherit odooConfFile optionsBlock;
}
