# Evaluation-level assertions over the dev shell's restore options
# (modules/devenv.nix, odoo-nix.restore.*): what reaches the `odoo` CLI's
# environment, and the old `restore.attachments` read as `restore.files`. A
# consumer's flake is evaluated through lib.mkFlake and only the shell's env
# is read, so nothing is built. Same `pairs` shape as eval.nix; flake.nix turns
# each into a named mkEvalCheck.
{
  pkgs,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;

  restoreEnv =
    restore:
    let
      env =
        (mkFlake
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
              workspaceRoot = ./fixtures/19.0;
              coreSource = inputs.ocb-19;
              odooSeries = "19.0";
              python = pkgs.python312;
              inherit restore;
            };
          }
        ).allSystems.${system}.config.devenv.shells.default.env;
    in
    {
      inherit (env)
        ODOO_NIX_RESTORE_FILES
        ODOO_NIX_RESTORE_MIGRATE
        ODOO_NIX_RESTORE_NEUTRALIZE
        ODOO_NIX_RESTORE_REQUIRE_DEVGUARD
        ;
    };
in
{
  # Migrate after restore, neutralise and refuse without devguard: on.
  # Mirroring object-store files: off.
  restore-defaults = {
    expected = {
      ODOO_NIX_RESTORE_FILES = "0";
      ODOO_NIX_RESTORE_MIGRATE = "1";
      ODOO_NIX_RESTORE_NEUTRALIZE = "1";
      ODOO_NIX_RESTORE_REQUIRE_DEVGUARD = "1";
    };
    actual = restoreEnv { };
  };
  restore-options = {
    expected = {
      ODOO_NIX_RESTORE_FILES = "1";
      ODOO_NIX_RESTORE_MIGRATE = "0";
      ODOO_NIX_RESTORE_NEUTRALIZE = "0";
      ODOO_NIX_RESTORE_REQUIRE_DEVGUARD = "0";
    };
    actual = restoreEnv {
      files = true;
      migrate = false;
      neutralize = false;
      requireDevguard = false;
    };
  };
  # The old name, for one release: "mirror" is files = true.
  restore-attachments-alias = {
    expected = [
      "1"
      "0"
    ];
    actual = [
      (restoreEnv { attachments = "mirror"; }).ODOO_NIX_RESTORE_FILES
      (restoreEnv { attachments = "none"; }).ODOO_NIX_RESTORE_FILES
    ];
  };
}
