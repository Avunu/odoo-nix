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
  # A store path, not a path literal: mkPackage names `src` in the build
  # script ("the product's tree (${toString src})"), and toString of a path
  # literal is the path inside the flake's source with no string context, so
  # the derivation referenced a store path it did not depend on (Nix's
  # "without a proper context" warning). __pycache__ is left out, as
  # mkPackage's own copy of a path literal does.
  src = builtins.path {
    path = ./devguard/odoo_devguard;
    name = "odoo-devguard-src";
    filter = path: _type: baseNameOf path != "__pycache__";
  };
}
