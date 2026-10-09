"""Object-store guard: fs.storage opens local filesystems only.

OCA ``fs_storage`` is the single doorway to S3, SFTP and friends for
``fs_attachment`` and for the ``auto_backup_fs_storage`` bridge: everything goes
through ``fs.storage._get_filesystem``. A database restored from production
carries a storage record pointing at the production bucket, with credentials in
its options. ``odoo db restore`` rewrites those to local directories; this guard
is what makes that rewrite non-optional -- a storage that still names S3, SFTP
or any other remote protocol cannot be opened at all, so attachments can neither
be read from nor written to (or deleted from) a production bucket.

Which also covers the ``odoo_backup`` storage the bridge module creates: its
``$BACKUPS_*`` options resolve only if those variables are in the environment,
and the guard keeps a shell that happens to have them from making it live.
"""

import functools
import json

from .._hook import on_import
from .._patch import announce, block, require, require_any
from .._settings import settings

NAME = "objectstore"

_INSTALLED = False


def enabled():
    return settings().guard_enabled(NAME)


def _effective_protocol(storage):
    """The protocol that actually touches storage.

    ``rooted_dir`` is a wrapper: it is local only if the filesystem it wraps is.
    """
    protocol = storage.protocol
    if protocol == "rooted_dir":
        try:
            options = json.loads(storage.options or "{}")
        except ValueError:
            return protocol
        return options.get("target_protocol") or "file"
    return protocol


def _patch(module):
    _name, cls = require_any(module, "FSStorage", "FsStorage")
    original = require(cls, "_get_filesystem")

    @functools.wraps(original)
    def _get_filesystem(self, *args, **kwargs):
        if enabled():
            local = set(settings().items(NAME, "local_protocols"))
            protocol = _effective_protocol(self)
            if protocol not in local:
                announce(NAME, "fs.storage records are limited to local protocols")
                block(
                    NAME,
                    f"storage '{self.code}' uses protocol '{protocol}'. A development "
                    "database must not reach a remote store: restore it with `odoo db restore` "
                    "(which points remote storages at local disk), or set the storage's "
                    "protocol to 'file'.",
                )
        return original(self, *args, **kwargs)

    cls._get_filesystem = _get_filesystem


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    on_import("odoo.addons.fs_storage.models.fs_storage", _patch)
