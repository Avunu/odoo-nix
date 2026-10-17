# Evaluation-level assertions over the dev shell's renamed options
# (modules/devenv.nix, README "Renamed options"): an old name evaluates,
# reaches its replacement (and the shell's env, the packages' names or the
# baked devguard settings), and is announced on
# `odoo-nix.deprecations` (what the module lib.warn's). A consumer's flake is
# evaluated through lib.mkFlake and nothing is built. Same `pairs` shape as
# eval.nix; flake.nix turns each into a named mkEvalCheck.
{
  pkgs,
  lib,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;

  perSystemConfig =
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
        # An old name for the identity replaces the new one, which would
        # otherwise be defined twice.
        perSystem.odoo-nix =
          removeAttrs {
            enable = true;
            name = "acme";
            workspaceRoot = ./fixtures/19.0;
            coreSource = inputs.ocb-19;
            odooSeries = "19.0";
          } (lib.optional (odoo-nix ? projectName) "name")
          // odoo-nix;
      }
    ).allSystems.${system}.config;

  renamed =
    odoo-nix:
    let
      config = perSystemConfig odoo-nix;
    in
    {
      inherit (config.odoo-nix.devguard) mail;
      inherit (config.devenv.shells.default.env) MAILPIT_SMTP_PORT MAILPIT_HTTP_PORT;
      deprecations = map (
        msg:
        lib.hasPrefix "The option `odoo-nix.mailcatch." msg
        && lib.hasInfix "has been renamed to `odoo-nix.devguard.mail." msg
      ) config.odoo-nix.deprecations;
    };

  renamedCrons =
    odoo-nix:
    let
      config = perSystemConfig odoo-nix;
    in
    {
      inherit (config.odoo-nix.devguard) jobs;
      deprecations = map (
        msg:
        lib.hasPrefix "The option `odoo-nix.devguard.crons." msg
        && lib.hasInfix "has been renamed to `odoo-nix.devguard.jobs." msg
      ) config.odoo-nix.deprecations;
    };

  # Which deprecations name `from' -> `to' (option-path prefixes).
  warned =
    from: to: config:
    map (
      msg:
      lib.hasPrefix "The option `odoo-nix.${from}" msg
      && lib.hasInfix "has been renamed to `odoo-nix.${to}" msg
    ) config.odoo-nix.deprecations;
in
{
  # projectName -> name (python-devops-nix CONVENTIONS.md, Identity
  # options): the identity names the packages and devenv's own `name`.
  rename-project-name =
    let
      config = perSystemConfig { projectName = "legacy"; };
    in
    {
      expected = {
        name = "legacy";
        shell = "legacy";
        cli = "legacy-odoo-cli";
        deprecations = [ true ];
      };
      actual = {
        inherit (config.odoo-nix) name;
        shell = config.devenv.shells.default.name;
        cli = config.packages.default.name;
        deprecations = warned "projectName'" "name'" config;
      };
    };
  # The identity is devenv's `name` too, unless the shell sets its own.
  identity-shell-name = {
    expected = "acme";
    actual = (perSystemConfig { }).devenv.shells.default.name;
  };
  # devguard.crons.* -> devguard.jobs.* (python-devops-nix CONVENTIONS.md,
  # Job denylist), for one release.
  rename-crons = {
    expected = {
      jobs = {
        enable = false;
        extraBlocked = [ "my_module.ir_cron_sync" ];
      };
      deprecations = [
        true
        true
      ];
    };
    actual = renamedCrons {
      devguard.crons = {
        enable = false;
        extraBlocked = [ "my_module.ir_cron_sync" ];
      };
    };
  };
  # The old names, for one release.
  rename-mailcatch = {
    expected = {
      mail = {
        enable = false;
        host = "127.0.0.2";
        port = 2525;
        httpPort = 9025;
      };
      MAILPIT_SMTP_PORT = "2525";
      MAILPIT_HTTP_PORT = "9025";
      deprecations = [
        true
        true
        true
        true
      ];
    };
    actual = renamed {
      mailcatch = {
        enable = false;
        host = "127.0.0.2";
        port = 2525;
        httpPort = 9025;
      };
    };
  };
  # Nothing old set: nothing to warn about.
  rename-none = {
    expected = [ ];
    actual = (perSystemConfig { }).odoo-nix.deprecations;
  };
}
