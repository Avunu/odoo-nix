# The odoo_devguard package (lib/devguard/odoo_devguard) with a project's
# settings baked in as odoo_devguard/_baked.json.
#
# DEVELOPMENT ONLY. lib/python.nix grafts the result into the dev and test
# virtualenvs and never into the production one: the guard stops a dev
# environment from reaching production services, so being absent from
# production is the property that matters. tests/ checks it
# (checks.devguard-not-in-prod).
#
#   import ./lib/devguard.nix { inherit pkgs lib; settings = { ... }; }
{
  pkgs,
  lib,
  # Merged over the package defaults at run time (odoo_devguard/_settings.py);
  # `ODOO_DEVGUARD_*` environment variables win over it.
  settings ? { },
}:

pkgs.runCommand "odoo-devguard" { } ''
  mkdir -p $out
  cp -r ${./devguard/odoo_devguard} $out/odoo_devguard
  chmod -R u+w $out
  find $out -name __pycache__ -prune -exec rm -rf {} +
  cp ${pkgs.writeText "odoo-devguard-baked.json" (builtins.toJSON settings)} $out/odoo_devguard/_baked.json
''
