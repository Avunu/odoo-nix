# Addons mode (modules/devenv.nix `addons`, `externalSources`) over
# tests/fixtures/addons-repo, a repository of two addons whose uv project is
# in nix/, with tests/fixtures/external-gamma as its one external source: the
# layout it derives, addons_path, the
# shell's environment, and that its environments and `nix run .#relock`
# evaluate. The consumer's flake is
# evaluated through lib.mkFlake and only drvPaths are read, so nothing is
# built. Same `pairs` shape as eval.nix.
{
  pkgs,
  lib,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;

  gamma = ./fixtures/external-gamma;
  ocb = inputs.ocb-18;

  perSystem =
    odoo-nix:
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
          name = "acme-addons";
          workspaceRoot = ./fixtures/addons-repo;
          odooSeries = "18.0";
          addons.enable = true;
          coreSource = ocb;
          externalSources = [
            {
              name = "gamma";
              src = gamma;
            }
          ];
        }
        // odoo-nix;
      }
    ).allSystems.${system};

  inherit (perSystem { }) config;
  shell = config.devenv.shells.default;
  evaluates = v: (builtins.tryEval (builtins.seq v true)).success;
in
{
  addons-mode-layout = {
    expected = {
      coreSrc = ".odoo-nix/odoo";
      externalDir = ".odoo-nix/modules";
      customDir = ".";
      extraAddons = [ ];
    };
    actual = config.odoo-nix.layout;
  };

  addons-mode-addons-path = {
    expected = "${ocb}/odoo/addons,${ocb}/addons,${toString gamma},./.";
    actual = config.odoo-nix.settings.options.addons_path;
  };

  # `nix run .#relock` evaluates where the shell would not (no lock yet):
  # its configuration (lock directory, install set, the links) is
  # tests/test_workspace.py's AddonsModeTest.
  addons-mode-relock = {
    expected = true;
    actual = evaluates (builtins.unsafeDiscardStringContext config.apps.relock.program);
  };

  addons-mode-shell = {
    expected = {
      evaluates = true;
      localAddons = ".";
      linksGamma = true;
    };
    actual = {
      # The shell itself reads the working directory (devenv), which pure
      # evaluation has none of: its Python environments and builtOdoo are
      # what addons mode changes.
      evaluates = lib.all evaluates [
        config.packages.odooDevEnv.drvPath
        config.packages.odooPythonEnv.drvPath
        config.packages.builtOdoo.drvPath
      ];
      localAddons = shell.env.ODOO_NIX_LOCAL_ADDONS;
      linksGamma =
        let
          plain = builtins.unsafeDiscardStringContext;
        in
        lib.hasInfix (plain ''ln -sfn "${toString gamma}" "$_ext/gamma"'') (plain shell.enterShell);
    };
  };

  # A project keeps the defaults it always had: no lock directory, modules.txt.
  addons-mode-off = {
    expected = {
      env = false;
      layout = {
        coreSrc = "odoo";
        externalDir = "modules";
        customDir = "custom";
        extraAddons = [ ];
      };
    };
    actual =
      let
        c =
          (perSystem {
            addons.enable = false;
            externalSources = [ ];
            workspaceRoot = ./fixtures/18.0;
          }).config;
      in
      {
        env = c.devenv.shells.default.env ? ODOO_NIX_LOCAL_ADDONS;
        inherit (c.odoo-nix) layout;
      };
  };

  # A lock directory that is not a plain subdirectory is refused.
  addons-mode-lock-dir = {
    expected = [
      false
      false
      true
    ];
    actual = map (d: evaluates (perSystem { addons.lockDir = d; }).config.odoo-nix.addons.lockDir) [
      "."
      "./nix"
      "tools/nix"
    ];
  };

  # Without OCB as an input there is no core to link.
  addons-mode-needs-core-source = {
    expected = false;
    actual = evaluates (perSystem { coreSource = null; }).config.packages.odooDevEnv.drvPath;
  };
}
