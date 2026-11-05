{
  description = "project-b — Odoo (OCB) + OCA project (odoo-nix)";

  inputs = {
    # odoo/ + modules/* are git submodules; expose their contents to the
    # flake source tree so the Nix engine can derive addons_path from them.
    self.submodules = true;
    odoo-nix.url = "github:Avunu/odoo-nix";
    # flake-parts resolves perSystem `pkgs` from an input literally named `nixpkgs`.
    nixpkgs.follows = "odoo-nix/nixpkgs";
  };

  nixConfig = {
    extra-substituters = [ "https://devenv.cachix.org" ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  # This flake exposes:
  #   packages.<system>.default    — the deployable Odoo (builtOdoo)
  #   packages.<system>.odooConf   — the synthesized odoo.conf
  #
  # Deployment servers import the NixOS module directly from odoo-nix:
  #   imports = [ odoo-nix.nixosModules.default ];
  #   services.odoo-nix.package = projectFlake.packages.x86_64-linux.default;

  outputs =
    { self, odoo-nix, ... }@inputs:
    odoo-nix.lib.mkFlake { inherit inputs; } (
      { ... }:
      {
        imports = [ odoo-nix.flakeModules.default ];

        # Backup credentials (S3) for `odoo db restore`, encrypted with agenix.
        # Declare who may read them, then run `setup-backup-access` in the dev
        # shell. See "Backups & restore" in the odoo-nix README.
        # odoo-nix.secrets = {
        #   dir = ./secrets;
        #   recipients.you = "ssh-ed25519 AAAA… you@host";
        # };

        systems = [
          "aarch64-darwin"
          "aarch64-linux"
          "x86_64-linux"
        ];

        perSystem =
          { pkgs, ... }:
          {
            odoo-nix = {
              enable = true;
              name = "odoo-project-b";
              workspaceRoot = ./.;
              odooSeries = "18.0";
              python = pkgs.python311;

              settings.dbName = "project_b";

              # A stable server: no --dev, so no auto-restart on .py changes and
              # minified assets. Stop the `odoo` process in process-compose first
              # (it holds the HTTP port, $ODOO_NIX_HTTP_PORT).
              extraScripts.odoo-demo = {
                description = "Run Odoo without --dev (for demos)";
                exec = ''
                  port="''${ODOO_NIX_HTTP_PORT:-8069}"
                  if (exec 3<>/dev/tcp/127.0.0.1/"$port") 2>/dev/null; then
                    echo "Port $port is in use. Stop the 'odoo' process in process-compose first." >&2
                    exit 1
                  fi
                  exec python "$REPO_ROOT/odoo/odoo-bin" -c "$REPO_ROOT/odoo.conf" "$@"
                '';
              };

              # Build production OCI images with `nix build .#builtOdoo` and the
              # container outputs once enabled:
              # containers.enable = true;
            };
          };
      }
    );
}
