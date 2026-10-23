# The odoo_journald package: odoo-nix's tree (lib/journald/odoo_journald,
# who the tenant is and where Odoo is patched) with python-devops-nix's
# journald core (_journald.py) and post-import hook (_hook.py) put beside it
# (lib.journald.mkGraft; python-devops-nix docs/conventions.md, Journald
# enablement).
#
# lib/python.nix grafts it into every environment it builds, the production
# one included: it is inert unless stderr is the journal (python-devops-nix
# docs/library.md, design rule 7 names the journald core as one of the things
# that may reach production).
#
#   import ./lib/journald.nix { inherit pkgs base; }
{
  pkgs,
  # inputs.python-devops-nix.lib
  base,
}:

base.journald.mkGraft {
  inherit pkgs;
  name = "odoo_journald";
  # A store path of its own, so an unrelated odoo-nix edit does not rebuild
  # every environment.
  src = builtins.path {
    path = ./journald/odoo_journald;
    name = "odoo-journald-src";
    filter = path: _type: baseNameOf path != "__pycache__";
  };
}
