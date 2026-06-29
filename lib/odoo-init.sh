# odoo-init — scaffold a new odoo-nix project (Odoo OCB + OCA).
# Baked at build time:
PRESETS="@PRESETS@"
TEMPLATE="@TEMPLATE@"
OCA_PYDEPS="@OCA_PYDEPS@"
UV_BUILD_DEPS="@UV_BUILD_DEPS@"
export OCA_DATASET="@OCA_DATASET@"
# shellcheck source=/dev/null
source "@OCA_LIB@"

usage() {
  cat <<'EOF'
Usage: odoo-init [options] [target-dir]

Scaffold a new odoo-nix-managed Odoo (OCB) + OCA project.

Options:
  --series <v>     Odoo series: 18.0 | 17.0 | 16.0   (default catalog: 18.0)
  --apps <a,b,c>   Comma-separated OCA application module names
  --name <name>    Project name (default: target dir basename)
  --db <name>      Default database name (default: odoo)
  -h, --help       Show this help

With a TTY and no flags, you'll be prompted interactively (via gum).
EOF
}

series=""
apps_csv=""
name=""
db=""
target=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --series) series="$2"; shift 2 ;;
    --series=*) series="${1#*=}"; shift ;;
    --apps) apps_csv="$2"; shift 2 ;;
    --apps=*) apps_csv="${1#*=}"; shift ;;
    --name) name="$2"; shift 2 ;;
    --name=*) name="${1#*=}"; shift ;;
    --db) db="$2"; shift 2 ;;
    --db=*) db="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "Unknown flag: $1" >&2; usage >&2; exit 1 ;;
    *) target="$1"; shift ;;
  esac
done

has_tty() { [ -t 0 ] && [ -t 1 ]; }

# ── series ─────────────────────────────────────────────────────────────────
mapfile -t preset_keys < <(jq -r 'keys_unsorted[]' "$PRESETS")
if [ -z "$series" ]; then
  if has_tty; then
    series="$(jq -r '.[].label' "$PRESETS" | gum choose --header "Odoo series:" | sed -E 's/ .*//')"
  else
    echo "ERROR: --series is required (one of: ${preset_keys[*]})" >&2
    exit 1
  fi
fi
if ! jq -e --arg v "$series" 'has($v)' "$PRESETS" >/dev/null; then
  echo "ERROR: unknown series '$series' (expected: ${preset_keys[*]})" >&2
  exit 1
fi

preset_field() { jq -r --arg v "$series" --arg k "$1" '.[$v][$k]' "$PRESETS"; }
python="$(preset_field python)"
requires_python="$(preset_field requiresPython)"
branch="$series"  # series is the literal git branch for OCB and every OCA repo

# ── apps ───────────────────────────────────────────────────────────────────
selected_modules=()
if [ -n "$apps_csv" ]; then
  IFS=',' read -ra selected_modules <<< "$apps_csv"
elif has_tty; then
  mapfile -t selected_modules < <(oca_pick_apps "$series")
fi
# Drop empties.
_tmp=(); for m in "${selected_modules[@]}"; do [ -n "$m" ] && _tmp+=("$m"); done
selected_modules=("${_tmp[@]}")

# Resolve the transitive closure of OCA repos to clone.
resolved_repos=()
if [ "${#selected_modules[@]}" -gt 0 ]; then
  mapfile -t resolved_repos < <(oca_resolve_repos "$series" "${selected_modules[@]}")
fi

# ── name / db / target dir ─────────────────────────────────────────────────
if [ -z "$target" ]; then
  if has_tty; then
    target="$(gum input --header "Project directory:" --value "odoo-project")"
  fi
  target="${target:-odoo-project}"
fi
[ -z "$name" ] && name="$(basename "$target")"
name="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9-' '-' | sed -E 's/-+/-/g; s/^-//; s/-$//')"
[ -z "$name" ] && name="odoo-project"
db="${db:-odoo}"
db="$(printf '%s' "$db" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '_' | sed -E 's/^_+//')"
[ -z "$db" ] && db="odoo"

if [ -e "$target" ] && [ -n "$(ls -A "$target" 2>/dev/null)" ]; then
  echo "ERROR: target '$target' already exists and is not empty" >&2
  exit 1
fi

echo "Creating project '$name' (Odoo $series → python ${python#python}) in $target"
if [ "${#selected_modules[@]}" -gt 0 ]; then
  echo "  apps : ${selected_modules[*]}"
  echo "  repos: ${resolved_repos[*]}"
fi

# ── lay down the template ──────────────────────────────────────────────────
mkdir -p "$target"
cp -R "$TEMPLATE"/. "$target"/
chmod -R u+w "$target"
cd "$target" || { echo "ERROR: cannot enter $target" >&2; exit 1; }
target_abs="$(pwd)"

sed -i \
  -e "s|@PROJECT_NAME@|$name|g" \
  -e "s|@DB_NAME@|$db|g" \
  -e "s|@SERIES@|$series|g" \
  -e "s|@PYTHON@|$python|g" \
  -e "s|@REQUIRES_PYTHON@|$requires_python|g" \
  flake.nix pyproject.toml README.md

# Record the selected application modules (the install list).
printf '%s\n' "${selected_modules[@]}" > oca-apps.txt

# ── git init + submodules ──────────────────────────────────────────────────
git init -q

add_submodule() {  # $1=url  $2=path
  local url="$1" path="$2"
  if git ls-remote --heads "$url" "$branch" 2>/dev/null | grep -q .; then
    echo "  + $path ($branch)"
    git clone -q --depth 1 --branch "$branch" -- "$url" "$path"
    git submodule add -q --force -b "$branch" -- "$url" "$path"
    git config -f .gitmodules "submodule.$path.shallow" true
    return 0
  fi
  echo "  ⚠  $url has no '$branch' branch — skipped" >&2
  return 1
}

echo "Adding OCB (Odoo $series) at odoo/…"
add_submodule "https://github.com/OCA/OCB.git" "odoo"

if [ "${#resolved_repos[@]}" -gt 0 ]; then
  echo "Adding OCA repo submodules under apps/…"
  for repo in "${resolved_repos[@]}"; do
    [ -n "$repo" ] && add_submodule "$(oca_repo_url "$repo")" "apps/$repo" || true
  done
fi
git submodule update --init --recursive

# ── generate the Python manifest ───────────────────────────────────────────
# Odoo core deps from odoo/requirements.txt (already valid PEP 508 specs).
if [ -f odoo/requirements.txt ]; then
  echo "Generating pyproject.toml dependencies from odoo/requirements.txt…"
  reqs="$(
    while IFS= read -r line; do
      line="${line%%#*}"                         # strip inline comments
      line="$(printf '%s' "$line" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"
      [ -z "$line" ] && continue
      printf '    "%s",\n' "$line"
    done < odoo/requirements.txt
  )"
  awk -v reqs="$reqs" '$0 == "@ODOO_REQS@" { print reqs; next } { print }' \
    pyproject.toml > pyproject.toml.tmp && mv pyproject.toml.tmp pyproject.toml
else
  sed -i '/@ODOO_REQS@/d' pyproject.toml
fi

# OCA modules' external_dependencies.python -> managed sentinel block.
python3 "$OCA_PYDEPS" update pyproject.toml apps custom || true

# ── resolve the python environment ─────────────────────────────────────────
echo "Resolving Python environment (uv lock)…"
if uv lock; then
  # Grant setuptools to sdist-only packages so uv2nix can build them.
  python3 "$UV_BUILD_DEPS" update pyproject.toml uv.lock || true
  uv lock || true
else
  echo "" >&2
  echo "⚠  uv lock failed — usually a version conflict. Adjust pyproject.toml" >&2
  echo "   [project].dependencies and re-run 'uv lock'." >&2
fi

git add -A

cat <<EOF

✅ Project '$name' created in $target_abs
   series : $series (python ${python#python})
   apps   : ${selected_modules[*]:-<none — Odoo core only>}

Next steps:
  cd $target
  direnv allow            # or: nix develop --no-pure-eval
  devenv up               # start postgres + odoo + mailpit
  provision-db            # (another shell) create DB + install apps
EOF
