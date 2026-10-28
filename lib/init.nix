# Scaffolder for odoo-nix projects — the `nix run` entry point.
#
# Produces an `odoo-init` executable that writes a new project (a thin
# odoo-nix wrapper flake, OCB + the selected OCA repos as git submodules with
# their transitive dependency repos resolved from the OCA catalog, a generated
# pyproject.toml and a uv.lock), or brings an existing Odoo tree in odoo-nix's
# layout into odoo-nix. The mode is detected from the target directory.
#
# The scaffolder itself is Python, `odoo_nix_cli.init` (lib/odoo_nix_cli/init,
# with the OCA catalog in lib/odoo_nix_cli/oca.py). This file is its glue: the
# store paths it needs, as the JSON ODOO_NIX_INIT_CONFIG names, and the
# commands it runs on PATH.
{ pkgs, base }:

let
  inherit (pkgs) lib;

  # odoo_nix_cli as a Python module of the interpreter below, so odoo-init runs
  # as `python -I -m` (lib/cli-module.nix).
  cliModule = import ./cli-module.nix { inherit pkgs base; };

  # The tool interpreter, with rich for the prompts.
  python = base.python.rich {
    python = pkgs.python3;
    extraPackages = ps: [ (cliModule ps) ];
  };

  # What odoo-init reads (lib/odoo_nix_cli/init/config.py); it refuses a
  # missing or an unknown key.
  config = pkgs.writeText "odoo-init.json" (
    builtins.toJSON {
      presets = "${./odoo-presets.json}";
      template = "${../templates/project}";
      ocaDataset = "${../data/oca-modules.json}";
      ocaBundles = "${../data/oca-bundles.json}";
      ocaSources = "${./oca_sources.py}";
      buildDeps = lib.getExe (import ./build-deps.nix { inherit pkgs base; });
    }
  );

  launch = ''
    ODOO_NIX_INIT_CONFIG=${config} exec ${python}/bin/python3 -I -m odoo_nix_cli.init "$@"
  '';
in
pkgs.writeShellApplication {
  name = "odoo-init";
  runtimeInputs = [
    # odoo-nix-sources: the first clone of OCB and each OCA repo.
    (import ./shell-tools.nix { inherit pkgs base; }).sources
    pkgs.git
    pkgs.uv
  ];
  text = launch;
  passthru = {
    # The launcher without the PATH writeShellApplication pins, so a test can
    # put stand-ins for uv and odoo-nix-sources in front (tests/odoo-init.sh).
    script = pkgs.writeText "odoo-init.sh" launch;
    # The interpreter, with odoo_nix_cli importable (tests/test_odoo_init.py).
    inherit python;
  };
  meta = {
    description = "Scaffold an odoo-nix project, or bring an existing Odoo tree into odoo-nix";
    mainProgram = "odoo-init";
  };
}
