# odoo_nix_cli (lib/cli-package.nix) as a Python module of PS's interpreter,
# for a tool that runs it as `python -I -m`: not as a console script, whose
# nixpkgs wrapper would put its own interpreter and bin/ on the PATH of every
# git and uv it starts (frappe-nix#110), and isolated, because the tool runs
# inside projects whose directory or dev-shell PYTHONPATH must not shadow the
# package. odoo-init (lib/init.nix) and the relock app (lib/relock.nix).
#
#   python.withPackages (ps: [ (import ./cli-module.nix { inherit pkgs base; } ps) ])
{ pkgs, base }:
ps:
ps.toPythonModule (
  pkgs.runCommandLocal "odoo-nix-cli-module" { } ''
    mkdir -p $out/${ps.python.sitePackages}
    cp -r ${
      import ./cli-package.nix { inherit pkgs base; }
    }/odoo_nix_cli $out/${ps.python.sitePackages}/
  ''
)
