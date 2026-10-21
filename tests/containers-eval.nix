# Evaluation-level assertions over the flake-parts module's container image
# (modules/containers.nix): the name the image is built under, with and
# without containers.registry. A consumer's flake is evaluated through
# lib.mkFlake and only the image's imageName is read, so nothing is built.
# Same `pairs` shape as eval.nix; flake.nix turns each into a named
# check (lib.checks.mk's `eval`).
{
  pkgs,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;

  imageName =
    registry:
    (mkFlake
      {
        inputs.self = {
          outPath = ../.;
          inherit inputs;
        };
      }
      {
        systems = [ system ];
        imports = [ ../modules/flake-module.nix ];
        perSystem.odoo-nix = {
          enable = true;
          name = "acme";
          workspaceRoot = ./fixtures/19.0;
          coreSource = inputs.ocb-19;
          odooSeries = "19.0";
          python = pkgs.python312;
          containers = {
            enable = true;
            inherit registry;
          };
        };
      }
    ).packages.${system}.container-odoo.imageName;
in
{
  container-name = {
    expected = "acme-odoo";
    actual = imageName "";
  };
  container-name-registry = {
    expected = "ghcr.io/avunu/acme-odoo";
    actual = imageName "ghcr.io/avunu";
  };
  # A trailing slash is the separator already: not doubled.
  container-name-registry-slash = {
    expected = "ghcr.io/avunu/acme-odoo";
    actual = imageName "ghcr.io/avunu/";
  };
}
