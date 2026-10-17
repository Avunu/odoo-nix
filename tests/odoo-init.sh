# The scaffolder (lib/odoo-init.sh), offline: git and uv are stand-ins, so no
# submodule is fetched and nothing is locked. What is checked is what it
# writes into the template: the project's identity as `odoo-nix.name`
# (python-devops-nix CONVENTIONS.md, Identity options), and the database.
#
#   bash tests/odoo-init.sh <odoo-init's script (lib/init.nix passthru.script)>
set -euo pipefail
script=$1
refute() { if "$@"; then echo "refuted, but it succeeded: $*" >&2; exit 1; fi; }

stubs=$PWD/stubs
mkdir -p "$stubs"
printf '#!%s\n' "$BASH" | tee "$stubs/git" "$stubs/uv" >/dev/null
cat >> "$stubs/git" <<'SH'
# ls-remote --heads <url> <branch>: every branch exists; clone: an empty tree.
case "$1" in
  ls-remote) echo "0000000000000000000000000000000000000000 refs/heads/$4" ;;
  clone) mkdir -p "${*: -1}" ;;
esac
SH
chmod +x "$stubs/git" "$stubs/uv"

PATH="$stubs:$PATH" bash -euo pipefail "$script" \
  --series 18.0 --name "Acme Shop" --db "acme-db" acme </dev/null >init.log 2>&1 \
  || { cat init.log >&2; exit 1; }

flake=acme/flake.nix
grep -qE '^\s*name = "acme-shop";$' "$flake"
refute grep -q projectName "$flake"
refute grep -q '@[A-Z_]*@' "$flake"
grep -qE '^\s*odooConf\.dbName = "acme_db";$' "$flake"
grep -qE '^name = "acme-shop"$' acme/pyproject.toml
echo "odoo-init: ok"
