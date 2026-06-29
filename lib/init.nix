# Scaffolder for new odoo-nix projects — the `nix run` entry point.
#
# Produces an `odoo-init` executable that interactively (or via flags) writes a
# new project: a thin odoo-nix wrapper flake, OCB + selected OCA repos as git
# submodules (with their transitive dependency repos resolved from the OCA
# catalog), a generated pyproject.toml, and a uv.lock.
{ pkgs }:

pkgs.writeShellApplication {
  name = "odoo-init";
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
  # Bake the presets, template dir, OCA dataset, shared helper lib, and the
  # python-dep tool store paths into the placeholders.
  text = builtins.replaceStrings
    [ "@PRESETS@" "@TEMPLATE@" "@OCA_DATASET@" "@OCA_LIB@" "@OCA_PYDEPS@" "@UV_BUILD_DEPS@" ]
    [
      "${./odoo-presets.json}"
      "${../templates/project}"
      "${../data/oca-modules.json}"
      "${./oca-lib.sh}"
      "${./oca_pydeps.py}"
      "${./uv_build_deps.py}"
    ]
    (builtins.readFile ./odoo-init.sh);
}
