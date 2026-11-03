# The standards fixtures, synced (py/odoo_nix_tools/DESIGN.md §7.3):
#
#   standards-fixtures-{project,addons}  each fixture under each built-in profile and
#       the example-org profile, with that profile's locks
#       (tests/fixtures/standards-locks), synced offline and then checked:
#       `sync --write --offline` exits 0, a second one changes nothing, `sync --check`
#       exits 0
#   standards-prek-{project,addons}  each fixture synced under example-org, with
#       tools/.venv, tools/.bin and node_modules linked (built from the example-org
#       locks, lib/standards/tools.nix): the managed files are clean under their own
#       hooks (`prek run -c .pre-commit-config.yaml --files <what sync wrote>`); a
#       nested config under an addon does not run; zizmor sees .github/ and reports
#       an unpinned `uses:`
#   standards-prettier-stable  the locked prettier `--check` on the managed JSON, YAML
#       and JavaScript of both synced fixtures
#
# ODOO_NIX_ALLOW_SKEW=1: no caller SHA or core rev matches a fixture lock's fake rev.
#
# The project runs the `odoo-nix` command (packages.odoo-nix). The addon repository's
# [tool.odoo-nix] is in nix/pyproject.toml, which the core reads only once it has CR1
# (DESIGN.md §10): until then it runs the core's CLI with the suites' stand-in product
# (tests/support.py ADDONS_PRODUCT), whose config file is that path.
{
  pkgs,
  lib,
  scriptCheck,
  odooNix,
  odooNixTools,
  # lib/standards/shell.nix over a checkout (flake.nix standardsShellFor).
  standardsShell,
}:
let
  fixtures = lib.fileset.toSource {
    root = ../fixtures;
    fileset = lib.fileset.unions [
      ../fixtures/standards-project
      ../fixtures/standards-addons
      ../fixtures/standards-profiles
      ../fixtures/standards-locks
    ];
  };
  python = odooNixTools.pythonModule.withPackages (_: [ odooNixTools ]);
  addonsCli = pkgs.writeShellScript "odoo-nix-addons" ''
    exec ${python}/bin/python -c '
    import sys
    sys.path.insert(0, "${odooNixTools.src}/tests")
    from standards_core.cli import main
    from support import ADDONS_PRODUCT
    sys.exit(main(ADDONS_PRODUCT, sys.argv[1:]))
    ' "$@"
  '';

  shapes = {
    project = {
      config = "pyproject.toml";
      cli = lib.getExe odooNix;
      addon = "custom/fixture_sale";
    };
    addons = {
      config = "nix/pyproject.toml";
      cli = addonsCli;
      addon = "fixture_a";
    };
  };

  env = ''
    export HOME="$TMPDIR" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
    export ODOO_NIX_ALLOW_SKEW=1 PYTHONDONTWRITEBYTECODE=1
    export GIT_AUTHOR_NAME=fixtures GIT_AUTHOR_EMAIL=fixtures@example.org
    export GIT_COMMITTER_NAME=fixtures GIT_COMMITTER_EMAIL=fixtures@example.org
  '';

  # fixture <profile> <dir> [<prepare command>]: a git copy of the fixture under the
  # profile, with that profile's locks (not the manifests beside them, which sync
  # renders), committed; the prepare command runs in it before the commit.
  fixture =
    name:
    let
      s = shapes.${name};
    in
    ''
      fixture() {
        local profile=$1 w=$2 ref=$1
        mkdir -p "$w"
        cp -r ${fixtures}/standards-${name}/. "$w"
        if [ "$profile" = example-org ]; then
          cp -r ${fixtures}/standards-profiles/example-org "$w/.standards-profile"
          ref=./.standards-profile
        fi
        locks=${fixtures}/standards-locks/standards-${name}/"$profile"
        for f in tools/uv.lock package-lock.json; do
          if [ -f "$locks/$f" ]; then
            mkdir -p "$(dirname "$w/$f")"
            cp "$locks/$f" "$w/$f"
          fi
        done
        chmod -R u+w "$w"
        sed -i "s|^profile = \"recommended\"$|profile = \"$ref\"|" "$w/${s.config}"
        grep -q "^profile = \"$ref\"$" "$w/${s.config}"
        if [ -n "''${3:-}" ]; then (cd "$w" && eval "$3"); fi
        git -C "$w" init -q -b main
        git -C "$w" add -A
        git -C "$w" commit -q -m fixture
      }
    '';

  run =
    name:
    let
      s = shapes.${name};
    in
    scriptCheck "standards-fixtures-${name}"
      {
        tools = [
          pkgs.git
          pkgs.gnused
          pkgs.gnugrep
          pkgs.coreutils
        ];
      }
      ''
        ${env}
        ${fixture name}
        for profile in minimal recommended example-org; do
          echo "== standards-${name} × $profile"
          w="$TMPDIR/$profile/fixture-${name}"
          fixture "$profile" "$w"
          (cd "$w" && ${s.cli} sync --write --offline)
          git -C "$w" add -A
          git -C "$w" commit -q -m synced
          (cd "$w" && ${s.cli} sync --write --offline)
          test -z "$(git -C "$w" status --porcelain)" || {
            git -C "$w" status --porcelain
            echo "a second sync --write changed the files above" >&2
            exit 1
          }
          (cd "$w" && ${s.cli} sync --check)
        done
      '';

  # The tools each fixture links, from its example-org locks.
  toolsOf =
    name:
    standardsShell {
      root = ../fixtures/standards-${name};
      toolsRoot = ../fixtures/standards-locks/standards-${name}/example-org;
      addonsMode = name == "addons";
    };

  # synced <dir>: the fixture under example-org, synced and committed, with the tools
  # linked as the shell links them; <dir>.managed lists what sync wrote. The fixture's
  # .vscode/extensions.json has no final newline on purpose (DESIGN.md §7.1: jsonc-merge
  # keeps it absent), which end-of-file-fixer would add: it gets one first, as an
  # adoption's `style:` commit would give it.
  synced =
    name:
    let
      s = shapes.${name};
      shell = toolsOf name;
    in
    ''
      ${fixture name}
      synced() {
        local w=$1
        fixture example-org "$w" \
          '[ ! -f .vscode/extensions.json ] || [ -z "$(tail -c1 .vscode/extensions.json)" ] || echo >> .vscode/extensions.json'
        (cd "$w" && ${s.cli} sync --write --offline)
        git -C "$w" add -A
        git -C "$w" commit -q -m synced
        mkdir -p "$w/tools"
        ln -s ${shell.tools.toolsEnv} "$w/tools/.venv"
        ln -s ${shell.nixToolsEnv}/bin "$w/tools/.bin"
        ln -s ${shell.tools.nodeModules}/node_modules "$w/node_modules"
        # The links are the managed .gitignore block's.
        test -z "$(git -C "$w" status --porcelain)"
        git -C "$w" diff --name-only --diff-filter=d HEAD~1 HEAD > "$w.managed"
      }
    '';

  prek =
    name:
    let
      s = shapes.${name};
      shell = toolsOf name;
    in
    scriptCheck "standards-prek-${name}"
      {
        tools = [
          pkgs.git
          pkgs.gnused
          pkgs.gnugrep
          pkgs.coreutils
          pkgs.nodejs
        ];
      }
      ''
        ${env}
        ${synced name}
        prek=${lib.getExe shell.tools.prek}
        w="$TMPDIR/fixture-${name}"
        synced "$w"
        cd "$w"
        echo "== the managed files under their own hooks"
        mapfile -t managed < "$w.managed"
        "$prek" run -c .pre-commit-config.yaml --files "''${managed[@]}"
        test -z "$(git status --porcelain)"

        echo "== a nested config does not run"
        cat > ${s.addon}/.pre-commit-config.yaml <<'YAML'
        repos:
          - repo: local
            hooks:
              - id: nested-must-not-run
                name: nested-must-not-run
                entry: a nested config ran
                language: fail
        YAML
        echo plain > ${s.addon}/nested.txt
        git add -A
        "$prek" run -c .pre-commit-config.yaml --files ${s.addon}/nested.txt | tee nested.log
        refute grep -q nested-must-not-run nested.log

        echo "== zizmor sees .github/"
        cat > .github/workflows/unpinned.yml <<'YAML'
        name: unpinned
        on: [push]
        permissions: {}
        jobs:
          unpinned:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
                with:
                  persist-credentials: false
        YAML
        git add -A
        refute "$prek" run zizmor -c .pre-commit-config.yaml --all-files > zizmor.log 2>&1
        cat zizmor.log
        grep -q unpinned-uses zizmor.log
        grep -q 'workflows/unpinned.yml' zizmor.log
      '';

  # prettier --check on what sync wrote: not .vscode/ (deviation prettier-vscode), not
  # the files OCA's exclude keeps from prettier (eslint.config.cjs, prettier.config.cjs:
  # OCA's own text), not the locks.
  prettier =
    scriptCheck "standards-prettier-stable"
      {
        tools = [
          pkgs.git
          pkgs.gnused
          pkgs.gnugrep
          pkgs.coreutils
          pkgs.nodejs
        ];
      }
      (
        env
        + lib.concatMapStrings (name: ''
          (
            ${synced name}
            w="$TMPDIR/prettier-${name}"
            synced "$w"
            cd "$w"
            grep -E '\.(json|ya?ml|c?js|mjs)$' "$w.managed" \
              | grep -vE '^\.vscode/|^(eslint|prettier)\.config\.cjs$|(^|/)package-lock\.json$' > "$w.checked"
            echo "== ${name}: $(tr '\n' ' ' < "$w.checked")"
            test -s "$w.checked"
            mapfile -t files < "$w.checked"
            node_modules/.bin/prettier --check "''${files[@]}"
          )
        '') (lib.attrNames shapes)
      );
in
{
  standards-fixtures-project = run "project";
  standards-fixtures-addons = run "addons";
  standards-prek-project = prek "project";
  standards-prek-addons = prek "addons";
  standards-prettier-stable = prettier;
}
