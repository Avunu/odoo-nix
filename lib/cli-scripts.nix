# The OCA/git submodule management helpers behind `odoo module add`,
# `odoo module add-bundle` and `odoo project update`'s code-pulling phase.
#
# Interactive pickers (gum) and git/submodule plumbing stay in bash here --
# porting proven, delicate logic like this to Python would be a rewrite for
# no behavioral gain. `odoo_nix_cli`'s module.py/project.py os.execv (or
# subprocess) into these; everything DB-shaped (provision/upgrade/migrate/
# backup/restore) is instead implemented directly against odoo.service.db /
# Registry.new in Python (lib/odoo_nix_cli/), for the progress feedback a
# subprocess-wrapped odoo-bin call cannot give.
#
# This is what `lib/scripts.nix` used to be; only the git/OCA-shaped scripts
# survive here; everything DB-shaped moved to Python.
#
# Usage:
#   import ./lib/cli-scripts.nix {
#     inherit lib pkgs;
#     odooSeries = cfg.odooSeries;
#     ocaDataset = ../data/oca-modules.json;
#     ocaLib = ./oca-lib.sh;
#     bundlesFile = ../data/oca-bundles.json;
#     layout = cfg.layout;
#     python = "${pythonEnvs.devPythonEnv}/bin/python";
#   }

{
  lib,
  pkgs,
  odooSeries,
  ocaDataset,
  ocaLib,
  bundlesFile,
  layout,
  python,
  # OCB from a flake input (see modules/devenv.nix `coreSource`) -- affects
  # only the "bump it with nix flake update" note in projectUpdate.
  coreSource ? null,
}:

let
  preamble = ''
    set -euo pipefail
    cd "''${REPO_ROOT:-$PWD}"
  '';

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
  # addModules, addGitSubmodule and projectUpdate, so this uv-lock/patch-
  # build-deps/relock sequence exists in exactly one place.
  regenerateAndLock = pkgs.writeShellScript "oca-regenerate-and-lock" ''
    set -euo pipefail
    cd "''${REPO_ROOT:-$PWD}"
    echo "==> Regenerating uv path-sources…"
    ${python} ${./oca_sources.py} update pyproject.toml \
      modules.txt "${layout.externalDir}" "${layout.customDir}" "${layout.coreSrc}"
    echo "==> Re-locking Python environment (uv lock)…"
    ${lib.optionalString (coreSource != null) ''
      # shellcheck source=/dev/null
      source ${./core-shadow.sh}
      _shadow="$(core_shadow_begin "${layout.coreSrc}" "${toString coreSource}")"
      trap 'core_shadow_end "${layout.coreSrc}" "${toString coreSource}" "$_shadow"' EXIT
    ''}
    if ${pkgs.uv}/bin/uv lock; then
      ${python} ${./uv_build_deps.py} update pyproject.toml uv.lock || true
      ${pkgs.uv}/bin/uv lock || true
    else
      echo "⚠  uv lock failed — resolve in pyproject.toml and re-run." >&2
    fi
  '';

  # Shared "add these module seeds" flow used by moduleAdd and
  # moduleAddBundle: resolve the transitive repo closure, add the NEW repos as
  # shallow submodules, record the seeds in modules.txt, re-aggregate the
  # scoped OCA Python deps and re-lock. Takes module names as positional args.
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
        # are installable; `odoo db provision` will report anything missing), then
        # sort it.
        for m in "''${SEL[@]}"; do ${addToModulesTxt} "$m"; done
        ${sortModulesTxt}

        ${regenerateAndLock}

        cat <<EOF

    ✅ Added ''${#SEL[@]} module(s) to modules.txt.
       1. Reload so the Nix engine re-derives addons_path + rebuilds the env:
            direnv reload
       2. Install:  odoo db provision    (installs everything in modules.txt)
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
       2. Install:  odoo db provision    (installs everything in modules.txt)
    EOF
        else
          cat <<EOF

    ✅ Added $path as a submodule (no modules recorded in modules.txt).
       Reload so the Nix engine picks up the new addons_path:
         direnv reload
    EOF
        fi
  '';

  # Pick more OCA modules (interactive picker or args), then add them -- or,
  # given a git URL / "owner/repo" shorthand, add that repo directly as a
  # submodule instead (any git host, not just OCA/GitHub).
  moduleAdd = pkgs.writeShellScript "odoo-nix-module-add" ''
    ${preamble}
    ${ocaPreamble}
    export PATH="${pkgs.git}/bin:$PATH"
    has_tty() { [ -t 0 ] && [ -t 1 ]; }

    MODE="oca"
    if [ "$#" -gt 0 ] && oca_url_shaped "$1"; then
      MODE="git"
    elif [ "$#" -eq 0 ] && has_tty; then
      choice="$(printf '%s\n' "Browse OCA catalog" "Add from a Git URL" \
        | gum choose --header "odoo module add: what do you want to add?" || true)"
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
          echo "usage: odoo module add <git-url-or-owner/repo> [branch] [path]" >&2
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

  # Add a curated OCA module bundle (a named set of "must-have" modules,
  # defined in data/oca-bundles.json). The picker and the series-scoped
  # expansion are shared with the scaffolder via lib/oca-lib.sh.
  moduleAddBundle = pkgs.writeShellScript "odoo-nix-module-add-bundle" ''
    ${preamble}
    ${ocaPreamble}
    if [ "$#" -gt 0 ]; then
      NAMES=("$@")
    elif [ -t 0 ] && [ -t 1 ]; then
      mapfile -t NAMES < <(oca_pick_bundles)
    else
      echo "usage: odoo module add-bundle <name …>   (available: $(oca_bundle_names | tr '\n' ' '))" >&2
      exit 1
    fi
    [ "''${#NAMES[@]}" -eq 0 ] && { echo "No bundle selected."; exit 0; }

    mapfile -t MODULES < <(oca_expand_bundles "${odooSeries}" "''${NAMES[@]}")
    [ "''${#MODULES[@]}" -eq 0 ] && { echo "No modules in the selected bundle(s)."; exit 0; }

    echo "==> Bundle(s): ''${NAMES[*]}  →  ''${#MODULES[@]} module(s)"
    exec ${addModules} "''${MODULES[@]}"
  '';

  # Pull submodules on their pinned branch, re-aggregate OCA python deps,
  # relock. Database migration is a separate, Python-implemented step (`odoo
  # project update` runs this, then calls into odoo_nix_cli's migrate engine
  # unless --no-migrate).
  projectUpdate = pkgs.writeShellScript "odoo-nix-project-update" ''
    ${preamble}
    echo "==> Updating git submodules…"
    git submodule update --init --recursive
    # Move each submodule to the tip of its .gitmodules-pinned branch, fetched
    # fresh by name. Two things rule out the more obvious approaches here:
    # `update --init --recursive` alone leaves submodules in detached HEAD, so
    # `git rev-parse --abbrev-ref HEAD` returns the literal string "HEAD", and
    # pulling "origin HEAD" then follows the remote's *default* branch instead
    # of the pinned one. `git submodule update --remote` avoids that but can
    # still fail if a submodule's local remote-tracking refspec was narrowed
    # to some other branch at clone time. Both surface as "Not possible to
    # fast-forward" whenever a repo's GitHub default branch no longer matches
    # what's pinned. Fetching the pinned branch by name every time sidesteps
    # both.
    git submodule foreach --quiet '
      branch="$(git config -f "$toplevel/.gitmodules" --get "submodule.$sm_path.branch")"
      [ -n "$branch" ] || branch="$(git symbolic-ref --quiet --short HEAD || true)"
      [ -n "$branch" ] && git fetch --depth 1 --quiet origin "$branch" && git checkout --quiet FETCH_HEAD || true
    '
    ${lib.optionalString (coreSource != null) ''
      echo "    (${layout.coreSrc} is a flake input, not a submodule: bump it with 'nix flake update')"
    ''}

    ${regenerateAndLock}
    echo "✅ Code updated."
  '';
in
{
  inherit moduleAdd moduleAddBundle projectUpdate;
}
