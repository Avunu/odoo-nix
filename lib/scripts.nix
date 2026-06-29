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

  addToAppsTxt = pkgs.writeShellScript "oca-apps-append" ''
    # Append a module name to oca-apps.txt iff absent, newline-safe.
    mod="$1"; f="oca-apps.txt"
    grep -qxF "$mod" "$f" 2>/dev/null && exit 0
    if [ -s "$f" ] && [ -n "$(tail -c1 "$f" 2>/dev/null)" ]; then echo >> "$f"; fi
    echo "$mod" >> "$f"
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

  # Provision: create the DB and install every module listed in oca-apps.txt.
  provision-db = {
    description = "Create the dev DB + install all modules from oca-apps.txt";
    exec = ''
      ${preamble}
      [ "$#" -ge 1 ] && DB="$1"
      MODS="base"
      if [ -f oca-apps.txt ]; then
        while IFS= read -r m; do
          [ -z "$m" ] && continue
          MODS="$MODS,$m"
        done < oca-apps.txt
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

      echo "==> Re-aggregating OCA Python dependencies…"
      ${pkgs.python3}/bin/python3 ${./oca_pydeps.py} update pyproject.toml \
        "${layout.externalDir}" "${layout.customDir}"

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

  # Pick more OCA apps, resolve NEW repo deps, add them as submodules, relock.
  odoo-add-app = {
    description = "Add OCA app(s): odoo-add-app [module …] (interactive if none)";
    exec = ''
      ${preamble}
      ${ocaPreamble}

      if [ "$#" -gt 0 ]; then
        SEL=("$@")
      else
        mapfile -t SEL < <(oca_pick_apps "${odooSeries}")
      fi
      [ "''${#SEL[@]}" -eq 0 ] && { echo "Nothing selected."; exit 0; }

      echo "==> Resolving dependency closure for: ''${SEL[*]}"
      mapfile -t ALL_REPOS < <(oca_resolve_repos "${odooSeries}" "''${SEL[@]}")

      # Diff against already-present src/external/* dirs.
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
          if ${pkgs.git}/bin/git ls-remote --heads "$url" "${odooSeries}" 2>/dev/null | grep -q .; then
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

      # Record selected seeds in oca-apps.txt.
      for m in "''${SEL[@]}"; do ${addToAppsTxt} "$m"; done

      echo "==> Re-aggregating OCA Python dependencies + uv lock…"
      ${pkgs.python3}/bin/python3 ${./oca_pydeps.py} update pyproject.toml \
        "${layout.externalDir}" "${layout.customDir}"
      if ${pkgs.uv}/bin/uv lock; then
        ${pkgs.python3}/bin/python3 ${./uv_build_deps.py} update pyproject.toml uv.lock || true
        ${pkgs.uv}/bin/uv lock || true
      else
        echo "⚠  uv lock failed — resolve in pyproject.toml and re-run." >&2
      fi

      cat <<EOF

✅ Added: ''${SEL[*]}
   1. Reload so the Nix engine re-derives addons_path + rebuilds the env:
        direnv reload
   2. Install the new app(s):
        odoo-upgrade ''$(IFS=,; echo "''${SEL[*]}")   # or: provision-db
EOF
    '';
  };
}
