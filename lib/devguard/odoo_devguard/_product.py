"""odoo-nix's side of the devguard contract (python-devops-nix CONVENTIONS.md,
"The core and the product's package").

``lib.devguard.mkPackage`` (python-devops-nix) merges this tree with the core
(``__init__``, ``_hook``, ``_settings``, ``_patch``, ``guards/egress``,
``guards/mail_stdlib``) into ``odoo_devguard`` and bakes ``_baked.json``. The
core is loaded at interpreter start from ``zzz-odoo-devguard.pth`` inside the
dev and test virtualenvs (and explicitly by the ``odoo`` CLI), that is *below*
Odoo itself. Every interpreter that can import Odoo from that environment is
covered (the server, ``odoo shell``, ``odoo db ...``, an ad-hoc script) without
installing a module into any database or editing any odoo.conf.

A database restored from production carries working production credentials:
SMTP and IMAP logins, S3 keys, API tokens, webhooks, an SFTP backup target.
Neutralization (``neutralize.sql``) covers what Odoo and a few addons remember
to cover; each guard closes one route neutralization does not. The core's
``egress`` and ``mail_stdlib`` hold at the transport level; the guards listed
in ``GUARDS`` patch Odoo and addon APIs so the failure is readable.

``ODOO_DEVGUARD_ENABLED=0`` (everything) or ``ODOO_DEVGUARD_DISABLE=egress,jobs``
(named guards) gives stock behaviour for a single command.

DEVELOPMENT ONLY, by construction: lib/python.nix grafts the package into the
dev and test environments and never into the production one, so
``services.odoo-nix`` and the container image cannot contain it
(checks.odoo-init-<major> asserts it).
"""

#: ``<P>``: the settings variables are ``ODOO_DEVGUARD_*``.
ENV_PREFIX = "ODOO"

#: What a fail-closed ``require`` names: "Odoo's internals have moved ...
#: Update odoo-nix".
FRAMEWORK = "Odoo"
PRODUCT = "odoo-nix"

#: Merged over the core's defaults, key by key. A guard's key here is the name
#: ``ODOO_DEVGUARD_DISABLE`` takes and the Nix option ``devguard.<name>``.
DEFAULTS = {
    "guards": {
        "jobs": {
            # Matched EXACT-STRING against the cron's external id
            # ("<module>.<name>"). Neutralization already deactivates every
            # cron; this is the backstop for one a developer switches back on.
            # A restored database also carries crons for modules that talk to
            # the outside world on every tick. The consumer's additions are
            # jobs.extra_blocked (devguard.jobs.extraBlocked), unioned with
            # these by the core's settings().blocked_jobs.
            "blocked_jobs": [
                "auto_backup.ir_cron_backup_scheduler_0",
                "currency_rate_update.ir_cron_currency_rates_update_every_day",
                "account_statement_import_online.ir_cron_account_pull_online_bank_statements",
                "edi_core_oca.cron_edi_backend_check_output_exchange",
                "mail.ir_cron_mail_gateway_action",
                "mail.ir_cron_module_update_notification",
                "mail.ir_cron_web_push_notification",
            ],
        },
        # fs.storage: only local protocols may be opened.
        "objectstore": {
            "enable": True,
            "local_protocols": ["file", "odoofs", "memory"],
        },
        "backups": {"enable": True},
        "webhooks": {"enable": True},
        "iap": {"enable": True},
    },
}

#: Odoo's own guards, under guards/, installed after the core's egress and
#: mail_stdlib. Order matters only for readability: every guard is independent.
GUARDS = ("mail", "jobs", "objectstore", "backups", "webhooks", "iap")


def user_error(guard, message):
    """Raise Odoo's ``UserError``, which the web client shows in its dialog.

    For deliberate user actions (a button, an RPC) where a silent no-op would
    leave someone believing the action happened. The core's
    ``_patch.user_error`` has already logged the refusal. Imported here, at
    call time: guards run before Odoo is importable.
    """
    from odoo.exceptions import UserError

    raise UserError(f"Blocked by odoo-devguard: {message}")
