# `nix run .#relock-standards-fixtures` (py/odoo_nix_tools/DESIGN.md §7.1): in the
# odoo-nix work tree, py/odoo_nix_tools/scripts/relock_fixtures.py (each standards
# fixture synced under each profile with tools, then `uv lock --project tools` and
# `npm install --package-lock-only` there, needs network), then
# scripts/gen_fixture_data.py (the fixture data the package ships). The work
# tree's odoo-nix-tools runs, against standards-core from the locked
# python-devops-nix.
{
  pkgs,
  standardsCore,
}:
let
  python = pkgs.python3.withPackages (_: [ standardsCore ]);
in
pkgs.writeShellApplication {
  name = "odoo-nix-relock-standards-fixtures";
  runtimeInputs = [
    pkgs.git
    pkgs.uv
    pkgs.nodejs
  ];
  text = ''
    root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
      echo "run it in the odoo-nix work tree" >&2
      exit 1
    }
    tools="$root/py/odoo_nix_tools"
    [ -f "$tools/scripts/relock_fixtures.py" ] || {
      echo "$root is not odoo-nix's work tree (no py/odoo_nix_tools)" >&2
      exit 1
    }
    cd "$tools"
    export PYTHONPATH="$tools:$tools/tests" PYTHONDONTWRITEBYTECODE=1
    # uv locks for the tools' floor; nixpkgs' uv, which the pinned uv2nix reads.
    export UV_PYTHON_DOWNLOADS=never
    ${python}/bin/python scripts/relock_fixtures.py
    ${python}/bin/python scripts/gen_fixture_data.py
  '';
}
