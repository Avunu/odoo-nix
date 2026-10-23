# odoo.conf's INI dialect, shared by the dev shell's renderer (lib/odoo-conf.nix)
# and the NixOS module's `settings` (modules/nixos.nix).
#
# A pkgs.formats.ini whose values render the way Odoo's config parser reads
# them:
#   - bools as Odoo's literal "True"/"False". pkgs.formats.ini's default would
#     write "true"/"false", which Odoo's parser does not coerce back to a
#     boolean (a string "false" is truthy).
#   - lists as one comma-separated value (addons_path, server_wide_modules,
#     log_handler, ...), never as duplicate keys: ConfigParser keeps the last
#     duplicate only.
#   - ints and floats as their decimal text; Odoo casts the string itself.
#   - null as the key's absence (see `generate`), so a computed key can be
#     unset. "No value" for a string option is the missing key, never a
#     literal "False": Odoo <= 18.0 coerced that to a falsy bool, 19.0 skips
#     the key with a warning.
#
# Keys render as `key=value`, as pkgs.formats.ini always has; ConfigParser
# reads that and `key = value` alike.
{ pkgs, lib }:

let
  toIniValue =
    v:
    if builtins.isBool v then
      (if v then "True" else "False")
    else if builtins.isList v then
      lib.concatMapStringsSep "," toIniValue v
    else
      lib.generators.mkValueStringDefault { } v;

  format = pkgs.formats.ini {
    listsAsDuplicateKeys = false;
    listToValue = toIniValue;
    mkKeyValue = lib.generators.mkKeyValueDefault { mkValueString = toIniValue; } "=";
  };
in
{
  inherit toIniValue;

  # `type` is attrs of sections, a section attrs of INI atoms: null, bool,
  # int, float, string, or a non-empty list of those.
  inherit (format) type;
  atomType = format.lib.types.atom;

  # Drops null keys, then renders through pkgs.formats.ini (pkgs.writeText:
  # the store path follows the name and the text alone).
  generate =
    name: sections:
    format.generate name (builtins.mapAttrs (_: lib.filterAttrs (_: v: v != null)) sections);
}
