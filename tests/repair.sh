#!/usr/bin/env bash
# odoo-nix-repair: what `nix run github:Avunu/odoo-nix#repair` does to a project Nix cannot
# read. The logic and its cases are python-devops-nix's lib.sources; this is the
# product's configuration of it, on the state it exists for: a submodule shallow
# (what `git submodule update --init` makes of `shallow = true`), and one removed
# by hand. `nix` is not on PATH here, so the last step is reported as not done.
#
# Usage: repair.sh <path-to-the-repair-command>
set -euo pipefail

TOOL="$1"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com
export GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
export GIT_CONFIG_COUNT=2
export GIT_CONFIG_KEY_0=protocol.file.allow GIT_CONFIG_VALUE_0=always
export GIT_CONFIG_KEY_1=init.defaultBranch GIT_CONFIG_VALUE_1=main

fail() {
  echo "✗ $1" >&2
  exit 1
}

remote() { # <name>
  git init -q "$ROOT/seed/$1"
  for n in 1 2 3; do
    printf '%s\n' "$n" > "$ROOT/seed/$1/f"
    git -C "$ROOT/seed/$1" add f
    git -C "$ROOT/seed/$1" commit -q -m "$n"
  done
  git clone -q --bare "$ROOT/seed/$1" "$ROOT/remotes/$1.git"
  git -C "$ROOT/remotes/$1.git" config uploadpack.allowFilter true
}

remote shallow
remote removed
remote odoo

git init -q "$ROOT/project"
cd "$ROOT/project"
git submodule add -q -b main "file://$ROOT/remotes/shallow.git" modules/shallow
git submodule add -q -b main "file://$ROOT/remotes/removed.git" modules/removed
git submodule add -q -b main "file://$ROOT/remotes/odoo.git" odoo
git commit -q -m project

git clone -q "$ROOT/project" "$ROOT/clone"
cd "$ROOT/clone"
git submodule update -q --init --depth 1 -- modules/shallow odoo
git submodule update -q --init -- modules/removed
rm -rf modules/removed
printf 'a change\n' > uncommitted
[ "$(git -C modules/shallow rev-parse --is-shallow-repository)" = true ] || fail "the fixture is not shallow"

output="$("$TOOL" 2>&1)" || fail "repair failed: $output"
grep -qF "odoo-nix: the project's sources are settled" <<< "$output" || fail "repair did not say it settled: $output"
[ "$(git -C modules/shallow rev-parse --is-shallow-repository)" = false ] || fail "modules/shallow is still shallow"
[ -f modules/removed/f ] || fail "modules/removed was not brought back"
[ "$(cat uncommitted)" = "a change" ] || fail "repair touched an uncommitted file"
[ "$(git -C odoo config remote.origin.partialclonefilter)" = tree:0 ] || fail "odoo is not commits-only"

mkdir "$ROOT/empty"
cd "$ROOT/empty"
if "$TOOL" > /dev/null 2>&1; then fail "outside a repository, repair should fail"; fi

echo "all checks passed"
