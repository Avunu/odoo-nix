# Evaluation-level assertions over the dev shell's renamed options
# (modules/devenv.nix, docs/development/upgrading.md): an old name evaluates,
# reaches its replacement (and the shell's env, the packages' names or the
# baked devguard settings), and is announced on
# `odoo-nix.deprecations` (what the module lib.warn's). A consumer's flake is
# evaluated through lib.mkFlake and nothing is built. Same `pairs` shape as
# eval.nix; flake.nix turns each into a named check (lib.checks.mk's `eval`).
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
      inherit (config.odoo-nix) mailpit;
      mailGuard = config.odoo-nix.devguard.mail.enable;
      inherit (config.devenv.shells.default.env) MAILPIT_SMTP_PORT MAILPIT_HTTP_PORT;
      # How many warnings name each rename, and how many there are.
      deprecations = {
        guard = count "mailcatch.enable'" "devguard.mail.enable'" config;
        mailcatch = count "mailcatch." "mailpit." config;
        devguardMail = count "devguard.mail." "mailpit." config;
        all = builtins.length config.odoo-nix.deprecations;
      };
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
  count =
    from: to: config:
    lib.count lib.id (warned from to config);
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
  # Job denylist), kept through 1.x (removed in 2.0.0).
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
  # The old names, kept through 1.x (removed in 2.0.0): mailcatch.enable is the mail guard's,
  # the rest the catcher's (the mailpit tree).
  rename-mailcatch = {
    expected = {
      mailpit = {
        enable = true;
        host = "127.0.0.2";
        port = 2525;
        httpPort = 9025;
      };
      mailGuard = false;
      MAILPIT_SMTP_PORT = "2525";
      MAILPIT_HTTP_PORT = "9025";
      deprecations = {
        guard = 1;
        mailcatch = 3;
        devguardMail = 0;
        all = 4;
      };
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
  # devguard.mail.{host,port,httpPort} -> mailpit.* (The development shell
  # option tree): the catcher is a service, not a guard.
  rename-devguard-mail = {
    expected = {
      mailpit = {
        enable = true;
        host = "127.0.0.2";
        port = 2525;
        httpPort = 9025;
      };
      mailGuard = true;
      MAILPIT_SMTP_PORT = "2525";
      MAILPIT_HTTP_PORT = "9025";
      deprecations = {
        guard = 0;
        mailcatch = 0;
        devguardMail = 3;
        all = 3;
      };
    };
    actual = renamed {
      devguard.mail = {
        host = "127.0.0.2";
        port = 2525;
        httpPort = 9025;
      };
    };
  };
  # dev.autoReload -> watch.python: the server is started without the
  # watchdog fallback.
  rename-dev-auto-reload =
    let
      config = perSystemConfig { dev.autoReload = false; };
    in
    {
      expected = {
        python = false;
        watchdog = false;
        deprecations = [ true ];
      };
      actual = {
        inherit (config.odoo-nix.watch) python;
        watchdog = lib.hasInfix "import watchdog" config.devenv.shells.default.processes.odoo.exec;
        deprecations = warned "dev.autoReload'" "watch.python'" config;
      };
    };
  # Nothing old set: nothing to warn about.
  rename-none = {
    expected = [ ];
    actual = (perSystemConfig { }).odoo-nix.deprecations;
  };
}
