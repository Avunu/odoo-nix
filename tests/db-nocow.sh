#!/usr/bin/env bash
# Checks for `odoo-nix-db-nocow` -- keeping the dev PostgreSQL datadir off btrfs
# copy-on-write. See lib/db-nocow.nix. Ported from frappe-nix's tests/db-nocow.sh.
#
# Usage: db-nocow.sh <path-to-odoo-nix-db-nocow>
#
# What the tool does depends on the filesystem it runs on, and a build sandbox
# lives on whatever the builder's temp directory is (tmpfs, usually). So the
# assertions branch: on btrfs they check the attribute is really set and the
# copy really made; on anything else, that every subcommand is a silent no-op.
# Both branches check the refusals. To run the btrfs branch by hand, point
# TMPDIR at a btrfs directory.
set -euo pipefail

TOOL="$1"

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

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
nocow() { lsattr -d -- "$1" 2> /dev/null | cut -d' ' -f1 | grep -q C; }

if [ "$(stat -f -c %T "$ROOT")" = btrfs ]; then
  btrfs=1
  echo "(running on btrfs: checking the attribute and the copy)"
else
  btrfs=0
  echo "(not on btrfs: checking that nothing is done)"
fi

echo "── prepare, before initdb ───────────────────────────────────────"
# devenv runs initdb only when $PGDATA does not exist: it must not be created.
out=$("$TOOL" prepare "$ROOT/state/postgres")
check "a missing datadir is not created (devenv would skip initdb)" test ! -e "$ROOT/state/postgres"
check "…its parent is" test -d "$ROOT/state"
check "…silently" test -z "$out"
# What initdb does: mkdir, then files.
mkdir "$ROOT/state/postgres"
touch "$ROOT/state/postgres/PG_VERSION"
if [ "$btrfs" = 1 ]; then
  check "the parent gets copy-on-write off for initdb's mkdir" nocow "$ROOT/state"
  check "…which the datadir inherits" nocow "$ROOT/state/postgres"
  check "…and its files with it" nocow "$ROOT/state/postgres/PG_VERSION"
else
  check_not "no attribute is set off btrfs" nocow "$ROOT/state"
fi
out=$("$TOOL" prepare "$ROOT/state/postgres")
check "the next entry is silent" test -z "$out"
check_not "…and clears the parent's attribute" nocow "$ROOT/state"
check "…and its marker" test ! -e "$ROOT/state/.odoo-nix-nocow-parent"
if [ "$btrfs" = 1 ]; then
  check "…leaving the datadir's" nocow "$ROOT/state/postgres"
fi

echo "── prepare, existing datadirs ───────────────────────────────────"
mkdir -p "$ROOT/empty"
out=$("$TOOL" prepare "$ROOT/empty")
check "an empty datadir is prepared silently" test -z "$out"
if [ "$btrfs" = 1 ]; then
  check "…with copy-on-write off" nocow "$ROOT/empty"
fi

mkdir -p "$ROOT/used"
echo 16 > "$ROOT/used/PG_VERSION"
out=$("$TOOL" prepare "$ROOT/used")
check_not "a datadir already holding a cluster is left as it is" nocow "$ROOT/used"
if [ "$btrfs" = 1 ]; then
  check "…and reported, with the command that fixes it" \
    grep -q "odoo-nix-db-nocow migrate" <<< "$out"
else
  check "…and not reported off btrfs" test -z "$out"
fi

echo "── migrate ──────────────────────────────────────────────────────"
mkdir -p "$ROOT/db/base/1"
chmod 0700 "$ROOT/db"
echo one > "$ROOT/db/PG_VERSION"
echo two > "$ROOT/db/base/1/1259"

# PostgreSQL's lock file, naming a live process: the server is running.
sleep 30 &
server=$!
printf '%s\n%s\n' "$server" "$ROOT/db" > "$ROOT/db/postmaster.pid"
if [ "$btrfs" = 1 ]; then
  check_not "migrate refuses while PostgreSQL is running on the datadir" "$TOOL" migrate "$ROOT/db"
fi
kill "$server" 2> /dev/null || true
wait "$server" 2> /dev/null || true
# A crash leaves the file behind, naming a dead pid: not running.
check "migrate succeeds once it is stopped, past a stale postmaster.pid" "$TOOL" migrate "$ROOT/db"
rm -f "$ROOT/db/postmaster.pid"
check "the data is all still there" \
  test "$(cat "$ROOT/db/PG_VERSION")-$(cat "$ROOT/db/base/1/1259")" = "one-two"
check "the datadir keeps mode 0700, which PostgreSQL requires" test "$(stat -c %a "$ROOT/db")" = 700
if [ "$btrfs" = 1 ]; then
  check "the datadir has copy-on-write off" nocow "$ROOT/db"
  check "and so do the files copied into it" nocow "$ROOT/db/base/1/1259"
  check "the original is kept beside it" \
    test "$(cat "$ROOT"/db.cow-backup-*/base/1/1259)" = "two"
  check "a second migrate has nothing to do" "$TOOL" migrate "$ROOT/db"
  check "and leaves no second backup" \
    test "$(find "$ROOT" -maxdepth 1 -name 'db.cow-backup-*' | wc -l)" -eq 1
else
  check "nothing is copied off btrfs" \
    test "$(find "$ROOT" -maxdepth 1 -name 'db.*' | wc -l)" -eq 0
fi
check_not "a missing datadir is an error" "$TOOL" migrate "$ROOT/nope"

echo "── usage ────────────────────────────────────────────────────────"
check_not "no arguments is an error" "$TOOL"
check_not "an unknown subcommand is an error" "$TOOL" frobnicate
check_not "prepare takes one datadir" "$TOOL" prepare "$ROOT/a" "$ROOT/b"

echo ""
if [ "$fails" -eq 0 ]; then
  echo "All db-nocow checks passed."
else
  echo "$fails check(s) failed."
  exit 1
fi
