# checks.standards-fixtures-{project,addons} (py/odoo_nix_tools/DESIGN.md §7.3): each
# standards fixture, under each built-in profile and the example-org profile, with that
# profile's locks (tests/fixtures/standards-locks), synced offline and then checked:
# `sync --write --offline` exits 0, a second one changes nothing, `sync --check` exits 0.
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
  run =
    {
      name,
      config,
      cli,
    }:
    scriptCheck "standards-fixtures-${name}"
      {
        tools = [
          pkgs.git
          pkgs.gnused
          pkgs.coreutils
        ];
      }
      ''
        export HOME="$TMPDIR" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
        export ODOO_NIX_ALLOW_SKEW=1 PYTHONDONTWRITEBYTECODE=1
        export GIT_AUTHOR_NAME=fixtures GIT_AUTHOR_EMAIL=fixtures@example.org
        export GIT_COMMITTER_NAME=fixtures GIT_COMMITTER_EMAIL=fixtures@example.org
        for profile in minimal recommended example-org; do
          echo "== standards-${name} × $profile"
          w="$TMPDIR/$profile/fixture-${name}"
          mkdir -p "$w"
          cp -r ${fixtures}/standards-${name}/. "$w"
          ref="$profile"
          if [ "$profile" = example-org ]; then
            cp -r ${fixtures}/standards-profiles/example-org "$w/.standards-profile"
            ref=./.standards-profile
          fi
          if [ -d ${fixtures}/standards-locks/standards-${name}/"$profile" ]; then
            cp -r ${fixtures}/standards-locks/standards-${name}/"$profile"/. "$w"
          fi
          chmod -R u+w "$w"
          sed -i "s|^profile = \"recommended\"$|profile = \"$ref\"|" "$w/${config}"
          grep -q "^profile = \"$ref\"$" "$w/${config}"
          git -C "$w" init -q -b main
          git -C "$w" add -A
          git -C "$w" commit -q -m fixture
          (cd "$w" && ${cli} sync --write --offline)
          git -C "$w" add -A
          git -C "$w" commit -q -m synced
          (cd "$w" && ${cli} sync --write --offline)
          test -z "$(git -C "$w" status --porcelain)" || {
            git -C "$w" status --porcelain
            echo "a second sync --write changed the files above" >&2
            exit 1
          }
          (cd "$w" && ${cli} sync --check)
        done
      '';
in
{
  standards-fixtures-project = run {
    name = "project";
    config = "pyproject.toml";
    cli = lib.getExe odooNix;
  };
  standards-fixtures-addons = run {
    name = "addons";
    config = "nix/pyproject.toml";
    cli = addonsCli;
  };
}
