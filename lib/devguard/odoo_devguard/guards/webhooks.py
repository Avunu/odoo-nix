"""Webhook guard: outbound webhook server actions do nothing.

Neutralization points every webhook action at a dummy URL; this covers an action
created, or edited, after the restore. A no-op rather than an error, because a
raise here fails the save that triggered an automation, which breaks forms for
a side effect nobody wanted anyway.

Only the outbound action (``ir.actions.server`` of state ``webhook``) is
touched. base_automation's ``/web/hook/<uuid>`` endpoint is inbound.
"""

import functools

from .._hook import on_import
from .._patch import announce, require, warn
from .._settings import settings

NAME = "webhooks"

_INSTALLED = False


def enabled():
    return settings().guard_enabled(NAME)


def _patch(module):
    cls = require(module, "IrActionsServer")
    original = require(cls, "_run_action_webhook")

    @functools.wraps(original)
    def _run_action_webhook(self, *args, **kwargs):
        if not enabled():
            return original(self, *args, **kwargs)
        announce(NAME, "outbound webhook actions are skipped")
        warn(NAME, f"skipping webhook action {self.id} ({self.name!r})")
        return None

    cls._run_action_webhook = _run_action_webhook


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    on_import("odoo.addons.base.models.ir_actions", _patch)
