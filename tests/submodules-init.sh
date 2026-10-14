#!/usr/bin/env bash
# Checks for `odoo-nix-submodules-init` -- what the dev shell does about the
# project's git submodules on entry. On a fresh clone it checks out every
# submodule, once. After that it touches none: checking out whatever it found
# without a checkout is how a submodule removed by hand came back, re-cloned,
# on the next direnv reload.
#
# Usage: submodules-init.sh <path-to-odoo-nix-submodules-init>
set -euo pipefail

TOOL="$1"

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com
export GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
# Submodule operations on file:// URLs are refused by default. Every fetch keeps
# its pack (git unpacks one under 100 objects into loose ones, where a repeated
# download would overwrite itself and leave nothing to count), and a gc runs in
# the foreground, where there is something to look at when it is done.
export GIT_CONFIG_COUNT=3
export GIT_CONFIG_KEY_0=protocol.file.allow GIT_CONFIG_VALUE_0=always
export GIT_CONFIG_KEY_1=transfer.unpackLimit GIT_CONFIG_VALUE_1=1
export GIT_CONFIG_KEY_2=gc.autoDetach GIT_CONFIG_VALUE_2=false

fails=0
ok() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
no() {
  printf '  \033[31m✗\033[0m %s\n' "$1"
  fails=$((fails + 1))
}
check() { # <description> <command...>
  local desc=$1
  shift
  if "$@" > /dev/null 2>&1; then ok "$desc"; else no "$desc"; fi
}
check_not() { # <description> <command...> -- passes when the command fails
  local desc=$1
  shift
  if "$@" > /dev/null 2>&1; then no "$desc"; else ok "$desc"; fi
}
check_eq() { # <description> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1"; else no "$1 (expected '$2', got '$3')"; fi
}
says() { grep -qF -- "$1" <<< "$OUT"; }
silent_on() { ! grep -qF -- "$1" <<< "$OUT"; }
run() { OUT="$("$TOOL" --core odoo "$PWD" 2>&1)" && RC=0 || RC=$?; }

# Whether an object is on disk, without the lazy fetch a partial clone would
# otherwise make to answer the question.
has_obj() { # <repo> <object>
  GIT_NO_LAZY_FETCH=1 git -C "$1" cat-file -e "$2" 2> /dev/null
}

# The shape the first entry gives a clone: partial, not shallow, every branch
# of origin fetched, folders but no file contents from here on (OCB: commits
# only), and no recursing into nested submodules on fetch.
partial_all_branches() { # <path>
  local filter=blob:none
  [ "$1" != odoo ] || filter=tree:0
  [ "$(git -C "$1" config remote.origin.promisor)" = true ] \
    && [ "$(git -C "$1" rev-parse --is-shallow-repository)" = false ] \
    && [ "$(git -C "$1" config --get-all remote.origin.fetch)" = '+refs/heads/*:refs/remotes/origin/*' ] \
    && [ "$(git -C "$1" config remote.origin.partialclonefilter)" = "$filter" ] \
    && [ "$(git -C "$1" config fetch.recurseSubmodules)" = false ] \
    && git -C "$1" rev-parse -q --verify refs/remotes/origin/other > /dev/null
}

# Everything git knows about the project and its submodules, and the file tree.
snapshot() {
  git status --porcelain --ignore-submodules=none
  git ls-files -s
  cat .gitmodules .git/config
  find .git/modules -maxdepth 3 -name HEAD -exec sh -c 'echo "$1: $(cat "$1")"' _ {} \; 2>/dev/null | sort
  find odoo modules -maxdepth 1 2>/dev/null | sort
}

# Checked out, at the commit the project records for it.
at_pin() { # <path>
  [ -f "$1/README" ] \
    && [ "$(git -C "$1" rev-parse HEAD)" = "$(git ls-files -s -- "$1" | awk '{ print $2 }')" ]
}
empty() { [ -z "$(ls -A "$1" 2>/dev/null)" ]; }

commit_to() { # <name> <branch> <message> -- a commit on the seed, pushed
  local seed="$ROOT/seed/$1"
  git -C "$seed" checkout -q "$2"
  mkdir -p "$seed/$2"
  printf '%s\n' "$3" > "$seed/$2/log.txt"
  git -C "$seed" add -A
  git -C "$seed" commit -q -m "$3"
  git -C "$seed" push -q "$ROOT/remotes/$1.git" "$2"
}
# main, which the project pins, and other, which it never checks out. Filters
# allowed, as GitHub does: without them a partial clone quietly falls back to
# a full one and nothing below would be tested.
seed_remote() { # <name>
  local seed="$ROOT/seed/$1"
  mkdir -p "$seed"
  printf '%s\n' "$1" > "$seed/README"
  git -C "$seed" init -q -b main
  git -C "$seed" add -A
  git -C "$seed" commit -q -m init
  git init -q --bare "$ROOT/remotes/$1.git"
  git -C "$ROOT/remotes/$1.git" symbolic-ref HEAD refs/heads/main
  git -C "$ROOT/remotes/$1.git" config uploadpack.allowFilter true
  git -C "$ROOT/remotes/$1.git" config uploadpack.allowAnySHA1InWant true
  git -C "$seed" push -q "$ROOT/remotes/$1.git" main
  git -C "$seed" branch -q other
  commit_to "$1" main "main 1"
  commit_to "$1" other "other 1"
}
for r in odoo present fresh taken inplace; do seed_remote "$r"; done

PROJECT="$ROOT/project"
mkdir -p "$PROJECT"
cd "$PROJECT"
git init -q -b main
git submodule add -q -b main "file://$ROOT/remotes/odoo.git" odoo
for r in present fresh taken; do
  git submodule add -q -b main "file://$ROOT/remotes/$r.git" "modules/$r"
done
# inplace: registered over a checkout that was already there -- its .git stays
# in modules/inplace, and the project's git dir holds no clone of it.
git clone -q -b main "file://$ROOT/remotes/inplace.git" modules/inplace
git submodule add -q -b main "file://$ROOT/remotes/inplace.git" modules/inplace 2> /dev/null
# stray: a nested repo `git add`ed as-is -- a gitlink with no .gitmodules
# entry, which `git submodule status` dies on.
mkdir -p modules/stray && git -C modules/stray init -q -b main
printf 'x\n' > modules/stray/f && git -C modules/stray add -A && git -C modules/stray commit -q -m i
git -c advice.addEmbeddedRepo=false add -A 2> /dev/null
git commit -q -m project
# Upstream moves on past what the project pins, so a checkout at the branch
# tip is not a checkout at the pin.
for r in odoo present fresh taken inplace; do commit_to "$r" main "main 2"; done

# Fresh clones of the project as committed, for the sections further down.
git clone -q "$PROJECT" "$ROOT/clone"
git clone -q "$PROJECT" "$ROOT/clone2"
git clone -q "$PROJECT" "$ROOT/clone3"

# fresh: what `git submodule deinit` leaves -- its clone kept in the git dir.
git submodule deinit -q -f -- modules/fresh
# taken, inplace: removed by hand.
rm -rf modules/taken modules/inplace

echo "── a project with one of each ───────────────────────────────────"
before="$(snapshot)"
run
after="$(snapshot)"
check_eq "exits 0" 0 "$RC"
check_eq "changes nothing -- no checkout, no clone, no index or config edit" "$before" "$after"
check "…so modules/fresh is still empty" empty modules/fresh
check "…and the ones removed by hand are still gone" test ! -e modules/taken -a ! -e modules/inplace
check "says it is initializing nothing" silent_on "Initializing"
check "names the submodules taken out since" says "registered but not checked out: modules/fresh modules/taken modules/inplace"
check "…with the command that checks out their pinned commits" says "git submodule update --init --recursive -- modules/fresh modules/taken modules/inplace"
check "…and the one that pulls them" says "odoo project update"
check "says nothing of a checked-out submodule" silent_on "modules/present"

echo "── a project with nothing to say ────────────────────────────────"
git submodule update -q --init -- modules/fresh modules/taken modules/inplace
run
check_eq "exits 0" 0 "$RC"
check_eq "and prints nothing" "" "$OUT"

echo "── a fresh clone ────────────────────────────────────────────────"
cd "$ROOT/clone"
mkdir -p modules/taken/leftover
run
check_eq "exits 0" 0 "$RC"
for p in odoo modules/present modules/fresh modules/inplace; do
  check "checks out $p at its pinned commit" at_pin "$p"
  check "…as a partial clone of every branch" partial_all_branches "$p"
done
# origin/main is a commit past the pin, so nothing of it was checked out.
check "the paired branch has its folders past the checkout…" has_obj modules/present 'origin/main^{tree}'
check_not "…but not their file contents" has_obj modules/present 'origin/main:main/log.txt'
check_not "…except OCB's, whose branch comes as commits only" has_obj odoo 'origin/main^{tree}'
# Not commits only (tree:0): a clone without folders fetches them one commit at
# a time, in a pack apiece, for anything that walks history.
check "another branch has its folders too…" has_obj modules/present 'origin/other^{tree}'
check_not "…but not their file contents" has_obj modules/present 'origin/other:other/log.txt'
check_not "…except OCB's, commits only there too" has_obj odoo 'origin/other^{tree}'
check "and switching to it downloads what it needs" git -C modules/present switch -q other
check "…files and all" test -f modules/present/other/log.txt
git -C modules/present switch -q --detach "$(git ls-files -s -- modules/present | awk '{ print $2 }')"
check "…past a gitlink with no .gitmodules entry" empty modules/stray
check "says so" says "Initializing git submodule odoo (first shell entry in this clone)"
check "names a submodule whose directory is in the way" says "modules/taken is not checked out, but its directory is not empty"
check "…and what is in it" says "leftover"
check "…leaves that directory as it was" test -d modules/taken/leftover -a ! -e modules/taken/.git
check_not "…and does not set it up, so the next entry still counts it as new" git config --get submodule.modules/taken.url
check "reports nothing as taken out" silent_on "registered but not checked out"

before="$(snapshot)"
run
after="$(snapshot)"
check_eq "a second entry changes nothing" "$before" "$after"
check "…and initializes nothing" silent_on "Initializing"

rm -rf modules/present
git submodule deinit -q -f -- modules/fresh
run
check "a submodule removed by hand after the first entry stays removed" test ! -e modules/present
check "…as does a deinitialized one" empty modules/fresh
check "…and both are reported" says "registered but not checked out: modules/present modules/fresh"

rmdir modules/taken/leftover
run
check "once its directory is cleared, the one in the way is checked out" at_pin modules/taken

echo "── shallow clones from before ───────────────────────────────────"
cd "$ROOT/clone3"
# What `shallow = true` made of a submodule: the remote's default branch at
# depth 1, and only that branch followed ...
git submodule update -q --init --depth 1 -- odoo modules/present modules/fresh modules/taken
printf 'mine\n' > modules/present/local.txt
git -C modules/present add local.txt
git -C modules/present commit -q -m "a local commit"
# ... and what the scaffolder and `odoo module add` made: a --depth 1 clone
# registered in place, its .git kept in the working tree.
git clone -q --depth 1 --branch main "file://$ROOT/remotes/inplace.git" modules/inplace
git submodule init -q -- modules/inplace
declare -A head_before
for p in odoo modules/present modules/fresh modules/taken modules/inplace; do
  head_before[$p]="$(git -C "$p" rev-parse HEAD)"
done
check "(they start out shallow)" test "$(git -C modules/inplace rev-parse --is-shallow-repository)" = true
run
check_eq "exits 0" 0 "$RC"
for p in odoo modules/present modules/fresh modules/taken modules/inplace; do
  check "$p becomes a partial clone of every branch" partial_all_branches "$p"
  check_eq "…its checkout where it was" "${head_before[$p]}" "$(git -C "$p" rev-parse HEAD)"
done
check_eq "a local commit is kept, and the worktree left clean" "" "$(git -C modules/present status --porcelain)"
check "the paired branch gains its folders" has_obj modules/fresh 'origin/main~2^{tree}'
check "says what it is fetching" says "modules/fresh is a shallow or single-branch clone"
before="$(snapshot)"
run
after="$(snapshot)"
check_eq "the next entry changes nothing" "$before" "$after"
check_eq "…and says nothing" "" "$OUT"

echo "── a first checkout that fails ──────────────────────────────────"
cd "$ROOT/clone2"
mv "$ROOT/remotes/fresh.git" "$ROOT/remotes/fresh.git.away"
run
check_eq "exits 0" 0 "$RC"
check "names the submodule it could not check out" says "could not check out: modules/fresh"
check "…still checks out the rest" at_pin modules/present
check "…leaves the failed one's directory empty" empty modules/fresh
check_not "…with no URL left in the config" git config --get submodule.modules/fresh.url
check_not "…nor an activation" git config --get submodule.modules/fresh.active
mv "$ROOT/remotes/fresh.git.away" "$ROOT/remotes/fresh.git"
run
check "and the next entry tries again" at_pin modules/fresh

echo "── a repo with submodules of its own ────────────────────────────"
# A fetch's on-demand submodule check diffs every commit it brings in for a
# moved gitlink, and in a treeless clone each of those trees is a lazy fetch
# from the remote: one round trip per commit on another branch.
seed_remote ui
seed_remote nested
git -C "$ROOT/seed/nested" checkout -q main
git -C "$ROOT/seed/nested" submodule add -q "file://$ROOT/remotes/ui.git" ui
git -C "$ROOT/seed/nested" commit -q -m "add ui"
git -C "$ROOT/seed/nested" push -q "$ROOT/remotes/nested.git" main
commit_to nested other "other 2"
mkdir -p "$ROOT/nestproject"
cd "$ROOT/nestproject"
git init -q -b main
git submodule add -q -b main "file://$ROOT/remotes/nested.git" modules/nested
git commit -q -m project
git clone -q "$ROOT/nestproject" "$ROOT/nestclone"
cd "$ROOT/nestclone"
run
check_eq "exits 0" 0 "$RC"
check "checks it out as a partial clone of every branch" partial_all_branches modules/nested
# A clone an earlier odoo-nix made: commits without their folders, which is
# where the on-demand check is a lazy fetch per commit.
git -C modules/nested config remote.origin.partialclonefilter tree:0
commit_to nested other "other 3"
git -C modules/nested fetch -q
check_not "…so a plain git fetch in a clone made treeless does not fetch folders to look for submodule changes" \
  has_obj modules/nested 'origin/other^{tree}'
# A clone converted before the setting existed.
git -C modules/nested config --unset fetch.recurseSubmodules || true
run
check_eq "an existing treeless clone gets the setting on the next entry" \
  false "$(git -C modules/nested config --get fetch.recurseSubmodules)"
check_eq "…and folders along with the commits it fetches from now on" \
  blob:none "$(git -C modules/nested config --get remote.origin.partialclonefilter)"
check_eq "…silently" "" "$OUT"
git -C modules/nested config fetch.recurseSubmodules on-demand
run
check_eq "but one set by hand is left as it is" \
  on-demand "$(git -C modules/nested config --get fetch.recurseSubmodules)"
cd "$ROOT/clone"
run
check_eq "OCB stays commits only" tree:0 "$(git -C odoo config --get remote.origin.partialclonefilter)"

echo "── a pin the clone does not have ────────────────────────────────"
# `git submodule update` to a pin a partial clone lacks first asks the clone for
# it. The answer is a lazy fetch that negotiates nothing, so the remote sends
# the commit's whole history again -- a clone's worth of data per pin bump.
# Entry fetches the pin the ordinary way first.
pack_entries() { # <git dir> -- object entries across all of its packs
  local n=0 i
  for i in "$1"/objects/pack/*.idx; do n=$((n + $(git show-index < "$i" | wc -l))); done
  echo "$n"
}
bump_pin() { # <name> -- point the project at the remote's main tip
  git update-index --cacheinfo "160000,$(git -C "$ROOT/remotes/$1.git" rev-parse main),modules/$1"
}
seed_remote pins
for i in $(seq 40); do commit_to pins main "main 1$i"; done
mkdir -p "$ROOT/pinproject"
cd "$ROOT/pinproject"
git init -q -b main
git submodule add -q -b main "file://$ROOT/remotes/pins.git" modules/pins
git commit -q -m project
git clone -q "$ROOT/pinproject" "$ROOT/pinclone"
git clone -q "$ROOT/pinproject" "$ROOT/pincontrol"
for c in pinclone pincontrol; do
  cd "$ROOT/$c"
  run
done
GD=.git/modules/modules/pins

# The control: what git does by itself, with no entry in between.
cd "$ROOT/pincontrol"
for i in 1 2 3 4 5; do commit_to pins main "main 2$i"; done
bump_pin pins
before="$(pack_entries $GD)"
git submodule update -q -- modules/pins
raw=$(($(pack_entries $GD) - before))
echo "  · (git alone: a submodule update to a new pin adds $raw object entries to a clone of $before)"

cd "$ROOT/pinclone"
bump_pin pins
before="$(pack_entries $GD)"
run
check_eq "exits 0" 0 "$RC"
check "entry fetches the pin the clone lacked" has_obj modules/pins "$(git ls-files -s -- modules/pins | awk '{ print $2 }')"
check "…and says nothing about it" silent_on "pinned commit"
git submodule update -q -- modules/pins
added=$(($(pack_entries $GD) - before))
check "a submodule update to it then lands on the pin" at_pin modules/pins
# The history is 45 commits and, with their folders, over 180 objects: what a
# lazy fetch of the pin sends. What is new is 5 commits and their folders.
check "…and adds only what is new ($added object entries; git alone added $raw)" \
  test "$added" -lt 60
if [ "$raw" -lt 60 ]; then
  echo "  · note: git alone no longer re-downloads the history for a new pin; prefetch_pin may be unneeded"
fi
# Offline, or a remote that no longer has the pin: said, and the clone left alone.
for i in 1 2 3; do commit_to pins main "main 3$i"; done
bump_pin pins
mv "$ROOT/remotes/pins.git" "$ROOT/remotes/pins.git.away"
before="$(pack_entries $GD)"
run
check_eq "exits 0 when the remote cannot be reached" 0 "$RC"
check "…says the pin could not be fetched" says "could not fetch modules/pins's pinned commit"
check "…and the history it would cost" says "download its whole history again"
check_eq "…leaving the clone's packs as they were" "$before" "$(pack_entries $GD)"
mv "$ROOT/remotes/pins.git.away" "$ROOT/remotes/pins.git"
run
check "the next entry fetches it" has_obj modules/pins "$(git ls-files -s -- modules/pins | awk '{ print $2 }')"

echo "── a clone that took the repeated download ──────────────────────"
# pincontrol ran `git submodule update` on its own, above: the history again, as
# a pack beside the one it was already in.
cd "$ROOT/pincontrol"
unique() { GIT_NO_LAZY_FETCH=1 git -C modules/pins cat-file --batch-all-objects --batch-check='%(objectname)' 2> /dev/null | wc -l | tr -d ' '; }
u="$(unique)"
entries="$(pack_entries $GD)"
check "(it holds more object entries than objects: $entries for $u)" test "$entries" -gt $((u + u / 5))
run
check_eq "exits 0" 0 "$RC"
check "an entry merges the repeat away: $(pack_entries $GD) entries" test "$(pack_entries $GD)" -le $((u + u / 10))
check_eq "…keeping every object" "$u" "$(unique)"
check_eq "…silently" "" "$OUT"

echo "── a partial clone with many packs ──────────────────────────────"
# Every lazy fetch is a pack of its own. The `git maintenance run --auto` that a
# fetch starts does not merge them in a partial clone.
cd "$ROOT/pinclone"
for i in 1 2 3 4 5 6 7; do
  commit_to pins other "other 4$i"
  git -C modules/pins fetch -q
done
packs() { find "$GD/objects/pack" -name '*.pack' | wc -l | tr -d ' '; }
objects() { git -C modules/pins rev-list --all --objects --missing=allow-promisor | wc -l | tr -d ' '; }
check "(a pack per fetch piles up)" test "$(packs)" -gt 4
objs_before="$(objects)"
run
check_eq "exits 0" 0 "$RC"
check "an entry consolidates them" test "$(packs)" -le 4
check_eq "…without losing an object" "$objs_before" "$(objects)"
check_eq "…silently" "" "$OUT"
git -C modules/pins config remote.origin.partialclonefilter 'blob:limit=1k'
run
check_eq "a filter set by hand is left as it is" 'blob:limit=1k' "$(git -C modules/pins config --get remote.origin.partialclonefilter)"

echo "── no submodules ────────────────────────────────────────────────"
mkdir -p "$ROOT/plain"
OUT="$("$TOOL" "$ROOT/plain" 2>&1)" && RC=0 || RC=$?
check_eq "exits 0" 0 "$RC"
check_eq "and prints nothing" "" "$OUT"

echo
if [ "$fails" -gt 0 ]; then
  echo "$fails check(s) failed"
  exit 1
fi
echo "all checks passed"
