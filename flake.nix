{
  description = "Reusable Nix infrastructure for Odoo (OCB) + OCA projects";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    devenv.url = "github:cachix/devenv";
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
    # source tree, in the shape the README's "OCB as a flake input" section   #
    # prescribes for consumers. flake.lock records the revision; dependabot   #
    # moves it weekly. tests/fixtures/<series>/uv.lock was locked against a   #
    # revision of this tree; checks.lock-fresh-<major> says when they drift.  #
    # ---------------------------------------------------------------------- #
    ocb-18 = {
      url = "github:OCA/OCB/18.0";
      flake = false;
    };
    ocb-19 = {
      url = "github:OCA/OCB/19.0";
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
      odooInit = pkgs: import ./lib/init.nix { inherit pkgs; };

      # Series -> pinned OCB. The interpreter per series comes from the same
      # presets file odoo-init uses, so the fixtures cannot disagree with it.
      ocbInputs = {
        "18.0" = inputs.ocb-18;
        "19.0" = inputs.ocb-19;
      };
      presets = builtins.fromJSON (builtins.readFile ./lib/odoo-presets.json);

      # odoo-nix's own addons (dev_mailcatch), as their own store path -- the
      # same expression modules/devenv.nix uses, for the same reason.
      odooNixAddons = builtins.path {
        path = ./addons;
        name = "odoo-nix-addons";
      };

      # One small derivation per assertion: `nix flake check` names what
      # broke, and a slow Odoo run cannot mask a fast check. `script` runs in
      # checkPhase so hooks that attach to preCheck -- postgresqlTestHook --
      # work. HOME and CWD are the build directory.
      mkCheck =
        pkgs: name:
        {
          nativeCheckInputs ? [ ],
          env ? { },
        }:
        script:
        pkgs.stdenvNoCC.mkDerivation (
          {
            name = "odoo-nix-check-${name}";
            dontUnpack = true;
            dontConfigure = true;
            dontBuild = true;
            dontFixup = true;
            doCheck = true;
            inherit nativeCheckInputs;
            checkPhase = ''
              runHook preCheck
              set -o pipefail
              export HOME="$NIX_BUILD_TOP"
              cd "$NIX_BUILD_TOP"
              ${script}
              runHook postCheck
            '';
            # Keep the Odoo log (if any) in the output for inspection.
            installPhase = ''
              mkdir -p $out
              if [ -e odoo.log ]; then cp odoo.log $out/; fi
            '';
          }
          // env
        );

      # A pure-eval assertion as a derivation: the two sides are serialised at
      # evaluation time and compared in the sandbox, so a mismatch fails the
      # named check rather than aborting the whole `nix flake check` evaluation.
      mkEvalCheck =
        pkgs: name:
        { expected, actual }:
        pkgs.runCommandLocal "odoo-nix-eval-${name}"
          {
            expected = builtins.toJSON expected;
            actual = builtins.toJSON actual;
          }
          ''
            if [ "$expected" != "$actual" ]; then
              echo "eval check '${name}' failed" >&2
              echo "  expected: $expected" >&2
              echo "  actual:   $actual" >&2
              exit 1
            fi
            touch $out
          '';

      relock = pkgs: import ./tests/relock.nix { inherit pkgs ocbInputs presets; };
    in
    {
      flakeModules.default = ./modules/flake-module.nix;

      nixosModules.default = ./modules/nixos.nix;

      lib = {
        # Wrapper around flake-parts.lib.mkFlake that merges odoo-nix's own inputs
        # with the consumer's, so a consuming flake only declares odoo-nix +
        # nixpkgs.follows. Mirrors frappe-nix.lib.mkFlake.
        mkFlake =
          {
            inputs ? { },
            ...
          }@consumerArgs:
          config:
          flake-parts.lib.mkFlake {
            inputs = self.inputs // inputs;
          } config;

        # Composable Python package overrides for native-build packages.
        overrides = import ./lib/overrides.nix;

        # The addons_path synthesis core, exposed for testing / advanced use.
        addons = import ./lib/addons.nix;

        # The odoo-ls (Odoo language server) package builder.
        odoo-ls = import ./lib/odoo-ls.nix;
      };

      # checks.<system>:
      #   eval-addons-*, eval-odoo-conf-*, odoo-conf-render   pure library tests (all systems)
      #   eval-*-<major>, lock-fresh-<major>                  per-series, no Odoo run (all systems)
      #   builtOdoo-<major>, odoo-init-<major>, odoo-test-<major>,
      #   module-odoo-<major>, module-nginx                   run Odoo / a VM (Linux only)
      checks = forAllSystems (
        pkgs:
        let
          inherit (pkgs) lib;
          isLinux = pkgs.stdenv.hostPlatform.isLinux;
          evalTests = import ./tests/eval.nix { inherit pkgs lib; };
          evalChecks =
            suffix:
            lib.mapAttrs' (n: v: lib.nameValuePair "eval-${n}${suffix}" (mkEvalCheck pkgs "${n}${suffix}" v));
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
                mkCheck = mkCheck pkgs;
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
          odoo-conf-render = mkCheck pkgs "odoo-conf-render" { } ''
            f=${evalTests.rendered}
            grep -qE '^\[dev_mailcatch\]$' "$f"
            grep -qE '^enabled\s*=\s*True$' "$f"
            grep -qE '^port\s*=\s*2525$' "$f"
            grep -qE '^without_demo\s*=\s*True$' "$f"
            grep -qE '^server_wide_modules\s*=\s*base,rpc,web,dev_mailcatch$' "$f"
            grep -qE '^proxy_mode\s*=\s*True$' "$f"
            ! grep -qE '^log_db\s*=' "$f"
            ! grep -qE '^db_password\s*=' "$f"
            grep -qE '^http_interface\s*=\s*127\.0\.0\.1$' "$f"
            grep -qE '^limit_time_real\s*=\s*1200$' "$f"
          '';
        }
        // perSeries
        // lib.optionalAttrs isLinux {
          # The nginx/socket contract test, against a stub Odoo (see the file
          # header). Real-Odoo module tests are module-odoo-<major>.
          module-nginx = import ./tests/module-nginx.nix {
            inherit pkgs;
            odooModule = ./modules/nixos.nix;
          };
        }
      );

      # `nix run github:<owner>/odoo-nix` scaffolds a new Odoo + OCA project.
      packages = forAllSystems (pkgs: rec {
        odoo-init = odooInit pkgs;
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
          # `nix run .#relock [-- --upgrade]`: regenerate tests/fixtures/*/uv.lock
          # against the pinned OCB inputs (needs network; never runs in a check).
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

      # For working on odoo-nix itself (consumers get devenv shells from the
      # flake-parts module). uv here is the same nixpkgs uv the scripts use, so
      # the lock revision it writes is the one the pinned uv2nix reads.
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.uv
            pkgs.nixfmt
            pkgs.python3
            pkgs.jq
            (relock pkgs)
          ];
          OCB_18 = "${inputs.ocb-18}";
          OCB_19 = "${inputs.ocb-19}";
          shellHook = ''
            echo "odoo-nix dev shell: ocb-18 -> $OCB_18"
            echo "                    ocb-19 -> $OCB_19"
            echo "  nix flake check -L        run everything (needs KVM for module-*)"
            echo "  odoo-nix-relock           re-lock tests/fixtures/*/uv.lock"
          '';
        };
      });
    };
}
