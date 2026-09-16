# shellcheck shell=bash
# Lock-time shadow of an OCB tree that lives in the Nix store.
#
# With `coreSource`, <coreSrc> (./odoo) is a symlink to a read-only store
# path. `uv lock` resolves `odoo = { path = "odoo" }` through it and asks
# setuptools for the package metadata -- whose egg_info step writes
# `odoo.egg-info` into the project root, which fails on the store. uv also
# refuses a `backend-path` (`setup/`) that resolves outside the source tree,
# so the whole tree cannot simply be a directory of symlinks either.
#
# So for the duration of a lock the link points at a throwaway shadow: the
# small top-level entries copied (setup/, setup.py, pyproject.toml, ...),
# the two big ones -- odoo/, addons/ -- symlinked. Writable at the root,
# identical everywhere setuptools looks. Afterwards the link goes back to the
# store path, which is what everything else (odoo-bin, the IDE mirror) wants.
#
#   core_shadow_begin <link> <store path>   # prints the shadow dir
#   core_shadow_end   <link> <store path> <shadow dir>
#
# Both are no-ops when <link> is not a symlink (a submodule checkout).

core_shadow_begin() {
  local link="$1" ocb="$2" shadow entry
  [ -L "$link" ] || return 0
  shadow="$(mktemp -d -t odoo-nix-core-shadow.XXXXXX)"
  for entry in "$ocb"/* "$ocb"/.[!.]*; do
    [ -e "$entry" ] || continue
    case "$(basename "$entry")" in
      odoo | addons) ln -s "$entry" "$shadow/" ;;
      *) cp -r --no-preserve=mode,ownership "$entry" "$shadow/" ;;
    esac
  done
  ln -sfn "$shadow" "$link"
  echo "$shadow"
}

core_shadow_end() {
  local link="$1" ocb="$2" shadow="$3"
  [ -n "$shadow" ] || return 0
  rm -rf "$shadow"
  ln -sfn "$ocb" "$link"
}
