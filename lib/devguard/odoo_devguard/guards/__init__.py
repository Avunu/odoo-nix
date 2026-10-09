"""Guard registry.

Each guard module exposes ``NAME`` and ``install()``. ``install()`` registers
post-import hooks (or patches the standard library); it never imports Odoo
itself, so importing a guard on a machine with no Odoo is free.
"""

from . import backups, crons, egress, iap, mail, mail_stdlib, objectstore, webhooks

#: Order matters only for readability -- every guard is independent. ``egress``
#: first: it is the one that holds when the others have drifted.
GUARDS = (
    egress,
    mail_stdlib,
    mail,
    crons,
    objectstore,
    backups,
    webhooks,
    iap,
)

__all__ = ["GUARDS"]
