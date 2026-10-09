"""Cron guard.

Neutralization deactivates every cron, but a developer can switch one back on
(or restore with ``--no-neutralize``), and a restored database carries crons for
modules that reach out on every tick: the auto_backup scheduler, currency-rate
providers, bank-statement pulls, EDI output sync, fetchmail, publisher warranty.

Patches ``ir.cron._callback`` -- the one place every cron's server action runs,
in the threaded server and in prefork workers alike -- and skips a cron whose
external id (``<module>.<name>``) is on the list. The list matches the exact
string, never a substring.

Skipping, not raising: the job counts as having run, so it is not retried on
every tick and ``ir.cron.progress`` stays tidy. The ``WARNING`` line names it.
"""

import functools

from .._hook import on_import
from .._patch import announce, require, require_any, warn
from .._settings import settings

NAME = "crons"

_INSTALLED = False


def enabled():
    return settings().guard_enabled(NAME)


def blocked():
    st = settings()
    return set(st.items(NAME, "blocked_crons")) | set(st.items(NAME, "extra_blocked_crons"))


def _external_id(cron):
    return cron.get_external_id().get(cron.id) or ""


def _patch(module):
    # `ir_cron` through 18.0; Odoo 19 moved to CamelCase model classes.
    _name, cls = require_any(module, "IrCron", "ir_cron")
    original = require(cls, "_callback")

    @functools.wraps(original)
    def _callback(self, cron_name, server_action_id, *args, **kwargs):
        if enabled():
            xmlid = _external_id(self)
            if xmlid in blocked():
                announce(NAME, "scheduled actions on the denylist are skipped, not run")
                warn(NAME, f"skipping cron {xmlid} ({cron_name!r})")
                return None
        return original(self, cron_name, server_action_id, *args, **kwargs)

    cls._callback = _callback


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    on_import("odoo.addons.base.models.ir_cron", _patch)
