"""Settings resolution and shared exception types.

Resolution order, highest first: ``ODOO_DEVGUARD_*`` environment variables,
then the values baked in by Nix (``_baked.json``, written next to this file at
build time), then the defaults below. Env wins so a single command can be
re-pointed without a rebuild; the baked values mean the guards still hold when
the devenv environment is absent (an editor terminal, ``nix run``, a stray
``sudo -u``), because the guard travels with the virtualenv rather than with
the shell.

Settings are read at *call* time rather than frozen at import, so a guard can
be turned off for a single command without a rebuild.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    BAKED: dict[str, Any] = json.loads((Path(__file__).parent / "_baked.json").read_text())
except (OSError, ValueError):  # absent in a bare source checkout (the unit test)
    BAKED = {}

#: Every guard, and its defaults. A guard's key here is the name used by
#: ``ODOO_DEVGUARD_DISABLE`` and by the Nix option ``devguard.<name>``.
DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "guards": {
        # Catch-all: every non-loopback connect() from this process.
        "egress": {"enable": True, "allow_hosts": []},
        "mail": {
            "enable": True,
            "host": "127.0.0.1",
            "port": 1025,
            "http_port": 8025,
            "pop3_enabled": False,
            "pop3_port": 1110,
            "pop3_user": "dev",
            "pop3_password": "dev",
        },
        "crons": {
            "enable": True,
            # Matched EXACT-STRING against the cron's external id
            # ("<module>.<name>"). Neutralization already deactivates every
            # cron; this is the backstop for one a developer switches back on.
            # A restored database also carries crons for modules that talk to
            # the outside world on every tick.
            "blocked_crons": [
                "auto_backup.ir_cron_backup_scheduler_0",
                "currency_rate_update.ir_cron_currency_rates_update_every_day",
                "account_statement_import_online.ir_cron_account_pull_online_bank_statements",
                "edi_core_oca.cron_edi_backend_check_output_exchange",
                "mail.ir_cron_mail_gateway_action",
                "mail.ir_cron_module_update_notification",
                "mail.ir_cron_web_push_notification",
            ],
            # Unioned with blocked_crons, so a consumer adds rather than restates.
            "extra_blocked_crons": [],
        },
        # fs.storage: only local protocols may be opened.
        "objectstore": {"enable": True, "local_protocols": ["file", "odoofs", "memory"]},
        "backups": {"enable": True},
        "webhooks": {"enable": True},
        "iap": {"enable": True},
    },
}

_TRUTHY = {"1", "true", "yes", "on", "t", "y"}
_FALSY = {"0", "false", "no", "off", "f", "n", ""}


class DevGuardBlocked(OSError):
    """Raised when a guard refuses an action that would reach production.

    Subclasses ``OSError`` so callers that already handle "the remote service
    is unreachable" degrade the way they would for a network failure.
    """


class DevGuardPatchError(RuntimeError):
    """A patch target went missing -- Odoo's or an addon's internals moved.

    Raised from inside the post-import hook so the offending ``import`` fails
    loudly instead of leaving a silently inert guard behind.
    """


def _as_bool(value, fallback):
    if isinstance(value, bool):
        return value
    if value is None:
        return fallback
    text = str(value).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    return fallback


def warn(message):
    sys.stderr.write(f"WARNING odoo_devguard {message}\n")


def _as_int(value, fallback):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        warn(f"invalid integer {value!r}; falling back to {fallback!r}")
        return fallback


def _as_list(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    if value is None:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _env(*parts):
    name = "_".join(["ODOO_DEVGUARD", *parts]).upper()
    value = os.environ.get(name)
    return value if value is not None and value.strip() != "" else None


class Settings:
    """Lazily-resolved view of the guard configuration."""

    __slots__ = ()

    @property
    def enabled(self):
        return _as_bool(_env("enabled") or BAKED.get("enabled"), DEFAULTS["enabled"])

    @property
    def disabled_guards(self):
        """Guards switched off for this process by ``ODOO_DEVGUARD_DISABLE``."""
        return {name.lower() for name in _as_list(_env("disable"))}

    def guard_enabled(self, guard):
        if not self.enabled or guard in self.disabled_guards:
            return False
        return _as_bool(self.get(guard, "enable"), True)

    def get(self, guard, key):
        """Resolve one setting: env, then baked, then default."""
        value = _env(guard, key)
        if value is None:
            value = BAKED.get("guards", {}).get(guard, {}).get(key)
        if value is None:
            value = DEFAULTS["guards"].get(guard, {}).get(key)
        return value

    def flag(self, guard, key, fallback=True):
        return _as_bool(self.get(guard, key), fallback)

    def number(self, guard, key, fallback=0):
        return _as_int(self.get(guard, key), fallback)

    def text(self, guard, key, fallback=""):
        value = self.get(guard, key)
        return fallback if value is None else str(value)

    def items(self, guard, key):
        return _as_list(self.get(guard, key))

    # -- mail, which has enough settings to deserve named accessors ---------

    @property
    def mail_host(self):
        return self.text("mail", "host", "127.0.0.1")

    @property
    def mail_port(self):
        return self.number("mail", "port", 1025)

    @property
    def mail_http_port(self):
        return self.number("mail", "http_port", 8025)

    @property
    def pop3_enabled(self):
        return self.flag("mail", "pop3_enabled", False)

    @property
    def pop3_port(self):
        return self.number("mail", "pop3_port", 1110)

    @property
    def pop3_user(self):
        return self.text("mail", "pop3_user", "dev")

    @property
    def pop3_password(self):
        return self.text("mail", "pop3_password", "dev")

    @property
    def block_incoming(self):
        """Incoming mail is blocked unless it has somewhere safe to point."""
        return not self.pop3_enabled


_SETTINGS = Settings()


def settings():
    return _SETTINGS
