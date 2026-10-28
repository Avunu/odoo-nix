# `nix run .#relock-fixtures [-- --upgrade]`: regenerate
# tests/fixtures/<series>/uv.lock against the pinned OCB inputs. odoo-nix's
# own fixtures only; a project re-locks with `odoo project relock` or `nix run
# .#relock` (lib/relock.nix). Needs network (PyPI) and so runs on the
# developer's machine, never in a check.
#
# The lock is the one `odoo project relock` runs, from the same Python
# (lib/odoo_nix_cli/workspace/lock.py: `uv lock`, odoo-nix-build-deps, `uv
# lock` again, through a writable shadow of the store path), minus
# oca_sources.py: the fixture pyproject.toml is hand-written, and the custom
# addon is not a uv source. Unlike a project's, any failed step fails it.
{
  pkgs,
  ocbInputs,
  presets,
  # lib/build-deps.nix: odoo-nix-build-deps.
  buildDeps,
  # lib/cli-package.nix: the odoo_nix_cli package, for its lock module.
  cliPackage,
}:
pkgs.writeShellApplication {
  name = "odoo-nix-relock-fixtures";
  runtimeInputs = [
    pkgs.git
    pkgs.coreutils
  ];
  text = ''
    root="$(git rev-parse --show-toplevel)"

    relock() {
      local series="$1" ocb="$2" py="$3"
      shift 3
      local dir="$root/tests/fixtures/$series"
      # uv resolves `odoo = { path = "odoo" }` through this link (gitignored).
      ln -sfn "$ocb" "$dir/odoo"
      echo "==> $series: uv lock $* (python: $py)"
      (
        cd "$dir"
        UV_PYTHON="$py" UV_PYTHON_DOWNLOADS=never PYTHONPATH=${cliPackage} \
          ${pkgs.python3.interpreter} -m odoo_nix_cli.workspace.lock \
          --uv ${pkgs.lib.getExe pkgs.uv} --build-deps ${pkgs.lib.getExe buildDeps} \
          --core "odoo=$ocb" -- "$@"
      ) || exit 1
    }

    ${pkgs.lib.concatMapStringsSep "\n" (
      series:
      ''relock ${series} ${ocbInputs.${series}} ${pkgs.${presets.${series}.python}}/bin/python "$@"''
    ) (builtins.attrNames ocbInputs)}

    echo "Done. Review and commit tests/fixtures/*/uv.lock (and pyproject.toml if the managed block changed)."
  '';
}
