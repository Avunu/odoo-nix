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

The settings are the shared job denylist's (``jobs``: ``devguard.jobs.*``,
``ODOO_DEVGUARD_JOBS_*``, ``ODOO_DEVGUARD_DISABLE=jobs``); the log lines keep
Odoo's word, ``odoo_devguard[crons]``. ``ODOO_DEVGUARD_DISABLE=crons``, the
name before the shared one, still turns the guard off, with a warning, through
odoo-nix 1.x; it is removed in 2.0.0.
"""

import functools

from .._hook import on_import
from .._patch import announce, require, require_any, warn
from .._settings import env_name, settings

#: The settings key, and the name ODOO_DEVGUARD_DISABLE takes.
NAME = "jobs"

#: The name the log lines carry: Odoo calls these crons.
LOG = "crons"

#: The guard's name before the shared one (python-devops-nix CONVENTIONS.md,
#: Job denylist), still accepted by ODOO_DEVGUARD_DISABLE through 1.x, removed in 2.0.0.
_OLD_NAME = "crons"

_INSTALLED = False
_WARNED_OLD_NAME = False


def enabled():
    global _WARNED_OLD_NAME
    st = settings()
    if _OLD_NAME in st.disabled_guards:
        if not _WARNED_OLD_NAME:
            _WARNED_OLD_NAME = True
            warn(
                LOG,
                f"{env_name('disable')}={_OLD_NAME} is deprecated; use "
                f"{env_name('disable')}={NAME} (the old name is kept through 1.x, removed in 2.0.0)",
            )
        return False
    return st.guard_enabled(NAME)


def blocked():
    return set(settings().blocked_jobs)


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
                announce(LOG, "scheduled actions on the denylist are skipped, not run")
                warn(LOG, f"skipping cron {xmlid} ({cron_name!r})")
                return None
        return original(self, cron_name, server_action_id, *args, **kwargs)

    cls._callback = _callback


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    on_import("odoo.addons.base.models.ir_cron", _patch)
