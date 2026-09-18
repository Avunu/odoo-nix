# `nix run .#relock [-- --upgrade]`: regenerate tests/fixtures/<series>/uv.lock
# against the pinned OCB inputs. Needs network (PyPI) and so runs on the
# developer's machine, never in a check. The sequence is lib/cli-scripts.nix's
# regenerateAndLock minus oca_sources.py: the fixture pyproject.toml is
# hand-written, and the custom addon is not a uv source.
{
  pkgs,
  ocbInputs,
  presets,
}:
pkgs.writeShellApplication {
  name = "odoo-nix-relock";
  runtimeInputs = [
    pkgs.uv
    pkgs.python3
    pkgs.git
    pkgs.coreutils
  ];
  text = ''
    root="$(git rev-parse --show-toplevel)"
    # shellcheck source=/dev/null
    source ${../lib/core-shadow.sh}

    relock() {
      local series="$1" ocb="$2" py="$3"
      shift 3
      local dir="$root/tests/fixtures/$series" shadow
      # uv resolves `odoo = { path = "odoo" }` through this link (gitignored),
      # via a lock-time shadow of the store path -- see lib/core-shadow.sh,
      # the same helper a consumer's odoo-update uses under coreSource.
      ln -sfn "$ocb" "$dir/odoo"
      shadow="$(core_shadow_begin "$dir/odoo" "$ocb")"
      (
        cd "$dir"
        export UV_PYTHON="$py" UV_PYTHON_DOWNLOADS=never
        echo "==> $series: uv lock $* (python: $py)"
        uv lock "$@"
        python3 "$root/lib/uv_build_deps.py" update pyproject.toml uv.lock
        uv lock
      ) || {
        core_shadow_end "$dir/odoo" "$ocb" "$shadow"
        exit 1
      }
      core_shadow_end "$dir/odoo" "$ocb" "$shadow"
    }

    ${pkgs.lib.concatMapStringsSep "\n" (
      series:
      ''relock ${series} ${ocbInputs.${series}} ${pkgs.${presets.${series}.python}}/bin/python "$@"''
    ) (builtins.attrNames ocbInputs)}

    echo "Done. Review and commit tests/fixtures/*/uv.lock (and pyproject.toml if the managed block changed)."
  '';
}
