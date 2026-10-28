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
# Usage: the text runs Odoo from "$tree", which the caller sets first.
#   import ./lib/raw-odoo.nix { inherit pkgs; python = "${env}/bin/python"; }

{
  pkgs,
  # The application's interpreter: the environment Odoo runs in.
  python,
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
in
''
  if [ -e "$tree/odoo-bin" ] || [ ! -e "$tree/odoo/__main__.py" ]; then
    exec ${python} "$tree/odoo-bin" "$@"
  fi
  export PYTHONPATH="$tree''${PYTHONPATH:+:$PYTHONPATH}"
  exec ${python} ${launcher}/odoo-bin "$@"
''
