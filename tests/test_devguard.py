"""odoo-nix's side of odoo_devguard, without Odoo or a network.

The core (the post-import hook, settings precedence, egress, the mail
transport) is python-devops-nix's, and so are its tests (checks.devguard-core).
What is odoo-nix's is tested here: ``_product.py`` (the names, the defaults,
the user error) and the Odoo-facing guards, against stand-in modules registered
in ``sys.modules`` under the names the guards hook (the post-import hook fires
at once for a module that is already imported, which is the same code path as
a real import).

Run: python3 -I tests/test_devguard.py <dir holding odoo_devguard, as
lib/devguard.nix builds it>   (checks.devguard)

Everything here patches process-global state, so the guards are installed
once at import time and each test switches them with ``ODOO_DEVGUARD_*``
environment variables, which is also how a developer bypasses them for a
single command.
"""

import contextlib
import io
import os
import socket
import sys
import types
import unittest
import unittest.mock

LIB = os.path.abspath(sys.argv.pop(1))
sys.path.insert(0, LIB)

# Keep a developer's own devguard settings out of the run.
for key in [k for k in os.environ if k.startswith("ODOO_DEVGUARD_")]:
    del os.environ[key]

import odoo_devguard
from odoo_devguard import (
    DevGuardBlocked,
    DevGuardPatchError,
    _product,
    _settings,
    settings,
)
from odoo_devguard.guards import jobs


def env(**kw):
    """Patch ODOO_DEVGUARD_* for one test. env(EGRESS_ALLOW_HOSTS="a,b")."""
    return unittest.mock.patch.dict(
        os.environ, {f"ODOO_DEVGUARD_{k}": str(v) for k, v in kw.items()}
    )


def fake_module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


class Recs(list):
    """The slice of an Odoo recordset the guards use."""

    def filtered(self, fn):
        return Recs(r for r in self if fn(r))

    def __sub__(self, other):
        return Recs(r for r in self if r not in other)


# --------------------------------------------------------------------------
# Fake Odoo modules, installed before the guards so the hooks fire straight away
# --------------------------------------------------------------------------


class FakeUserError(Exception):
    pass


fake_module("odoo")
fake_module("odoo.exceptions", UserError=FakeUserError)

CALLS = []


class ir_cron:  # 18.0 spells the class in lower case
    def __init__(self, id, xmlid):
        self.id, self._xmlid = id, xmlid

    def get_external_id(self):
        return {self.id: self._xmlid}

    def _callback(self, cron_name, server_action_id):
        CALLS.append(("cron", self._xmlid))
        return "ran"


fake_module("odoo.addons.base.models.ir_cron", ir_cron=ir_cron)


class FSStorage:
    def __init__(self, code, protocol, options="{}"):
        self.code, self.protocol, self.options = code, protocol, options

    def _get_filesystem(self):
        return f"fs:{self.protocol}"


fake_module("odoo.addons.fs_storage.models.fs_storage", FSStorage=FSStorage)


class Backup:
    def __init__(self, name, method):
        self.name, self.method = name, method


class DbBackup:
    def action_backup(self):
        CALLS.append(("backup", [r.name for r in self]))
        return "backed up"

    def cleanup(self):
        CALLS.append(("cleanup", [r.name for r in self]))


fake_module("odoo.addons.auto_backup.models.db_backup", DbBackup=DbBackup)


class IrActionsServer:
    id, name = 7, "Notify"

    def _run_action_webhook(self, eval_context=None):
        CALLS.append(("webhook",))
        return "sent"


fake_module("odoo.addons.base.models.ir_actions", IrActionsServer=IrActionsServer)


def iap_jsonrpc(url, method="call", params=None, timeout=15):
    CALLS.append(("iap", url))
    return {"ok": True}


fake_module("odoo.addons.iap.tools.iap_tools", iap_jsonrpc=iap_jsonrpc)


class SMTPConnection:
    pass


class IrMailServer:
    def _connect__(
        self,
        host=None,
        port=None,
        user=None,
        password=None,
        encryption=None,
        smtp_from=None,
        ssl_certificate=None,
        ssl_private_key=None,
        smtp_debug=False,
        mail_server_id=None,
        allow_archived=False,
    ):
        CALLS.append(
            ("connect", host, port, user, password, encryption, mail_server_id)
        )
        conn = types.SimpleNamespace(from_filter="smtp.corp")
        return conn

    def _find_mail_server(self, email_from, mail_servers=None):
        return "SERVER-RECORD", "notifications@corp"

    def send_email(
        self, message, mail_server_id=None, smtp_server=None, smtp_session=None
    ):
        CALLS.append(("send", mail_server_id, smtp_session))


fake_module(
    "odoo.addons.base.models.ir_mail_server",
    IrMailServer=IrMailServer,
    SMTPConnection=SMTPConnection,
)

# Install every guard exactly as the .pth bootstrap would.
odoo_devguard.install()


def reset_calls():
    CALLS.clear()


# --------------------------------------------------------------------------
# _product.py: what the core reads from odoo-nix
# --------------------------------------------------------------------------


class ProductTest(unittest.TestCase):
    def test_names(self):
        # The log prefix, the .pth bootstrap and the variables keep the names
        # they had before the core moved to python-devops-nix.
        self.assertEqual(_settings.PACKAGE, "odoo_devguard")
        self.assertEqual(_settings.env_name("mail", "port"), "ODOO_DEVGUARD_MAIL_PORT")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            from odoo_devguard import _patch

            _patch.warn("crons", "probe")
        self.assertEqual(err.getvalue(), "WARNING odoo_devguard[crons] probe\n")

    def test_every_guard_is_installed(self):
        names = [
            guard.__name__.rpartition(".")[2] for guard in odoo_devguard.all_guards()
        ]
        self.assertEqual(
            names,
            [
                "egress",
                "mail_stdlib",
                "mail",
                "jobs",
                "objectstore",
                "backups",
                "webhooks",
                "iap",
            ],
        )

    def test_defaults(self):
        st = settings()
        for guard in (
            "egress",
            "mail",
            "jobs",
            "objectstore",
            "backups",
            "webhooks",
            "iap",
        ):
            self.assertTrue(st.guard_enabled(guard), guard)
        self.assertEqual(st.mail_port, 1025)
        self.assertEqual(
            st.items("objectstore", "local_protocols"), ["file", "odoofs", "memory"]
        )
        self.assertEqual(
            st.blocked_jobs, _product.DEFAULTS["guards"]["jobs"]["blocked_jobs"]
        )

    def test_moved_internals_name_odoo_and_odoo_nix(self):
        from odoo_devguard import _patch

        with self.assertRaises(DevGuardPatchError) as ctx:
            _patch.require(types.SimpleNamespace(__name__="x"), "gone")
        self.assertIn("Odoo's internals have moved", str(ctx.exception))
        self.assertIn("Update odoo-nix", str(ctx.exception))
        self.assertIn("ODOO_DEVGUARD_ENABLED=0", str(ctx.exception))

    def test_guard_on_a_moved_module_fails_the_import(self):
        # The post-import callback raises, so the import itself does.
        fake_module("odoo.addons.base.models.ir_actions_probe")
        from odoo_devguard.guards import webhooks

        with self.assertRaises(DevGuardPatchError):
            webhooks._patch(sys.modules["odoo.addons.base.models.ir_actions_probe"])

    def test_egress_still_holds(self):
        # One refusal, so a broken merge of the core cannot pass unnoticed.
        with socket.socket() as s, self.assertRaises(DevGuardBlocked) as ctx:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: nothing is ever there
        self.assertTrue(
            str(ctx.exception).startswith("odoo_devguard[egress]: "), ctx.exception
        )


# --------------------------------------------------------------------------
# Odoo-facing guards, against the stand-in modules above
# --------------------------------------------------------------------------


class JobGuardTest(unittest.TestCase):
    def setUp(self):
        reset_calls()

    def test_denylisted_cron_is_skipped_and_others_run(self):
        self.assertIsNone(
            ir_cron(1, "auto_backup.ir_cron_backup_scheduler_0")._callback("backup", 3)
        )
        self.assertEqual(CALLS, [])
        self.assertEqual(
            ir_cron(2, "mail.ir_cron_mail_scheduler_action")._callback("mail", 4), "ran"
        )
        self.assertEqual(CALLS, [("cron", "mail.ir_cron_mail_scheduler_action")])

    def test_match_is_exact_not_substring(self):
        self.assertEqual(
            ir_cron(3, "auto_backup.ir_cron_backup_scheduler_0_local")._callback(
                "x", 1
            ),
            "ran",
        )

    def test_extra_and_disable(self):
        with env(JOBS_EXTRA_BLOCKED="my_mod.sync"):
            self.assertIsNone(ir_cron(4, "my_mod.sync")._callback("sync", 1))
        for switch in ({"DISABLE": "jobs"}, {"JOBS_ENABLE": 0}):
            with env(**switch):
                self.assertEqual(
                    ir_cron(1, "auto_backup.ir_cron_backup_scheduler_0")._callback(
                        "b", 1
                    ),
                    "ran",
                )

    def test_log_lines_say_crons(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ir_cron(5, "auto_backup.ir_cron_backup_scheduler_0")._callback("backup", 3)
        self.assertIn(
            "WARNING odoo_devguard[crons] skipping cron auto_backup.ir_cron_backup_scheduler_0",
            err.getvalue(),
        )

    def test_old_variables_are_read_as_the_new_ones(self):
        environ = {
            "ODOO_DEVGUARD_CRONS_EXTRA_BLOCKED_CRONS": "old.sync",
            "ODOO_DEVGUARD_CRONS_ENABLE": "0",
        }
        _product._WARNED_ENV.clear()  # a fresh process
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _product.alias_old_env(environ)
            _product.alias_old_env(environ)  # warned once only
        self.assertEqual(environ["ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED"], "old.sync")
        self.assertEqual(environ["ODOO_DEVGUARD_JOBS_ENABLE"], "0")
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertIn(
            "WARNING odoo_devguard[crons] ODOO_DEVGUARD_CRONS_EXTRA_BLOCKED_CRONS is "
            "deprecated; use ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED",
            err.getvalue(),
        )
        # ...and the guard honours the result.
        with unittest.mock.patch.dict(os.environ, environ):
            self.assertFalse(jobs.enabled())
        with unittest.mock.patch.dict(
            os.environ, {"ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED": "old.sync"}
        ):
            self.assertIsNone(ir_cron(6, "old.sync")._callback("sync", 1))

    def test_a_new_variable_wins_over_the_old(self):
        environ = {
            "ODOO_DEVGUARD_CRONS_EXTRA_BLOCKED_CRONS": "old.sync",
            "ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED": "new.sync",
        }
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            _product._WARNED_ENV.clear()  # a fresh process
            _product.alias_old_env(environ)
        self.assertEqual(environ["ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED"], "new.sync")
        self.assertIn(
            "use ODOO_DEVGUARD_JOBS_EXTRA_BLOCKED (ignored: it is set too)",
            err.getvalue(),
        )

    def test_the_old_name_still_disables_with_a_warning(self):
        err = io.StringIO()
        with env(DISABLE="crons"), contextlib.redirect_stderr(err):
            self.assertEqual(
                ir_cron(1, "auto_backup.ir_cron_backup_scheduler_0")._callback("b", 1),
                "ran",
            )
            self.assertFalse(jobs.enabled())
        self.assertIn(
            "ODOO_DEVGUARD_DISABLE=crons is deprecated; use ODOO_DEVGUARD_DISABLE=jobs",
            err.getvalue(),
        )


class ObjectstoreGuardTest(unittest.TestCase):
    def test_remote_protocols_cannot_be_opened(self):
        for protocol in ("s3", "sftp", "gcs", "odoo_remote"):
            with self.assertRaises(DevGuardBlocked) as ctx:
                FSStorage("prod_att", protocol)._get_filesystem()
            self.assertIn("prod_att", str(ctx.exception))
            self.assertIn(protocol, str(ctx.exception))

    def test_local_protocols_pass(self):
        for protocol in ("file", "odoofs", "memory"):
            self.assertEqual(
                FSStorage("a", protocol)._get_filesystem(), f"fs:{protocol}"
            )

    def test_rooted_dir_is_judged_by_what_it_wraps(self):
        with self.assertRaises(DevGuardBlocked):
            FSStorage("a", "rooted_dir", '{"target_protocol": "s3"}')._get_filesystem()
        self.assertEqual(
            FSStorage(
                "a", "rooted_dir", '{"target_protocol": "file"}'
            )._get_filesystem(),
            "fs:rooted_dir",
        )
        self.assertEqual(
            FSStorage("a", "rooted_dir", "{}")._get_filesystem(), "fs:rooted_dir"
        )

    def test_disable(self):
        with env(DISABLE="objectstore"):
            self.assertEqual(FSStorage("a", "s3")._get_filesystem(), "fs:s3")


class BackupGuardTest(unittest.TestCase):
    def setUp(self):
        reset_calls()

    def _recs(self):
        class R(Recs):
            action_backup = DbBackup.action_backup
            cleanup = DbBackup.cleanup

        return R(
            [
                Backup("local@dev", "local"),
                Backup("sftp://prod", "sftp"),
                Backup("prod_bucket", "fs_storage"),
            ]
        )

    def test_only_local_jobs_run(self):
        self.assertEqual(self._recs().action_backup(), "backed up")
        self.assertEqual(CALLS, [("backup", ["local@dev"])])

    def test_remote_only_is_a_clean_no_op(self):
        class R(Recs):
            action_backup = DbBackup.action_backup
            cleanup = DbBackup.cleanup

        recs = R([Backup("sftp://prod", "sftp")])
        self.assertIsNone(recs.cleanup())
        self.assertEqual(CALLS, [])

    def test_retention_never_reaches_a_remote_destination(self):
        self._recs().cleanup()
        self.assertEqual(CALLS, [("cleanup", ["local@dev"])])

    def test_disable(self):
        with env(DISABLE="backups"):
            self._recs().action_backup()
        self.assertEqual(len(CALLS[0][1]), 3)


class WebhookAndIapGuardTest(unittest.TestCase):
    def setUp(self):
        reset_calls()

    def test_webhook_is_skipped_quietly(self):
        self.assertIsNone(IrActionsServer()._run_action_webhook())
        self.assertEqual(CALLS, [])
        with env(DISABLE="webhooks"):
            self.assertEqual(IrActionsServer()._run_action_webhook(), "sent")

    def test_iap_raises_a_user_error(self):
        mod = sys.modules["odoo.addons.iap.tools.iap_tools"]
        with self.assertRaises(FakeUserError) as ctx:
            mod.iap_jsonrpc("https://iap.odoo.com/x")
        self.assertIn("odoo-devguard", str(ctx.exception))
        self.assertEqual(CALLS, [])
        with env(DISABLE="iap"):
            self.assertEqual(mod.iap_jsonrpc("https://iap.odoo.com/x"), {"ok": True})


class MailOdooLayerTest(unittest.TestCase):
    def setUp(self):
        reset_calls()

    def test_connect_is_forced_to_the_catcher(self):
        with env(MAIL_PORT=2525):
            conn = IrMailServer()._connect__(
                host="smtp.corp",
                port=587,
                user="u",
                password="p",
                encryption="starttls",
                mail_server_id=9,
            )
        self.assertEqual(
            CALLS, [("connect", "127.0.0.1", 2525, False, False, "none", None)]
        )
        self.assertFalse(conn.from_filter)

    def test_server_choice_and_sender_are_left_alone(self):
        self.assertEqual(IrMailServer()._find_mail_server("a@b.c"), (None, "a@b.c"))

    def test_api_transport_session_is_discarded(self):
        IrMailServer().send_email("msg", mail_server_id=5, smtp_session=object())
        self.assertEqual(CALLS, [("send", None, None)])
        reset_calls()
        smtp = SMTPConnection()
        IrMailServer().send_email("msg", mail_server_id=5, smtp_session=smtp)
        self.assertEqual(CALLS, [("send", 5, smtp)])

    def test_disable_restores_stock_behaviour(self):
        with env(DISABLE="mail"):
            self.assertEqual(
                IrMailServer()._find_mail_server("a@b.c"),
                ("SERVER-RECORD", "notifications@corp"),
            )
            IrMailServer()._connect__(host="smtp.corp", port=587)
        self.assertEqual(CALLS[0][:3], ("connect", "smtp.corp", 587))


class StatusTest(unittest.TestCase):
    def test_reports_what_was_patched(self):
        st = odoo_devguard.status()
        for target in (
            "socket.socket.connect",
            "socket.getaddrinfo",
            "ir_cron._callback",
            "FSStorage._get_filesystem",
        ):
            self.assertEqual(st.get(target), "patched", target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
