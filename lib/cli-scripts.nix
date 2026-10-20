# The workspace side of the `odoo` CLI: what `odoo module add`, `add-bundle`
# and `remove` read (lib/odoo_nix_cli/workspace, Python), and the bash behind
# `odoo project update`'s code-pulling phase.
#
# `workspaceConfig` is the JSON ODOO_NIX_WORKSPACE_CONFIG names: the series,
# the OCA catalog, the layout, odoo-nix-sources, and `regenerateAndLock`, the
# one place the uv-path-sources / uv lock / build-deps / relock sequence lives
# (shared with projectUpdate, and kept bash for lib/core-shadow.sh around the
# lock). Everything DB-shaped (provision/upgrade/migrate/backup/restore) is
# implemented directly against odoo.service.db / Registry.new in Python
# (lib/odoo_nix_cli/).
#
# Usage:
#   import ./lib/cli-scripts.nix {
#     inherit lib pkgs;
#     odooSeries = cfg.odooSeries;
#     ocaDataset = ../data/oca-modules.json;
#     bundlesFile = ../data/oca-bundles.json;
#     layout = cfg.layout;
#     python = "${pythonEnvs.devPythonEnv}/bin/python";
#   }

{
  lib,
  pkgs,
  odooSeries,
  ocaDataset,
  bundlesFile,
  layout,
  python,
  # OCB from a flake input (see modules/devenv.nix `coreSource`) -- affects
  # only the "bump it with nix flake update" note in projectUpdate.
  coreSource ? null,
  # odoo-nix-sources (lib/shell-tools.nix, python-devops-nix's lib.sources):
  # `module add` clones a new repo with it, and projectUpdate checks out a
  # submodule this clone has never had the way shell entry does, as a partial
  # clone. A bare name is looked up on PATH (the module-cli check's stand-in).
  sourcesBin,
  # lib/build-deps.nix: odoo-nix-build-deps, which keeps pyproject.toml's
  # sdist build dependencies in step with uv.lock after each `uv lock`.
  buildDeps,
}:

let
  preamble = ''
    set -euo pipefail
    cd "''${REPO_ROOT:-$PWD}"
  '';

  # Regenerate the uv path-sources block in pyproject.toml from whatever is on
  # disk under layout.{externalDir,customDir}, then re-lock. Shared by the
  # workspace commands (lib/odoo_nix_cli/workspace) and projectUpdate, so this
  # uv-lock/patch-build-deps/relock sequence exists in exactly one place.
  regenerateAndLock = pkgs.writeShellScript "oca-regenerate-and-lock" ''
    set -euo pipefail
    cd "''${REPO_ROOT:-$PWD}"
    echo "==> Regenerating uv path-sources…"
    ${python} ${./oca_sources.py} update pyproject.toml \
      modules.txt "${layout.externalDir}" "${layout.customDir}" "${layout.coreSrc}"
    echo "==> Re-locking Python environment (uv lock)…"
    ${lib.optionalString (coreSource != null) ''
      # shellcheck source=/dev/null
      source ${./core-shadow.sh}
      _shadow="$(core_shadow_begin "${layout.coreSrc}" "${toString coreSource}")"
      trap 'core_shadow_end "${layout.coreSrc}" "${toString coreSource}" "$_shadow"' EXIT
    ''}
    if ${pkgs.uv}/bin/uv lock; then
      ${lib.getExe buildDeps} update pyproject.toml uv.lock || true
      ${pkgs.uv}/bin/uv lock || true
    else
      echo "⚠  uv lock failed — resolve in pyproject.toml and re-run." >&2
    fi
  '';

  # What lib/odoo_nix_cli/workspace/config.py reads; it refuses a missing or an
  # unknown key.
  workspaceConfig = pkgs.writeText "odoo-nix-workspace.json" (
    builtins.toJSON {
      series = odooSeries;
      ocaDataset = "${ocaDataset}";
      ocaBundles = "${bundlesFile}";
      layout = {
        inherit (layout) coreSrc externalDir customDir;
      };
      sources = sourcesBin;
      regenerate = "${regenerateAndLock}";
    }
  );

  # Pull submodules on their pinned branch, re-aggregate OCA python deps,
  # relock. Database migration is a separate, Python-implemented step (`odoo
  # project update` runs this, then calls into odoo_nix_cli's migrate engine
  # unless --no-migrate).
  projectUpdate = pkgs.writeShellScript "odoo-nix-project-update" ''
    ${preamble}
    echo "==> Updating git submodules…"
    # A submodule this clone has never had is checked out as shell entry
    # does it -- a partial clone, not the shallow one `update --init` makes.
    ${sourcesBin} enter --treeless ${lib.escapeShellArg layout.coreSrc} "$PWD"
    git submodule update --init --recursive
    # Move each submodule to the tip of its .gitmodules-pinned branch, fetched
    # fresh by name. Two things rule out the more obvious approaches here:
    # `update --init --recursive` alone leaves submodules in detached HEAD, so
    # `git rev-parse --abbrev-ref HEAD` returns the literal string "HEAD", and
    # pulling "origin HEAD" then follows the remote's *default* branch instead
    # of the pinned one. `git submodule update --remote` avoids that but can
    # still fail if a submodule's local remote-tracking refspec was narrowed
    # to some other branch at clone time. Both surface as "Not possible to
    # fast-forward" whenever a repo's GitHub default branch no longer matches
    # what's pinned. Fetching the pinned branch by name every time sidesteps
    # both.
    #
    # How much of it to fetch follows how the submodule was cloned. A partial
    # clone (odoo-nix-sources) keeps its branch with every commit's
    # folders -- OCB (${layout.coreSrc}) with its commits only -- so ask for
    # the folders, except for OCB. --depth 1 would turn it into a shallow
    # clone again, so that is only for one still shallow. Never recursing into
    # nested submodules: in a partial clone that check is a lazy fetch per
    # commit (see python-devops-nix's python/sources.py).
    git submodule foreach --quiet '
      branch="$(git config -f "$toplevel/.gitmodules" --get "submodule.$sm_path.branch")"
      [ -n "$branch" ] || branch="$(git symbolic-ref --quiet --short HEAD || true)"
      if [ "$(git config remote.origin.promisor)" = true ]; then
        if [ "$sm_path" = "${layout.coreSrc}" ]; then depth=""; else depth="--filter=blob:none"; fi
      elif [ "$(git rev-parse --is-shallow-repository)" = true ]; then
        depth="--depth=1"
      else
        depth=""
      fi
      [ -n "$branch" ] && git fetch $depth --quiet --no-recurse-submodules origin "$branch" && git checkout --quiet FETCH_HEAD || true
    '
    ${lib.optionalString (coreSource != null) ''
      echo "    (${layout.coreSrc} is a flake input, not a submodule: bump it with 'nix flake update')"
    ''}

    ${regenerateAndLock}
    echo "✅ Code updated."
  '';
in
{
  inherit workspaceConfig projectUpdate;
}
