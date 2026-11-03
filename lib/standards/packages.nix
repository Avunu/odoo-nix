# The standards' packages, built once for flake.nix and the dev shell
# (modules/devenv.nix) alike (py/odoo_nix_tools/DESIGN.md §5.1):
#
#   tools PYTHON  odoo-nix-tools for PYTHON (lib/standards/package.nix)
#   odooNixTools  the same for pkgs.python3
#   odooNix       the `odoo-nix` command (lib/standards/cli.nix)
#   odooInit      odoo-init, which runs `odoo-nix sync` in-process (lib/init.nix)
#
# `coreRev` is the python-devops-nix input's rev (null for a `path:` input).
{
  pkgs,
  base,
  coreRev ? null,
}:
let
  tools =
    python:
    python.pkgs.callPackage ./package.nix {
      inherit pkgs base coreRev;
    };
  odooNixTools = tools pkgs.python3;
  odooNix = import ./cli.nix {
    inherit pkgs odooNixTools;
    inherit (pkgs) lib;
  };
in
{
  inherit tools odooNixTools odooNix;
  odooInit = import ../init.nix {
    inherit
      pkgs
      base
      odooNixTools
      odooNix
      ;
  };
}
