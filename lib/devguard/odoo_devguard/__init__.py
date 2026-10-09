"""Guard rails for odoo-nix development environments.

Loaded at interpreter start from ``zzz-odoo-devguard.pth`` inside the dev
virtualenv (and explicitly by the ``odoo`` CLI), i.e. *below* Odoo itself.
Every interpreter that can import Odoo from that environment is covered --
the server, ``odoo shell``, ``odoo db ...``, an ad-hoc script -- without
installing a module into any database or editing any odoo.conf.

A database restored from production carries working production credentials:
SMTP and IMAP logins, S3 keys, API tokens, webhooks, an SFTP backup target.
Left alone it will mail real customers, push a dev-mutated database over the
production backup rotation, delete production files, and call every
integration it has a key for. Neutralization (``neutralize.sql``) covers what
Odoo and a few addons remember to cover; each guard here closes one route
neutralization does not.

Two layers, deliberately:

``egress``
    transport level. Refuses every non-loopback ``connect()`` made by this
    process, whatever library asked -- requests, httpx, aiohttp (s3fs),
    paramiko, urllib, smtplib. It knows nothing about Odoo, so it holds across
    upgrades, third-party addons and code nobody has read.
the rest
    Odoo and addon APIs, patched so the failure is readable ("storage 'prod'
    is S3; restore localized it", a cron skipped by name) instead of a socket
    error three frames down. These are one refactor or one unknown addon away
    from being bypassed; the fail-closed checks in ``_patch.require`` make such
    drift loud, but they are not the same guarantee -- which is why ``egress``
    exists.

``ODOO_DEVGUARD_ENABLED=0`` (everything) or ``ODOO_DEVGUARD_DISABLE=egress,crons``
(named guards) gives stock behaviour for a single command.

This package is DEVELOPMENT ONLY, by construction: lib/python.nix grafts it into
the dev and test environments and never into the production one, so
``services.odoo-nix`` and the container image cannot contain it.
"""

from ._settings import DevGuardBlocked, DevGuardPatchError, settings

__all__ = [
    "DevGuardBlocked",
    "DevGuardPatchError",
    "install",
    "settings",
    "status",
]

_INSTALLED = False


def install():
    """Install every enabled guard. Idempotent; safe to call from anywhere."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from .guards import GUARDS

    for guard in GUARDS:
        if settings().guard_enabled(guard.NAME):
            guard.install()


def status():
    """Per-target report of what has been patched so far."""
    from ._patch import STATUS

    return dict(STATUS)


# NB: install() is called by the .pth bootstrap, not here. Importing the guard
# modules from this module's body would make `import odoo_devguard.guards.X`
# re-enter a partially initialised package.
