# The `odoo-nix` command (py/odoo_nix_tools/DESIGN.md §5.1): the package's
# console script behind a wrapper, so the package's Python closure never lands
# on a dev shell's PATH or PYTHONPATH. git and gh are appended to PATH: the
# commands run git everywhere and gh for the repository ones, and a checkout's
# own come first.
{
  lib,
  pkgs,
  odooNixTools,
}:
pkgs.runCommand "odoo-nix-${odooNixTools.version}"
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    meta = {
      description = "odoo-nix's standards tools (odoo-nix sync, profile, config, …)";
      mainProgram = "odoo-nix";
      inherit (odooNixTools.meta) license;
    };
  }
  ''
    makeWrapper ${lib.getExe odooNixTools} "$out/bin/odoo-nix" \
      --suffix PATH : ${
        lib.makeBinPath [
          pkgs.git
          pkgs.gh
        ]
      }
  ''
