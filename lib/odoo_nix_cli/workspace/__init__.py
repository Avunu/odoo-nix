"""The workspace's source repositories: `odoo module add`, `odoo module
add-bundle` and `odoo module remove` (python-devops-nix docs/conventions.md,
Source management). Was the bash in lib/cli-scripts.nix and lib/oca-lib.sh.

config (what lib/cli-scripts.nix bakes), common (modules.txt, submodules and
the re-lock), add and remove. The OCA catalogue is odoo_nix_cli.oca, and the
prompts and process helpers are the scaffolder's (odoo_nix_cli.init.ui and
.proc). Database access, for remove's in-use check, is the CLI's own
(odoo_nix_cli.odooenv), and imported only when it is needed.
"""
