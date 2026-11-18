# The odoo_devwatch package: odoo-nix's tree (lib/devwatch/odoo_devwatch: the
# autoreload watcher's filter, configured by ODOO_NIX_WATCH_EXCLUDE and
# ODOO_NIX_WATCH_EXCLUDE_IF_COVERED) with python-devops-nix's post-import hook
# (_hook.py) put beside it, as lib.python.mkGraft does for every .pth graft.
#
# DEVELOPMENT ONLY. lib/python.nix grafts it into the dev and test virtualenvs
# and never into the production one: the watcher it filters exists only under
# --dev=reload. With neither variable set it does nothing. The dev shell sets
# both from devenv's watch.exclude and watch.excludeIfCovered
# (modules/devenv.nix); the second is non-empty by default, so the filter is on
# in every dev shell.
#
#   import ./lib/devwatch.nix { inherit pkgs base; }
{
  pkgs,
  # inputs.python-devops-nix.lib
  base,
}:

base.python.mkGraft {
  inherit pkgs;
  name = "odoo_devwatch";
  # A store path of its own, so an unrelated odoo-nix edit does not rebuild
  # every environment.
  src = builtins.path {
    path = ./devwatch/odoo_devwatch;
    name = "odoo-devwatch-src";
    filter = path: _type: baseNameOf path != "__pycache__";
  };
}
