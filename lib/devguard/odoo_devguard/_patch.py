"""Shared patching helpers used by every guard.

Nothing here imports Odoo at module scope: most guards run from a post-import
hook, and ``install()`` runs from a ``.pth`` file before Odoo is importable.
"""

import sys

from ._settings import DevGuardBlocked, DevGuardPatchError

#: target -> "patched". Lets a test (or a curious developer) see which targets
#: a process actually reached; a module that is never imported never reaches its
#: post-import callback, which is fail-safe but otherwise invisible.
STATUS = {}

_ANNOUNCED = set()


def warn(guard, message):
    """Announce on stderr.

    Not through ``logging``: guards run before Odoo configures its handlers, and
    a record emitted earlier would be printed twice (lastResort, then Odoo's).
    Raising alone is not enough either -- cron and mail paths catch Exception
    and turn it into a log line nobody ties back to the guard.
    """
    sys.stderr.write(f"WARNING odoo_devguard[{guard}] {message}\n")


def announce(guard, detail):
    """Emit a guard's activation banner once per process, on first use.

    Deferred rather than printed at install so the many Python processes a dev
    shell starts which never reach a guarded code path stay quiet.
    """
    if guard in _ANNOUNCED:
        return
    _ANNOUNCED.add(guard)
    warn(guard, f"ACTIVE -- {detail}")


def block(guard, message):
    """Announce and raise. For code paths where failing is the right answer."""
    warn(guard, message)
    raise DevGuardBlocked(f"odoo_devguard[{guard}]: {message}")


def user_error(guard, message):
    """Announce and surface the message in the web client.

    For deliberate user actions -- a button, an RPC -- where a silent no-op
    would leave someone believing the action happened.
    """
    from odoo.exceptions import UserError

    warn(guard, message)
    raise UserError(f"Blocked by odoo-devguard: {message}")


def mark(fn, target):
    """Tag a replacement so it is identifiable after ``functools.wraps``."""
    fn.__devguard__ = target
    return fn


def is_guarded(fn):
    return getattr(fn, "__devguard__", None) is not None


def no_op(guard, what, banner=None):
    """Replacement that logs and returns None."""

    def replacement(*_args, **_kwargs):
        if banner:
            announce(guard, banner)
        warn(guard, f"skipping {what}")

    return mark(replacement, what)


def blocking(guard, what, message, banner=None):
    """Replacement that logs and raises. For the funnels that must not proceed."""

    def replacement(*_args, **_kwargs):
        if banner:
            announce(guard, banner)
        block(guard, f"{what}: {message}")

    return mark(replacement, what)


def require(owner, name):
    """Fetch a patch target, or fail the import loudly."""
    value = getattr(owner, name, None)
    if value is None:
        label = getattr(owner, "__qualname__", None) or getattr(owner, "__name__", owner)
        raise DevGuardPatchError(
            f"odoo_devguard: {label}.{name} is missing -- Odoo's (or an addon's) internals "
            "have moved and this guard can no longer be relied on. Update odoo-nix, or set "
            "ODOO_DEVGUARD_ENABLED=0 to run without it."
        )
    STATUS[f"{getattr(owner, '__name__', owner)}.{name}"] = "patched"
    return value


def require_any(owner, *names):
    """Fetch the first surviving spelling of a renamed target, or fail loudly.

    For an internal Odoo renamed across the series odoo-nix spans (18.0 and
    19.0): any known spelling will do, but none of them surviving still has to
    be loud. Returns the name too, so the caller patches back the spelling this
    Odoo actually uses.
    """
    for name in names:
        value = getattr(owner, name, None)
        if value is not None:
            STATUS[f"{getattr(owner, '__name__', owner)}.{name}"] = "patched"
            return name, value
    label = getattr(owner, "__qualname__", None) or getattr(owner, "__name__", owner)
    raise DevGuardPatchError(
        f"odoo_devguard: {label} has none of {', '.join(names)} -- Odoo's internals have "
        "moved and this guard can no longer be relied on. Update odoo-nix, or set "
        "ODOO_DEVGUARD_ENABLED=0 to run without it."
    )
