# `nix run .#relock-odoo-ls`: regenerate lib/odoo-ls-Cargo.lock against the
# pinned odoo-ls-src input. Needs network (crates.io + the git dependency
# repos) and so runs on the developer's machine, never in a check -- a
# drifted or force-pushed lockfile instead simply fails `nix build .#odoo-ls`
# outright, which is the lighter-weight equivalent of OCB's lock-fresh-<major>
# check for this input. odoo-ls does not commit a Cargo.lock upstream
# (gitignored there), so this is the only way odoo-nix's copy gets refreshed.
{
  pkgs,
  src,
}:
pkgs.writeShellApplication {
  name = "odoo-nix-relock-odoo-ls";
  runtimeInputs = [
    pkgs.cargo
    pkgs.rustc
    pkgs.coreutils
  ];
  text = ''
    root="$(git rev-parse --show-toplevel)"
    work="$(mktemp -d)"
    trap 'rm -rf "$work"' EXIT

    cp -r --no-preserve=mode "${src}/server" "$work/server"
    (
      cd "$work/server"
      echo "==> cargo generate-lockfile (odoo-ls @ ${src})"
      cargo generate-lockfile
    )
    cp "$work/server/Cargo.lock" "$root/lib/odoo-ls-Cargo.lock"

    echo "Done. Review and commit lib/odoo-ls-Cargo.lock."
    echo "If lib/odoo-ls.nix pins output hashes for its git dependencies (it"
    echo "currently uses allowBuiltinFetchGit instead, so this should not be"
    echo "necessary), refresh those too."
  '';
}
