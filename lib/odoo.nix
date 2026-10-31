# builtOdoo — the deployable Odoo artifact (analogue of frappe-nix's builtBench).
#
# Odoo compiles assets at runtime into the filestore/DB, so its own assembly
# is the source tree + the Nix Python env + a wrapper. The one build step is an
# addon's own: one whose package.json has a build script (lib/node.nix) is
# copied as its build left it, `nodeBuilds`, over the source.
# It is consumed by the NixOS module and the container builder, which read the
# absolute addons_path and interpreter from `passthru`.
#
# Layout produced (the project's `layout`, shown with its defaults):
#   $out/odoo               (OCB core, layout.coreSrc)
#   $out/modules/<repo>     (OCA repos, layout.externalDir)
#   $out/custom             (project addons, layout.customDir)
#   $out/bin/odoo           (wrapper: env python + odoo-bin, lib/raw-odoo.nix)
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
  # OCB from outside the workspace (see modules/devenv.nix `coreSource`).
  coreSource ? null,
  # { <key> = built tree; }: lib/node.nix's builds, keys relative to the
  # workspace (`custom/acme_ui`, or a repository root for a workspace).
  nodeBuilds ? { },
}:

let
  addons = import ./addons.nix {
    inherit
      lib
      workspaceRoot
      layout
      coreSource
      ;
  };

  # Run the tree's odoo-bin, or Odoo as `python -m odoo` when it has none.
  rawOdoo = import ./raw-odoo.nix {
    inherit pkgs;
    python = "${odooPythonEnv}/bin/python";
  };

  # Where the OCB tree is read from: the workspace submodule, or the store path.
  coreRoot = if coreSource != null then toString coreSource else "${workspaceRoot}/${layout.coreSrc}";

  copyDir = src: dst: ''
    if [ -e "${src}" ]; then
      mkdir -p "$(dirname "${dst}")"
      cp -r "${src}" "${dst}"
      chmod -R u+w "${dst}"
    fi
  '';

  builtOdoo =
    pkgs.runCommandLocal "${projectName}-odoo"
      {
        passthru = {
          pythonEnv = odooPythonEnv;
          inherit (addons) externalRepos addonsPathList;
          # root -> absolute comma-separated addons_path against an assembled tree.
          addonsPath = addons.addonsPathFor;
          odooVersion = odooSeries;
          inherit nodeBuilds;
        };
        meta.description = "Assembled Odoo (OCB + OCA + custom) for ${projectName}";
      }
      ''
        mkdir -p $out/bin

        # Assemble the tree into the SAME relative layout the project uses, so the
        # package's addonsPath (addons.addonsPathFor "$out") resolves against it.
        ${
          if coreSource != null then
            # Already in the store: link rather than duplicate a 2 GB tree.
            ''ln -s "${coreRoot}" "$out/${layout.coreSrc}"''
          else
            copyDir coreRoot "$out/${layout.coreSrc}"
        }
        ${lib.concatMapStringsSep "\n" (
          repo: copyDir "${workspaceRoot}/${layout.externalDir}/${repo}" "$out/${layout.externalDir}/${repo}"
        ) addons.externalRepos}
        ${copyDir "${workspaceRoot}/${layout.customDir}" "$out/${layout.customDir}"}

        # The addons' JavaScript builds, each over its source: a repository
        # root before the addons in it.
        ${lib.concatMapStrings (key: ''
          mkdir -p "$out/${key}"
          cp -rT ${nodeBuilds.${key}} "$out/${key}"
          chmod -R u+w "$out/${key}"
        '') (lib.sort (a: b: lib.stringLength a < lib.stringLength b) (lib.attrNames nodeBuilds))}

        # Drop any vendored VCS metadata to keep the closure lean.
        find $out -name .git -prune -exec rm -rf {} + 2>/dev/null || true

        # Wrapper: run Odoo from the assembled OCB source with the Nix env python.
        cat > $out/bin/odoo <<EOF
        #!${pkgs.runtimeShell}
        tree=$out/${layout.coreSrc}
        EOF
        cat >> $out/bin/odoo <<'EOF'
        ${rawOdoo}
        EOF
        chmod +x $out/bin/odoo
      '';
in
builtOdoo
