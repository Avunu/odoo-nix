# Python environment factory for Odoo + OCA projects.
#
# Builds production and development Python environments from a uv project
# (pyproject.toml + uv.lock) via uv2nix. Unlike frappe-nix this is NOT a
# multi-member workspace: Odoo addons (OCB core, OCA repos, src/custom) load via
# `addons_path`, not pip. The root pyproject is a single virtual project whose
# [project].dependencies is the union of:
#   - Odoo core runtime deps (translated from src/odoo/requirements.txt), and
#   - OCA modules' external_dependencies.python (aggregated by the scaffolder).
#
# Odoo itself runs from source (`python src/odoo/odoo-bin`), so it is NOT a
# dependency here — only its third-party libraries are.
#
# Usage:
#   import ./lib/python.nix {
#     inherit pkgs lib python projectName workspaceRoot;
#     pyproject-nix = inputs.pyproject-nix;
#     pyproject-build-systems = inputs.pyproject-build-systems;
#     uv2nix = inputs.uv2nix;
#     extraOverrides = final: prev: { ... };
#   }

{
  pkgs,
  lib,
  python,
  workspaceRoot,
  projectName,
  pyproject-nix,
  pyproject-build-systems,
  uv2nix,
  extraOverrides ? (_final: _prev: { }),
}:

let
  workspace = uv2nix.lib.workspace.loadWorkspace { inherit workspaceRoot; };

  rootPyproject = builtins.fromTOML (builtins.readFile (workspaceRoot + "/pyproject.toml"));

  # The root project name from pyproject.toml [project].name (virtual package).
  rootPkgName = rootPyproject.project.name;

  overlay = workspace.mkPyprojectOverlay {
    sourcePreference = "wheel";
  };

  pythonSet =
    (pkgs.callPackage pyproject-nix.build.packages {
      inherit python;
    }).overrideScope
      (
        lib.composeManyExtensions [
          pyproject-build-systems.overlays.default
          overlay
          extraOverrides
        ]
      );

  # For a virtual single-root project, `workspace.deps.default` is just the root
  # node ({ ${rootPkgName} = [extras]; }); its dependencies (with environment
  # markers) are resolved + marker-pruned by mkVirtualEnv. Passing the root node
  # as-is is therefore correct AND respects markers — re-adding deps by name
  # (frappe's pattern) would wrongly reference marker-excluded packages such as
  # `lxml-html-clean` (python_version >= '3.12') on a 3.11 interpreter.

  # Production: runtime deps only, no dev tooling.
  odooPythonEnv = pythonSet.mkVirtualEnv "${projectName}-odoo-env" workspace.deps.default;

  # Development: also pulls in [dependency-groups] (ruff, pytest, debugpy, …).
  # No editable overlay — Odoo + OCA addons resolve via addons_path + PYTHONPATH
  # and hot-reload through `--dev=all`, so nothing is pip-installed from source.
  devPythonEnv = pythonSet.mkVirtualEnv "${projectName}-odoo-dev-env" (
    workspace.deps.default // workspace.deps.groups
  );
in
{
  inherit
    pythonSet
    odooPythonEnv
    devPythonEnv
    workspace
    rootPyproject
    rootPkgName
    ;
}
