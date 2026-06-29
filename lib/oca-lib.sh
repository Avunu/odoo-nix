# oca-lib.sh — shared OCA catalog helpers for odoo-nix.
#
# Sourced by the scaffolder (odoo-init) and the in-project `odoo-add-app` script.
# Requires the environment variable OCA_DATASET to point at oca-modules.json
# (both callers bake the vendored data/oca-modules.json store path into it).
#
# Provides:
#   oca_repo_url <repo>                 -> https git URL for an OCA repo
#   oca_resolve_repos <series> <mod>... -> deduped, sorted repo names (closure)
#   oca_pick_apps <series>              -> interactively chosen module names
#
# Aggregating OCA external_dependencies.python into pyproject.toml is handled by
# the canonical lib/oca_pydeps.py (scan/update modes), not here.

oca_repo_url() {
  printf 'https://github.com/OCA/%s.git\n' "$1"
}

# Transitive closure of OCA repos for a set of seed module names, within one
# Odoo series. BFS over `depends`; a dep that is not an in-series OCA module is
# Odoo core (satisfied by OCB) and is skipped. Cycles terminate via a seen set.
# Prints the deduped, sorted repo names (one per line).
oca_resolve_repos() {
  local series="$1"; shift
  local seeds_json
  seeds_json="$(printf '%s\n' "$@" | jq -R . | jq -s 'map(select(length > 0))')"
  jq -r --arg series "$series" --argjson seeds "$seeds_json" '
    [ .[] | select(.version | startswith($series + ".")) ] as $mods
    | (reduce $mods[] as $m ({}; .[$m.module] = $m.repo)) as $repo_of
    | (reduce $mods[] as $m ({}; .[$m.module] = ($m.depends // []))) as $deps_of
    | { queue: $seeds, seen: {}, repos: {} }
    | until( (.queue | length) == 0;
        .queue[0] as $cur
        | .queue |= .[1:]
        | if .seen[$cur] then .
          else
            .seen[$cur] = true
            | (if $repo_of[$cur] then .repos[$repo_of[$cur]] = true else . end)
            | .queue += ( ($deps_of[$cur] // []) | map(select($repo_of[.])) )
          end )
    | .repos | keys | sort | .[]
  ' "$OCA_DATASET"
}

# Present the application modules for a series in a gum picker; print the chosen
# bare module names. Uses a TAB-separated module<TAB>label rows table so the
# decorated label never has to be parsed back into a module name.
oca_pick_apps() {
  local series="$1"
  local rows
  rows="$(jq -r --arg s "$series" '
      [ .[] | select(.application == true and (.version | startswith($s + "."))) ]
      | sort_by(.module)[]
      | "\(.module)\t\(.module)  [\(.repo)]  —  \((.summary // "") | gsub("\\s+"; " ") | .[0:70])"
    ' "$OCA_DATASET")"
  [ -z "$rows" ] && { echo "No application modules found for series $series." >&2; return 0; }
  local chosen_labels
  chosen_labels="$(cut -f2 <<<"$rows" \
    | gum choose --no-limit --height 20 \
        --header "OCA applications for $series (space=toggle, enter=confirm; none=Odoo core only):" || true)"
  while IFS= read -r lbl; do
    [ -z "$lbl" ] && continue
    awk -F'\t' -v l="$lbl" '$2 == l { print $1 }' <<<"$rows"
  done <<<"$chosen_labels"
}
