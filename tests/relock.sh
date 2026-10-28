# A project's `nix run .#relock` (lib/relock.nix), offline: the app built with
# the workspace configuration a shell would bake (lib/cli-scripts.nix), OCB a
# flake input (coreSource, a stand-in tree), uv and odoo-nix-build-deps stand-ins
# that log to $CALLS. The project's uv.lock is stale: modules.txt gained
# queue_job and nothing re-locked it. lib/oca_sources.py, odoo-nix-sources and
# git are real.
#
#   bash tests/relock.sh <odoo-nix-relock> <OCB tree> <templates/project/pyproject.toml> <interpreter>
set -euo pipefail
relock=$1
ocb=$2
pyproject_template=$3
python=$4

T=$PWD
export CALLS=$T/calls HOME=$T
unset REPO_ROOT UV_PYTHON

fails=0
pass() { printf '  ok %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1" >&2
  fails=$((fails + 1))
}
check() {
  local desc=$1
  shift
  if "$@"; then pass "$desc"; else fail "$desc"; fi
}
refute() { ! "$@"; }
hasF() { grep -qF -- "$1" "$2"; }

# run <args...>: the app in the working directory; stdout in $T/out, stderr in
# $T/err, the status in $rc, the stand-ins' calls in $CALLS.
run() {
  echo "== ${PWD#"$T"}: nix run .#relock $*"
  : > "$CALLS"
  rc=0
  "$relock" "$@" < /dev/null > "$T/out" 2> "$T/err" || rc=$?
}
expect_rc() {
  if [ "$rc" = "$1" ]; then
    pass "exit $1"
  else
    fail "exit $rc, expected $1"
    sed 's/^/    out: /' "$T/out" >&2
    sed 's/^/    err: /' "$T/err" >&2
  fi
}

# A fresh clone of a project: no odoo/ link yet (the shell never started), one
# module in modules.txt that the lock does not have.
mkdir -p "$T/shop/custom" "$T/shop/modules/queue/queue_job"
cd "$T/shop"
sed -e 's/@PROJECT_NAME@/shop/; s/@REQUIRES_PYTHON@/>=3.11/' "$pyproject_template" > pyproject.toml
echo queue_job > modules.txt
echo "{'name': 'Job Queue', 'depends': ['base']}" > modules/queue/queue_job/__manifest__.py
printf '[project]\nname = "odoo-addon-queue_job"\n' > modules/queue/queue_job/pyproject.toml
printf 'version = 1\n# stale\n' > uv.lock

run --upgrade-package lxml
expect_rc 0
check "the install set and the module sources are regenerated" eval \
  'hasF "\"odoo-addon-queue_job\"," pyproject.toml && hasF "\"odoo-addon-queue_job\" = { path = \"modules/queue/queue_job\", editable = true }" pyproject.toml'
check "...and OCB as a path source" hasF 'odoo = { path = "odoo" }' pyproject.toml
check "uv lock with the arguments, the build-dependency block, uv lock again" eval \
  '[ "$(cut -d" " -f1-2 "$CALLS" | tr "\n" ";")" = "uv lock;build-deps update;uv lock;" ]'
check "...the arguments whole" hasF 'uv lock --upgrade-package lxml shadow' "$CALLS"
check "each lock through a writable shadow of OCB" eval '[ "$(grep -c "^uv lock.* shadow " "$CALLS")" = 2 ]'
check "uv locks with the project's interpreter" eval '[ "$(grep -c "^uv lock.* UV_PYTHON=$python\$" "$CALLS")" = 2 ]'
check "the lock is rewritten" hasF 'locked' uv.lock
check "odoo/ is made, a link to OCB, as shell entry would" eval '[ "$(readlink odoo)" = "$ocb" ]'
check "it says it is done" hasF '✅ Re-locked' "$T/out"

# From elsewhere: the project root is $REPO_ROOT, else the working directory.
mkdir -p custom/sub
cd custom/sub
run
expect_rc 1
check "outside the root it refuses" hasF 'odoo-nix-relock: no pyproject.toml in' "$T/err"
check "...and runs nothing" refute test -s "$CALLS"
REPO_ROOT=$T/shop run
expect_rc 0
check "\$REPO_ROOT is the root" hasF 'build-deps update pyproject.toml uv.lock' "$CALLS"
cd "$T/shop"

UV_FAIL=1 run
expect_rc 3
check "a failed lock is said" hasF 'uv lock failed' "$T/err"
check "...and nothing follows it" eval '[ "$(wc -l < "$CALLS")" = 1 ]'
check "...and nothing says it is done" refute hasF '✅' "$T/out"
check "odoo/ points at OCB again" eval '[ "$(readlink odoo)" = "$ocb" ]'

BUILD_DEPS_FAIL=1 run
expect_rc 4
check "a failed build-dependency sync still locks again" eval '[ "$(tail -n1 "$CALLS" | cut -d" " -f1-2)" = "uv lock" ]'
check "...and is said" hasF 'odoo-nix-build-deps, or the uv lock after it, failed' "$T/err"

run --upgrade --help
expect_rc 0
check "--help is the app's own, not uv's" hasF 'Usage: nix run .#relock' "$T/out"
check "...and runs nothing" refute test -s "$CALLS"

# A pull that brought a new repository: .gitmodules and modules.txt name it,
# and the clone has never checked it out, as a pull does not. The app checks
# it out as shell entry would, so its module stays in the lock.
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.com
export GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.com
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=protocol.file.allow GIT_CONFIG_VALUE_0=always
git init -q -b 18.0 "$T/queue"
mkdir "$T/queue/queue_job"
echo "{'name': 'Job Queue', 'depends': ['base']}" > "$T/queue/queue_job/__manifest__.py"
printf '[project]\nname = "odoo-addon-queue_job"\n' > "$T/queue/queue_job/pyproject.toml"
git -C "$T/queue" add -A
git -C "$T/queue" commit -qm queue
git init -q -b main "$T/upstream"
cd "$T/upstream"
sed -e 's/@PROJECT_NAME@/shop/; s/@REQUIRES_PYTHON@/>=3.11/' "$pyproject_template" > pyproject.toml
echo queue_job > modules.txt
printf 'version = 1\n# stale\n' > uv.lock
git submodule add -q -b 18.0 "file://$T/queue" modules/queue
git add -A
git commit -qm project
git clone -q "$T/upstream" "$T/clone"
cd "$T/clone"
check "the clone has not checked the repository out" refute test -e modules/queue/queue_job
run
expect_rc 0
check "the app checks it out" test -f modules/queue/queue_job/__manifest__.py
check "...as shell entry would" hasF 'checking out modules/queue' "$T/err"
check "...so its module stays in the install set and the module sources" eval \
  'hasF "\"odoo-addon-queue_job\"," pyproject.toml && hasF "\"odoo-addon-queue_job\" = { path = \"modules/queue/queue_job\", editable = true }" pyproject.toml'
check "...and none is skipped" refute hasF 'not found on disk' "$T/err"
check "the lock is rewritten" hasF 'locked' uv.lock

if [ "$fails" -gt 0 ]; then
  echo "relock: $fails failure(s)" >&2
  exit 1
fi
echo "relock: ok"
