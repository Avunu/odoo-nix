# A consumer's `nix run .#relock` (lib/relock.nix, wired in modules/devenv.nix)
# in a project whose lock is stale: tests/fixtures/stale-lock, which the
# stale-lock audit refuses. The app evaluates and the dev shell does not, so
# the relock is reachable exactly when `odoo project relock` is not. The
# consumer's flake is evaluated through lib.mkFlake and only drvPaths are read,
# so nothing is built. Same `pairs` shape as eval.nix; flake.nix turns each
# into a named check (lib.checks.mk's `eval`). tests/relock.sh runs the app.
{
  pkgs,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;

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
          workspaceRoot = ./fixtures/stale-lock;
          coreSource = inputs.ocb-18;
          odooSeries = "18.0";
        };
      };

  evaluates = v: (builtins.tryEval (builtins.seq v true)).success;
  app = flake.apps.${system}.relock;
in
{
  relock-stale-lock = {
    expected = {
      app = true;
      program = true;
      shell = false;
      odoo = false;
    };
    actual = {
      app = app.type == "app";
      program = evaluates (builtins.unsafeDiscardStringContext app.program);
      shell = evaluates flake.devShells.${system}.default.drvPath;
      odoo = evaluates flake.packages.${system}.odooCli.drvPath;
    };
  };
}
