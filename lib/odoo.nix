# builtOdoo — the deployable Odoo artifact (analogue of frappe-nix's builtBench).
#
# Odoo compiles assets at runtime into the filestore/DB, so there is NO build
# step: this is a pure source-tree assembly + the Nix Python env + a wrapper.
# It is consumed by the NixOS module and the container builder, which read the
# absolute addons_path and interpreter from `passthru`.
#
# Layout produced:
#   $out/src/odoo           (OCB core)
#   $out/src/external/<repo>(OCA repos)
#   $out/src/custom         (project addons)
#   $out/bin/odoo           (wrapper: env python + odoo-bin)
#
# Usage:
#   import ./lib/odoo.nix {
#     inherit pkgs lib workspaceRoot layout projectName;
#     odooPythonEnv = pythonEnvs.odooPythonEnv;  # prod env
#   }

{
  pkgs,
  lib,
  workspaceRoot,
  layout,
  projectName,
  odooSeries,
  odooPythonEnv,
}:

let
  addons = import ./addons.nix { inherit lib workspaceRoot layout; };

  copyDir = src: dst: ''
    if [ -e "${src}" ]; then
      mkdir -p "$(dirname "${dst}")"
      cp -r "${src}" "${dst}"
      chmod -R u+w "${dst}"
    fi
  '';

  builtOdoo = pkgs.runCommandLocal "${projectName}-odoo" {
    passthru = {
      pythonEnv = odooPythonEnv;
      inherit (addons) externalRepos addonsPathList;
      # root -> absolute comma-separated addons_path against an assembled tree.
      addonsPath = addons.addonsPathFor;
      odooVersion = odooSeries;
    };
    meta.description = "Assembled Odoo (OCB + OCA + custom) for ${projectName}";
  } ''
    mkdir -p $out/src $out/bin

    ${copyDir "${workspaceRoot}/${layout.coreSrc}" "$out/src/odoo"}
    ${lib.concatMapStringsSep "\n" (
      repo: copyDir "${workspaceRoot}/${layout.externalDir}/${repo}" "$out/src/external/${repo}"
    ) addons.externalRepos}
    ${copyDir "${workspaceRoot}/${layout.customDir}" "$out/src/custom"}

    # Drop any vendored VCS metadata to keep the closure lean.
    find $out/src -name .git -prune -exec rm -rf {} + 2>/dev/null || true

    # Wrapper: run odoo-bin from the assembled OCB source with the Nix env python.
    cat > $out/bin/odoo <<EOF
    #!${pkgs.runtimeShell}
    exec ${odooPythonEnv}/bin/python $out/src/odoo/odoo-bin "\$@"
    EOF
    chmod +x $out/bin/odoo
  '';
in
builtOdoo
