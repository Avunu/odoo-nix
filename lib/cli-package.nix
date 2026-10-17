# The odoo_nix_cli package as the `odoo` CLI ships it, $out/odoo_nix_cli/:
# lib/odoo_nix_cli with two files from python-devops-nix put beside it
# (PLAN.md, design rule 6):
#
#   _hook.py     the post-import hook every graft shares (lib.python.mkGraft),
#                which journald.py patches odoo.netsvc with
#   _backups.py  the backup fetch layer (lib.backups.module), which backups.py
#                lists and downloads remote backups with
#
# lib/cli.nix wraps it; the journald-formatter and backup-layout checks test
# it, so they see the tree the CLI really runs.
#
#   import ./lib/cli-package.nix { inherit pkgs; base = inputs.python-devops-nix.lib; }
{ pkgs, base }:

let
  graft = base.python.mkGraft {
    inherit pkgs;
    name = "odoo_nix_cli";
    src = ./odoo_nix_cli;
  };
in
pkgs.runCommandLocal "odoo-nix-cli-package" { } ''
  mkdir -p $out
  cp -r ${graft}/odoo_nix_cli $out/odoo_nix_cli
  chmod u+w $out/odoo_nix_cli
  cp ${base.backups.module} $out/odoo_nix_cli/_backups.py
''
