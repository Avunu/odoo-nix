# devenv shell scripts for Odoo + OCA projects.
#
# Mirrors frappe-nix/lib/scripts.nix but Odoo-shaped: no bench CLI, no asset
# build. Scripts run `odoo-bin -c odoo.conf` from the OCB source submodule using
# the Nix-built Python env, and manage the OCA submodule selection.
#
# Usage:
#   import ./lib/scripts.nix {
#     inherit lib pkgs;
#     python = "${devPythonEnv}/bin/python";
#     odooSeries = cfg.odooSeries;
#     dbName = cfg.odooConf.dbName or "odoo_dev";
#     ocaDataset = ../data/oca-modules.json;   # store path
#     ocaLib = ./oca-lib.sh;                    # store path
#     bundlesFile = ../data/oca-bundles.json;   # store path
#     layout = cfg.layout;
#   }

{
  lib,
  pkgs,
  python,
  odooSeries,
  dbName,
  ocaDataset,
  ocaLib,
  bundlesFile,
  layout,
}:

let
  # Common preamble: run from the workspace root, locate odoo-bin in the OCB
  # submodule, default the target DB.
  preamble = ''
    set -euo pipefail
    cd "''${REPO_ROOT:-$PWD}"
    ODOO_BIN="''${REPO_ROOT:-$PWD}/${layout.coreSrc}/odoo-bin"
    CONF="''${REPO_ROOT:-$PWD}/odoo.conf"
    DB="''${ODOO_DB:-${dbName}}"
  '';

  # Preamble for OCA-catalog scripts: expose the dataset + source the helpers.
  ocaPreamble = ''
    export OCA_DATASET="${ocaDataset}"
    # shellcheck source=/dev/null
    source "${ocaLib}"
  '';

  addToModulesTxt = pkgs.writeShellScript "modules-txt-append" ''
    # Append a module name to modules.txt iff absent, newline-safe.
    mod="$1"; f="modules.txt"
    grep -qxF "$mod" "$f" 2>/dev/null && exit 0
    if [ -s "$f" ] && [ -n "$(tail -c1 "$f" 2>/dev/null)" ]; then echo >> "$f"; fi
    echo "$mod" >> "$f"
  '';

  # Keep modules.txt sorted + de-duplicated (deterministic, clean diffs).
  sortModulesTxt = pkgs.writeShellScript "modules-txt-sort" ''
    f="modules.txt"
    [ -f "$f" ] || exit 0
    ${pkgs.gnugrep}/bin/grep -vE '^[[:space:]]*$' "$f" \
      | LC_ALL=C ${pkgs.coreutils}/bin/sort -u > "$f.tmp" && mv "$f.tmp" "$f"
  '';

  # Shared "add these module seeds" flow used by odoo-add-module and
  # odoo-add-bundle: resolve the transitive repo closure, add the NEW repos as
  # shallow submodules, record the seeds in modules.txt, re-aggregate the scoped
  # OCA Python deps and re-lock. Takes module names as positional args.
  addModules = pkgs.writeShellScript "oca-add-modules" ''
    set -euo pipefail
    cd "''${REPO_ROOT:-$PWD}"
    export PATH="${pkgs.git}/bin:$PATH"
    export OCA_DATASET="${ocaDataset}"
    # shellcheck source=/dev/null
    source "${ocaLib}"

    SEL=("$@")
    [ "''${#SEL[@]}" -eq 0 ] && { echo "Nothing to add."; exit 0; }

    echo "==> Resolving dependency closure for ''${#SEL[@]} module(s)…"
    mapfile -t ALL_REPOS < <(oca_resolve_repos "${odooSeries}" "''${SEL[@]}")

    mkdir -p "${layout.externalDir}"
    ls -1 "${layout.externalDir}" 2>/dev/null | sort > .oca-existing.tmp || true
    NEW_REPOS=()
    for r in "''${ALL_REPOS[@]}"; do
      grep -qxF "$r" .oca-existing.tmp 2>/dev/null || NEW_REPOS+=("$r")
    done
    rm -f .oca-existing.tmp

    if [ "''${#NEW_REPOS[@]}" -gt 0 ]; then
      echo "==> Adding ''${#NEW_REPOS[@]} new repo submodule(s): ''${NEW_REPOS[*]}"
      for repo in "''${NEW_REPOS[@]}"; do
        url="$(oca_repo_url "$repo")"; path="${layout.externalDir}/$repo"
        if git ls-remote --heads "$url" "${odooSeries}" 2>/dev/null | grep -q .; then
          git clone -q --depth 1 --branch "${odooSeries}" -- "$url" "$path"
          git submodule add -q --force -b "${odooSeries}" -- "$url" "$path"
          git config -f .gitmodules "submodule.$path.shallow" true
          echo "   + $path"
        else
          echo "   ⚠  $repo has no '${odooSeries}' branch — skipped" >&2
        fi
      done
      git submodule update --init --recursive
    else
      echo "==> All required repos already present."
    fi

    # Record the seeds in modules.txt (only those present in the catalog/closure
    # are installable; provision-db will report anything missing), then sort it.
    for m in "''${SEL[@]}"; do ${addToModulesTxt} "$m"; done
    ${sortModulesTxt}

    echo "==> Generating uv path-sources + lock (uv resolves all deps)…"
    ${pkgs.python3}/bin/python3 ${./oca_sources.py} update pyproject.toml \
      modules.txt "${layout.externalDir}" "${layout.customDir}" "${layout.coreSrc}"
    if ${pkgs.uv}/bin/uv lock; then
      ${pkgs.python3}/bin/python3 ${./uv_build_deps.py} update pyproject.toml uv.lock || true
      ${pkgs.uv}/bin/uv lock || true
    else
      echo "⚠  uv lock failed — resolve in pyproject.toml and re-run." >&2
    fi

    cat <<EOF

✅ Added ''${#SEL[@]} module(s) to modules.txt.
   1. Reload so the Nix engine re-derives addons_path + rebuilds the env:
        direnv reload
   2. Install:  provision-db    (installs everything in modules.txt)
EOF
  '';
in
{
  # Create + initialize a database (base module only).
  odoo-init-db = {
    description = "Create + initialize an Odoo database: odoo-init-db [db]";
    exec = ''
      ${preamble}
      [ "$#" -ge 1 ] && DB="$1"
      echo "==> Initializing database '$DB' (base)…"
      exec ${python} "$ODOO_BIN" -c "$CONF" -d "$DB" -i base --stop-after-init
    '';
  };

  # Open the Odoo shell REPL against a database.
  odoo-shell = {
    description = "Open the Odoo shell REPL: odoo-shell [db]";
    exec = ''
      ${preamble}
      [ "$#" -ge 1 ] && DB="$1"
      exec ${python} "$ODOO_BIN" shell -c "$CONF" -d "$DB"
    '';
  };

  # Upgrade one or more modules (comma-separated).
  odoo-upgrade = {
    description = "Upgrade module(s): odoo-upgrade <module[,module2,…]>";
    exec = ''
      ${preamble}
      [ "$#" -ge 1 ] || { echo "usage: odoo-upgrade <module[,module2]> [db]" >&2; exit 1; }
      MODS="$1"; shift || true
      [ "$#" -ge 1 ] && DB="$1"
      exec ${python} "$ODOO_BIN" -c "$CONF" -d "$DB" -u "$MODS" --stop-after-init
    '';
  };

  # Provision: create the DB and install every module listed in modules.txt.
  provision-db = {
    description = "Create the dev DB + install all modules from modules.txt";
    exec = ''
      ${preamble}
      [ "$#" -ge 1 ] && DB="$1"
      MODS="base"
      if [ -f modules.txt ]; then
        while IFS= read -r m; do
          [ -z "$m" ] && continue
          MODS="$MODS,$m"
        done < modules.txt
      fi
      echo "==> Provisioning '$DB' with: $MODS"
      exec ${python} "$ODOO_BIN" -c "$CONF" -d "$DB" -i "$MODS" --stop-after-init
    '';
  };

  # Pull submodules on their pinned branch, re-aggregate OCA python deps, relock.
  odoo-update = {
    description = "Pull src submodules, refresh OCA python deps, uv lock";
    exec = ''
      ${preamble}
      ${ocaPreamble}
      echo "==> Updating git submodules…"
      git submodule update --init --recursive
      git submodule foreach --quiet 'git pull --ff-only origin "$(git rev-parse --abbrev-ref HEAD)" || true'

      echo "==> Regenerating uv path-sources…"
      ${pkgs.python3}/bin/python3 ${./oca_sources.py} update pyproject.toml \
        modules.txt "${layout.externalDir}" "${layout.customDir}" "${layout.coreSrc}"

      echo "==> Re-locking Python environment (uv lock)…"
      if ${pkgs.uv}/bin/uv lock; then
        ${pkgs.python3}/bin/python3 ${./uv_build_deps.py} update pyproject.toml uv.lock || true
        ${pkgs.uv}/bin/uv lock || true
      else
        echo "⚠  uv lock failed — resolve in pyproject.toml and re-run." >&2
      fi
      echo "✅ Update complete. Run 'direnv reload' to rebuild the Nix env."
    '';
  };

  # Pick more OCA modules (interactive picker or args), then add them.
  odoo-add-module = {
    description = "Add OCA module(s): odoo-add-module [module …] (interactive if none)";
    exec = ''
      ${preamble}
      ${ocaPreamble}
      if [ "$#" -gt 0 ]; then
        SEL=("$@")
      else
        mapfile -t SEL < <(oca_pick_modules "${odooSeries}")
      fi
      [ "''${#SEL[@]}" -eq 0 ] && { echo "Nothing selected."; exit 0; }
      exec ${addModules} "''${SEL[@]}"
    '';
  };

  # Add a curated OCA module bundle (a named set of "must-have" modules,
  # defined in data/oca-bundles.json).
  odoo-add-bundle = {
    description = "Add an OCA module bundle: odoo-add-bundle [name …] (interactive if none)";
    exec = ''
      ${preamble}
      BUNDLES="${bundlesFile}"
      jq() { ${pkgs.jq}/bin/jq "$@"; }

      avail() { jq -r 'keys[]' "$BUNDLES"; }

      if [ "$#" -gt 0 ]; then
        NAMES=("$@")
      elif ${pkgs.gum}/bin/gum --version >/dev/null 2>&1 && [ -t 0 ] && [ -t 1 ]; then
        # Interactive picker: name<TAB>"name — label (N modules)".
        _rows="$(jq -r 'to_entries[]
          | "\(.key)\t\(.key)  —  \(.value.label)  (\(.value.modules | length) modules)"' "$BUNDLES")"
        mapfile -t NAMES < <(
          cut -f2 <<<"$_rows" \
            | ${pkgs.gum}/bin/gum choose --no-limit \
                --header "Select OCA bundle(s) (space=toggle, enter=confirm):" \
            | while IFS= read -r lbl; do
                [ -z "$lbl" ] && continue
                awk -F'\t' -v l="$lbl" '$2 == l { print $1 }' <<<"$_rows"
              done
        )
      else
        echo "usage: odoo-add-bundle <name …>   (available: $(avail | tr '\n' ' '))" >&2
        exit 1
      fi
      [ "''${#NAMES[@]}" -eq 0 ] && { echo "No bundle selected."; exit 0; }

      # Collect the union of modules across the selected bundles.
      MODULES=()
      for n in "''${NAMES[@]}"; do
        if ! jq -e --arg n "$n" 'has($n)' "$BUNDLES" >/dev/null; then
          echo "⚠  unknown bundle: $n   (available: $(avail | tr '\n' ' '))" >&2
          continue
        fi
        while IFS= read -r m; do
          [ -n "$m" ] && MODULES+=("$m")
        done < <(jq -r --arg n "$n" '.[$n].modules[]' "$BUNDLES")
      done
      [ "''${#MODULES[@]}" -eq 0 ] && { echo "No modules in the selected bundle(s)."; exit 0; }

      echo "==> Bundle(s): ''${NAMES[*]}  →  ''${#MODULES[@]} module(s)"
      exec ${addModules} "''${MODULES[@]}"
    '';
  };
}
