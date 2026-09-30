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
# Submodule operations on file:// URLs are refused by default.
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=protocol.file.allow GIT_CONFIG_VALUE_0=always

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
# of origin fetched, and commits only from here on.
partial_all_branches() { # <path>
  [ "$(git -C "$1" config remote.origin.promisor)" = true ] \
    && [ "$(git -C "$1" rev-parse --is-shallow-repository)" = false ] \
    && [ "$(git -C "$1" config --get-all remote.origin.fetch)" = '+refs/heads/*:refs/remotes/origin/*' ] \
    && [ "$(git -C "$1" config remote.origin.partialclonefilter)" = tree:0 ] \
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
check_not "another branch has its commits but not its folders" has_obj modules/present 'origin/other^{tree}'
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
