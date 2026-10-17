# The odoo_devguard package: python-devops-nix's devguard core merged with
# odoo-nix's own tree (lib/devguard/odoo_devguard: _product.py and the guards
# that patch Odoo), with a project's settings baked in as
# odoo_devguard/_baked.json. python-devops-nix CONVENTIONS.md, "The core and
# the product's package", has the contract.
#
# DEVELOPMENT ONLY. lib/python.nix grafts the result into the dev and test
# virtualenvs and never into the production one: the guard stops a dev
# environment from reaching production services, so being absent from
# production is the property that matters. checks.odoo-init-<major> checks it.
#
#   import ./lib/devguard.nix { inherit pkgs base; settings = { ... }; }
{
  pkgs,
  # inputs.python-devops-nix.lib
  base,
  # The baked layer: { enabled, guards.<guard>.<key> }, below the
  # `ODOO_DEVGUARD_*` environment and the runtime file, above the defaults
  # (odoo_devguard/_product.py over the core's).
  settings ? { },
}:

base.devguard.mkPackage {
  inherit pkgs settings;
  name = "odoo_devguard";
  src = ./devguard/odoo_devguard;
}
