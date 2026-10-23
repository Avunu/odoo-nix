# Evaluation-level assertions over the dev shell's removed options
# (modules/devenv.nix, docs/development/upgrading.md, "1.x to 2.0"): every
# name 1.x renamed and kept as an alias is refused since 2.0.0. Defining one
# puts a message on `odoo-nix.removals` naming its replacement, and the shell
# then fails to evaluate with all of them. A consumer's flake is evaluated
# through lib.mkFlake and nothing is built. Same `pairs` shape as eval.nix;
# flake.nix turns each into a named check (lib.checks.mk's `eval`).
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
        perSystem.odoo-nix = {
          enable = true;
          name = "acme";
          workspaceRoot = ./fixtures/19.0;
          coreSource = inputs.ocb-19;
          odooSeries = "19.0";
        }
        // odoo-nix;
      }
    ).allSystems.${system}.config;

  # For an old definition: one message per removed name, each naming the
  # old path (a prefix of it, through its closing quote) and its
  # replacement, and a shell that does not evaluate.
  refused =
    odoo-nix: old: new:
    let
      config = perSystemConfig odoo-nix;
      inherit (config.odoo-nix) removals;
    in
    {
      messages = builtins.length removals;
      named = lib.all (m: lib.hasInfix "`odoo-nix.${old}" m && lib.hasInfix new m) removals;
      evaluates = (builtins.tryEval config.packages.odooConf.outPath).success;
    };
  isRefused = n: {
    messages = n;
    named = true;
    evaluates = false;
  };
in
{
  # projectName -> name (python-devops-nix CONVENTIONS.md, Identity options).
  removed-project-name = {
    expected = isRefused 1;
    actual = refused { projectName = "legacy"; } "projectName'" "`name`";
  };
  # The identity is devenv's `name` too, unless the shell sets its own.
  identity-shell-name = {
    expected = "acme";
    actual = (perSystemConfig { }).devenv.shells.default.name;
  };
  # devguard.crons.* -> devguard.jobs.* (Job denylist).
  removed-crons = {
    expected = isRefused 1;
    actual = refused {
      devguard.crons = {
        enable = false;
        extraBlocked = [ "my_module.ir_cron_sync" ];
      };
    } "devguard.crons'" "devguard.jobs.{enable,extraBlocked}";
  };
  # mailcatch.* -> devguard.mail.enable and mailpit.*.
  removed-mailcatch = {
    expected = isRefused 1;
    actual = refused {
      mailcatch = {
        enable = false;
        port = 2525;
      };
    } "mailcatch'" "mailpit.{host,port,httpPort}";
  };
  # devguard.mail.{host,port,httpPort} -> mailpit.* (The development shell
  # option tree): the catcher is a service, not a guard. One message each.
  removed-devguard-mail = {
    expected = isRefused 3;
    actual = refused {
      devguard.mail = {
        host = "127.0.0.2";
        port = 2525;
        httpPort = 9025;
      };
    } "devguard.mail." "It is mailpit.";
  };
  # dev.autoReload -> watch.python; the `dev` tree is gone.
  removed-dev-auto-reload = {
    expected = isRefused 1;
    actual = refused { dev.autoReload = false; } "dev'" "watch.python";
  };
  # restore.attachments -> restore.files.
  removed-restore-attachments = {
    expected = isRefused 1;
    actual = refused { restore.attachments = "mirror"; } "restore.attachments'" "restore.files";
  };
  # containers.roleImageNames: the image is always <name>/odoo since 2.0.0.
  removed-role-image-names = {
    expected = isRefused 1;
    actual = refused {
      containers.roleImageNames = true;
    } "containers.roleImageNames'" "<registry>/<name>/odoo";
  };
  # odooConf.* -> settings.options, dbName and ports.
  removed-odoo-conf = {
    expected = isRefused 1;
    actual = refused { odooConf.dbName = "legacy"; } "odooConf'" "settings.options.<key>";
  };
  # The guard's own setting is still the guard's: devguard.mail.enable is
  # not one of the removed names.
  removed-none = {
    expected = {
      removals = [ ];
      mailGuard = false;
    };
    actual =
      let
        config = perSystemConfig { devguard.mail.enable = false; };
      in
      {
        inherit (config.odoo-nix) removals;
        mailGuard = config.odoo-nix.devguard.mail.enable;
      };
  };
}
