# odoo_nix_cli packaging -- wraps `rawOdooBin` (whatever "run the real
# odoo-bin" means for this caller) with the `odoo` CLI: db/module/project
# subcommands implemented in Python, everything else passed straight through
# to `rawOdooBin`. See lib/odoo_nix_cli/ for the Python side and
# lib/cli-scripts.nix for the bash helpers module/project delegate to.
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
#   - Dev shell (mirrorTree = null, rawOdooBin = a small script that resolves
#     $REPO_ROOT/<coreSrc>/odoo-bin at runtime through devPythonEnv): the
#     live, editable-installed workspace checkout, not a Nix-assembled
#     snapshot -- the same thing the old lib/scripts.nix preamble resolved,
#     and nothing in the dev shell reads this package's passthru (odoo.conf's
#     addons_path is synthesized independently), so $out is just bin/ + lib/.
#
# click/rich are nixpkgs packages (lib/rich-python.nix), not part of the
# *consuming* project's own uv-managed pyproject.toml/uv.lock (which
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
#   }

{
  pkgs,
  lib,
  python,
  name,
  rawOdooBin,
  targetPythonEnv,
  mirrorTree ? null,
  # lib/cli-scripts.nix's { moduleAdd, moduleAddBundle, projectUpdate }, or
  # null: `odoo module add` and `odoo project update` then fail with a clear
  # message instead of being wired to scripts that assume a git checkout.
  cliScripts ? null,
}:

let
  cliPython = import ./rich-python.nix {
    inherit pkgs python;
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
    ++ lib.optionals (cliScripts != null) [
      ''--set ODOO_NIX_MODULE_ADD "${cliScripts.moduleAdd}"''
      ''--set ODOO_NIX_MODULE_ADD_BUNDLE "${cliScripts.moduleAddBundle}"''
      ''--set ODOO_NIX_PROJECT_UPDATE "${cliScripts.projectUpdate}"''
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
    cp -r ${./odoo_nix_cli} $out/lib/odoo_nix_cli
    makeWrapper ${cliPython}/bin/python $out/bin/odoo ${wrapperArgs}
  ''
