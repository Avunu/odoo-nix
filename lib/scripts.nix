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
  # OCB from a flake input (see modules/devenv.nix `coreSource`): only affects
  # what odoo-update tells the user, the symlink makes everything else the same.
  coreSource ? null,
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

  # Preamble for OCA-catalog scripts: expose the dataset + bundles and source
  # the helpers.
  ocaPreamble = ''
    export OCA_DATASET="${ocaDataset}"
    export OCA_BUNDLES="${bundlesFile}"
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

  # Regenerate the uv path-sources block in pyproject.toml from whatever is on
  # disk under layout.{externalDir,customDir}, then re-lock. Shared by
  # addModules, addGitSubmodule and odoo-update, so this uv-lock/patch-build-
  # deps/relock sequence exists in exactly one place instead of being
  # copy-pasted per caller.
  regenerateAndLock = pkgs.writeShellScript "oca-regenerate-and-lock" ''
    set -euo pipefail
    cd "''${REPO_ROOT:-$PWD}"
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

    ${regenerateAndLock}

    cat <<EOF

✅ Added ''${#SEL[@]} module(s) to modules.txt.
   1. Reload so the Nix engine re-derives addons_path + rebuilds the env:
        direnv reload
   2. Install:  provision-db    (installs everything in modules.txt)
EOF
  '';

  # Register an already-cloned repo (at $3, cloned by the caller into its
  # final resolved path under layout.externalDir) as a submodule, then record
  # the given module names (already chosen by the caller -- this does no
  # prompting) in modules.txt and re-lock. Mirrors the per-repo tail of
  # addModules' loop, but for exactly one caller-supplied repo instead of an
  # OCA dependency closure of many.
  addGitSubmodule = pkgs.writeShellScript "oca-add-git-submodule" ''
    set -euo pipefail
    cd "''${REPO_ROOT:-$PWD}"
    export PATH="${pkgs.git}/bin:$PATH"

    url="$1" branch="$2" path="$3"; shift 3
    MODS=("$@")

    echo "==> Registering $path as a submodule ($branch)…"
    git submodule add -q --force -b "$branch" -- "$url" "$path"
    git config -f .gitmodules "submodule.$path.shallow" true
    git submodule update --init --recursive -- "$path"

    if [ "''${#MODS[@]}" -gt 0 ]; then
      for m in "''${MODS[@]}"; do ${addToModulesTxt} "$m"; done
      ${sortModulesTxt}
      ${regenerateAndLock}
      cat <<EOF

✅ Added $path as a submodule and recorded ''${#MODS[@]} module(s) in modules.txt.
   1. Reload so the Nix engine re-derives addons_path + rebuilds the env:
        direnv reload
   2. Install:  provision-db    (installs everything in modules.txt)
EOF
    else
      cat <<EOF

✅ Added $path as a submodule (no modules recorded in modules.txt).
   Reload so the Nix engine picks up the new addons_path:
     direnv reload
EOF
    fi
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

  # Run tests, and refuse to call a skipped browser tour a pass.
  #
  # Odoo degrades quietly when the tour prerequisites are missing: no
  # `websocket` module, or no Chrome on PATH, and every HttpCase is *skipped*.
  # The summary line reports skips and passes identically --
  # "0 failed, 0 error(s) of N tests" -- so a broken environment reads as a
  # green run. That is the failure this script exists to prevent: it checks the
  # prerequisites up front and exits non-zero saying what is missing, rather
  # than letting the suite claim success for tests that never executed.
  odoo-test = {
    description = "Run tests: odoo-test <module[,module2]> [db] (fails if tours cannot run)";
    exec = ''
      ${preamble}
      [ "$#" -ge 1 ] || {
        echo "usage: odoo-test <module[,module2]> [db]" >&2; exit 1; }
      MODS="$1"; shift || true
      [ "$#" -ge 1 ] && DB="$1"

      MISSING=""
      ${python} -c 'import websocket' 2>/dev/null \
        || MISSING="$MISSING\n  - the 'websocket-client' package (add it to [dependency-groups].dev, then re-lock)"
      # `if`, not `cmd && {...}`: under `set -e` a failing AND-list as the last
      # statement of the loop body would abort the script on the first name
      # that is not installed -- which is every run where chromium is second.
      BROWSER=""
      for b in google-chrome chromium chromium-browser google-chrome-stable; do
        if command -v "$b" >/dev/null 2>&1; then BROWSER="$b"; break; fi
      done
      [ -n "$BROWSER" ] \
        || MISSING="$MISSING\n  - a headless browser (set odoo.testBrowser, or put one on PATH)"

      if [ -n "$MISSING" ]; then
        echo "✗ Browser tours cannot run here, and Odoo would skip them silently:" >&2
        printf "%b\n" "$MISSING" >&2
        echo "" >&2
        echo "  Refusing to run, because a skipped tour is reported exactly like" >&2
        echo "  a passing one. Set ODOO_TEST_ALLOW_SKIP=1 to run anyway." >&2
        [ "''${ODOO_TEST_ALLOW_SKIP:-}" = "1" ] || exit 1
      else
        echo "==> tours enabled (browser: $BROWSER)"
      fi

      # "a,b" -> "/a,/b": --test-tags wants a leading slash per module, and
      # "/a,b" would silently select nothing for b.
      TAGS="/$(printf '%s' "$MODS" | ${pkgs.gnused}/bin/sed 's/,/,\//g')"

      echo "==> Testing $MODS on '$DB' (tags: $TAGS)…"
      exec ${python} "$ODOO_BIN" -c "$CONF" -d "$DB" -u "$MODS" \
        --test-enable --test-tags "$TAGS" --stop-after-init
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
      ${lib.optionalString (coreSource != null) ''
        echo "    (${layout.coreSrc} is a flake input, not a submodule: bump it with 'nix flake update')"
      ''}

      ${regenerateAndLock}
      echo "✅ Update complete. Run 'direnv reload' to rebuild the Nix env."
    '';
  };

  # Pick more OCA modules (interactive picker or args), then add them -- or,
  # given a git URL / "owner/repo" shorthand, add that repo directly as a
  # submodule instead (any git host, not just OCA/GitHub).
  odoo-add-module = {
    description = "Add OCA module(s), or a third-party git repo as a submodule: odoo-add-module [module …] | odoo-add-module <git-url-or-owner/repo> [branch] [path]";
    exec = ''
      ${preamble}
      ${ocaPreamble}
      export PATH="${pkgs.git}/bin:$PATH"
      has_tty() { [ -t 0 ] && [ -t 1 ]; }

      MODE="oca"
      if [ "$#" -gt 0 ] && oca_url_shaped "$1"; then
        MODE="git"
      elif [ "$#" -eq 0 ] && has_tty; then
        choice="$(printf '%s\n' "Browse OCA catalog" "Add from a Git URL" \
          | gum choose --header "odoo-add-module: what do you want to add?" || true)"
        case "$choice" in
          "Add from a Git URL") MODE="git" ;;
          "Browse OCA catalog") MODE="oca" ;;
          *) echo "Nothing selected."; exit 0 ;;
        esac
      fi

      if [ "$MODE" = "git" ]; then
        SRC="''${1:-}"; BRANCH_ARG="''${2:-}"; PATH_ARG="''${3:-}"
        if [ -z "$SRC" ]; then
          if has_tty; then
            SRC="$(gum input --header "Git URL or owner/repo:" \
              --placeholder "https://example.com/owner/repo.git  or  owner/repo" || true)"
            [ -z "$SRC" ] && { echo "Nothing entered."; exit 0; }
          else
            echo "usage: odoo-add-module <git-url-or-owner/repo> [branch] [path]" >&2
            exit 1
          fi
        fi

        url="$(oca_resolve_git_url "$SRC")"
        slug="$(oca_repo_slug "$url")"
        if [ -n "$PATH_ARG" ]; then
          slug="$PATH_ARG"
        elif has_tty; then
          slug="$(gum input --header "Submodule path (under ${layout.externalDir}/):" --value "$slug" || true)"
          [ -z "$slug" ] && { echo "Nothing entered."; exit 0; }
        fi
        path="${layout.externalDir}/$slug"

        if [ -e "$path" ] || git config -f .gitmodules --get "submodule.$path.path" >/dev/null 2>&1; then
          echo "✗ '$path' already exists (directory or registered submodule) — pass a different path as the third argument." >&2
          exit 1
        fi

        if [ -n "$BRANCH_ARG" ]; then
          branch="$BRANCH_ARG"
          git ls-remote --heads "$url" "$branch" 2>/dev/null | grep -q . \
            || { echo "✗ branch '$branch' not found on $url" >&2; exit 1; }
        elif git ls-remote --heads "$url" "${odooSeries}" 2>/dev/null | grep -q .; then
          branch="${odooSeries}"
        else
          default_branch="$(oca_default_branch "$url")"
          [ -z "$default_branch" ] \
            && { echo "✗ no '${odooSeries}' branch, and could not detect a default branch on $url — pass [branch] explicitly." >&2; exit 1; }
          if has_tty; then
            branch="$(gum input --header "No '${odooSeries}' branch on $url — confirm the branch to use:" --value "$default_branch" || true)"
            [ -z "$branch" ] && branch="$default_branch"
          else
            branch="$default_branch"
            echo "==> no '${odooSeries}' branch — using detected default branch '$branch'." >&2
          fi
        fi

        echo "==> Cloning $url ($branch) → $path…"
        mkdir -p "$(dirname "$path")"
        git clone -q --depth 1 --branch "$branch" -- "$url" "$path"

        mapfile -t FOUND < <(oca_scan_modules "$path" | LC_ALL=C sort -u)
        SEL=()
        if [ "''${#FOUND[@]}" -eq 0 ]; then
          echo "⚠  no __manifest__.py found in $url — adding the submodule without registering any module." >&2
        elif [ "''${#FOUND[@]}" -eq 1 ]; then
          SEL=("''${FOUND[@]}")
        elif has_tty; then
          mapfile -t SEL < <(printf '%s\n' "''${FOUND[@]}" \
            | oca_pick_from_list "Select module(s) to record in modules.txt (space=toggle, enter=confirm):")
        else
          SEL=("''${FOUND[@]}")
          echo "==> non-interactive: recording all ''${#SEL[@]} discovered module(s)." >&2
        fi

        exec ${addGitSubmodule} "$url" "$branch" "$path" "''${SEL[@]}"
      fi

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
  # defined in data/oca-bundles.json). The picker and the series-scoped
  # expansion are shared with the scaffolder via lib/oca-lib.sh.
  odoo-add-bundle = {
    description = "Add an OCA module bundle: odoo-add-bundle [name …] (interactive if none)";
    exec = ''
      ${preamble}
      ${ocaPreamble}
      if [ "$#" -gt 0 ]; then
        NAMES=("$@")
      elif [ -t 0 ] && [ -t 1 ]; then
        mapfile -t NAMES < <(oca_pick_bundles)
      else
        echo "usage: odoo-add-bundle <name …>   (available: $(oca_bundle_names | tr '\n' ' '))" >&2
        exit 1
      fi
      [ "''${#NAMES[@]}" -eq 0 ] && { echo "No bundle selected."; exit 0; }

      mapfile -t MODULES < <(oca_expand_bundles "${odooSeries}" "''${NAMES[@]}")
      [ "''${#MODULES[@]}" -eq 0 ] && { echo "No modules in the selected bundle(s)."; exit 0; }

      echo "==> Bundle(s): ''${NAMES[*]}  →  ''${#MODULES[@]} module(s)"
      exec ${addModules} "''${MODULES[@]}"
    '';
  };
}
