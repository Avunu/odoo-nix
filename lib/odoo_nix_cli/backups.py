"""The backup store behind `odoo db restore` and `odoo project restore`:
python-devops-nix's fetch layer (lib.backups, PLAN.md Phase 2) with odoo-nix's
layout and names.

`_backups` is the base's python/backups.py, copied into this package when Nix
builds the CLI (lib/cli.nix; PLAN.md, design rule 6), so it is not in the
source tree. Standard library only, and no `odoo` import.

Connection: the BACKUPS_* variables of the backup-access secret. Overrides:
ODOO_NIX_BACKUP_SOURCE (a directory, or an mc target, laid out like the
bucket), ODOO_NIX_MC (the minio-client binary).
"""
from . import _backups, backup_layout
from ._backups import BackupError, BackupSet, Fetched, Store, parse_at, pick

__all__ = ["BackupError", "BackupSet", "Fetched", "Store", "parse_at", "backups", "pick"]

#: The fetch layer, as odoo-nix names it: messages are "odoo-nix: ...", the
#: overrides are ODOO_NIX_*, and the throwaway mc alias is `odoonix`.
backups = _backups.Backups(label="odoo-nix", env_prefix="ODOO", layout=backup_layout)
