{
  description = "An example Odoo project (odoo-nix)";

  inputs = {
    # src/odoo + src/external/* are git submodules; expose their contents to the
    # flake source tree so the Nix engine can derive addons_path from them.
    self.submodules = true;
    odoo-nix.url = "github:Avunu/odoo-nix";
    nixpkgs.follows = "odoo-nix/nixpkgs";
  };

  nixConfig = {
    extra-substituters = [ "https://devenv.cachix.org" ];
    extra-trusted-public-keys = [
      "devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw="
    ];
  };

  outputs =
    { self, odoo-nix, ... }@inputs:
    odoo-nix.lib.mkFlake { inherit inputs; } (
      { ... }:
      {
        imports = [ odoo-nix.flakeModules.default ];

        systems = [
          "aarch64-darwin"
          "aarch64-linux"
          "x86_64-darwin"
          "x86_64-linux"
        ];

        perSystem =
          { pkgs, ... }:
          {
            odoo-nix = {
              enable = true;
              name = "odoo-project-a";
              dbName = "project_a";
              workspaceRoot = ./.;
              odooSeries = "18.0";
              python = pkgs.python311;
              pythonLibraries = {
                pycups = [
                  pkgs.pkg-config
                  pkgs.cups.dev
                ];
              };

              settings = {
                options = {
                  limit_time_real = "600";
                  log_level = "info";
                  logfile = "./odoo.log";
                  server_wide_modules = "base,web,queue_job";
                  without_demo = true;
                };
              };
              watch = {
                python = false;
              };
              devguard = {
                enable = true;
                egress = {
                  enable = true;
                  allowHosts = [
                    "example.com"
                  ];
                };
              };
            };
          };
      }
    );
}
