{
  description = "Reusable Nix infrastructure for Odoo (OCB) + OCA projects";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    devenv.url = "github:cachix/devenv";
    nix2container = {
      url = "github:nlewo/nix2container";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  nixConfig = {
    extra-substituters = [
      "https://devenv.cachix.org"
    ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  outputs =
    { self, nixpkgs, flake-parts, ... }@inputs:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));
      odooInit = pkgs: import ./lib/init.nix { inherit pkgs; };
    in
    {
      flakeModules.default = ./modules/flake-module.nix;

      nixosModules.default = ./modules/nixos.nix;

      lib = {
        # Wrapper around flake-parts.lib.mkFlake that merges odoo-nix's own inputs
        # with the consumer's, so a consuming flake only declares odoo-nix +
        # nixpkgs.follows. Mirrors frappe-nix.lib.mkFlake.
        mkFlake =
          {
            inputs ? { },
            ...
          }@consumerArgs:
          config:
          flake-parts.lib.mkFlake {
            inputs = self.inputs // inputs;
          } config;

        # Composable Python package overrides for native-build packages.
        overrides = import ./lib/overrides.nix;

        # The addons_path synthesis core, exposed for testing / advanced use.
        addons = import ./lib/addons.nix;
      };

      # `nix run github:<owner>/odoo-nix` scaffolds a new Odoo + OCA project.
      packages = forAllSystems (pkgs: rec {
        odoo-init = odooInit pkgs;
        default = odoo-init;
      });

      apps = forAllSystems (pkgs: let
        program = "${odooInit pkgs}/bin/odoo-init";
        app = {
          type = "app";
          inherit program;
          meta.description = "Scaffold a new odoo-nix project (Odoo OCB + OCA)";
        };
      in {
        default = app;
        odoo-init = app;
      });
    };
}
