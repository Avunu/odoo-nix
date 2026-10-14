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
# The clone this makes is a partial one, not the shallow one `shallow = true`
# in .gitmodules asks for. A shallow `git submodule update` clones the remote's
# *default* branch at depth 1 and then fetches the pinned commit — usually on
# another branch (an OCA repo's default is the newest series) — with no depth
# at all, so it is slow and still leaves the clone following one branch that
# is not even the project's. Instead:
#
#   - the branch .gitmodules pairs the submodule with is cloned with its whole
#     history of commits and folders, but no file contents
#     (--filter=blob:none): `git log`, `git log -- <file>` and merge-bases work
#     offline, and a checkout downloads only the files it needs. OCB (--core)
#     is the exception: its folder history alone is enormous, so its branch
#     comes as commits only too, folders and files downloaded as needed;
#   - every other branch is fetched the same way (OCB's as commits only), so
#     `git switch <any branch>` works and downloads only the files it needs.
#
# Not commits-only (tree:0) for an OCA repo's other branches, which is what
# this once did. A treeless clone has no folders for any commit, so everything
# that walks history — `git log -p` or `git log -- <path>` in an editor's
# history view, `git blame`, `git diff` across a range — fetches them one
# commit at a time, each as a pack of its own with the folders the last one
# already had repeated in it (frappe-nix measured 345 packs holding 1.9x the
# objects there were). OCB stays treeless all the same: its folder history is
# the bigger cost there, and a history walk in it is the rarer thing.
#
# Two more things keep a partial clone from growing without bound, because
# git does neither:
#
#   - the pinned commit is fetched, the ordinary way, before anything can ask
#     git for a commit the clone lacks (prefetch_pin). `git submodule update`
#     to a pin the clone has not got first asks the clone for it, and a
#     partial clone answers with a lazy fetch that negotiates nothing — no
#     "have" lines — so the remote sends the commit's whole history over
#     again: a clone's worth of data per pin bump, where with the pin fetched
#     first it is the handful of new commits;
#   - the clone's packs are merged where they are alike in size (tidy_packs).
#     Every lazy fetch is a pack, and the `git maintenance run --auto` that a
#     fetch starts does not merge them in a partial clone. Not `git gc
#     --auto`, which counts packs and not bytes, and so leaves a few giant
#     duplicates alone until there are fifty.
#
# Every one of these clones is set never to recurse into submodules on fetch
# (no_submodule_fetch). A repo with submodules of its own otherwise has git
# diff each commit a fetch brings in, looking for a moved gitlink, and in a
# treeless clone each of those trees is a lazy fetch from the remote: one
# round trip per commit on any other branch.
#
# A submodule already checked out shallow, or following a single branch —
# every clone made before this — is brought to the same shape in place, once:
# the checkout does not move, only history is fetched. See needs_history. An
# OCA clone an earlier odoo-nix made treeless keeps the commits it has without
# their folders, and gets folders for the ones it fetches from now on (see
# stop_treeless); `git fetch --refetch` in it fills in the rest, at the price
# of downloading its history again.
#
#   odoo-nix-submodules-init [--core <path>] [<project root>]
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
    core=""
    if [ "''${1:-}" = --core ]; then
      core="''${2:-}"
      shift 2
    fi
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

    # The branch .gitmodules pairs the submodule with. Empty, or git's "." (the
    # superproject's branch), is the remote's default.
    branch_of() { # <name>
      local b
      b="$(git config -f .gitmodules --get "submodule.$1.branch" || true)"
      [ "$b" != "." ] || b=""
      printf '%s' "$b"
    }

    # What the paired branch keeps of its history: every folder, or — for OCB —
    # commits alone.
    filter_of() { # <path>
      if [ -n "$core" ] && [ "$1" = "$core" ]; then echo tree:0; else echo blob:none; fi
    }

    is_shallow() { # <path>
      [ "$(git -C "$1" rev-parse --is-shallow-repository 2>/dev/null)" = true ]
    }

    # A partial clone's own fetches (yours, an editor's autofetch, the next
    # one here) skip the on-demand submodule check — see the header. In the
    # clone's config, and only where it says nothing of its own, so a value
    # someone set there by hand stands.
    no_submodule_fetch() { # <path>
      git -C "$1" config --local --get fetch.recurseSubmodules > /dev/null 2>&1 \
        || git -C "$1" config fetch.recurseSubmodules false
    }

    # Every branch, as the paired one is kept (filter_of), from here on. The
    # refspec goes into the config only once the fetch has worked, so a clone
    # the fetch failed on still reads as needing it (see needs_history) and
    # the next entry retries.
    track_all_branches() { # <path>
      local filter args
      filter="$(filter_of "$1")"
      args=(--filter="$filter" --no-recurse-submodules)
      if is_shallow "$1"; then args+=(--unshallow); fi
      git -C "$1" fetch -q "''${args[@]}" origin '+refs/heads/*:refs/remotes/origin/*' < /dev/null || return 1
      git -C "$1" config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
      git -C "$1" config remote.origin.partialclonefilter "$filter"
      no_submodule_fetch "$1"
    }

    is_partial() { # <path>
      [ "$(git -C "$1" config --get remote.origin.promisor 2>/dev/null)" = true ]
    }

    # An OCA clone an earlier odoo-nix made treeless fetches folders along
    # with commits from now on (see the header). Config only: nothing is
    # downloaded here, and the commits it already has stay as they are. OCB
    # stays treeless, and a filter someone set by hand to anything but tree:0
    # stands.
    stop_treeless() { # <path>
      [ "$(filter_of "$1")" = blob:none ] || return 0
      [ "$(git -C "$1" config --get remote.origin.partialclonefilter 2>/dev/null)" = tree:0 ] || return 0
      git -C "$1" config remote.origin.partialclonefilter blob:none
    }

    # The commit the project records for a submodule.
    pinned_commit() { # <path>
      git ls-files -s -- "$1" 2>/dev/null \
        | awk -v p="$1" '$1 == "160000" && $4 == p { print $2 }'
    }

    # Whether a commit is on disk, without the lazy fetch a partial clone would
    # make to answer the question — which is the whole reason to ask.
    have_commit() { # <path> <commit>
      GIT_NO_LAZY_FETCH=1 git -C "$1" cat-file -e "$2^{commit}" 2> /dev/null
    }

    # Fetch the commit the project records, the ordinary way, when the clone
    # lacks it; see the header for what asking a partial clone for it costs
    # otherwise. An ordinary fetch negotiates, so what comes down is the
    # commits since the clone's last one. Asked on every entry, because a pin
    # moves under a clone with a `git pull` of the project, which changes
    # nothing the shell watches; the next entry is the first chance to fetch
    # it before `git submodule update` is run. A fetch that fails (offline, a
    # pin the remote no longer has) is reported and leaves the clone as it was.
    prefetch_pin() { # <path>
      local pin
      pin="$(pinned_commit "$1")"
      [ -n "$pin" ] || return 0
      have_commit "$1" "$pin" && return 0
      timeout 300 git -C "$1" fetch -q --no-recurse-submodules origin "$pin" < /dev/null > /dev/null 2>&1 \
        || echo "odoo-nix: could not fetch ''${1}'s pinned commit ''${pin:0:12} -- 'git submodule update' on it will download its whole history again" >&2
    }

    # Merge a partial clone's packs where they are alike in size. git's own
    # background maintenance does not (see the header). A geometric repack
    # keeps each pack at least twice the size of the next smaller, so packs of
    # one size — what a repeated download is — are merged, and the objects
    # they share are stored once; when they already are in that shape it does
    # nothing, so asking on every entry costs a directory listing.
    tidy_packs() { # <path>
      local packs
      packs="$(find "$(git -C "$1" rev-parse --git-path objects/pack)" -name '*.pack' 2> /dev/null | wc -l)"
      [ "$packs" -gt 1 ] || return 0
      git -C "$1" maintenance run --quiet --task=geometric-repack < /dev/null > /dev/null 2>&1 || true
    }

    # The clone the first entry makes (see the header), at the pinned commit.
    # git's own submodule clone cannot pick the branch — it always takes the
    # remote's default — so this clones by hand and then hands the result to
    # git: absorbgitdirs moves it under .git/modules/<name> as `git submodule
    # update` would have put it, and `update --force` checks out the pin (it
    # otherwise skips a submodule whose HEAD is already the pinned commit,
    # checked out or not) and its own nested submodules.
    first_checkout() { # <path> <name>
      local url branch filter args=()
      git submodule init -q -- "$1" || return 1
      url="$(git config --get "submodule.$2.url")" || return 1
      branch="$(branch_of "$2")"
      filter="$(filter_of "$1")"
      if [ -n "$branch" ]; then args=(--branch "$branch"); fi
      if ! git clone -q --no-checkout --filter="$filter" --single-branch "''${args[@]}" -- "$url" "$1" < /dev/null; then
        [ -n "$branch" ] || return 1
        echo "odoo-nix: could not clone $1 at '$branch' (.gitmodules' branch) -- trying its remote's default branch" >&2
        git clone -q --no-checkout --filter="$filter" --single-branch -- "$url" "$1" < /dev/null || return 1
      fi
      git submodule absorbgitdirs -- "$1" > /dev/null || return 1
      # The pin is usually on another branch than the one just cloned, and
      # `submodule update` asks the clone for it before it fetches anything.
      prefetch_pin "$1"
      git submodule update --force --recursive -- "$1" < /dev/null || return 1
      track_all_branches "$1" || echo "odoo-nix: $1 is checked out, but its other branches could not be fetched; the next shell entry tries again" >&2
    }

    # Put things back as they were before first_checkout — which, since it only
    # ever runs for a submodule this clone has never set up, is: no clone under
    # the git dir, no URL in the config, and an empty directory. So the next
    # entry still counts it as new and tries again, rather than as one someone
    # took out.
    undo_first_checkout() { # <path> <name> <submodule.<name>.active before>
      local gitdir
      gitdir="$(git rev-parse --git-path "modules/$2")"
      case "$2" in
        *..*) ;;
        *) rm -rf "$gitdir" ;;
      esac
      if [ -d "$1" ]; then find "$1" -mindepth 1 -delete 2>/dev/null || true; fi
      git config --unset "submodule.$2.url" || true
      [ -n "$3" ] || git config --unset "submodule.$2.active" || true
    }

    # A checked-out submodule that is shallow, or follows one branch of origin:
    # what `shallow = true`, `odoo module add` and the scaffolder made of every
    # submodule until the first entry cloned them as above. One with no origin,
    # or whose origin already fetches every branch (a full clone), is left as
    # it is.
    needs_history() { # <path>
      local specs
      is_shallow "$1" && return 0
      specs="$(git -C "$1" config --get-all remote.origin.fetch 2>/dev/null || true)"
      [ -n "$specs" ] || return 1
      [[ "$specs" != *'refs/heads/*:'* ]]
    }

    # needs_history's submodule, in place, to first_checkout's shape: the
    # paired branch's history, and every other branch's the same way. HEAD,
    # the checkout and any local branch stay exactly where they are; this only
    # fetches.
    add_history() { # <path> <name>
      local branch args=()
      branch="$(branch_of "$2")"
      if [ -n "$branch" ]; then
        if is_shallow "$1"; then args+=(--unshallow); fi
        git -C "$1" fetch -q "''${args[@]}" --filter="$(filter_of "$1")" --no-recurse-submodules origin \
          "+refs/heads/$branch:refs/remotes/origin/$branch" < /dev/null \
          || echo "odoo-nix: could not fetch $1's '$branch' history -- fetching every branch's history instead" >&2
      fi
      track_all_branches "$1"
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
    checked=()
    for i in "''${!paths[@]}"; do
      name="''${names[$i]}"
      path="''${paths[$i]}"
      if [ -e "$path/.git" ]; then
        checked+=("$i")
        continue
      fi
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
      if first_checkout "$path" "$name"; then
        continue
      fi
      failed+=("$path")
      undo_first_checkout "$path" "$name" "$active_before"
    done

    for i in "''${checked[@]}"; do
      if is_partial "''${paths[$i]}"; then
        no_submodule_fetch "''${paths[$i]}"
        stop_treeless "''${paths[$i]}"
        prefetch_pin "''${paths[$i]}"
        tidy_packs "''${paths[$i]}"
      fi
      needs_history "''${paths[$i]}" || continue
      echo "odoo-nix: ''${paths[$i]} is a shallow or single-branch clone -- fetching its branch's history" >&2
      echo "  (no file contents) and every branch's, once. This can take a while." >&2
      add_history "''${paths[$i]}" "''${names[$i]}" \
        || echo "odoo-nix: could not fetch ''${paths[$i]}'s history -- the next shell entry tries again" >&2
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
