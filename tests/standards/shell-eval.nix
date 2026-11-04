# checks.standards-shell-eval-* (py/odoo_nix_tools/DESIGN.md §7.3): the standards'
# shell additions (lib/standards/shell.nix), evaluated, nothing built.
#
#   - a project and an addon repository that have not opted in get the shell
#     they get without the additions at all (the internal standardsShell = false):
#     the same packages, entry, environment, `odoo` CLI (its raw odoo-bin's
#     coverage hook) and apps;
#   - opted in: apps.odoo-init and apps.odoo-nix, devShells.odoo-nix-lint, the
#     tool links and `prek install -c` on shell entry, and in addons mode with a
#     root package.json the "." node exclude;
#   - lib.standards.lintShell evaluates over a plain fixture path, and with a
#     fixture's locks its tools (tools/.venv, node_modules) evaluate.
#
# Pure evaluation has no working directory, which the devenv shell derivation
# reads, so the shell is compared through what it is made of. Same `pairs`
# shape as tests/eval.nix.
{
  pkgs,
  lib,
  inputs,
  mkFlake,
  lintShell,
  standardsShell,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;
  plain = builtins.unsafeDiscardStringContext;
  evaluates = v: (builtins.tryEval (builtins.deepSeq v true)).success;

  perSystem =
    odoo-nix:
    (mkFlake
      {
        inputs.self = {
          outPath = ../..;
          inherit inputs;
        };
      }
      {
        debug = true;
        systems = [ system ];
        imports = [ ../../modules/flake-module.nix ];
        perSystem.odoo-nix = {
          enable = true;
          name = "acme";
          odooSeries = "18.0";
        }
        // odoo-nix;
      }
    ).allSystems.${system}.config;

  project = {
    workspaceRoot = ../fixtures/19.0;
    coreSource = inputs.ocb-19;
    odooSeries = "19.0";
  };
  addons = {
    workspaceRoot = ../fixtures/addons-repo;
    addons.enable = true;
    coreSource = inputs.ocb-18;
  };

  # What the shell and its outputs are made of.
  made =
    config:
    let
      shell = config.devenv.shells.default;
    in
    {
      packages = map (p: plain p.drvPath) shell.packages;
      enterShell = plain shell.enterShell;
      env = lib.mapAttrs (_: v: if builtins.isString v then plain v else v) (
        lib.filterAttrs (_: v: builtins.isString v || builtins.isBool v || builtins.isInt v) shell.env
      );
      odooCli = plain config.packages.odooCli.drvPath;
      apps = lib.attrNames config.apps;
      devShells = lib.attrNames config.devShells;
      packageNames = lib.attrNames config.packages;
    };
  unchanged = settings: {
    expected = made (perSystem (settings // { standardsShell = false; }));
    actual = made (perSystem settings);
  };

  optedIn = perSystem {
    workspaceRoot = ../fixtures/standards-project;
  };
  optedInAddons = perSystem {
    workspaceRoot = ../fixtures/standards-shell-addons;
    addons.enable = true;
    coreSource = inputs.ocb-18;
  };
  # shell.nix itself, over the opted-in addons tree.
  addonsShell = standardsShell {
    root = ../fixtures/standards-shell-addons;
    addonsMode = true;
  };
  locks = ../fixtures/standards-locks/standards-project/example-org;
  # Opted in, with the Odoo lock and a tools lock that pins coverage
  # (symlinks into the fixtures above): the raw odoo-bin's coverage hook gets
  # the lock's coverage.
  withCoverage = perSystem {
    workspaceRoot = ../fixtures/standards-coverage;
    addons.enable = true;
    coreSource = inputs.ocb-18;
  };
  withoutStandards = perSystem {
    workspaceRoot = ../fixtures/standards-coverage;
    addons.enable = true;
    coreSource = inputs.ocb-18;
    standardsShell = false;
  };
in
{
  standards-shell-eval-project-unchanged = unchanged project;
  standards-shell-eval-addons-unchanged = unchanged addons;

  # The flake's outputs through lib.mkFlake; the shell entry from shell.nix itself
  # (the fixture has no uv.lock, which the whole entry would need).
  standards-shell-eval-opted-in = {
    expected = {
      apps = [
        "odoo-init"
        "odoo-nix"
        "relock"
      ];
      lint = true;
      packages = true;
      links = true;
      prekInstall = true;
      blame = true;
    };
    actual =
      let
        module = (standardsShell { root = ../fixtures/standards-project; }).devenvModule;
        entry = plain module.enterShell;
      in
      {
        apps = lib.attrNames optedIn.apps;
        lint = optedIn.devShells ? odoo-nix-lint;
        packages = lib.all (n: lib.any (p: lib.hasPrefix n (p.name or "")) module.packages) [
          "odoo-nix-"
          "odoo-init"
          "committed"
          "deadnix"
        ];
        links = lib.hasInfix "_odoo_nix_link tools/.bin" entry;
        prekInstall = lib.hasInfix "install -c .pre-commit-config.yaml" entry;
        blame = lib.hasInfix "blame.ignoreRevsFile .git-blame-ignore-revs" entry;
      };
  };

  # The `odoo` CLI and the default shell evaluate once the tools lock has
  # coverage (O9: tools.nix's coverage carried no pythonModule for the hook).
  standards-shell-eval-coverage = {
    expected = {
      odooCli = true;
      packages = true;
      lockCoverage = true;
    };
    actual = {
      odooCli = evaluates withCoverage.packages.odooCli.drvPath;
      packages = evaluates (map (p: p.drvPath) withCoverage.devenv.shells.default.packages);
      # The hook takes the lock's coverage, not nixpkgs' (what the CLI gets
      # without the standards' additions).
      lockCoverage = withCoverage.packages.odooCli.drvPath != withoutStandards.packages.odooCli.drvPath;
    };
  };

  standards-shell-eval-addons-opted-in = {
    expected = {
      optedIn = true;
      nodeExcludes = [ "." ];
      apps = [
        "odoo-init"
        "odoo-nix"
        "relock"
      ];
      lint = true;
    };
    actual = {
      inherit (addonsShell) optedIn nodeExcludes;
      apps = lib.attrNames optedInAddons.apps;
      lint = optedInAddons.devShells ? odoo-nix-lint;
    };
  };

  # A project's root package.json is the standards' alone: no exclude needed.
  standards-shell-eval-node-excludes = {
    expected = [
      [ ]
      [ ]
    ];
    actual = [
      (standardsShell {
        root = ../fixtures/standards-shell-addons;
        addonsMode = false;
        configFile = "nix/pyproject.toml";
      }).nodeExcludes
      (standardsShell {
        root = ../fixtures/addons-repo;
        addonsMode = true;
      }).nodeExcludes
    ];
  };

  standards-shell-eval-lint-shell = {
    expected = {
      plain = true;
      withLocks = true;
      toolsEnv = true;
      nodeModules = true;
    };
    actual =
      let
        withLocks = standardsShell {
          root = ../fixtures/standards-project;
          toolsRoot = locks;
        };
      in
      {
        plain =
          evaluates
            (lintShell {
              inherit system;
              root = ../fixtures/standards-project;
            }).drvPath;
        withLocks = evaluates withLocks.lintShell.drvPath;
        toolsEnv = lib.hasInfix "_odoo_nix_link tools/.venv" (plain withLocks.links);
        nodeModules = lib.hasInfix "_odoo_nix_link node_modules" (plain withLocks.links);
      };
  };
}
