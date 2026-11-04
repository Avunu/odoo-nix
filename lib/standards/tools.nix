# The checkout's locked standards tools (py/odoo_nix_tools/DESIGN.md §5.3):
# tools/uv.lock (uv2nix), package-lock.json (importNpmLock), and coverage from
# the same lock built for Odoo's interpreter. The Python set is assembled the way
# lib/python.nix assembles the Odoo one, so the tools get the same package fixes
# and the same stale-lock guard.
#
#   toolsEnv     the tools' virtualenv (tools/.venv), null without tools/uv.lock
#   coverage     the lock's coverage built for `odooPython`, with
#                passthru.pythonModule (lib/raw-odoo.nix's hook), null without
#                a lock or without coverage in it
#   nodeModules  package-lock.json's node_modules (its /node_modules), null
#                without a package-lock.json
#   prek         the lock's prek (bin/prek) when it pins one, else nixpkgs'
#
# `workspaceRoot` is read only at tools/{pyproject.toml,uv.lock} and
# {package.json,package-lock.json}: a checkout, or any directory holding them
# (the standards-prek-* checks pass a fixture's lock directory).
{
  pkgs,
  lib,
  base,
  uv2nix,
  pyproject-nix,
  pyproject-build-systems,
  workspaceRoot,
  # The tools' interpreter (series data's default_language_version).
  toolsPython ? pkgs.python312,
  # Odoo's interpreter, for the coverage the raw odoo-bin imports.
  odooPython,
  nodejs ? pkgs.nodejs,
}:
let
  pythonLib = base.python;
  toolsDir = workspaceRoot + "/tools";
  hasLock = builtins.pathExists (toolsDir + "/uv.lock");
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = toolsDir; };

  # oca-maintainers-tools is a `git` source built with hatchling and hatch-vcs
  # (setuptools-scm underneath), which uv2nix neither knows nor can feed: the lock
  # records no build dependencies, and the fetched tree has no .git for
  # setuptools-scm to read. The version is the one uv recorded
  # (0.1.dev<n>+g<rev>).
  maintainerTools =
    final: prev:
    lib.optionalAttrs (prev ? oca-maintainers-tools) {
      oca-maintainers-tools = prev.oca-maintainers-tools.overrideAttrs (old: {
        env = (old.env or { }) // {
          SETUPTOOLS_SCM_PRETEND_VERSION = old.version;
        };
        nativeBuildInputs =
          (old.nativeBuildInputs or [ ])
          ++ final.resolveBuildSystem {
            hatchling = [ ];
            hatch-vcs = [ ];
          };
      });
    };

  setFor =
    python:
    (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope (
      lib.composeManyExtensions [
        pyproject-build-systems.overlays.default
        (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
        # The package fixes both products share (lib/python.nix).
        (pythonLib.overrides { inherit pkgs; })
        maintainerTools
      ]
    );
  toolsSet = setFor toolsPython;

  # lib/python.nix's guard, for tools/: a dependency tools/pyproject.toml declares
  # and tools/uv.lock predates fails evaluation with a sentence, not uv2nix's
  # missing attribute. The Nix side of the stale-lock item (DESIGN.md §3.4).
  lockAudit = pythonLib.lockAudit {
    workspaceRoot = toolsDir;
    label = "odoo-nix standards tools";
    lock = "tools/uv.lock";
    hasPackage = name: toolsSet ? ${name};
    relock = ''

      tools/pyproject.toml changed and tools/uv.lock was not regenerated:

          uv lock --project tools
    '';
  };

  toolsEnv =
    if hasLock then
      lockAudit.assertCurrent (
        (toolsSet.mkVirtualEnv "odoo-nix-tools-env" workspace.deps.default).overrideAttrs {
          # pylint-odoo and oca-odoo-pre-commit-hooks both install a top-level
          # requirements/requirements.txt, which nothing reads.
          venvIgnoreCollisions = [ "requirements/*" ];
        }
      )
    else
      null;

  hasNpmLock = builtins.pathExists (workspaceRoot + "/package-lock.json");
  npmRoot = lib.fileset.toSource {
    root = workspaceRoot;
    fileset = lib.fileset.unions [
      (workspaceRoot + "/package.json")
      (workspaceRoot + "/package-lock.json")
    ];
  };

  # Whether the lock pins a package (its root's dependencies name it).
  locks =
    name:
    hasLock && lib.any (p: p.name == name) (lib.importTOML (toolsDir + "/uv.lock")).package or [ ];
in
{
  inherit toolsEnv;
  # pyproject-nix's packages carry no pythonModule, which lib/raw-odoo.nix's
  # hook reads for the site-packages path (nixpkgs' packages do): passthru only,
  # so the derivation is unchanged.
  coverage =
    if locks "coverage" then
      (setFor odooPython).coverage.overrideAttrs (old: {
        passthru = (old.passthru or { }) // {
          pythonModule = odooPython;
        };
      })
    else
      null;
  nodeModules =
    if hasNpmLock then pkgs.importNpmLock.buildNodeModules { inherit nodejs npmRoot; } else null;
  prek =
    if locks "prek" then
      pkgs.runCommand "prek-${toolsSet.prek.version or "locked"}" { meta.mainProgram = "prek"; } ''
        mkdir -p $out/bin
        ln -s ${toolsEnv}/bin/prek $out/bin/prek
      ''
    else
      pkgs.prek;
}
