# A nixpkgs Python interpreter with `rich` usable standalone -- for
# odoo-nix's own small pieces of tooling (the `odoo` CLI wrapper, the
# dev-shell welcome banner) that have nothing to do with a *consuming*
# project's own uv-managed Python dependency graph, and so have no business
# being added to it.
#
# rich's python3.11 build (odoo-nix's default 18.0 interpreter) has been
# seen failing in nixpkgs: markdown-it-py, one of rich's own *runtime*
# dependencies (it renders markdown in the terminal, not just a test
# fixture), defaults to doCheck = true, and its own test suite pulls in
# pytest-regressions -> numpy, and a numpy version landed that requires
# Python >=3.12 while still being offered to 3.11 -- a nixpkgs-side version
# mismatch, not anything about markdown-it-py's or rich's actual code.
# Disabling rich's *own* doCheck is not enough: markdown-it-py is still
# pulled in as a plain dependency and still built with its own doCheck
# default, independent of rich's. `overridePythonAttrs` (not the generic
# `overrideAttrs`, which only edits an already-finalized derivation's
# attributes and has no effect on `doCheck` specifically -- confirmed
# empirically: nativeBuildInputs is computed from `doCheck` inside
# buildPythonPackage itself, before overrideAttrs ever runs) on
# markdown-it-py itself, substituted into rich via `.override`, drops that
# whole checkInputs closure from the build.
#
# Usage:
#   import ./lib/rich-python.nix { inherit pkgs python; }                     # rich only
#   import ./lib/rich-python.nix { inherit pkgs python; extraPackages = ps: [ ps.click ]; }

{
  pkgs,
  python,
  extraPackages ? (_ps: [ ]),
}:

python.withPackages (
  ps:
  let
    noCheckMarkdownItPy = ps."markdown-it-py".overridePythonAttrs (_: {
      doCheck = false;
    });
  in
  [
    (ps.rich.override { "markdown-it-py" = noCheckMarkdownItPy; })
  ]
  ++ extraPackages ps
)
