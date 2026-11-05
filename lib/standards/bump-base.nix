# `nix run .#bump-base -- REV [COMMENT]` (core DESIGN.md §10.3): every pin of
# python-devops-nix (standards-core) in odoo-nix's work tree, moved to one commit
# at once, as checks.standards-core-pins requires:
#
#   1. flake.lock's python-devops-nix node, by `nix flake lock --override-input`
#      (flake.nix keeps its ref-less url; the lock records the commit);
#   2. py/odoo_nix_tools/pyproject.toml's `standards-core @ git+…@<sha>` line and
#      every `Avunu/python-devops-nix/…@<sha>` in .github/** (lib/standards/bump_base.py),
#      each `uses:` with COMMENT as its version comment (default: REV as given);
#   3. the dev lock, py/odoo_nix_tools/uv.lock (`uv lock --upgrade-package standards-core`).
#
# REV is a 40-hex commit, or a tag or branch of github.com/Avunu/python-devops-nix
# (resolved with `git ls-remote`). Needs network; never runs in a check, though
# checks.bump-base runs bump_base.py over a copy offline. nix is the caller's.
{ pkgs }:
pkgs.writeShellApplication {
  name = "odoo-nix-bump-base";
  runtimeInputs = [
    pkgs.git
    pkgs.uv
    pkgs.python3
    pkgs.gawk
  ];
  text = ''
    if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
      echo "usage: nix run .#bump-base -- REV [COMMENT]" >&2
      exit 2
    fi
    root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
      echo "run it in the odoo-nix work tree" >&2
      exit 1
    }
    [ -f "$root/py/odoo_nix_tools/pyproject.toml" ] || {
      echo "$root is not odoo-nix's work tree (no py/odoo_nix_tools)" >&2
      exit 1
    }
    url=https://github.com/Avunu/python-devops-nix
    rev=$1
    comment=''${2:-python-devops-nix $1}
    if ! [[ "$rev" =~ ^[0-9a-f]{40}$ ]]; then
      refs="$(git ls-remote "$url" "refs/tags/$rev" "refs/heads/$rev")"
      sha=""
      # An annotated tag's commit (its peeled line), else the tag, else the branch.
      for ref in "refs/tags/$rev^{}" "refs/tags/$rev" "refs/heads/$rev"; do
        [ -n "$sha" ] || sha="$(awk -v ref="$ref" '$2 == ref { print $1; exit }' <<<"$refs")"
      done
      [ -n "$sha" ] || {
        echo "$rev is neither a commit nor a tag or branch of $url" >&2
        exit 1
      }
      rev=$sha
    fi
    cd "$root"
    nix flake lock --override-input python-devops-nix "github:Avunu/python-devops-nix/$rev"
    python3 -I ${./bump_base.py} "$root" "$rev" "$comment"
    export UV_PYTHON_DOWNLOADS=never
    uv lock --project py/odoo_nix_tools --upgrade-package standards-core
    echo "python-devops-nix is at $rev: check with nix build .#checks.$(nix eval --raw --impure --expr builtins.currentSystem).standards-core-pins"
  '';
}
