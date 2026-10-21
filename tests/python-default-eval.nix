# Evaluation-level assertions over the dev shell's `python` default
# (modules/devenv.nix): a consumer that sets only odooSeries gets that
# series' interpreter from lib/odoo-presets.json, and the container image
# built with it evaluates (its Python version checks pass). A consumer's flake
# is evaluated through lib.mkFlake and only the interpreter's version and the
# image's drvPath are read, so nothing is built. Same `pairs` shape as
# eval.nix; flake.nix turns each into a named check (lib.checks.mk's `eval`).
{
  pkgs,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;

  # `python` deliberately unset.
  consumer =
    series: ocb:
    let
      flake =
        mkFlake
          {
            inputs.self = {
              outPath = ../.;
              inherit inputs;
            };
          }
          {
            debug = true;
            systems = [ system ];
            imports = [ ../modules/flake-module.nix ];
            perSystem.odoo-nix = {
              enable = true;
              name = "acme";
              workspaceRoot = ./fixtures + "/${series}";
              coreSource = ocb;
              odooSeries = series;
              containers.enable = true;
            };
          };
    in
    {
      python = flake.allSystems.${system}.config.odoo-nix.python.pythonVersion;
      image = builtins.isString flake.packages.${system}.container-odoo.drvPath;
    };
in
{
  python-default-18 = {
    expected = {
      python = "3.11";
      image = true;
    };
    actual = consumer "18.0" inputs.ocb-18;
  };
  python-default-19 = {
    expected = {
      python = "3.12";
      image = true;
    };
    actual = consumer "19.0" inputs.ocb-19;
  };
  python-default-20 = {
    expected = {
      python = "3.12";
      image = true;
    };
    actual = consumer "20.0" inputs.ocb-20;
  };
}
