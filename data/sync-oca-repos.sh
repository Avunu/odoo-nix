#!/usr/bin/env bash
# Sync the OCA repos the catalog is built from, one shallow branch per series.
#
# The previous version cloned each repo's *default* branch with no --branch, so
# the catalog only ever described whichever series OCA happened to have made
# default — which is why it read 18.0 -> 2585 modules but 19.0 -> 103 and
# 17.0 -> 0. This keeps one bare mirror per repo and fetches each supported
# series into it as a shallow branch: no working trees, ~1/3 the objects of a
# clone-per-series, and every series described equally.
#
# Repos come from data/oca-repos.txt (column 1, "OCA/<repo>") so the inventory
# is not duplicated. Repos without a given branch are skipped silently — most
# of the 260 entries are tooling repos with no addons at all.
#
# Usage:  data/sync-oca-repos.sh [series …]      (default: the SERIES below)
# Then:   data/extract_manifests.py              (regenerates oca-modules.json)

set -euo pipefail

cd "$(dirname "$0")"

# Keep in sync with lib/odoo-presets.json.
SERIES=("$@")
[ "${#SERIES[@]}" -eq 0 ] && SERIES=(19.0 18.0)

CACHE=".cache"
mkdir -p "$CACHE"

mapfile -t repos < <(cut -f1 oca-repos.txt | sed 's|^OCA/||' | grep -vE '^\s*$' | sort -u)
echo "==> ${#repos[@]} repos × ${#SERIES[@]} series (${SERIES[*]})" >&2

n=0
for repo in "${repos[@]}"; do
  n=$((n + 1))
  git_dir="$CACHE/$repo.git"
  if [ ! -d "$git_dir" ]; then
    git init --bare -q "$git_dir"
    git -C "$git_dir" remote add origin "https://github.com/OCA/$repo.git"
  fi
  got=()
  for s in "${SERIES[@]}"; do
    if git -C "$git_dir" fetch -q --depth 1 --no-tags origin \
         "refs/heads/$s:refs/heads/$s" 2>/dev/null; then
      got+=("$s")
    fi
  done
  printf '[%3d/%3d] %-45s %s\n' "$n" "${#repos[@]}" "$repo" "${got[*]:-—}" >&2
done

echo "==> Done. Now run: data/extract_manifests.py" >&2
