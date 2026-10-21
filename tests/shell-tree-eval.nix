# Evaluation-level assertions over the dev shell's option tree
# (python-devops-nix CONVENTIONS.md, The development shell option tree):
# `watch`, `devguard`, `mailpit` and `ports`, their defaults, and the ports
# a project derives from its name (python-devops-nix's lib.ports). A consumer's flake is
# evaluated through lib.mkFlake and nothing is built. Same `pairs` shape as
# eval.nix; flake.nix turns each into a named check (lib.checks.mk's `eval`). The old names are
# tests/renames-eval.nix's.
{
  pkgs,
  lib,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;
  inherit (inputs.python-devops-nix.lib) ports;

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
          name = "acme";
          workspaceRoot = ./fixtures/19.0;
          coreSource = inputs.ocb-19;
          odooSeries = "19.0";
        }
        // odoo-nix;
      }
    ).allSystems.${system};

  shell = odoo-nix: (perSystem odoo-nix).config.devenv.shells.default;

  # Pure evaluation has no PWD: the offset is the name's hash.
  offset = ports.offsetFor "acme";
  portsOf = config: {
    inherit (config.odoo-nix.ports)
      offset
      http
      gevent
      db
      smtp
      mailUi
      ;
  };
in
{
  # Every port from one offset, hashed from `name`, and read everywhere.
  ports-default =
    let
      inherit (perSystem { }) config;
    in
    {
      expected = {
        ports = {
          inherit offset;
          http = 10000 + offset;
          gevent = 11000 + offset;
          db = 12000 + offset;
          smtp = 13000 + offset;
          mailUi = 14000 + offset;
        };
        mailpit = {
          port = 13000 + offset;
          httpPort = 14000 + offset;
        };
        pg = 12000 + offset;
        env = {
          ODOO_NIX_HTTP_PORT = toString (10000 + offset);
          ODOO_NIX_GEVENT_PORT = toString (11000 + offset);
          MAILPIT_SMTP_PORT = toString (13000 + offset);
          MAILPIT_HTTP_PORT = toString (14000 + offset);
        };
      };
      actual = {
        ports = portsOf config;
        mailpit = { inherit (config.odoo-nix.mailpit) port httpPort; };
        pg = config.devenv.shells.default.services.postgres.port;
        env = {
          inherit (config.devenv.shells.default.env)
            ODOO_NIX_HTTP_PORT
            ODOO_NIX_GEVENT_PORT
            MAILPIT_SMTP_PORT
            MAILPIT_HTTP_PORT
            ;
        };
      };
    };
  # Another name, other ports.
  ports-name = {
    expected = ports.offsetFor "other" + 10000;
    actual = (perSystem { name = "other"; }).config.odoo-nix.ports.http;
  };
  # `ports.offset` moves them all; `ports.base` pins the HTTP port alone.
  ports-offset-base = {
    expected = {
      offset = {
        offset = 7;
        http = 10007;
        gevent = 11007;
        db = 12007;
        smtp = 13007;
        mailUi = 14007;
      };
      base = {
        inherit offset;
        http = 8069;
        gevent = 11000 + offset;
        db = 12000 + offset;
        smtp = 13000 + offset;
        mailUi = 14000 + offset;
      };
    };
    actual = {
      offset = portsOf (perSystem { ports.offset = 7; }).config;
      base = portsOf (perSystem { ports.base = 8069; }).config;
    };
  };
  # The fixed ports from before, pinned with lib.mkForce.
  ports-pinned =
    let
      inherit
        (perSystem {
          ports = lib.mapAttrs (_: lib.mkForce) {
            http = 8069;
            gevent = 8072;
            db = 5432;
            smtp = 1025;
            mailUi = 8025;
          };
        })
        config
        ;
    in
    {
      expected = {
        http = 8069;
        gevent = 8072;
        db = 5432;
        smtp = 1025;
        mailUi = 8025;
        mailpit = 1025;
        pg = 5432;
      };
      actual = {
        inherit (config.odoo-nix.ports)
          http
          gevent
          db
          smtp
          mailUi
          ;
        mailpit = config.odoo-nix.mailpit.port;
        pg = config.devenv.shells.default.services.postgres.port;
      };
    };
  # A linked worktree (its .git a file) salts the seed with its path when
  # worktreeSalt is on; the primary checkout never does.
  ports-seed = {
    expected = [
      "acme@/w/acme-2"
      "acme"
      "acme"
      "acme"
    ];
    actual =
      map
        (
          a:
          ports.seed (
            {
              name = "acme";
              pwd = "/w/acme-2";
            }
            // a
          )
        )
        [
          {
            salt = true;
            gitKind = "regular";
          }
          {
            salt = true;
            gitKind = "directory";
          }
          {
            salt = false;
            gitKind = "regular";
          }
          {
            salt = true;
            gitKind = null;
          }
        ];
  };
  ports-env-offset = {
    expected = [
      null
      12
      899
      null
    ];
    actual =
      map
        (ports.parseEnvOffset {
          label = "odoo-nix";
          variable = "ODOO_NIX_PORT_OFFSET";
        })
        [
          ""
          "12"
          "899"
          "900"
        ];
  };
  # Mailpit runs, and the server starts after it, whether or not the mail
  # guard (or the whole devguard) is on.
  mailpit-default =
    let
      on = shell { };
      guardOff = shell { devguard.enable = false; };
    in
    {
      expected = {
        enable = true;
        process = true;
        after = true;
        afterGuardOff = true;
      };
      actual = {
        inherit ((perSystem { }).config.odoo-nix.mailpit) enable;
        process = on.processes ? mailpit;
        after = lib.elem "devenv:processes:mailpit@started" on.processes.odoo.after;
        afterGuardOff = lib.elem "devenv:processes:mailpit@started" guardOff.processes.odoo.after;
      };
    };
  mailpit-off =
    let
      off = shell { mailpit.enable = false; };
    in
    {
      expected = {
        process = false;
        after = false;
      };
      actual = {
        process = off.processes ? mailpit;
        after = lib.elem "devenv:processes:mailpit@started" off.processes.odoo.after;
      };
    };
  # CI mode (python-devops-nix's lib.ciMode, CONVENTIONS.md, CI mode):
  # enterShell exports PC_TUI_ENABLED=0 before anything else of odoo-nix's
  # runs, skips the submodule checkout, and prints one line for its banner.
  ci-mode =
    let
      es = (shell { }).enterShell;
      before = marker: builtins.head (lib.splitString marker es);
      lastLines = n: text: lib.concatStringsSep "\n" (lib.takeEnd n (lib.splitString "\n" text));
    in
    {
      expected = {
        exportsFirst = true;
        sourcesUnlessCi = true;
        oneLine = true;
        bannerOutsideCi = true;
      };
      actual = {
        exportsFirst = lib.hasInfix "PC_TUI_ENABLED=0" (before "/bin/odoo-nix-db-nocow prepare");
        sourcesUnlessCi = lib.hasInfix ''if ! case "''${ODOO_NIX_CI:-}"'' (
          lastLines 4 (before "/bin/odoo-nix-sources enter")
        );
        oneLine = lib.hasInfix ''echo "odoo-nix: CI mode (acme, Odoo 19.0, http ${toString (10000 + offset)})"'' es;
        bannerOutsideCi = lib.hasInfix "/bin/odoo-nix-banner /nix/store/" es;
      };
    };
  # watch.python is on by default: the server gets the watchdog fallback.
  watch-default = {
    expected = {
      python = true;
      watchdog = true;
    };
    actual = {
      inherit ((perSystem { }).config.odoo-nix.watch) python;
      watchdog = lib.hasInfix "import watchdog" (shell { }).processes.odoo.exec;
    };
  };
  # The tree: watch, devguard, mailpit and ports; `dev` only as the hidden
  # alias of dev.autoReload, and the ports out of settings.
  tree =
    let
      o = (perSystem { }).options.odoo-nix;
    in
    {
      expected = {
        trees = [
          true
          true
          true
          true
        ];
        dev = false;
        settingsPorts = [
          false
          false
          false
        ];
      };
      actual = {
        trees = map (t: o ? ${t}) [
          "watch"
          "devguard"
          "mailpit"
          "ports"
        ];
        dev = o.dev.autoReload.visible;
        settingsPorts = map (p: (o.settings.${p}.visible or true) && !(o.settings.${p}.internal or false)) [
          "httpPort"
          "geventPort"
          "dbPort"
        ];
      };
    };
}
