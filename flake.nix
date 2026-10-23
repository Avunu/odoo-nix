{
  description = "Reusable Nix infrastructure for Odoo (OCB) + OCA projects";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    devenv.url = "github:cachix/devenv";
    # Decrypts age secrets into a dev shell. Imported by
    # modules/flake-module.nix, so consumers do not declare it themselves.
    # The agenix *CLI* is deliberately not an input (ryantm/agenix drags
    # darwin + home-manager into every consumer's lock); `pkgs.ragenix` is a
    # drop-in with the same RULES / -e / -r interface.
    agenix-shell = {
      url = "github:aciceri/agenix-shell";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.flake-parts.follows = "flake-parts";
    };
    # Shared building blocks with frappe-nix: the secrets toolkit
    # (lib.secrets), the backup fetch layer (lib.backups) and the repository
    # checks (lib.checks). Its own inputs are nixpkgs and flake-parts, both
    # followed, so it adds one node to a consumer's lock.
    python-devops-nix = {
      url = "github:Avunu/python-devops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.flake-parts.follows = "flake-parts";
    };
    nix2container = {
      url = "github:nlewo/nix2container";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # ---------------------------------------------------------------------- #
    # THE OCB TREES THE TEST SUITE BUILDS.                                     #
    #                                                                         #
    # odoo-nix is a library: consumers assemble the real Odoo. Its own        #
    # checks do the same, from these pins, with the same library code the     #
    # flake-parts module calls (tests/series.nix). `flake = false` -- a       #
    # source tree, in the shape docs/scaffolding/write-the-flake.md ("A       #
    # repository of modules") prescribes for consumers. flake.lock records    #
    # the revision; dependabot moves it weekly. tests/fixtures/<series>/     #
    # uv.lock was locked against a revision of this tree;                     #
    # checks.lock-fresh-<major> says when they drift.                         #
    # ---------------------------------------------------------------------- #
    ocb-18 = {
      url = "github:OCA/OCB/18.0";
      flake = false;
    };
    ocb-19 = {
      url = "github:OCA/OCB/19.0";
      flake = false;
    };
    ocb-20 = {
      url = "github:OCA/OCB/20.0";
      flake = false;
    };

    # odoo-ls (github.com/odoo/odoo-ls): the Odoo-aware Rust language server,
    # packaged in lib/odoo-ls.nix. Pinned to its stable 1.4.0 tag (even-minor
    # = stable per its own release convention). odoo-ls-typeshed is the exact
    # commit its own `server/typeshed` git submodule points at for that tag --
    # bump both together (`nix run .#relock-odoo-ls` also refreshes
    # lib/odoo-ls-Cargo.lock, since odoo-ls does not commit one upstream).
    odoo-ls-src = {
      url = "github:odoo/odoo-ls?ref=1.4.0";
      flake = false;
    };
    odoo-ls-typeshed = {
      url = "github:python/typeshed?rev=80fd73de22748b0fa97d9cc414c0ba854bd6901e";
      flake = false;
    };
  };

  nixConfig = {
    extra-substituters = [
      "https://devenv.cachix.org"
    ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-parts,
      ...
    }@inputs:
    let
      # No x86_64-darwin: nixpkgs 26.11 dropped it (its Darwin stdenv is
      # gone), so evaluating anything for it is an error, and consumers
      # `follows` this nixpkgs.
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));
      odooInit = pkgs: import ./lib/init.nix { inherit pkgs base; };

      # Series -> pinned OCB. The interpreter per series comes from the same
      # presets file odoo-init uses, so the fixtures cannot disagree with it.
      ocbInputs = {
        "18.0" = inputs.ocb-18;
        "19.0" = inputs.ocb-19;
        "20.0" = inputs.ocb-20;
      };
      presets = builtins.fromJSON (builtins.readFile ./lib/odoo-presets.json);

      # odoo-nix's own addons (dev_mailcatch), as their own store path -- the
      # same expression modules/devenv.nix uses, for the same reason.
      odooNixAddons = builtins.path {
        path = ./addons;
        name = "odoo-nix-addons";
      };

      base = inputs.python-devops-nix.lib;

      # The repo's own Nix files, for `nix fmt` and checks.nix-lint alike:
      # everything but templates/ (@PLACEHOLDERS@, not Nix that parses) and
      # tests/fixtures/ (stand-ins for consumer projects).
      nixLintIgnore = [
        "templates"
        "tests/fixtures"
      ];
      nixFiles = pkgs: ''
        ${pkgs.findutils}/bin/find . \( -path ./templates -o -path ./tests/fixtures -o -path ./.git \
          -o -path ./.direnv -o -path ./.devenv -o -name result -o -name 'result-*' \) -prune \
          -o -name '*.nix' -type f -print0
      '';

      # One small derivation per assertion: `nix flake check` names what
      # broke, and a slow Odoo run cannot mask a fast check. Every check is
      # registered through python-devops-nix's lib.checks.mk (CONVENTIONS.md,
      # Tests): checks.<system>.<x>, built as odoo-nix-<x>-check, or
      # vm-test-run-odoo-nix-<x> for a VM test.
      checksFor =
        pkgs:
        base.checks.mk {
          inherit pkgs;
          product = "odoo-nix";
        };

      # Its `script`, with two additions. `refute CMD...` fails the check when
      # CMD succeeds: a bare `! CMD` never does, bash exempts `!` pipelines
      # from errexit. And an Odoo log the script left (odoo.log) is kept in
      # the output for inspection. The script runs in the build directory.
      scriptCheck =
        pkgs: name: args: text:
        (checksFor pkgs).script name args ''
          refute() {
            if "$@"; then
              echo "refuted, but it succeeded: $*" >&2
              exit 1
            fi
          }
          ${text}
          if [ -e odoo.log ]; then
            mkdir -p "$out"
            cp odoo.log "$out/"
          fi
        '';

      # The interpreters every preset names: the devguard loads into Odoo's own.
      devguardInterpreters = base.python.interpreters { presets = [ ./lib/odoo-presets.json ]; };
      devguardPackage =
        pkgs:
        {
          settings ? { },
        }:
        import ./lib/devguard.nix { inherit pkgs base settings; };
      cliPackage = pkgs: import ./lib/cli-package.nix { inherit pkgs base; };
      journaldGraft = pkgs: import ./lib/journald.nix { inherit pkgs base; };
      shellTools = pkgs: import ./lib/shell-tools.nix { inherit pkgs base; };

      relock =
        pkgs:
        import ./tests/relock.nix {
          inherit pkgs ocbInputs presets;
          buildDeps = import ./lib/build-deps.nix { inherit pkgs base; };
          cliPackage = cliPackage pkgs;
        };

      # services.odoo-nix, with python-devops-nix's library as the module
      # argument `odooNixBase` (modules/nixos.nix takes the thread caps from
      # it). The checks import this, not ./modules/nixos.nix alone.
      nixosModule = {
        imports = [ ./modules/nixos.nix ];
        _module.args.odooNixBase = base;
      };
    in
    {
      flakeModules.default = ./modules/flake-module.nix;

      nixosModules.default = nixosModule;

      lib = {
        # Wrapper around flake-parts.lib.mkFlake that merges odoo-nix's own inputs
        # with the consumer's, so a consuming flake only declares odoo-nix +
        # nixpkgs.follows. Mirrors frappe-nix.lib.mkFlake.
        mkFlake =
          {
            inputs ? { },
            ...
          }:
          config:
          flake-parts.lib.mkFlake {
            inputs = self.inputs // inputs;
          } config;

        # Composable Python package overrides for native-build packages:
        # python-devops-nix's shared fixes one by one, and libsass.
        overrides = import ./lib/overrides.nix { pythonLib = base.python; };

        # The addons_path synthesis core, exposed for testing / advanced use.
        addons = import ./lib/addons.nix;

        # The odoo-ls (Odoo language server) package builder.
        odoo-ls = import ./lib/odoo-ls.nix;
      };

      # checks.<system> (names: python-devops-nix CONVENTIONS.md, Tests):
      #   addons-*, odoo-ini-*, odoo-ini-render               pure library tests (all systems)
      #   journald-formatter                                  the CLI's journald output (all systems)
      #   devguard-core, devguard, devguard-baked             the dev guard rails: base core, odoo-nix's side (all systems)
      #   sources                                             shell entry's submodule checkout (all systems)
      #   bootstrap, bootstrap-lock-*                         the fresh-clone checkout before `use flake` (all systems)
      #   scaffold, odoo-init-unit                            odoo-init: its projects, offline; its pieces (all systems)
      #   odoo-module-cli, odoo-module-unit                   `odoo module add|add-bundle|remove`, offline; their pieces (all systems)
      #   db-nocow                                            the dev datadir's btrfs NOCOW (Linux only)
      #   nix-lint, shared-config                             python-devops-nix's repository checks (all systems)
      #   pr-policy, workflows                                the PR policy script; actionlint and zizmor on .github (all systems)
      #   backups, backup-layout                              the backup fetch layer, base and odoo-nix's side (all systems)
      #   odoo-db-compat                                      the CLI's one API over Odoo's two database-management APIs (all systems)
      #   secrets-*                                           odoo-nix's secrets module (all systems)
      #   lock-audit-*                                        the stale-lock audit on a stale fixture (all systems)
      #   restore-*                                           the dev shell's restore options (Linux only)
      #   service-*                                           services.odoo-nix evaluation (Linux only)
      #   container-*                                         the OCI image's name, user, labels, healthcheck (Linux only)
      #   python-default-*                                    the series' default interpreter (Linux only)
      #   settings-*                                          the dev shell's odoo.conf, by section (Linux only)
      #   rename-*, identity-*                                renamed dev-shell options (Linux only)
      #   {ports,mailpit,watch}-*, ci-mode, tree              the dev shell's option tree and its ports (Linux only)
      #   fixture-requires-python-<major>, built-odoo-{addons-path,version}-<major>,
      #   lock-audit-<major>, lock-fresh-<major>, build-deps-<major>
      #                                                       per-series, no Odoo run (all systems)
      #   built-odoo-<major>, odoo-init-<major>, odoo-test-<major>,
      #   cli-*-<major>                                       run Odoo (Linux only)
      #   service-<major>, nginx                              NixOS VM tests (Linux only)
      checks = forAllSystems (
        pkgs:
        let
          inherit (pkgs) lib;
          isLinux = pkgs.stdenv.hostPlatform.isLinux;
          evalTests = import ./tests/eval.nix { inherit pkgs lib; };
          evalChecks =
            suffix:
            lib.mapAttrs' (n: v: lib.nameValuePair "${n}${suffix}" ((checksFor pkgs).eval "${n}${suffix}" v));
          perSeries = lib.concatMapAttrs (
            series: ocb:
            let
              major = lib.versions.major series;
              s = import ./tests/series.nix {
                inherit
                  pkgs
                  lib
                  inputs
                  series
                  ocb
                  odooNixAddons
                  ;
                python = pkgs.${presets.${series}.python};
                scriptCheck = scriptCheck pkgs;
                inherit (checksFor pkgs) nixosTest;
              };
              suffixed = lib.mapAttrs' (n: v: lib.nameValuePair "${n}-${major}" v);
            in
            evalChecks "-${major}" s.eval // suffixed (s.all // lib.optionalAttrs isLinux s.linux)
          ) ocbInputs;
        in
        evalChecks "" evalTests.pairs
        // {
          # The rendered INI, not just the attrset: pkgs.formats.ini is part of
          # the contract (True/False literals, extra sections verbatim).
          odoo-ini-render = scriptCheck pkgs "odoo-ini-render" { } ''
            f=${evalTests.rendered}
            grep -qE '^\[dev_mailcatch\]$' "$f"
            grep -qE '^enabled=True$' "$f"
            grep -qE '^port=2525$' "$f"
            grep -qE '^without_demo=True$' "$f"
            grep -qE '^list_db=False$' "$f"
            grep -qE '^server_wide_modules=base,rpc,web,dev_mailcatch$' "$f"
            grep -qE '^log_handler=werkzeug:WARNING$' "$f"
            grep -qE '^proxy_mode=True$' "$f"
            refute grep -qE '^log_db=' "$f"
            refute grep -qE '^db_password=' "$f"
            grep -qE '^http_interface=127\.0\.0\.1$' "$f"
            grep -qE '^limit_time_real=1200$' "$f"
          '';

          # odoo_journald (lib/journald.nix) needs neither Odoo nor the CLI's
          # click/rich, so it runs on plain interpreters: every one a preset
          # names, since it loads into Odoo's own. Against the graft as
          # lib/python.nix puts it in the environments, with python-devops-nix's
          # core and hook beside it, and the CLI package that execs odoo-bin.
          journald-formatter = scriptCheck pkgs "journald-formatter" { } (
            lib.concatMapStrings (py: ''
              ${pkgs.${py}.interpreter} -I ${./tests/test_journald.py} ${journaldGraft pkgs} ${cliPackage pkgs}
            '') devguardInterpreters
          );

          # What shell entry does about the project's submodules: checks out a
          # fresh clone's once, and past that touches nothing. Git only, with
          # file:// remotes standing in for GitHub.
          # The devguard core (python-devops-nix, python/devguard): its own
          # tests against its stub product -- the hook, settings precedence,
          # the egress matrix and passage(), the mail transport -- on every
          # interpreter a preset names, since it loads into Odoo's (PLAN.md,
          # Python versions).
          devguard-core = base.devguard.check {
            inherit pkgs;
            product = "odoo-nix";
            interpreters = devguardInterpreters;
          };

          # odoo-nix's side (lib/devguard/odoo_devguard), without Odoo or a
          # network: _product.py's names and defaults, and the Odoo-facing
          # guards against stand-in modules, in the package lib/devguard.nix
          # builds (the core merged in), on the same interpreters.
          devguard = scriptCheck pkgs "devguard" { } (
            lib.concatMapStrings (py: ''
              ${pkgs.${py}.interpreter} -I ${./tests/test_devguard.py} ${devguardPackage pkgs { }}
            '') devguardInterpreters
          );

          # ...and with Nix-baked settings actually reaching the guard, the
          # log prefix and the .pth file name the shell and the docs promise.
          devguard-baked =
            let
              pkg = devguardPackage pkgs {
                settings.guards = {
                  mail.port = 2525;
                  egress.allow_hosts = [ "api.example.com" ];
                  jobs.extra_blocked = [ "my_module.ir_cron_sync" ];
                };
              };
            in
            scriptCheck pkgs "devguard-baked" { } ''
              test "${base.python.pthName pkg.module}" = zzz-odoo-devguard.pth
              PYTHONPATH=${pkg} ${pkgs.python3}/bin/python3 - <<'PY'
              import odoo_devguard as g
              from odoo_devguard import _patch, _settings
              st = g.settings()
              assert st.mail_port == 2525, st.mail_port
              assert st.items("egress", "allow_hosts") == ["api.example.com"], st.items("egress", "allow_hosts")
              assert st.mail_host == "127.0.0.1"  # untouched keys keep their defaults
              # The product's built-in denylist, then the baked additions.
              assert st.blocked_jobs[0] == "auto_backup.ir_cron_backup_scheduler_0", st.blocked_jobs
              assert st.blocked_jobs[-1] == "my_module.ir_cron_sync", st.blocked_jobs
              assert _settings.PACKAGE == "odoo_devguard", _settings.PACKAGE
              assert _settings.env_name("mail", "port") == "ODOO_DEVGUARD_MAIL_PORT"
              PY
              PYTHONPATH=${pkg} ${pkgs.python3}/bin/python3 -c \
                'from odoo_devguard import _patch; _patch.warn("egress", "probe")' 2> warn.log
              grep -qxF 'WARNING odoo_devguard[egress] probe' warn.log
            '';

          # python-devops-nix's backup fetch layer, which the `odoo` CLI
          # imports in-process: the base's own tests, on every interpreter a
          # preset runs the CLI on (PLAN.md, Python versions).
          backups = base.backups.check {
            inherit pkgs;
            product = "odoo-nix";
            interpreters = base.python.interpreters { presets = [ ./lib/odoo-presets.json ]; };
          };

          # odoo-nix's side of it (lib/odoo_nix_cli/backups.py,
          # backup_layout.py): the layout, the names, `--at`, without Odoo or
          # a network, on the same interpreters, against the package as
          # lib/cli.nix vendors it.
          backup-layout = scriptCheck pkgs "backup-layout" { } (
            lib.concatMapStrings (py: ''
              ${pkgs.${py}.interpreter} -I ${./tests/test_backups.py} ${cliPackage pkgs}
            '') (base.python.interpreters { presets = [ ./lib/odoo-presets.json ]; })
          );

          # lib/odoo_nix_cli/odoo_db.py: one set of names over Odoo's two
          # database-management APIs (odoo.service.db through 19.0,
          # odoo.modules.db from 20.0), against stand-ins shaped like each,
          # on the interpreters the CLI runs on.
          odoo-db-compat = scriptCheck pkgs "odoo-db-compat" { } (
            lib.concatMapStrings (py: ''
              ${pkgs.${py}.interpreter} -I ${./tests/test_odoo_db.py} ${cliPackage pkgs}
            '') (base.python.interpreters { presets = [ ./lib/odoo-presets.json ]; })
          );

          # nixfmt-rs (what `nix fmt` writes), statix (statix.toml, compared
          # with the base's) and deadnix, over the files `nix fmt` covers.
          nix-lint = base.checks.nixLint {
            inherit pkgs;
            src = ./.;
            product = "odoo-nix";
            ignore = nixLintIgnore;
          };

          # .editorconfig, .pre-commit-config.yaml and ruff.toml carry the
          # base's settings (python-devops-nix CONVENTIONS.md, Repository files).
          shared-config = base.checks.sharedConfig {
            inherit pkgs;
            src = ./.;
            product = "odoo-nix";
          };

          # The pr-policy check (lib/pr_policy.py) against throwaway git
          # repositories, through the real committed and committed.toml.
          pr-policy =
            scriptCheck pkgs "pr-policy"
              {
                tools = [
                  pkgs.git
                  pkgs.committed
                ];
              }
              ''
                export HOME="$TMPDIR" GIT_CONFIG_GLOBAL=/dev/null
                ${pkgs.python3.interpreter} -I ${./tests/test_pr_policy.py} ${./lib/pr_policy.py} ${./committed.toml}
              '';

          # The workflows: actionlint (with shellcheck over each `run:`) and
          # zizmor offline, with .github/zizmor.yml (every `uses:` SHA-pinned).
          workflows =
            scriptCheck pkgs "workflows"
              {
                tools = with pkgs; [
                  git
                  actionlint
                  shellcheck
                  zizmor
                ];
              }
              ''
                export HOME="$TMPDIR" GIT_CONFIG_GLOBAL=/dev/null
                mkdir repo
                cp -r ${./.github} repo/.github
                chmod -R u+w repo
                cd repo
                git init -q
                actionlint
                zizmor --offline --config .github/zizmor.yml .github/workflows
              '';

          # The scaffolder, offline (odoo-nix-sources and uv stood in, git
          # real): every flag and branch, its exit codes, and what it writes
          # (tests/odoo-init.sh).
          scaffold =
            scriptCheck pkgs "scaffold"
              {
                tools = with pkgs; [
                  git
                  jq
                  gawk
                  gnused
                  gnugrep
                  coreutils
                  python3
                ];
              }
              ''
                bash ${./tests/odoo-init.sh} ${(odooInit pkgs).script}
              '';

          # Its pieces, without git remotes, uv or a terminal: the command
          # line, the config and presets schemas, the template, the OCA
          # catalog (odoo_nix_cli.oca), mode and series detection, and the
          # prompts (rich faked). On odoo-init's interpreter and on every one
          # a preset runs the `odoo` CLI on, which imports odoo_nix_cli.oca.
          odoo-init-unit = scriptCheck pkgs "odoo-init-unit" { tools = [ pkgs.git ]; } (
            lib.concatMapStrings
              (py: ''
                ODOO_PRESETS=${./lib/odoo-presets.json} ${py.interpreter} -I ${./tests/test_odoo_init.py} \
                  ${cliPackage pkgs} ${./data} ${./templates/project}
              '')
              (
                lib.unique (
                  [ pkgs.python3 ]
                  ++ map (py: pkgs.${py}) (base.python.interpreters { presets = [ ./lib/odoo-presets.json ]; })
                )
              )
          );

          # `odoo module add`, `add-bundle` and `remove`, offline: the `odoo`
          # CLI with the workspace scripts and no Odoo, odoo-nix-sources stood
          # in, git real, uv real and offline (tests/module.sh).
          odoo-module-cli =
            let
              python = pkgs.${presets."18.0".python};
              cli = import ./lib/cli.nix {
                inherit pkgs lib python;
                name = "odoo-nix-module-cli";
                rawOdooBin = "${pkgs.coreutils}/bin/false";
                targetPythonEnv = python;
                inherit base;
                cliScripts = import ./lib/cli-scripts.nix {
                  inherit lib pkgs;
                  odooSeries = "18.0";
                  ocaDataset = ./data/oca-modules.json;
                  bundlesFile = ./data/oca-bundles.json;
                  layout = {
                    coreSrc = "odoo";
                    externalDir = "modules";
                    customDir = "custom";
                  };
                  python = "${pkgs.python3}/bin/python";
                  # The stand-in on PATH (tests/module.sh).
                  sourcesBin = "odoo-nix-sources";
                  buildDeps = import ./lib/build-deps.nix { inherit pkgs base; };
                };
              };
            in
            scriptCheck pkgs "odoo-module-cli"
              {
                # python3: uv's interpreter, as the dev shell has one on PATH.
                tools = with pkgs; [
                  git
                  gnused
                  gnugrep
                  coreutils
                  python3
                ];
              }
              ''
                bash ${./tests/module.sh} ${cli}/bin/odoo ${./templates/project/pyproject.toml}
              '';

          # Their pieces (lib/odoo_nix_cli/workspace): the config schema, what a
          # removal takes, and the in-use check against databases with Odoo
          # stood in. On each interpreter a preset runs the CLI on, with click.
          odoo-module-unit = scriptCheck pkgs "odoo-module-unit" { tools = [ pkgs.git ]; } (
            lib.concatMapStrings (py: ''
              ${
                base.python.rich {
                  python = pkgs.${py};
                  extraPackages = ps: [ ps.click ];
                }
              }/bin/python3 -I ${./tests/test_workspace.py} ${cliPackage pkgs} ${./data}
            '') (base.python.interpreters { presets = [ ./lib/odoo-presets.json ]; })
          );

          # odoo-nix-bootstrap and the template's .envrc: a fresh clone, its
          # tree dirty, gets its submodules from the pinned odoo-nix-sources
          # before `use flake`; `nix` is a stub (tests/bootstrap.sh).
          bootstrap =
            scriptCheck pkgs "bootstrap"
              {
                tools = [
                  pkgs.git
                  pkgs.gawk
                ];
              }
              ''
                bash ${./tests/bootstrap.sh} ${lib.getExe (shellTools pkgs).bootstrap} \
                  ${./templates/project/.envrc} odoo-nix
              '';

          # odoo-nix-sources (python-devops-nix's lib.sources, configured in
          # lib/shell-tools.nix): odoo-nix's acceptance test of it.
          sources =
            scriptCheck pkgs "sources"
              {
                tools = [
                  pkgs.git
                  pkgs.findutils
                  pkgs.gawk
                ];
              }
              ''
                bash ${./tests/sources.sh} ${lib.getExe (shellTools pkgs).sources}
              '';
        }
        // lib.optionalAttrs isLinux {
          # The dev datadir's btrfs NOCOW attribute (python-devops-nix's
          # lib.dbNocow, configured in lib/shell-tools.nix): arranged for a
          # datadir initdb has yet to create, reported on one holding a
          # cluster, and the one-off copy that fixes that. The base's own
          # test, run against odoo-nix's command. Branches on the sandbox's own
          # filesystem, so it checks the real attribute on a btrfs builder and
          # the no-op path everywhere else (TMPDIR=<btrfs dir> to run the
          # former by hand).
          db-nocow =
            scriptCheck pkgs "db-nocow"
              {
                tools = [
                  pkgs.e2fsprogs
                  pkgs.procps
                ];
              }
              ''
                bash ${inputs.python-devops-nix}/tests/db-nocow.sh \
                  ${lib.getExe (shellTools pkgs).dbNocow} parent pidfile odoo-nix
              '';
        }
        // perSeries
        // evalChecks "" (
          # lib/bootstrap-lock.nix: the pinned odoo-nix, from the lock alone.
          let
            pinned = import ./lib/bootstrap-lock.nix;
            lock = {
              version = 7;
              root = "root";
              nodes = {
                root.inputs = {
                  odoo-nix = "odoo-nix_2";
                  nixpkgs = [
                    "odoo-nix_2"
                    "nixpkgs"
                  ];
                };
                odoo-nix_2.locked = {
                  type = "github";
                  owner = "Avunu";
                  repo = "odoo-nix";
                  rev = "5557173c4cfb5cd2e245763c181236678c5293a4";
                  narHash = "sha256-OlOiOcu7OpTvDBKYSHgEIQ9HbJQLCVoGKvLLMlhjKPA=";
                  lastModified = 1792505124;
                };
              };
            };
          in
          {
            bootstrap-lock-renamed-node = {
              expected = "github:Avunu/odoo-nix/5557173c4cfb5cd2e245763c181236678c5293a4?narHash=sha256-OlOiOcu7OpTvDBKYSHgEIQ9HbJQLCVoGKvLLMlhjKPA%3D";
              actual = pinned {
                inherit lock;
                input = "odoo-nix";
              };
            };
            bootstrap-lock-follows = {
              expected = false;
              actual =
                (builtins.tryEval (pinned {
                  inherit lock;
                  input = "nixpkgs";
                })).success;
            };
            bootstrap-lock-no-input = {
              expected = false;
              actual =
                (builtins.tryEval (pinned {
                  inherit lock;
                  input = "frappe-nix";
                })).success;
            };
          }
        )
        // evalChecks "" (
          import ./tests/lock-audit.nix {
            inherit pkgs lib inputs;
            python = pkgs.${presets."18.0".python};
          }
        )
        // evalChecks "" (
          import ./tests/secrets-module.nix {
            inherit pkgs lib inputs;
            inherit (self.lib) mkFlake;
          }
        )
        // lib.optionalAttrs isLinux (
          evalChecks "" (
            import ./tests/module-eval.nix {
              inherit pkgs base;
              odooModule = nixosModule;
            }
          )
        )
        // lib.optionalAttrs isLinux (
          evalChecks "" (
            import ./tests/restore-eval.nix {
              inherit pkgs inputs;
              inherit (self.lib) mkFlake;
            }
          )
        )
        // lib.optionalAttrs isLinux (
          evalChecks "" (
            import ./tests/containers-eval.nix {
              inherit pkgs inputs;
              inherit (self.lib) mkFlake;
            }
          )
        )
        // lib.optionalAttrs isLinux (
          evalChecks "" (
            import ./tests/python-default-eval.nix {
              inherit pkgs inputs;
              inherit (self.lib) mkFlake;
            }
          )
        )
        // lib.optionalAttrs isLinux (
          evalChecks "" (
            import ./tests/shell-tree-eval.nix {
              inherit pkgs lib inputs;
              inherit (self.lib) mkFlake;
            }
          )
        )
        // lib.optionalAttrs isLinux (
          evalChecks "" (
            import ./tests/settings-eval.nix {
              inherit pkgs lib inputs;
              inherit (self.lib) mkFlake;
            }
          )
        )
        // lib.optionalAttrs isLinux (
          evalChecks "" (
            import ./tests/renames-eval.nix {
              inherit pkgs lib inputs;
              inherit (self.lib) mkFlake;
            }
          )
        )
        // lib.optionalAttrs isLinux {
          # The nginx/socket contract test, against a stub Odoo (see the file
          # header). Real-Odoo module tests are odoo-service-<major>.
          nginx = (checksFor pkgs).nixosTest "nginx" (
            import ./tests/nginx.nix {
              inherit pkgs;
              odooModule = nixosModule;
            }
          );
        }
      );

      # `nix run github:<owner>/odoo-nix` scaffolds a new Odoo + OCA project.
      # sources and bootstrap are the submodule checkout, outside the dev
      # shell: a project's .envrc runs bootstrap on a fresh clone, before Nix
      # evaluates the project's flake (lib/bootstrap.sh), and bootstrap runs
      # sources from the revision the project's flake.lock pins.
      packages = forAllSystems (pkgs: rec {
        odoo-init = odooInit pkgs;
        inherit (shellTools pkgs) sources bootstrap;
        odoo-ls = import ./lib/odoo-ls.nix {
          inherit pkgs;
          inherit (pkgs) lib;
          src = inputs.odoo-ls-src;
          typeshedSrc = inputs.odoo-ls-typeshed;
        };
        default = odoo-init;
      });

      apps = forAllSystems (
        pkgs:
        let
          program = "${odooInit pkgs}/bin/odoo-init";
          app = {
            type = "app";
            inherit program;
            meta.description = "Scaffold a new odoo-nix project (Odoo OCB + OCA)";
          };
          relockOdooLs = import ./tests/relock-odoo-ls.nix {
            inherit pkgs;
            src = inputs.odoo-ls-src;
          };
        in
        {
          default = app;
          odoo-init = app;
          # `nix run github:Avunu/odoo-nix#bootstrap -- ROOT`: a fresh clone's
          # submodules, before its flake is evaluated (a project's .envrc).
          bootstrap = {
            type = "app";
            program = pkgs.lib.getExe (shellTools pkgs).bootstrap;
            meta.description = "Check out a fresh clone's submodules before Nix evaluates the project's flake";
          };
          # `nix run github:Avunu/odoo-nix/<rev>#sources -- enter --treeless odoo ROOT`:
          # the dev shell's submodule checkout, outside it.
          sources = {
            type = "app";
            program = pkgs.lib.getExe (shellTools pkgs).sources;
            meta.description = "Check out a project's submodules as shell entry does (odoo-nix-sources)";
          };
          # `nix run .#relock [-- --upgrade]`: regenerate tests/fixtures/*/uv.lock
          # against the pinned OCB inputs (needs network; never runs in a check).
          # odoo-nix's own fixtures; a project re-locks with `odoo project relock`.
          relock = {
            type = "app";
            program = "${relock pkgs}/bin/odoo-nix-relock";
            meta.description = "Re-lock the test fixtures against the pinned OCB inputs";
          };
          # `nix run .#relock-odoo-ls`: regenerate lib/odoo-ls-Cargo.lock against
          # the pinned odoo-ls-src input (needs network; never runs in a check).
          relock-odoo-ls = {
            type = "app";
            program = "${relockOdooLs}/bin/odoo-nix-relock-odoo-ls";
            meta.description = "Re-lock lib/odoo-ls-Cargo.lock against the pinned odoo-ls-src input";
          };
        }
      );

      # `nix fmt`: the given files, or every file checks.nix-lint covers.
      formatter = forAllSystems (
        pkgs:
        pkgs.writeShellScriptBin "odoo-nix-fmt" ''
          if [ "$#" -gt 0 ]; then exec ${pkgs.lib.getExe pkgs.nixfmt-rs} "$@"; fi
          { ${nixFiles pkgs} } | ${pkgs.findutils}/bin/xargs -0 ${pkgs.lib.getExe pkgs.nixfmt-rs}
        ''
      );

      # For working on odoo-nix itself (consumers get devenv shells from the
      # flake-parts module). uv here is the same nixpkgs uv the scripts use, so
      # the lock revision it writes is the one the pinned uv2nix reads.
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.uv
            pkgs.nixfmt-rs
            pkgs.statix
            pkgs.deadnix
            pkgs.python3
            pkgs.jq
            (relock pkgs)
          ];
          OCB_18 = "${inputs.ocb-18}";
          OCB_19 = "${inputs.ocb-19}";
          OCB_20 = "${inputs.ocb-20}";
          shellHook = ''
            echo "odoo-nix dev shell: ocb-18 -> $OCB_18"
            echo "                    ocb-19 -> $OCB_19"
            echo "                    ocb-20 -> $OCB_20"
            echo "  nix flake check -L        run everything (needs KVM for the VM tests)"
            echo "  nix fmt                   format the Nix files (checks.nix-lint enforces it)"
            echo "  odoo-nix-relock           re-lock tests/fixtures/*/uv.lock"
          '';
        };
      });
    };
}
