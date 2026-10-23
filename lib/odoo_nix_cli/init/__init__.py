"""``odoo-init``: the scaffolder behind ``nix run github:Avunu/odoo-nix``.

It writes a new project, or brings an existing Odoo tree in odoo-nix's layout
(OCB at odoo/, OCA repositories under modules/, your own modules under
custom/) into odoo-nix, which is also how an odoo-nix project is repaired. The
mode comes from the target directory (detect.py) unless a flag forces one.

Modules, in the order a run reaches them: args (the command line), config and
presets (what Nix baked), detect (read-only probes), select (bundles and
modules), template and secret_files (what is written), pipeline (what both
modes share), scaffold and migrate (the modes), command (dispatch). The OCA
catalogue is odoo_nix_cli.oca. It imports no Odoo, click or rich at module
level; git, uv, odoo-nix-sources and odoo-nix-build-deps run as subprocesses.
Was lib/odoo-init.sh, and lib/oca-lib.sh for the catalogue.
"""
