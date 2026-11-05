# "Run the real odoo-bin" for an OCB source tree, as shell text: builtOdoo's
# bin/odoo (lib/odoo.nix) and the dev shell's passthrough target and server
# (modules/devenv.nix), which the `odoo` CLI execs through $ODOO_NIX_RAW_ODOO
# (lib/cli.nix).
#
# An Enterprise source tree can come without odoo-bin. Then Odoo runs the way
# `python -m odoo` runs it (odoo/__main__.py), with the tree first on
# PYTHONPATH, the way odoo-bin's own directory comes first on sys.path: the
# tree's `odoo` wins over the wheel in the environment. Not `-m` itself: Odoo
# runs sys.argv[0] again for the websocket worker (`gevent`, with workers > 0)
# and for --dev=reload, and under `-m` that is odoo/__main__.py, which cannot
# run as a script. The launcher can, and it is named odoo-bin, so Odoo's usage
# lines read as they do with the tree's own.
#
# A tree with neither odoo-bin nor odoo/__main__.py, such as an uninitialised
# submodule, still goes to odoo-bin, so the error names the tree. The
# launcher would run the wheel's Odoo instead.
#
# With `coverage` (a coverage.py package built for `python`), the text also
# measures a run when $ODOO_NIX_COVERAGE_RCFILE names an rcfile (`odoo test
# --coverage`, lib/odoo_nix_cli/testrun.py): Odoo then runs as `python -m
# coverage run --rcfile=<it> --parallel-mode <odoo-bin or the launcher>`, and
# writes its data where $COVERAGE_FILE says. Unset, the run is the plain one.
# The dev shell passes it; builtOdoo and the NixOS service pass null:
# production never measures, and its text is the same as without the option.
#
# Usage: the text runs Odoo from "$tree", which the caller sets first.
#   import ./lib/raw-odoo.nix { inherit pkgs; python = "${env}/bin/python"; }

{
  pkgs,
  # The application's interpreter: the environment Odoo runs in.
  python,
  # coverage.py for that interpreter, or null: no coverage hook.
  coverage ? null,
}:

let
  launcher = pkgs.writeTextFile {
    name = "odoo-nix-odoo-bin";
    destination = "/odoo-bin";
    text = ''
      # Odoo from a source tree without odoo-bin, as `python -m odoo` runs it.
      # sys.argv[0] stays this file, which Odoo can run again (lib/raw-odoo.nix).
      import runpy

      runpy.run_module("odoo", run_name="__main__")
    '';
  };
  # Before the plain runs below, and the same choice of entry point: the
  # tree's odoo-bin, or the launcher with the tree first on PYTHONPATH. Under
  # `coverage run` sys.argv[0] stays the entry point, so a process Odoo
  # starts again from it (the websocket worker, --dev=reload) is not measured.
  measure = ''-m coverage run --rcfile="$ODOO_NIX_COVERAGE_RCFILE" --parallel-mode'';
  coverageHook = pkgs.lib.optionalString (coverage != null) ''
    if [ -n "''${ODOO_NIX_COVERAGE_RCFILE:-}" ]; then
      export PYTHONPATH="${coverage}/${coverage.pythonModule.sitePackages}''${PYTHONPATH:+:$PYTHONPATH}"
      if [ -e "$tree/odoo-bin" ] || [ ! -e "$tree/odoo/__main__.py" ]; then
        exec ${python} ${measure} "$tree/odoo-bin" "$@"
      fi
      export PYTHONPATH="$tree:$PYTHONPATH"
      exec ${python} ${measure} ${launcher}/odoo-bin "$@"
    fi
  '';
in
coverageHook
+ ''
  if [ -e "$tree/odoo-bin" ] || [ ! -e "$tree/odoo/__main__.py" ]; then
    exec ${python} "$tree/odoo-bin" "$@"
  fi
  export PYTHONPATH="$tree''${PYTHONPATH:+:$PYTHONPATH}"
  exec ${python} ${launcher}/odoo-bin "$@"
''
