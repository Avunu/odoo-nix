{
  description = "@PROJECT_NAME@ — Odoo (OCB) + OCA project (odoo-nix)";

  inputs = {
    # src/odoo + src/external/* are git submodules; expose their contents to the
    # flake source tree so the Nix engine can derive addons_path from them.
    self.submodules = true;
    odoo-nix.url = "github:Avunu/odoo-nix";
    # flake-parts resolves perSystem `pkgs` from an input literally named `nixpkgs`.
    nixpkgs.follows = "odoo-nix/nixpkgs";
  };

  nixConfig = {
    extra-substituters = [ "https://devenv.cachix.org" ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  # This flake exposes:
  #   packages.<system>.default    — the deployable Odoo (builtOdoo)
  #   packages.<system>.odooConf   — the synthesized odoo.conf
  #
  # Deployment servers import the NixOS module directly from odoo-nix:
  #   imports = [ odoo-nix.nixosModules.default ];
  #   services.odoo-nix.package = projectFlake.packages.x86_64-linux.default;

  outputs =
    { self, odoo-nix, ... }@inputs:
    odoo-nix.lib.mkFlake { inherit inputs; } (
      { ... }:
      {
        imports = [ odoo-nix.flakeModules.default ];

        systems = [
          "aarch64-darwin"
          "aarch64-linux"
          "x86_64-darwin"
          "x86_64-linux"
        ];

        perSystem =
          { pkgs, ... }:
          {
            odoo-nix = {
              enable = true;
              projectName = "@PROJECT_NAME@";
              workspaceRoot = ./.;
              odooSeries = "@SERIES@";
              python = pkgs.@PYTHON@;

              odooConf.dbName = "@DB_NAME@";

              # Build production OCI images with `nix build .#builtOdoo` and the
              # container outputs once enabled:
              # containers.enable = true;
            };
          };
      }
    );
}
