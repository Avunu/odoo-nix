"""IAP guard: Odoo In-App Purchase calls raise a readable error.

``iap_jsonrpc`` is the funnel for IAP-backed features -- SMS, partner
autocomplete, document digitization, lead enrichment. Neutralization suffixes
the account tokens; this refuses the call outright, in the web client's own
error dialog, so the failure reads as "blocked by odoo-devguard" rather than as
a connection error.
"""

import functools

from .._hook import on_import
from .._patch import announce, require, user_error
from .._settings import settings

NAME = "iap"

_INSTALLED = False


def enabled():
    return settings().guard_enabled(NAME)


def _patch(module):
    original = require(module, "iap_jsonrpc")

    @functools.wraps(original)
    def iap_jsonrpc(*args, **kwargs):
        if not enabled():
            return original(*args, **kwargs)
        announce(NAME, "IAP calls are blocked")
        user_error(NAME, "IAP services are not reachable from a development environment.")

    module.iap_jsonrpc = iap_jsonrpc


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    on_import("odoo.addons.iap.tools.iap_tools", _patch)
