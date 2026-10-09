"""Backup guard: auto_backup jobs may only write to local disk.

A restored production database carries the production backup job (SFTP, or an
FS Storage). Run on a developer machine it would push a dev-mutated database
over the production rotation, and its retention pass would delete production's
backups -- ``cleanup`` removes every file older than ``days_to_keep``.

``egress`` and ``objectstore`` already make both fail; this skips the record up
front with a message in its chatter, and keeps the retention pass from ever
being attempted. Local jobs are untouched. The bridge module
(``auto_backup_fs_storage``) overrides both methods and handles its own records
before calling ``super()``, so the same wrapper is applied to its class too.
"""

import functools

from .._hook import on_import
from .._patch import announce, require, warn
from .._settings import settings

NAME = "backups"

_INSTALLED = False

_MODULES = (
    "odoo.addons.auto_backup.models.db_backup",
    "odoo.addons.auto_backup_fs_storage.models.db_backup",
)


def enabled():
    return settings().guard_enabled(NAME)


def _remote(recs):
    return recs.filtered(lambda r: r.method != "local")


def _wrap(original, what):
    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        if not enabled():
            return original(self, *args, **kwargs)
        remote = _remote(self)
        if remote:
            announce(NAME, "backup jobs to a remote destination are skipped")
            for rec in remote:
                warn(NAME, f"skipping {what} for '{rec.name}' ({rec.method})")
            self = self - remote
            if not self:
                return None
        return original(self, *args, **kwargs)

    return wrapper


def _patch(module):
    cls = require(module, "DbBackup")
    for name in ("action_backup", "cleanup"):
        # Only wrap what this class defines itself: wrapping an inherited method
        # here would shadow the class that really owns it.
        if name in cls.__dict__:
            setattr(cls, name, _wrap(cls.__dict__[name], name))


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    for name in _MODULES:
        on_import(name, _patch)
