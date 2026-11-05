{
  description = "vertical-auto-repair-addons: Avunu's Odoo addons, developed with odoo-nix (addons mode)";

  inputs = {
    odoo-nix.url = "github:Avunu/odoo-nix/feat/addons-mode";
    # flake-parts resolves perSystem `pkgs` from an input literally named `nixpkgs`.
    nixpkgs.follows = "odoo-nix/nixpkgs";

    # OCB and every repository the addons depend on, on this branch's series
    # (.odoo-series): source trees (`flake = false`) pinned by flake.lock.
    # `nix flake update` moves them; follow it with `odoo project relock`.
    # Generated from the addons' `depends`: keep it in step with them.
    ocb = {
      url = "github:OCA/OCB/18.0";
      flake = false;
    };
    avunu-edi-addons = {
      url = "github:Avunu/edi-addons/18.0";
      flake = false;
    };
    avunu-fleet-addons = {
      url = "github:Avunu/fleet-addons/18.0";
      flake = false;
    };
    avunu-repair-addons = {
      url = "github:Avunu/repair-addons/18.0";
      flake = false;
    };
    avunu-shopfloor-app-addons = {
      url = "github:Avunu/shopfloor-app-addons/18.0";
      flake = false;
    };
    avunu-web-addons = {
      url = "github:Avunu/web-addons/18.0";
      flake = false;
    };
    oca-calendar = {
      url = "github:OCA/calendar/18.0";
      flake = false;
    };
    oca-connector = {
      url = "github:OCA/connector/18.0";
      flake = false;
    };
    oca-edi = {
      url = "github:OCA/edi/18.0";
      flake = false;
    };
    oca-edi-framework = {
      url = "github:OCA/edi-framework/18.0";
      flake = false;
    };
    oca-fleet = {
      url = "github:OCA/fleet/18.0";
      flake = false;
    };
    oca-l10n-usa = {
      url = "github:OCA/l10n-usa/18.0";
      flake = false;
    };
    oca-project = {
      url = "github:OCA/project/18.0";
      flake = false;
    };
    oca-queue = {
      url = "github:OCA/queue/18.0";
      flake = false;
    };
    oca-repair = {
      url = "github:OCA/repair/18.0";
      flake = false;
    };
    oca-rest-framework = {
      url = "github:OCA/rest-framework/18.0";
      flake = false;
    };
    oca-server-auth = {
      url = "github:OCA/server-auth/18.0";
      flake = false;
    };
    oca-server-env = {
      url = "github:OCA/server-env/18.0";
      flake = false;
    };
    oca-server-tools = {
      url = "github:OCA/server-tools/18.0";
      flake = false;
    };
    oca-shopfloor-app = {
      url = "github:OCA/shopfloor-app/18.0";
      flake = false;
    };
    oca-timesheet = {
      url = "github:OCA/timesheet/18.0";
      flake = false;
    };
    oca-web = {
      url = "github:OCA/web/18.0";
      flake = false;
    };
    oca-web-api = {
      url = "github:OCA/web-api/18.0";
      flake = false;
    };
    muk-it-odoo-modules = {
      url = "github:muk-it/odoo-modules/18.0";
      flake = false;
    };
  };

  nixConfig = {
    extra-substituters = [ "https://devenv.cachix.org" ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  # Outputs:
  #   devShells.<system>.default  devenv: PostgreSQL, Odoo, Mailpit
  #   apps.<system>.relock        regenerate nix/pyproject.toml and nix/uv.lock
  outputs =
    { odoo-nix, ... }@inputs:
    odoo-nix.lib.mkFlake { inherit inputs; } (
      { ... }:
      {
        imports = [ odoo-nix.flakeModules.default ];

        systems = [
          "aarch64-darwin"
          "aarch64-linux"
          "x86_64-linux"
        ];

        perSystem =
          { lib, ... }:
          {
            odoo-nix = {
              enable = true;
              name = "vertical-auto-repair-addons";
              workspaceRoot = ./.;
              # The one per-branch fact: the series this branch's code targets.
              odooSeries = lib.fileContents ./.odoo-series;
              addons.enable = true;
              coreSource = inputs.ocb;
              externalSources = [
                {
                  name = "edi-addons";
                  src = inputs.avunu-edi-addons;
                }
                {
                  name = "fleet-addons";
                  src = inputs.avunu-fleet-addons;
                }
                {
                  name = "repair-addons";
                  src = inputs.avunu-repair-addons;
                }
                {
                  name = "shopfloor-app-addons";
                  src = inputs.avunu-shopfloor-app-addons;
                }
                {
                  name = "web-addons";
                  src = inputs.avunu-web-addons;
                }
                {
                  name = "calendar";
                  src = inputs.oca-calendar;
                }
                {
                  name = "connector";
                  src = inputs.oca-connector;
                }
                {
                  name = "edi";
                  src = inputs.oca-edi;
                }
                {
                  name = "edi-framework";
                  src = inputs.oca-edi-framework;
                }
                {
                  name = "fleet";
                  src = inputs.oca-fleet;
                }
                {
                  name = "l10n-usa";
                  src = inputs.oca-l10n-usa;
                }
                {
                  name = "project";
                  src = inputs.oca-project;
                }
                {
                  name = "queue";
                  src = inputs.oca-queue;
                }
                {
                  name = "repair";
                  src = inputs.oca-repair;
                }
                {
                  name = "rest-framework";
                  src = inputs.oca-rest-framework;
                }
                {
                  name = "server-auth";
                  src = inputs.oca-server-auth;
                }
                {
                  name = "server-env";
                  src = inputs.oca-server-env;
                }
                {
                  name = "server-tools";
                  src = inputs.oca-server-tools;
                }
                {
                  name = "shopfloor-app";
                  src = inputs.oca-shopfloor-app;
                }
                {
                  name = "timesheet";
                  src = inputs.oca-timesheet;
                }
                {
                  name = "web";
                  src = inputs.oca-web;
                }
                {
                  name = "web-api";
                  src = inputs.oca-web-api;
                }
                {
                  name = "muk-it-odoo-modules";
                  src = inputs.muk-it-odoo-modules;
                }
              ];
            };
          };
      }
    );
}
