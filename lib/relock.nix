# `nix run .#relock [-- UV_ARGS…]` in a project: its relock outside the dev
# shell, the same code as `odoo project relock` (odoo_nix_cli.workspace.relock)
# with the same workspace configuration (lib/cli-scripts.nix). Run from the
# project root.
#
# A flake app, deliberately outside the dev shell's dependency graph: it has to
# evaluate when nothing that reads uv.lock can, which is exactly when it is
# needed (a lock the stale-lock audit refuses, lib/python.nix). So it runs on
# the project's plain interpreter, not the dev environment the `odoo` command
# runs on.
#
#   import ./lib/relock.nix {
#     inherit pkgs base;
#     inherit (cfg) python;
#     inherit (cliScripts) workspaceConfig;
#   }
{
  pkgs,
  base,
  # The project's interpreter (odoo-nix.python). uv locks with it too, as it
  # does in the shell, where it is the one on PATH.
  python,
  # lib/cli-scripts.nix's workspaceConfig.
  workspaceConfig,
}:

let
  env = python.withPackages (ps: [ (import ./cli-module.nix { inherit pkgs base; } ps) ]);
in
pkgs.writeShellApplication {
  name = "odoo-nix-relock";
  text = ''
    export UV_PYTHON="''${UV_PYTHON:-${python.interpreter}}"
    ODOO_NIX_WORKSPACE_CONFIG=${workspaceConfig} exec ${env.interpreter} -I -m odoo_nix_cli.workspace.relock "$@"
  '';
  meta = {
    description = "Re-lock an odoo-nix project without its dev shell (odoo project relock)";
    mainProgram = "odoo-nix-relock";
  };
}
