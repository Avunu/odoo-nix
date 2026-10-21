# The scaffolder, offline: odoo-nix-sources and uv are stand-ins, so nothing is
# fetched and nothing is locked, and git is the real one. The stand-in clone is
# an empty repository on the branch asked for, so the submodules, .gitmodules
# and the index are real. What is checked is every flag and branch odoo-init
# has: what it writes into the template, the submodules, modules.txt, the
# install set handed to uv, its refusals and their exit codes, and what it
# prints at the end.
#
#   bash tests/odoo-init.sh <odoo-init's script (lib/init.nix passthru.script)>
#
# Prompts (a terminal on stdin and stdout) are not reached here: every run has
# stdin from /dev/null.
set -euo pipefail
script=$1

T=$PWD
stubs=$T/stubs
export STUB_LOG=$T/log
mkdir -p "$stubs" "$STUB_LOG" "$T/tmp"
# Where odoo-init stages the template; checked for leftovers at the end.
export TMPDIR=$T/tmp
export HOME=$T GIT_CONFIG_GLOBAL=$T/gitconfig
git config --global user.name t
git config --global user.email t@example.com
git config --global init.defaultBranch main
git config --global protocol.file.allow always

# odoo-nix-sources clone --branch <b> --require-branch [--treeless] <url> <path>:
# an empty repository on <b> with <url> as its origin. A URL matching
# $STUB_NOBRANCH has no such branch (the real tool's exit 3); one matching
# $STUB_FAIL cannot be cloned at all.
cat > "$stubs/odoo-nix-sources" <<SH
#!$BASH
set -eu
echo "\$*" >> "\$STUB_LOG/sources"
[ "\$1" = clone ] || exit 0
shift
branch=
while [ \$# -gt 0 ]; do
  case \$1 in
    --branch) branch=\$2; shift 2 ;;
    --require-branch | --treeless) shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done
url=\$1 path=\$2
case \$url in *"\${STUB_NOBRANCH:-@none@}"*) echo "odoo-nix: \$url has no branch \$branch" >&2; exit 3 ;; esac
case \$url in *"\${STUB_FAIL:-@none@}"*) echo "odoo-nix: cannot clone \$url" >&2; exit 128 ;; esac
git init -q -b "\$branch" "\$path"
git -C "\$path" commit -q --allow-empty -m init
git -C "\$path" remote add origin "\$url"
SH
# uv <args>: logged; `uv lock` writes a lock with no packages in it, or fails
# when $STUB_UV_FAIL is set.
cat > "$stubs/uv" <<SH
#!$BASH
echo "\$*" >> "\$STUB_LOG/uv"
if [ -n "\${STUB_UV_FAIL:-}" ]; then echo "uv: no solution" >&2; exit 1; fi
if [ "\$1" = lock ]; then printf 'version = 1\nrevision = 3\nrequires-python = ">=3.11"\n' > uv.lock; fi
SH
chmod +x "$stubs/odoo-nix-sources" "$stubs/uv"

fails=0
pass() { printf '  ok %s\n' "$1"; }
fail() {
  printf '  FAIL %s\n' "$1" >&2
  fails=$((fails + 1))
}
check() { # <description> <command...>
  local desc=$1
  shift
  if "$@"; then pass "$desc"; else fail "$desc"; fi
}
refute() { ! "$@"; }
has() { grep -qE -- "$1" "$2"; }
hasF() { grep -qF -- "$1" "$2"; }

# init <case> <args...>: odoo-init in a fresh directory $T/<case>, with stdout
# in $T/<case>/out, stderr in $T/<case>/err, and the exit status in $rc.
prep() {
  rm -rf "${T:?}/$1"
  mkdir -p "$T/$1"
  cd "$T/$1"
}
run() {
  echo "== ${PWD##*/}: odoo-init $*"
  : > "$STUB_LOG/sources"
  : > "$STUB_LOG/uv"
  rc=0
  PATH="$stubs:$PATH" bash -euo pipefail "$script" "$@" < /dev/null > out 2> err || rc=$?
}
init() {
  prep "$1"
  shift
  run "$@"
}
expect_rc() {
  if [ "$rc" = "$1" ]; then
    pass "exit $1"
  else
    fail "exit $rc, expected $1"
    sed 's/^/    out: /' out >&2
    sed 's/^/    err: /' err >&2
  fi
}

# ── the command line ─────────────────────────────────────────────────────────
init help --help
expect_rc 0
check "--help prints the usage" has '^Usage: odoo-init \[options\] \[target-dir\]' out
check "--help names --bundles and --modules" eval 'has --bundles out && has --modules out'
for flag in --version --init --migrate --force --dry-run '-y, --yes' --skip-lock --commit; do
  check "--help names $flag" hasF "$flag" out
done
check "--help does not name the old --series" refute hasF --series out

init no-value --version
expect_rc 1
check "a value flag with no value says so" hasF '--version needs a value' err

init unknown-flag --bogus
expect_rc 1
check "an unknown flag is named" grep -qiF 'unknown flag: --bogus' err
check "an unknown flag prints the usage" hasF 'Usage: odoo-init' err

# ── the series ───────────────────────────────────────────────────────────────
init no-series acme
expect_rc 5
check "no series and no terminal: it is required" has 'is required \(one of: 18\.0 19\.0\)' err
check "nothing is written without a series" test ! -e acme

init bad-series --version 17.0 acme
expect_rc 5
check "an unknown series is named, with the known ones" eval "has \"'17\\.0'\" err && has '18\\.0 19\\.0' err"
check "nothing is written for an unknown series" test ! -e acme

# ── the target ───────────────────────────────────────────────────────────────
prep not-empty
mkdir acme
touch acme/notes.txt
run --version 18.0 acme
expect_rc 6
check "a non-empty target is refused" has "acme'.*not empty" err
check "a non-empty target is left alone" eval '[ "$(ls -A acme)" = notes.txt ]'

# ── a project with modules ───────────────────────────────────────────────────
# account_tax_balance (account-financial-reporting) depends on date_range, in
# server-ux; not_a_module is in no catalog and is recorded all the same.
init full --version 18.0 --name "Acme Shop" --db "acme-db" \
  --modules account_tax_balance,not_a_module,account_tax_balance acme
expect_rc 0
flake=acme/flake.nix
check "flake.nix: the identity is odoo-nix.name, normalised" has '^\s*name = "acme-shop";$' "$flake"
check "flake.nix: no projectName" refute hasF projectName "$flake"
check "flake.nix: the database, normalised" has '^\s*settings\.dbName = "acme_db";$' "$flake"
check "flake.nix: the series" has '^\s*odooSeries = "18\.0";$' "$flake"
check "flake.nix: the series' interpreter" has '^\s*python = pkgs\.python311;$' "$flake"
check "pyproject.toml: [project].name" has '^name = "acme-shop"$' acme/pyproject.toml
check "pyproject.toml: requires-python from the preset" has '^requires-python = ">=3\.11"$' acme/pyproject.toml
check "no @TOKEN@ is left in the tree" refute grep -rqE --exclude-dir=.git '@[A-Z_]+@' acme
check "the template's custom/ is there" test -d acme/custom
check "modules.txt: the modules asked for, sorted, once each" \
  eval '[ "$(cat acme/modules.txt)" = "$(printf "account_tax_balance\nnot_a_module")" ]'
check "OCB is a partial clone of the series' branch, commits only" \
  hasF 'clone --branch 18.0 --require-branch --treeless https://github.com/OCA/OCB.git odoo' "$STUB_LOG/sources"
check "an OCA repo is a partial clone of the series' branch" \
  hasF 'clone --branch 18.0 --require-branch https://github.com/OCA/account-financial-reporting.git modules/account-financial-reporting' "$STUB_LOG/sources"
check "the dependency closure reaches server-ux" \
  hasF 'https://github.com/OCA/server-ux.git modules/server-ux' "$STUB_LOG/sources"
check "only the closure is cloned (OCB and two repos)" eval '[ "$(grep -c "^clone " "$STUB_LOG/sources")" = 3 ]'
gm=acme/.gitmodules
for p in odoo modules/account-financial-reporting modules/server-ux; do
  check ".gitmodules: $p on 18.0, shallow" eval \
    "[ \"\$(git config -f $gm submodule.$p.branch)\" = 18.0 ] && [ \"\$(git config -f $gm submodule.$p.shallow)\" = true ]"
done
check ".gitmodules: OCB's URL" eval "[ \"\$(git config -f $gm submodule.odoo.url)\" = https://github.com/OCA/OCB.git ]"
check "the install set names odoo" hasF '"odoo",' acme/pyproject.toml
check "OCB is a path source" hasF 'odoo = { path = "odoo" }' acme/pyproject.toml
check "uv lock, then lock again after the build dependencies" eval '[ "$(cat "$STUB_LOG/uv")" = "$(printf "lock\nlock")" ]'
check "everything is staged" eval \
  '[ -z "$(git -C acme status --porcelain | grep -v "^[AM] ")" ]'
for f in flake.nix pyproject.toml modules.txt .gitmodules uv.lock odoo modules/server-ux; do
  check "staged: $f" eval "git -C acme ls-files --error-unmatch -- $f > /dev/null 2>&1"
done
check "nothing is committed" refute git -C acme rev-parse -q --verify HEAD
check "the summary names the series and the interpreter" hasF '18.0' out
check "next steps: cd into the project" has '^  cd acme$' out
check "next steps: direnv allow" hasF 'direnv allow' out
check "next steps: devenv up" hasF 'devenv up' out
check "next steps: odoo db provision" hasF 'odoo db provision' out
check "next steps: review what is staged" hasF 'git diff --cached --stat' out
check "next steps: where restoring from backups is described" hasF 'Restore a production backup' out
check "secrets/README.md is seeded" hasF 'odoo-nix.secrets' acme/secrets/README.md
check "staged: secrets/README.md" eval 'git -C acme ls-files --error-unmatch -- secrets/README.md > /dev/null 2>&1'
check "no warnings: no warnings summary" refute hasF 'warning(s):' out

# ── defaults ─────────────────────────────────────────────────────────────────
init defaults --version 18.0
expect_rc 0
check "no target: ./odoo-project" test -f odoo-project/flake.nix
check "the name defaults to the target's" has '^\s*name = "odoo-project";$' odoo-project/flake.nix
check "the database defaults to odoo" has '^\s*settings\.dbName = "odoo";$' odoo-project/flake.nix
check "no modules: an empty modules.txt" test ! -s odoo-project/modules.txt
check "no modules: OCB alone" eval '[ "$(grep -c "^clone " "$STUB_LOG/sources")" = 1 ]'
check "no modules: the summary says core only" hasF 'Odoo core only' out

init names --version 18.0 --name '!!!' --db '__Shop DB' acme
expect_rc 0
check "a name with nothing left falls back to odoo-project" has '^\s*name = "odoo-project";$' acme/flake.nix
check "a database name loses leading underscores and odd characters" has '^\s*settings\.dbName = "shop_db";$' acme/flake.nix

init equals --version=19.0 --name=eq --db=eqdb --modules=partner_firstname eq
expect_rc 0
check "--flag=value: the series" has '^\s*odooSeries = "19\.0";$' eq/flake.nix
check "--flag=value: 19.0's interpreter" has '^\s*python = pkgs\.python312;$' eq/flake.nix
check "--flag=value: the name" has '^\s*name = "eq";$' eq/flake.nix
check "--flag=value: the modules" eval '[ "$(cat eq/modules.txt)" = partner_firstname ]'

init apps --version 18.0 --apps partner_firstname acme
expect_rc 0
check "--apps is --modules" eval '[ "$(cat acme/modules.txt)" = partner_firstname ]'
check "--apps: partner-contact is cloned" hasF 'modules/partner-contact' "$STUB_LOG/sources"

# ── bundles ──────────────────────────────────────────────────────────────────
# The project bundle has two members with no 19.0 release.
init bundles --version 19.0 --bundles project,nope --modules partner_firstname acme
expect_rc 0
check "an unknown bundle is named, with the known ones" eval \
  'hasF "unknown bundle: nope" err && hasF "oca-accounting" err'
check "bundle members not in the series are named and skipped" \
  hasF 'not available for 19.0, skipped: project_task_add_very_high project_timesheet_time_control' err
check "modules.txt: the bundle's in-series members and --modules, unioned and sorted" eval \
  '[ "$(cat acme/modules.txt)" = "$(printf "%s\n" partner_firstname project_parent project_pivot project_task_default_stage project_task_description_template project_task_name_with_id project_timeline)" ]'
check "modules.txt holds no skipped member" refute hasF project_task_add_very_high acme/modules.txt
check "modules.txt is sorted and unique" eval 'LC_ALL=C sort -uc acme/modules.txt'
check "the summary lists the bundles" has 'bundles : project nope' out

# ── failures along the way ───────────────────────────────────────────────────
STUB_NOBRANCH=server-ux init nobranch --version 18.0 --modules account_tax_balance acme
expect_rc 0
check "a repo with no branch for the series is skipped" refute hasF 'modules/server-ux' acme/.gitmodules
check "the skipped repo is in the warnings summary" eval \
  'hasF "1 warning(s):" out && grep -A1 -F "warning(s):" out | grep -qF "server-ux.git has no 18.0 branch"'
check "the rest of the closure is still added" hasF 'modules/account-financial-reporting' acme/.gitmodules

STUB_FAIL=OCB init ocb-fails --version 18.0 acme
expect_rc 1
check "OCB that cannot be cloned stops the scaffold" refute test -e acme/.gitmodules

STUB_UV_FAIL=1 init uv-fails --version 18.0 acme
expect_rc 0
check "a failed uv lock is reported" hasF 'uv lock failed' err
check "a failed uv lock is in the warnings summary" eval 'grep -A1 -F "warning(s):" out | grep -qF "uv lock failed"'
check "a failed uv lock is not retried" eval '[ "$(cat "$STUB_LOG/uv")" = lock ]'
check "a failed uv lock still stages the project" eval \
  'git -C acme ls-files --error-unmatch -- flake.nix > /dev/null 2>&1'

# ── renamed flags ────────────────────────────────────────────────────────────
# --series is --version's old name (python-devops-nix CONVENTIONS.md,
# Scaffolder: version flag): it works, and warns, through 1.x.
init renamed --series 19.0 acme
expect_rc 0
check "--series still sets the series" has '^\s*odooSeries = "19\.0";$' acme/flake.nix
check "--series warns" hasF '--series is now --version' err
check "the warning is in the summary" eval 'grep -A1 -F "warning(s):" out | grep -qF -- "--series is now --version"'

# ── --init, --dry-run, --skip-lock, --commit ─────────────────────────────────
prep init-not-empty
mkdir acme
touch acme/notes.txt
run --init --version 18.0 acme
expect_rc 2
check "--init into a directory that is not empty is refused" has 'not empty' err
check "...and it is left alone" eval '[ "$(ls -A acme)" = notes.txt ]'

prep init-force
mkdir acme
echo mine > acme/README.md
run --init --force --version 18.0 acme
expect_rc 0
check "--init --force scaffolds into it" test -f acme/flake.nix
check "--init --force overwrites nothing" eval '[ "$(cat acme/README.md)" = mine ]'
check "--init --force names the project after the directory" has '^\s*name = "acme";$' acme/flake.nix

init dry-run --dry-run --version 18.0 --modules account_tax_balance acme
expect_rc 0
check "--dry-run: nothing is written" test ! -e acme
check "--dry-run: nothing is cloned" test ! -s "$STUB_LOG/sources"
check "--dry-run: nothing is locked" test ! -s "$STUB_LOG/uv"
check "--dry-run: the plan names the project and its interpreter" hasF "project 'acme' (Odoo 18.0 → python 3.11)" out
check "--dry-run: the plan names the repos" hasF 'account-financial-reporting server-ux' out
check "--dry-run: the plan lists the seeded files" eval \
  'hasF flake.nix out && hasF modules.txt out && hasF secrets/README.md out'
check "--dry-run says so" hasF '--dry-run: nothing was changed.' out

init skip-lock --skip-lock --version 18.0 acme
expect_rc 0
check "--skip-lock: uv is not run" test ! -s "$STUB_LOG/uv"
check "--skip-lock says so" hasF 'skipping uv lock (--skip-lock)' out
check "--skip-lock: the path sources are still written" hasF 'odoo = { path = "odoo" }' acme/pyproject.toml

init commit --commit --version 18.0 acme
expect_rc 0
check "--commit commits" eval '[ "$(git -C acme log --format=%s)" = "chore: scaffold odoo-nix project" ]'
check "--commit leaves nothing uncommitted" eval '[ -z "$(git -C acme status --porcelain)" ]'
check "--commit: next steps review the commit" hasF 'git show --stat' out

init commit-msg --commit="feat: our shop" --version 18.0 acme
expect_rc 0
check "--commit=<msg> commits with it" eval '[ "$(git -C acme log --format=%s)" = "feat: our shop" ]'

prep commit-target
run --version 18.0 --commit acme
expect_rc 0
check "--commit <dir> is the flag and a target" eval '[ "$(git -C acme log --format=%s)" = "chore: scaffold odoo-nix project" ]'

# ── migrate an existing tree ─────────────────────────────────────────────────
# tree: a git repository in odoo-nix's layout made without it: one module of
# its own under custom/ (a whool package of 18.0), its own README and .gitignore.
# (out and err, which run writes here, are excluded.)
tree() {
  git init -q .
  printf 'out\nerr\n' >> .git/info/exclude
  mkdir -p custom/shop_theme
  printf '{"name": "Shop theme", "version": "%s.1.0.0", "depends": ["website"]}\n' "${1:-18.0}" \
    > custom/shop_theme/__manifest__.py
  printf '[project]\nname = "odoo-addon-shop_theme"\n' > custom/shop_theme/pyproject.toml
  echo "# our shop" > README.md
  echo '*.log' > .gitignore
  git add -A
  git commit -q -m "our tree"
}

prep migrate-missing
run --migrate --version 18.0 nowhere
expect_rc 1
check "--migrate on a missing directory: nothing to migrate" hasF 'nothing to migrate' err

prep migrate-not-odoo
mkdir stuff
touch stuff/notes.txt
run --migrate --version 18.0 stuff
expect_rc 6
check "--migrate on a directory that is no Odoo tree is refused" hasF 'does not look like an Odoo tree' err

prep migrate-empty-tree
mkdir -p shop/custom shop/modules
touch shop/custom/.gitkeep
run shop
expect_rc 7
check "custom/ and modules/ with nothing in them: nothing to migrate" hasF 'Nothing to migrate' err

prep migrate-no-yes
mkdir shop && cd shop && tree && cd ..
run shop
expect_rc 6
check "without a terminal, migrating needs --yes" hasF 'Re-run with --yes' err
check "...and nothing is changed" eval '[ -z "$(git -C shop status --porcelain)" ] && [ ! -e shop/flake.nix ]'
check "the plan is printed first" hasF 'Plan for ' out

prep migrate-dry-run
mkdir shop && cd shop && tree
run --dry-run
expect_rc 0
check "--dry-run in the tree itself: the series, detected" hasF '18.0 (detected from the module manifests)' out
check "--dry-run: the files it would write" eval 'hasF flake.nix out && hasF pyproject.toml out'
check "--dry-run: OCB would be added" hasF 'add odoo/' out
check "--dry-run: nothing is changed" eval '[ -z "$(git status --porcelain)" ]'
check "--dry-run: nothing is cloned" test ! -s "$STUB_LOG/sources"

prep migrate
mkdir shop && cd shop && tree
run -y --modules partner_firstname
expect_rc 0
check "migrate: the project is named after the directory" has '^\s*name = "shop";$' flake.nix
check "migrate: the detected series" has '^\s*odooSeries = "18\.0";$' flake.nix
check "migrate: OCB is added" hasF 'clone --branch 18.0 --require-branch --treeless https://github.com/OCA/OCB.git odoo' "$STUB_LOG/sources"
check "migrate: --modules' repo is added" eval '[ "$(git config -f .gitmodules submodule.modules/partner-contact.branch)" = 18.0 ]'
check "migrate: modules.txt" eval '[ "$(cat modules.txt)" = partner_firstname ]'
check "migrate: the tree's own module is a uv path source" \
  hasF '"odoo-addon-shop_theme" = { path = "custom/shop_theme", editable = true }' pyproject.toml
check "migrate: README.md is kept" eval '[ "$(cat README.md)" = "# our shop" ]'
check "migrate: .gitignore keeps its patterns" has '^\*\.log$' .gitignore
check "migrate: .gitignore gains odoo-nix's" has '^/\.devenv/$' .gitignore
check "migrate: secrets/ is not seeded" test ! -e secrets
check "migrate: the history is kept" eval '[ "$(git log --format=%s)" = "our tree" ]'
check "migrate: everything is staged" eval '[ -z "$(git status --porcelain | grep -v "^[AM] ")" ]'
check "migrate: it says so" hasF "Project 'shop' migrated" out

prep migrate-gitmodules
mkdir shop && cd shop && tree 19.0
git config -f .gitmodules submodule.odoo.path odoo
git config -f .gitmodules submodule.odoo.url https://github.com/OCA/OCB.git
git config -f .gitmodules submodule.odoo.branch 18.0
run -y
expect_rc 0
check "the series .gitmodules pairs odoo/ with wins over the manifests" has '^\s*odooSeries = "18\.0";$' flake.nix
check "OCB registered in .gitmodules is not added again" refute grep -q '^clone' "$STUB_LOG/sources"

prep migrate-mismatch
mkdir shop && cd shop && tree
run -y --version 19.0
expect_rc 0
check "--version over a different detected series warns" hasF 'the module manifests says 18.0' err
check "--version wins" has '^\s*python = pkgs\.python312;$' flake.nix

prep migrate-undetectable
mkdir -p shop/odoo && touch shop/odoo/odoo-bin
run -y shop
expect_rc 5
check "a series that cannot be detected is asked for" hasF 'could not detect the Odoo series; pass --version' err

prep migrate-old-series
mkdir shop && cd shop && tree 16.0
run -y
expect_rc 5
check "a series with no preset is refused" hasF 'says Odoo 16.0, which odoo-nix has no preset for' err

prep migrate-foreign-flake
mkdir shop && cd shop && tree && echo '{ outputs = _: { }; }' > flake.nix
run -y
expect_rc 4
check "an Odoo tree with a flake.nix that is not odoo-nix's" hasF 'flake.nix is not odoo-nix' err
run -y --migrate --force
expect_rc 0
check "--migrate --force keeps flake.nix" eval '[ "$(cat flake.nix)" = "{ outputs = _: { }; }" ]'
check "--migrate --force writes odoo-nix's beside it" has '^\s*name = "shop";$' flake.nix.odoo-nix
check "...and says so" hasF 'merge it by hand' err

prep migrate-foreign-pyproject
mkdir shop && cd shop && tree && printf '[project]\nname = "ours"\n' > pyproject.toml
run -y
expect_rc 4
check "a pyproject.toml that is not odoo-nix's" hasF 'pyproject.toml exists and is not odoo-nix' err
run -y --force
expect_rc 0
check "--force keeps pyproject.toml" eval '[ "$(sed -n 2p pyproject.toml)" = "name = \"ours\"" ]'
check "--force writes odoo-nix's beside it" has '^name = "shop"$' pyproject.toml.odoo-nix
check "nothing is locked against a pyproject.toml that is not odoo-nix's" test ! -s "$STUB_LOG/uv"

prep migrate-nested
git init -q .
mkdir shop && cd shop && mkdir -p custom/m && echo '{"version": "18.0.1.0.0"}' > custom/m/__manifest__.py
run -y
expect_rc 8
check "a tree inside another repository is refused" hasF 'inside another git repository' err
run -y --force
expect_rc 0
check "--force makes it its own repository" eval '[ "$(git rev-parse --show-toplevel)" = "$PWD" ]'

# ── repair an odoo-nix project ───────────────────────────────────────────────
cd "$T/full/acme"
printf 'out\nerr\n' >> .git/info/exclude
run -y
expect_rc 0
check "repair: detected without a flag" hasF 'repair mode' out
check "repair: the name in flake.nix is kept" has '^\s*name = "acme-shop";$' flake.nix
check "repair: the database in flake.nix is kept" has '^\s*settings\.dbName = "acme_db";$' flake.nix
check "repair: nothing is cloned again" refute grep -q '^clone' "$STUB_LOG/sources"
check "repair: modules.txt is kept" eval '[ "$(cat modules.txt)" = "$(printf "account_tax_balance\nnot_a_module")" ]'
check "repair: it says so" hasF "Project 'acme-shop' repaired" out
run -y --modules partner_firstname
expect_rc 0
check "repair with --modules: only the new repo is cloned" eval \
  '[ "$(grep -c "^clone" "$STUB_LOG/sources")" = 1 ] && hasF modules/partner-contact "$STUB_LOG/sources"'
check "repair with --modules: modules.txt gains it" eval \
  '[ "$(cat modules.txt)" = "$(printf "account_tax_balance\nnot_a_module\npartner_firstname")" ]'
cd "$T"

check "no staging directory is left behind" eval '[ -z "$(ls -A "$T/tmp")" ]'

if [ "$fails" -gt 0 ]; then
  echo "odoo-init: $fails failure(s)" >&2
  exit 1
fi
echo "odoo-init: ok"
