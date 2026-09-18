# odoo_ls_server -- the Rust-based Odoo language server (github.com/odoo/odoo-ls).
#
# Built from server/Cargo.toml (not a workspace root -- buildAndTestSubdir pushes
# cargo into it for the build/check phases; CARGO_TARGET_DIR stays at the repo
# root, so cargoInstallHook finds the built binary regardless). Cargo.lock isn't
# committed upstream (gitignored there), so odoo-nix vendors its own alongside
# this file; its two git-sourced dependency groups (ruff_* pinned to
# astral-sh/ruff, lsp-server pinned to rust-analyzer) are fetched via
# allowBuiltinFetchGit, content-addressed by the lockfile's own pinned commit
# SHAs -- no manually-maintained per-crate output hashes to keep in sync.
#
# In LSP-server mode (what every editor spawns) odoo-ls looks for
# typeshed/{stdlib,stubs} and additional_stubs next to its own executable,
# resolved via current_exe(). Its --stdlib/--stubs/--python CLI flags are read
# only in one-shot `--parse` mode, so they cannot be used to point a running
# server at these paths -- postInstall bakes them in next to the binary instead.
#
# Usage:
#   import ./lib/odoo-ls.nix {
#     inherit pkgs lib;
#     src = inputs.odoo-ls-src;              # flake = false source tree, pinned tag
#     typeshedSrc = inputs.odoo-ls-typeshed;  # flake = false source tree, pinned rev
#   }

{
  pkgs,
  lib,
  src,
  typeshedSrc,
}:

let
  # Without --logs-directory, the server writes its rolling log files next to
  # its own executable (<exe_dir>/logs) -- which is the read-only Nix store,
  # and it panics on startup trying to create that directory. It only honours
  # --logs-directory when the given path already *exists* (it never creates
  # one itself), so the real binary is wrapped rather than just handed a
  # default flag.
  wrapper = pkgs.writeShellScript "odoo-ls-wrapper" ''
    set -euo pipefail
    log_dir="''${XDG_STATE_HOME:-$HOME/.local/state}/odoo-ls/logs"
    mkdir -p "$log_dir"
    exec "$(dirname "$(readlink -f "$0")")/.odoo_ls_server-unwrapped" --logs-directory "$log_dir" "$@"
  '';
in
pkgs.rustPlatform.buildRustPackage {
  pname = "odoo-ls";
  version = "1.4.0";
  inherit src;

  # Cargo.toml lives at server/Cargo.toml, not the repo root, and isn't part
  # of any workspace. cargoRoot tells cargoSetupHook where to look for
  # Cargo.lock and the vendored deps; buildAndTestSubdir is what actually
  # pushd's into it for the build/check phases (CARGO_TARGET_DIR stays fixed
  # at the repo root either way, so cargoInstallHook still finds the binary).
  cargoRoot = "server";
  buildAndTestSubdir = "server";

  cargoLock = {
    lockFile = ./odoo-ls-Cargo.lock;
    allowBuiltinFetchGit = true;
  };

  # Cargo.lock isn't committed upstream at all (gitignored there), so
  # cargoSetupHook's consistency check has nothing to compare its vendored
  # copy against unless we put one in place ourselves -- same file as
  # cargoLock.lockFile above, so the two always agree.
  postPatch = ''
    cp ${./odoo-ls-Cargo.lock} server/Cargo.lock
  '';

  # Skips the unused print_config_schema binary.
  cargoBuildFlags = [
    "--bin"
    "odoo_ls_server"
  ];

  # The crate's dev-dependencies (bench/test harnesses) aren't worth running
  # in the Nix sandbox for odoo-nix's purposes.
  doCheck = false;

  postInstall = ''
    mkdir -p $out/bin/typeshed
    cp -r ${typeshedSrc}/stdlib $out/bin/typeshed/stdlib
    cp -r ${typeshedSrc}/stubs $out/bin/typeshed/stubs
    cp -r ${src}/server/additional_stubs $out/bin/additional_stubs
    chmod -R u+w $out/bin/typeshed $out/bin/additional_stubs

    mv $out/bin/odoo_ls_server $out/bin/.odoo_ls_server-unwrapped
    install -m755 ${wrapper} $out/bin/odoo_ls_server
  '';

  meta = with lib; {
    description = "Language server for Odoo (odoo-ls)";
    homepage = "https://github.com/odoo/odoo-ls";
    license = licenses.lgpl3Plus;
    mainProgram = "odoo_ls_server";
    platforms = platforms.unix;
  };
}
