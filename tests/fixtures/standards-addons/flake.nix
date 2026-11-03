{
  description = "fixture-addons — Odoo addons, developed with odoo-nix (addons mode)";

  inputs = {
    odoo-nix.url = "github:Avunu/odoo-nix";
    # flake-parts resolves perSystem `pkgs` from an input literally named `nixpkgs`.
    nixpkgs.follows = "odoo-nix/nixpkgs";

    # OCB and every repository the addons depend on, on the series branch
    # (.odoo-series). `flake = false`: source trees, pinned by flake.lock.
    # `nix flake update` moves them; follow it with `odoo project relock`.
    ocb = {
      url = "github:OCA/OCB/18.0";
      flake = false;
    };
    oca-queue = {
      url = "github:OCA/queue/18.0";
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
  #   devShells.<system>.default — devenv: PostgreSQL, Odoo, Mailpit
  #   apps.<system>.relock       — regenerate nix/pyproject.toml and nix/uv.lock
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
              name = "fixture-addons";
              workspaceRoot = ./.;
              # The one per-branch fact: the series this branch's code targets.
              odooSeries = lib.fileContents ./.odoo-series;
              addons.enable = true;
              coreSource = inputs.ocb;
              externalSources = [
                {
                  name = "queue";
                  src = inputs.oca-queue;
                }
              ];
            };
          };
      }
    );
}
