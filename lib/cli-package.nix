# The odoo_nix_cli package as the `odoo` CLI ships it, $out/odoo_nix_cli/:
# lib/odoo_nix_cli with python-devops-nix's modules put beside it
# (python-devops-nix docs/library.md, design rule 6):
#
#   _backups.py   the backup fetch layer (lib.backups.module), which
#                 backups.py lists and downloads remote backups with
#   _migrate/     the migrate-on-deploy flow (lib.nixos.migrate.modules:
#                 migrate.py and the journald.py it imports), whose snapshot
#                 steps `odoo db migrate` takes (commands/db.py)
#
# Journald output is not here: it is odoo_journald, grafted into the Python
# environment the CLI imports Odoo from (lib/journald.nix).
#
# lib/cli.nix wraps it; the backup-layout check tests it, so it sees the tree
# the CLI really runs.
#
#   import ./lib/cli-package.nix { inherit pkgs; base = inputs.python-devops-nix.lib; }
{ pkgs, base }:

base.python.mergeTrees {
  inherit pkgs;
  name = "odoo_nix_cli";
  what = "lib/cli-package.nix";
  trees = [
    {
      label = "lib/odoo_nix_cli";
      path = ./odoo_nix_cli;
    }
  ];
  files = {
    "_backups.py" = base.backups.module;
    "_migrate/__init__.py" = pkgs.writeText "odoo-nix-migrate-init.py" ''
      """python-devops-nix's migrate flow (lib.nixos.migrate.modules), vendored."""
    '';
    "_migrate/migrate.py" = "${base.nixos.migrate.modules}/migrate.py";
    "_migrate/journald.py" = "${base.nixos.migrate.modules}/journald.py";
  };
}
