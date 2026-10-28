# odoo_nix_cli packaging -- wraps `rawOdooBin` (whatever "run the real
# odoo-bin" means for this caller) with the `odoo` CLI: db/module/project
# subcommands implemented in Python, everything else passed straight through
# to `rawOdooBin`. See lib/odoo_nix_cli/ for the Python side and
# lib/cli-scripts.nix for the workspace configuration it reads.
#
# Two shapes, both built from this one file:
#
#   - Production (mirrorTree = the lib/odoo.nix builtOdoo tree, rawOdooBin =
#     "${builtOdoo}/bin/odoo"): `cfg.package` (services.odoo-nix, the
#     container builder, addonsPathFor) expects to be handed the assembled
#     Odoo tree itself -- $out/odoo/odoo-bin, $out/custom, etc, at the same
#     relative paths builtOdoo already puts them -- so $out mirrors that tree
#     via top-level symlinks into the (unmodified) store path, with only
#     bin/ replaced. No 2GB copy; builtOdoo's own bin/odoo stays reachable at
#     its own store path as the passthrough target.
#
#   - Dev shell (mirrorTree = null, rawOdooBin = a small script that runs
#     $REPO_ROOT/<coreSrc> at runtime through devPythonEnv and
#     lib/raw-odoo.nix, with or without odoo-bin): the
#     live, editable-installed workspace checkout, not a Nix-assembled
#     snapshot -- the same thing the old lib/scripts.nix preamble resolved,
#     and nothing in the dev shell reads this package's passthru (odoo.conf's
#     addons_path is synthesized independently), so $out is just bin/ + lib/.
#
# click/rich are nixpkgs packages (python-devops-nix's lib.python.rich), not
# part of the *consuming* project's own uv-managed pyproject.toml/uv.lock (which
# lib/oca_sources.py auto-generates around OCA module deps only, and which
# the CLI's own tooling deps have no business coupling to). `cliPython` uses
# the SAME interpreter passed into lib/python.nix, so PYTHONPATH-prefixing
# onto `targetPythonEnv`'s site-packages (the project's real, resolved Odoo +
# deps) is a same-ABI, safe operation -- that's how `import odoo.service.db`
# works in-process without click/rich ever needing to be in the project's own
# lock.
#
# Usage:
#   import ./lib/cli.nix {
#     inherit pkgs lib python;
#     name = "myproject-odoo-cli";
#     rawOdooBin = "${builtOdoo}/bin/odoo";
#     targetPythonEnv = pythonEnvs.odooPythonEnv;
#     mirrorTree = builtOdoo;               # null for the dev-shell shape
#     cliScripts = import ./lib/cli-scripts.nix { ... };  # null: no workspace
#     base = inputs.python-devops-nix.lib;
#   }

{
  pkgs,
  lib,
  python,
  name,
  rawOdooBin,
  targetPythonEnv,
  mirrorTree ? null,
  # lib/cli-scripts.nix's { workspaceConfig }, or null: `odoo module
  # add|add-bundle|remove` and `odoo project update|relock` then fail with a
  # clear message instead of being wired to a workspace that assumes a git
  # checkout.
  cliScripts ? null,
  # inputs.python-devops-nix.lib: lib/cli-package.nix vendors its post-import
  # hook and backup fetch layer into the package (python-devops-nix
  # docs/library.md, design rule 6).
  base,
  # Remote restore (lib/odoo_nix_cli/backups.py): the rclone binary, and the
  # wrapper that runs a command with the backup-access secret decrypted.
  # Dev shell only; null elsewhere.
  rcloneBin ? null,
  withSecrets ? null,
  # The dev shell's TUI (python-devops-nix's lib.tui.script): `odoo ui`, and a
  # bare `odoo` at a terminal. Dev shell only; null elsewhere.
  tui ? null,
}:

let
  cliPython = base.python.rich {
    inherit python;
    extraPackages = ps: [ ps.click ];
  };

  # One space-joined string, not a multi-line here-string with an embedded
  # optionalString -- interleaving a possibly-empty Nix interpolation between
  # backslash-continued shell lines silently breaks the continuation when it
  # renders empty (the following line stops being part of the command). Each
  # element is pre-quoted here (not lib.escapeShellArgs, which would wrap
  # "$out/..." in single quotes and stop the shell from expanding $out).
  wrapperArgs = lib.concatStringsSep " " (
    [
      ''--add-flags "-m odoo_nix_cli"''
      ''--set ODOO_NIX_RAW_ODOO "${rawOdooBin}"''
    ]
    # The identity `odoo db migrate --if-needed` records in the database
    # (odoo_nix.migrated_build) and compares against on every start. Only
    # for the store-assembled shape: the dev shell runs editable code, whose
    # changes never change this package's store path, so it gets no fast
    # path and always runs change detection instead.
    ++ lib.optionals (mirrorTree != null) [
      ''--set ODOO_NIX_BUILD "$out"''
    ]
    ++ lib.optionals (cliScripts != null) [
      ''--set ODOO_NIX_WORKSPACE_CONFIG "${cliScripts.workspaceConfig}"''
    ]
    ++ lib.optionals (rcloneBin != null) [
      ''--set ODOO_NIX_RCLONE "${rcloneBin}"''
    ]
    ++ lib.optionals (withSecrets != null) [
      ''--set ODOO_NIX_WITH_SECRETS "${withSecrets}"''
    ]
    ++ lib.optionals (tui != null) [
      ''--set ODOO_NIX_TUI "${lib.getExe tui}"''
    ]
    ++ [
      ''--prefix PYTHONPATH : "${targetPythonEnv}/${python.sitePackages}"''
      ''--prefix PYTHONPATH : "$out/lib"''
    ]
  );

  mirrorCmd = lib.optionalString (mirrorTree != null) ''
    for entry in ${mirrorTree}/*; do
      name="$(basename "$entry")"
      [ "$name" = "bin" ] && continue
      ln -s "$entry" "$out/$name"
    done
  '';
in
pkgs.runCommand name
  {
    nativeBuildInputs = [ pkgs.makeWrapper ];
    passthru = lib.optionalAttrs (mirrorTree != null) (
      mirrorTree.passthru // { builtOdoo = mirrorTree; }
    );
  }
  ''
    mkdir -p $out
    ${mirrorCmd}
    mkdir -p $out/bin $out/lib
    cp -r ${import ./cli-package.nix { inherit pkgs base; }}/odoo_nix_cli $out/lib/odoo_nix_cli
    makeWrapper ${cliPython}/bin/python $out/bin/odoo ${wrapperArgs}
  ''
