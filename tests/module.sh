# `odoo module add`, `add-bundle` and `remove`, offline: the `odoo` CLI built
# with the workspace scripts and no Odoo, in a project with OCB stood in.
# odoo-nix-sources is a stand-in: a file:// remote is cloned for real (so a
# third-party repo has modules in it), any other URL becomes an empty
# repository on the branch asked for. git is real; uv is real and offline, so
# every lock fails and says so.
#
# `remove` cannot read a database here (the CLI has no Odoo), so it refuses
# to take away a module's code without --force: that refusal is checked, and
# the rest runs with --force or with no module code at stake.
#
#   bash tests/module.sh <odoo> <templates/project/pyproject.toml>
set -euo pipefail
odoo=$1
pyproject_template=$2

T=$PWD
stubs=$T/stubs
export STUB_LOG=$T/log
mkdir -p "$stubs" "$STUB_LOG"
export HOME=$T GIT_CONFIG_GLOBAL=$T/gitconfig UV_OFFLINE=1 UV_NO_CACHE=1
git config --global user.name t
git config --global user.email t@example.com
git config --global init.defaultBranch main
git config --global protocol.file.allow always

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
case \$url in
  file://*)
    git ls-remote --exit-code --heads "\$url" "\$branch" > /dev/null || exit 3
    git clone -q --branch "\$branch" "\$url" "\$path" ;;
  *)
    git init -q -b "\$branch" "\$path"
    git -C "\$path" commit -q --allow-empty -m init
    git -C "\$path" remote add origin "\$url" ;;
esac
SH
chmod +x "$stubs/odoo-nix-sources"
export PATH="$stubs:$PATH"

# Third-party remotes: one module at the root; two modules on 18.0 and on
# main; no module at all, on main only.
remote() { # <name> <branch> <module dirs...>
  local name=$1 branch=$2
  shift 2
  local w=$T/work/$name
  mkdir -p "$w"
  git -C "$w" init -q -b "$branch"
  for m in "$@"; do
    mkdir -p "$w/$m"
    echo "{'name': '$m', 'version': '18.0.1.0.0'}" > "$w/$m/__manifest__.py"
  done
  echo x > "$w/README"
  git -C "$w" add -A
  git -C "$w" commit -q -m init
  git clone -q --bare "$w" "$T/remotes/$name.git"
}
mkdir -p "$T/remotes"
remote single main .
remote multi 18.0 mod_one mod_two
git -C "$T/remotes/multi.git" branch main 18.0
remote bare main

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
has() { grep -qE -- "$1" "$2"; }
hasF() { grep -qF -- "$1" "$2"; }

# project <case>: a fresh project in $T/<case>, OCB at odoo/ (an empty
# submodule), committed, and the working directory.
project() {
  rm -rf "${T:?}/$1"
  mkdir -p "$T/$1"
  cd "$T/$1"
  git init -q .
  printf 'out\nerr\n' >> .git/info/exclude
  sed -e 's/@PROJECT_NAME@/shop/; s/@REQUIRES_PYTHON@/>=3.11/' "$pyproject_template" > pyproject.toml
  : > modules.txt
  mkdir custom
  touch custom/.gitkeep
  odoo-nix-sources clone --branch 18.0 --require-branch https://github.com/OCA/OCB.git odoo
  git submodule add -q -b 18.0 https://github.com/OCA/OCB.git odoo
  git add -A
  git commit -q -m project
}
# run <args...>: `odoo <args>` in the working directory; stdout in out,
# stderr in err, the status in $rc.
run() {
  echo "== ${PWD##*/}: odoo $*"
  : > "$STUB_LOG/sources"
  rc=0
  "$odoo" "$@" < /dev/null > out 2> err || rc=$?
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
gm() { git config -f .gitmodules "submodule.$1.$2"; }

# ── OCA modules ──────────────────────────────────────────────────────────────
project oca
run module add account_tax_balance
expect_rc 0
check "the dependency closure is cloned on the series' branch" eval \
  'hasF "clone --branch 18.0 --require-branch https://github.com/OCA/account-financial-reporting.git modules/account-financial-reporting" "$STUB_LOG/sources" && hasF "modules/server-ux" "$STUB_LOG/sources"'
check "...and registered as shallow submodules on it" eval \
  '[ "$(gm modules/server-ux branch)" = 18.0 ] && [ "$(gm modules/server-ux shallow)" = true ]'
check "the module is recorded in modules.txt" eval '[ "$(cat modules.txt)" = account_tax_balance ]'
check "the path sources are regenerated" hasF 'odoo = { path = "odoo" }' pyproject.toml
check "the lock is attempted, and its failure reported" hasF 'uv lock failed' err
check "it says what was added" hasF 'Added 1 module(s) to modules.txt' out
check "it says how to install" hasF 'odoo db provision' out
run module add account_tax_balance date_range
expect_rc 0
check "repos already there are not cloned again" refute grep -q '^clone' "$STUB_LOG/sources"
check "it says so" hasF 'All required repos already present' out
check "modules.txt stays sorted and unique" eval '[ "$(cat modules.txt)" = "$(printf "account_tax_balance\ndate_range")" ]'

project oca-nobranch
STUB_NOBRANCH=server-ux run module add account_tax_balance
expect_rc 0
check "a repo with no branch for the series is skipped" refute hasF modules/server-ux .gitmodules
check "...and the rest is added" hasF modules/account-financial-reporting .gitmodules

project oca-fail
STUB_FAIL=server-ux run module add account_tax_balance
expect_rc 128
check "a clone that fails stops it, with the clone's status" refute hasF 'Added' out

project oca-none
run module add
expect_rc 0
check "no module and no terminal: nothing selected" hasF 'Nothing selected.' out
check "...and nothing changed" eval '[ -z "$(git status --porcelain)" ]'

# ── bundles ──────────────────────────────────────────────────────────────────
project bundle
run module add-bundle project nope
expect_rc 0
check "an unknown bundle is named" hasF 'unknown bundle: nope' err
check "the bundle's modules are added" hasF project_parent modules.txt
check "the bundle line" hasF '==> Bundle(s): project nope' out
check "project-related repos are cloned" hasF 'modules/project' "$STUB_LOG/sources"

project bundle-none
run module add-bundle
expect_rc 1
check "no bundle and no terminal: the usage, with the bundles" eval \
  'hasF "usage: odoo module add-bundle" err && hasF "oca-accounting" err'

# ── third-party repositories ─────────────────────────────────────────────────
project git-single
run module add "file://$T/remotes/single.git"
expect_rc 0
check "no 18.0 branch: the remote's default branch, said on stderr" \
  hasF "no '18.0' branch — using detected default branch 'main'" err
check "the slug is the path under modules/" eval '[ "$(gm modules/single branch)" = main ]'
check "registered shallow" eval '[ "$(gm modules/single shallow)" = true ]'
check "the URL is recorded" eval "[ \"\$(gm modules/single url)\" = file://$T/remotes/single.git ]"
check "a repo that is one module records it" eval '[ "$(cat modules.txt)" = single ]'
check "it says so" hasF 'Added modules/single as a submodule and recorded 1 module(s)' out

project git-multi
run module add "file://$T/remotes/multi.git" "" vendor
expect_rc 0
check "the series' branch when the remote has it" eval '[ "$(gm modules/vendor branch)" = 18.0 ]'
check "the path argument" test -d modules/vendor/mod_one
check "without a terminal, every module found is recorded" eval '[ "$(cat modules.txt)" = "$(printf "mod_one\nmod_two")" ]'
check "...and it says so" hasF 'non-interactive: recording all 2 discovered module(s)' err

project git-branch
run module add "file://$T/remotes/multi.git" main
expect_rc 0
check "an explicit branch" eval '[ "$(gm modules/multi branch)" = main ]'
run module add "file://$T/remotes/multi.git" nope other
expect_rc 1
check "an explicit branch the remote lacks" hasF "branch 'nope' not found" err

project git-exists
run module add "file://$T/remotes/single.git"
run module add "file://$T/remotes/single.git"
expect_rc 1
check "a path already taken is refused" hasF "'modules/single' already exists" err

project git-bare
run module add "file://$T/remotes/bare.git"
expect_rc 0
check "no manifest: said" hasF 'no __manifest__.py found' err
check "no manifest: added all the same" eval '[ "$(gm modules/bare branch)" = main ]'
check "no manifest: nothing recorded" test ! -s modules.txt
check "no manifest: it says so" hasF 'no modules recorded in modules.txt' out

project git-shorthand
run module add owner/nowhere
expect_rc 1
check "owner/repo is GitHub's" hasF 'https://github.com/owner/nowhere.git' err
check "...and with no branch to be found, it says what to pass" hasF 'pass [branch] explicitly' err

project git-bad
run module add a/b/c
expect_rc 1
check "a URL-shaped argument that is neither is refused" hasF "not a full git URL and not 'owner/repo' shorthand: a/b/c" err

# ── remove ───────────────────────────────────────────────────────────────────
commit() { git add -A && git commit -q -m "$1"; }
gone() { # <path>: no gitlink, no .gitmodules section (index or tree), no clone
  [ -z "$(git ls-files -s -- "$1")" ] &&
    ! git config -f .gitmodules --get "submodule.$1.path" > /dev/null &&
    ! git show :.gitmodules | grep -qF "\"$1\"" &&
    [ ! -e "$(git rev-parse --git-path "modules/$1")" ] &&
    [ ! -e "$1" ]
}

project remove-usage
run module remove
expect_rc 1
check "no name: the usage" eval 'hasF "Usage: odoo module remove" err && hasF "name a module or a repository" err'
run module remove --help
expect_rc 0
check "--help: the usage" hasF 'Usage: odoo module remove' out
run module remove --bogus x
expect_rc 1
check "an unknown flag" hasF 'unknown flag: --bogus' err
run module remove nope
expect_rc 1
check "a name that is neither a module nor a repo" hasF "no module 'nope' in modules.txt, and no repository modules/nope" err

project remove-oca
run module add account_tax_balance date_range
commit added
printf '\n[submodule "odoo"]\n\tunrelated = edit\n' >> .gitmodules
run module remove account_tax_balance
expect_rc 0
check "the module leaves modules.txt" eval '[ "$(cat modules.txt)" = date_range ]'
check "its repo, needed by nothing else, is removed" gone modules/account-financial-reporting
check "a repo another module still needs is kept" eval '[ "$(gm modules/server-ux branch)" = 18.0 ] && [ -d modules/server-ux/.git ] || [ -f modules/server-ux/.git ]'
check "the removal, and only it, is staged" eval '[ "$(git diff --cached --name-only | sort | tr "\n" " ")" = ".gitmodules modules/account-financial-reporting " ]'
check "an unrelated unstaged .gitmodules edit stays unstaged" eval \
  'grep -qF "unrelated = edit" .gitmodules && ! git show :.gitmodules | grep -qF "unrelated"'
check "the path sources are regenerated" hasF '==> Regenerating uv path-sources' out
check "it says what was removed" hasF '✅ Removed account_tax_balance modules/account-financial-reporting.' out
run module remove date_range
expect_rc 0
check "the last module out: its repo goes too" gone modules/server-ux
check "modules.txt is empty" test ! -s modules.txt
check "OCB is never touched" eval '[ "$(gm odoo branch)" = 18.0 ]'

project remove-repo
run module add account_tax_balance
commit added
run module remove server-ux
expect_rc 1
check "a repo a listed module still needs is refused" \
  hasF 'modules/server-ux is still needed by account_tax_balance' err
run module remove modules/account-financial-reporting
expect_rc 0
check "a repo by its path: removed, with its listed module" eval \
  'gone modules/account-financial-reporting && [ ! -s modules.txt ]'
check "...and the repos only it needed" gone modules/server-ux

project remove-third-party
run module add "file://$T/remotes/multi.git"
commit added
run module remove mod_one
expect_rc 0
check "a module whose repo still holds a listed one: only modules.txt" eval \
  '[ "$(cat modules.txt)" = mod_two ] && [ -d modules/multi/mod_two ]'
check "...and it says the database keeps it" hasF 'uninstall it in Odoo (Apps)' out
run module remove mod_two
expect_rc 1
check "code going away without a readable database is refused" hasF 'could not read the installed modules' err
check "...and nothing changed" eval '[ "$(cat modules.txt)" = mod_two ] && [ -d modules/multi/mod_two ]'
run module remove --force mod_two
expect_rc 0
check "--force removes it" gone modules/multi
run module add "file://$T/remotes/multi.git"
expect_rc 0
check "it can be added again" test -d modules/multi/mod_one

project remove-keep
run module add "file://$T/remotes/multi.git"
commit added
run module remove --keep-repos mod_one mod_two
expect_rc 0
check "--keep-repos: only modules.txt" eval '[ ! -s modules.txt ] && [ -d modules/multi/mod_one ]'

project remove-dirty
run module add "file://$T/remotes/bare.git"
commit added
echo local > modules/bare/local.txt
echo changed > modules/bare/README
run module remove bare
expect_rc 1
check "a repo with uncommitted changes is refused" eval \
  'hasF "modules/bare has uncommitted changes" err && hasF "README" err'
run module remove --force bare
expect_rc 0
check "--force discards them with the repo" gone modules/bare

if [ "$fails" -gt 0 ]; then
  echo "module: $fails failure(s)" >&2
  exit 1
fi
echo "module: ok"
