# The workspace side of the `odoo` CLI: the JSON ODOO_NIX_WORKSPACE_CONFIG
# names, which `odoo module add`, `add-bundle` and `remove`, `odoo project
# update` and `relock`, and `nix run .#relock` (lib/relock.nix) read
# (lib/odoo_nix_cli/workspace, Python): the series,
# the OCA catalog, the layout, odoo-nix-sources, and what the re-lock runs
# (lib/oca_sources.py, uv, odoo-nix-build-deps, and OCB's store path under
# coreSource). Everything DB-shaped (provision/upgrade/migrate/backup/restore)
# is implemented directly against odoo.service.db / Registry.new in Python
# (lib/odoo_nix_cli/).
#
# Usage:
#   import ./lib/cli-scripts.nix {
#     inherit lib pkgs;
#     odooSeries = cfg.odooSeries;
#     ocaDataset = ../data/oca-modules.json;
#     bundlesFile = ../data/oca-bundles.json;
#     layout = cfg.layout;
#     python = cfg.python.interpreter;
#   }

{
  lib,
  pkgs,
  odooSeries,
  ocaDataset,
  bundlesFile,
  layout,
  # The interpreter lib/oca_sources.py runs on (stdlib only). Not one built
  # from uv.lock: `nix run .#relock` reads this configuration when the lock
  # is too stale to evaluate.
  python,
  # OCB from a flake input (see modules/devenv.nix `coreSource`): <coreSrc> is
  # then a symlink to it, which the lock goes through a writable shadow of
  # (lib/odoo_nix_cli/workspace/lock.py), and `project update` says to bump it
  # with `nix flake update`.
  coreSource ? null,
  # odoo-nix-sources (lib/shell-tools.nix, python-devops-nix's lib.sources):
  # `module add` clones a new repo with it, and `project update` checks out a
  # submodule this clone has never had the way shell entry does, as a partial
  # clone. A bare name is looked up on PATH (the odoo-module-cli check's stand-in).
  sourcesBin,
  # lib/build-deps.nix: odoo-nix-build-deps, which keeps pyproject.toml's
  # sdist build dependencies in step with uv.lock after each `uv lock`.
  buildDeps,
  # uv, for the re-lock.
  uv ? pkgs.uv,
}:

{
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
      inherit python;
      ocaSources = "${./oca_sources.py}";
      uv = lib.getExe uv;
      buildDeps = lib.getExe buildDeps;
      coreSource = if coreSource == null then null else toString coreSource;
    }
  );
}
