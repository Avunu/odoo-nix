# Scaffolder for new odoo-nix projects — the `nix run` entry point.
#
# Produces an `odoo-init` executable that interactively (or via flags) writes a
# new project: a thin odoo-nix wrapper flake, OCB + selected OCA repos as git
# submodules (with their transitive dependency repos resolved from the OCA
# catalog), a generated pyproject.toml, and a uv.lock.
{ pkgs, base }:

let
  # Bake the presets, template dir, OCA dataset + bundles, shared helper lib,
  # and the python-dep tool store paths into the placeholders.
  text =
    builtins.replaceStrings
      [
        "@PRESETS@"
        "@TEMPLATE@"
        "@OCA_DATASET@"
        "@OCA_BUNDLES@"
        "@OCA_LIB@"
        "@OCA_SOURCES@"
        "@UV_BUILD_DEPS@"
      ]
      [
        "${./odoo-presets.json}"
        "${../templates/project}"
        "${../data/oca-modules.json}"
        "${../data/oca-bundles.json}"
        "${./oca-lib.sh}"
        "${./oca_sources.py}"
        "${pkgs.lib.getExe (import ./build-deps.nix { inherit pkgs base; })}"
      ]
      (builtins.readFile ./odoo-init.sh);
in
pkgs.writeShellApplication {
  name = "odoo-init";
  inherit text;
  # The script without the PATH writeShellApplication pins, so a test can
  # put stand-ins for git and uv in front (tests/odoo-init.sh).
  passthru.script = pkgs.writeText "odoo-init.sh" text;
  runtimeInputs = with pkgs; [
    git
    uv
    gum
    jq
    gawk
    gnused
    gnugrep
    coreutils
    python3
  ];
}
