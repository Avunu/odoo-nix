# What the dev shell does about the project's git submodules on entry: check
# out, once, the ones a fresh clone has never had, and only report on the rest.
#
# Once per clone, not on every entry. Entry runs on every `nix develop` and
# every direnv reload; checking out whatever submodule it found without a
# checkout (what this used to do) also brought back one removed by hand or
# deinitialized, freshly cloned from its remote, on the next reload. So the
# checkout is limited to a submodule this clone has never set up (see
# ever_set_up); one that has been set up and is now missing was taken out by
# someone, and entry leaves it out and says how to bring it back. Past that,
# submodules move only via an explicit `odoo project update`.
#
# One path at a time: a single `git submodule update` over several paths gives
# up on all of them when one clone fails, leaving the rest cloned but never
# checked out. .gitmodules, not `git submodule status`, names the submodules:
# the latter dies on the first gitlink with no .gitmodules entry.
#
#   odoo-nix-submodules-init [<project root>]
{ pkgs }:

pkgs.writeShellApplication {
  name = "odoo-nix-submodules-init";
  runtimeInputs = [
    pkgs.coreutils
    pkgs.findutils
    pkgs.gawk
    pkgs.git
  ];
  text = ''
    cd "''${1:-.}"
    [ -f .gitmodules ] || exit 0

    # Whether this clone has ever set the submodule up: a clone of it under the
    # git dir (what `git submodule update --init` and `git submodule add` make),
    # or a URL in the local config (what `git submodule init` writes, and all
    # that `git submodule add` over an existing checkout leaves, its .git kept
    # in the working tree). A fresh clone has neither for any submodule. One
    # removed by hand keeps both, and a deinitialized one keeps its clone.
    ever_set_up() { # <name>
      [ -e "$(git rev-parse --git-path "modules/$1")" ] \
        || git config --get "submodule.$1.url" > /dev/null 2>&1
    }

    # Recorded in the index as a submodule commit. A .gitmodules entry without
    # one has nothing to check out. awk reads to the end rather than exiting on
    # the match, so git never takes a SIGPIPE under pipefail.
    has_gitlink() { # <path>
      git ls-files -s -- "$1" 2>/dev/null \
        | awk -v p="$1" '$1 == "160000" && $4 == p { f = 1 } END { exit !f }'
    }

    names=()
    paths=()
    # `<key> <value>` per line; the name is the key between `submodule.` and
    # `.path`, and may itself contain dots.
    while read -r key path; do
      name="''${key#submodule.}"
      names+=("''${name%.path}")
      paths+=("$path")
    done < <(git config -f .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null || true)

    unchecked=()
    failed=()
    for i in "''${!paths[@]}"; do
      name="''${names[$i]}"
      path="''${paths[$i]}"
      [ ! -e "$path/.git" ] || continue
      has_gitlink "$path" || continue
      if ever_set_up "$name"; then
        unchecked+=("$path")
        continue
      fi
      # Git refuses to clone into a directory with anything in it. Say what is
      # in the way rather than set the submodule up for a clone that fails.
      if [ -n "$(find "$path" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
        echo "odoo-nix: $path is not checked out, but its directory is not empty, so git" >&2
        echo "  will not clone into it. Move what is there aside and re-enter the shell:" >&2
        find "$path" -mindepth 1 -maxdepth 1 -printf '    %f\n' | sort >&2
        continue
      fi
      active_before="$(git config --get "submodule.$name.active" || true)"
      echo "Initializing git submodule $path (first shell entry in this clone)…"
      if git submodule update --init --recursive -- "$path" < /dev/null; then
        continue
      fi
      failed+=("$path")
      # `--init` records the URL before it clones. With no clone to show for
      # it, take that back, so the submodule still reads as never set up and the
      # next entry tries again -- rather than as one someone took out.
      if [ ! -e "$(git rev-parse --git-path "modules/$name")" ]; then
        git config --unset "submodule.$name.url" || true
        [ -n "$active_before" ] || git config --unset "submodule.$name.active" || true
      fi
    done

    if [ "''${#failed[@]}" -gt 0 ]; then
      echo "odoo-nix: could not check out:$(printf ' %s' "''${failed[@]}") -- see git's error above." >&2
      echo "  The next shell entry tries again, or: git submodule update --init --recursive --$(printf ' %s' "''${failed[@]}")" >&2
    fi
    if [ "''${#unchecked[@]}" -gt 0 ]; then
      echo "odoo-nix: registered but not checked out:$(printf ' %s' "''${unchecked[@]}")" >&2
      echo "  (this clone has set them up before, so the shell does not bring them back)" >&2
      echo "  at the commits the project records:  git submodule update --init --recursive --$(printf ' %s' "''${unchecked[@]}")" >&2
      echo "  or at their branches' tips:          odoo project update" >&2
    fi
    exit 0
  '';
}
