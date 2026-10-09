"""lib/devguard/odoo_devguard without Odoo or a network.

The transport guards (egress, mail_stdlib) run against real sockets on
loopback; the Odoo-facing guards run against stand-in modules registered in
``sys.modules`` under the names the guards hook (the post-import hook fires at
once for a module that is already imported, which is the same code path as a
real import).

Run: python3 tests/test_devguard.py <path to lib/devguard>   (checks.devguard)

Everything here patches process-global state (socket, smtplib, ...), so the
guards are installed once at import time and each test switches them with
``ODOO_DEVGUARD_*`` environment variables, which is also how a developer
bypasses them for a single command.
"""
import asyncio
import importlib
import os
import smtplib
import socket
import socketserver
import sys
import tempfile
import threading
import types
import unittest
import unittest.mock
import urllib.error
import urllib.request

LIB = os.path.abspath(sys.argv.pop(1)) if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "lib", "devguard")
sys.path.insert(0, LIB)

# Keep a developer's own devguard settings out of the run.
for key in [k for k in os.environ if k.startswith("ODOO_DEVGUARD_")]:
    del os.environ[key]

import odoo_devguard
from odoo_devguard import DevGuardBlocked, DevGuardPatchError, settings
from odoo_devguard import _hook, _settings
from odoo_devguard.guards import egress

BLOCKED = ("192.0.2.1", 9)  # TEST-NET-1: nothing is ever there


def env(**kw):
    """Patch ODOO_DEVGUARD_* for one test. env(EGRESS_ALLOW_HOSTS="a,b")."""
    return unittest.mock.patch.dict(os.environ, {f"ODOO_DEVGUARD_{k}": str(v) for k, v in kw.items()})


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


class LoopbackServer:
    def __enter__(self):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        return self

    def __exit__(self, *exc):
        self.srv.close()


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
    def _connect__(self, host=None, port=None, user=None, password=None, encryption=None,
                   smtp_from=None, ssl_certificate=None, ssl_private_key=None,
                   smtp_debug=False, mail_server_id=None, allow_archived=False):
        CALLS.append(("connect", host, port, user, password, encryption, mail_server_id))
        conn = types.SimpleNamespace(from_filter="smtp.corp")
        return conn

    def _find_mail_server(self, email_from, mail_servers=None):
        return "SERVER-RECORD", "notifications@corp"

    def send_email(self, message, mail_server_id=None, smtp_server=None, smtp_session=None):
        CALLS.append(("send", mail_server_id, smtp_session))


fake_module("odoo.addons.base.models.ir_mail_server", IrMailServer=IrMailServer, SMTPConnection=SMTPConnection)

# Install every guard exactly as the .pth bootstrap would.
odoo_devguard.install()


def reset_calls():
    CALLS.clear()


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------


class SettingsTest(unittest.TestCase):
    def test_defaults_then_baked_then_env(self):
        st = settings()
        self.assertEqual(st.mail_port, 1025)
        with unittest.mock.patch.dict(_settings.BAKED, {"guards": {"mail": {"port": 2525}}}):
            self.assertEqual(st.mail_port, 2525)
            with env(MAIL_PORT=3535):
                self.assertEqual(st.mail_port, 3535)
        self.assertEqual(st.mail_port, 1025)

    def test_master_switch_and_named_disable(self):
        st = settings()
        self.assertTrue(st.guard_enabled("egress"))
        with env(ENABLED=0):
            self.assertFalse(st.guard_enabled("egress"))
        with env(DISABLE="egress, crons"):
            self.assertFalse(st.guard_enabled("egress"))
            self.assertFalse(st.guard_enabled("crons"))
            self.assertTrue(st.guard_enabled("mail"))
        with env(CRONS_ENABLE=0):
            self.assertFalse(st.guard_enabled("crons"))

    def test_lists_split_on_commas(self):
        with env(EGRESS_ALLOW_HOSTS="a.example, 10.0.0.0/8 ,"):
            self.assertEqual(settings().items("egress", "allow_hosts"), ["a.example", "10.0.0.0/8"])


# --------------------------------------------------------------------------
# hook + fail-closed
# --------------------------------------------------------------------------


class HookTest(unittest.TestCase):
    def test_fires_for_module_imported_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "devguard_probe_mod.py"), "w") as f:
                f.write("VALUE = 1\n")
            sys.path.insert(0, tmp)
            self.addCleanup(sys.path.remove, tmp)
            seen = []
            _hook.on_import("devguard_probe_mod", lambda m: seen.append(m.VALUE))
            self.assertEqual(seen, [])
            importlib.import_module("devguard_probe_mod")
            self.assertEqual(seen, [1])
            sys.modules.pop("devguard_probe_mod", None)

    def test_fires_at_once_for_module_already_imported(self):
        seen = []
        _hook.on_import("odoo.exceptions", lambda m: seen.append(m))
        self.assertEqual(len(seen), 1)

    def test_missing_target_fails_closed(self):
        from odoo_devguard import _patch
        with self.assertRaises(DevGuardPatchError):
            _patch.require(types.SimpleNamespace(__name__="x"), "gone")
        with self.assertRaises(DevGuardPatchError):
            _patch.require_any(types.SimpleNamespace(__name__="x"), "a", "b")
        self.assertEqual(_patch.require_any(types.SimpleNamespace(b=2), "a", "b"), ("b", 2))

    def test_guard_on_a_moved_module_fails_the_import(self):
        # The post-import callback raises, so the import itself does.
        fake_module("odoo.addons.base.models.ir_actions_probe")
        from odoo_devguard.guards import webhooks
        with self.assertRaises(DevGuardPatchError):
            webhooks._patch(sys.modules["odoo.addons.base.models.ir_actions_probe"])


# --------------------------------------------------------------------------
# egress
# --------------------------------------------------------------------------


class EgressTest(unittest.TestCase):
    def test_loopback_is_allowed_and_works(self):
        with LoopbackServer() as srv:
            c = socket.create_connection(("127.0.0.1", srv.port), timeout=2)
            c.close()
            c = socket.socket()
            self.assertEqual(c.connect_ex(("localhost", srv.port)), 0)
            c.close()

    def test_unix_sockets_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "s")
            srv = socket.socket(socket.AF_UNIX)
            srv.bind(path)
            srv.listen(1)
            c = socket.socket(socket.AF_UNIX)
            c.connect(path)
            c.close()
            srv.close()

    def test_everything_else_is_blocked_before_any_packet(self):
        s = socket.socket()
        with self.assertRaises(DevGuardBlocked) as ctx:
            s.connect(BLOCKED)
        self.assertIsInstance(ctx.exception, OSError)
        self.assertIn("192.0.2.1:9", str(ctx.exception))
        # connect_ex and a repeat (which is quiet but still raises)
        with self.assertRaises(DevGuardBlocked):
            s.connect_ex(BLOCKED)
        with self.assertRaises(DevGuardBlocked):
            socket.create_connection(BLOCKED, timeout=1)
        s.close()

    def test_urllib_and_asyncio_are_covered_too(self):
        with self.assertRaises(urllib.error.URLError) as ctx:
            urllib.request.urlopen("http://192.0.2.1/", timeout=1)
        self.assertIsInstance(ctx.exception.reason, DevGuardBlocked)
        with self.assertRaises(DevGuardBlocked):
            asyncio.run(asyncio.open_connection(*BLOCKED))

    def test_allowlist_matrix(self):
        with env(EGRESS_ALLOW_HOSTS="203.0.113.0/24, api.example.com, *.corp.test, 198.51.100.7"):
            for ok in ("127.0.0.1", "::1", "localhost", "203.0.113.50", "api.example.com",
                       "API.example.com", "a.corp.test", "corp.test", "198.51.100.7"):
                self.assertTrue(egress._allowed(ok), ok)
            for bad in ("192.0.2.1", "203.0.114.1", "example.com", "evilapi.example.com",
                        "corp.test.evil.com", "198.51.100.8"):
                self.assertFalse(egress._allowed(bad), bad)

    def test_a_name_resolving_only_to_loopback_is_allowed(self):
        with unittest.mock.patch.object(egress, "_resolve", return_value=(egress._ip("127.0.0.1"),)):
            self.assertTrue(egress._allowed("alias.internal"))
        with unittest.mock.patch.object(egress, "_resolve", return_value=(egress._ip("192.0.2.1"),)):
            self.assertFalse(egress._allowed("alias.internal"))
        with unittest.mock.patch.object(egress, "_resolve", return_value=()):
            self.assertFalse(egress._allowed("nxdomain.invalid"))

    def test_mail_catcher_host_is_always_allowed(self):
        with env(MAIL_HOST="catcher.lan"):
            self.assertTrue(egress._allowed("catcher.lan"))
        with env(MAIL_HOST="catcher.lan", MAIL_ENABLE=0):
            self.assertFalse(egress._allowed("catcher.lan"))

    def test_can_be_turned_off_for_one_command(self):
        with env(DISABLE="egress"):
            s = socket.socket()
            s.settimeout(0.2)
            try:
                s.connect(BLOCKED)
            except DevGuardBlocked:
                self.fail("guard still active")
            except OSError:
                pass  # the real network said no -- which is the point
            finally:
                s.close()


# --------------------------------------------------------------------------
# mail transport
# --------------------------------------------------------------------------


class StubServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class StubHandler(socketserver.StreamRequestHandler):
    banner = b"220 stub catcher\r\n"

    def handle(self):
        self.wfile.write(self.banner)
        while True:
            line = self.rfile.readline()
            if not line or line.upper().startswith(b"QUIT"):
                self.wfile.write(b"221 bye\r\n")
                return
            if line.upper().startswith((b"EHLO", b"HELO")):
                self.wfile.write(b"250 stub\r\n")
            else:
                self.wfile.write(b"250 ok\r\n")


class MailTransportTest(unittest.TestCase):
    def setUp(self):
        self.srv = StubServer(("127.0.0.1", 0), StubHandler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def test_any_smtp_target_lands_on_the_catcher(self):
        with env(MAIL_PORT=self.port):
            for tls in (False, True):
                smtp = smtplib.SMTP("smtp.gmail.com", 587, timeout=2)
                self.assertEqual(smtp.sock.getpeername()[1], self.port)
                if tls:
                    self.assertEqual(smtp.starttls()[0], 220)
                self.assertEqual(smtp.login("real", "secret")[0], 235)
                smtp.quit()

    def test_ssl_variant_is_not_wrapped(self):
        with env(MAIL_PORT=self.port):
            smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=2)
            self.assertEqual(smtp.sock.getpeername()[1], self.port)
            smtp.quit()

    def test_imap_and_pop_are_blocked_without_a_catcher_mailbox(self):
        import imaplib, poplib
        with self.assertRaises(DevGuardBlocked):
            imaplib.IMAP4("imap.gmail.com")
        with self.assertRaises(DevGuardBlocked):
            poplib.POP3("pop.gmail.com")

    def test_pop3_is_redirected_when_enabled(self):
        import poplib
        with env(MAIL_POP3_ENABLED=1, MAIL_POP3_PORT=self.port):
            StubHandler.banner = b"+OK stub pop3\r\n"
            self.addCleanup(setattr, StubHandler, "banner", b"220 stub catcher\r\n")
            pop = poplib.POP3("pop.gmail.com", 110, timeout=2)
            self.assertEqual(pop.sock.getpeername()[1], self.port)
            pop.sock.close()

    def test_disabled_guard_leaves_smtplib_alone(self):
        with env(DISABLE="mail", MAIL_PORT=self.port):
            # With the mail guard off nothing redirects the connection, so it is
            # left to egress, which names the real destination.
            with self.assertRaises(DevGuardBlocked) as ctx:
                smtplib.SMTP("192.0.2.1", 25, timeout=1)
            self.assertIn("192.0.2.1", str(ctx.exception))


# --------------------------------------------------------------------------
# Odoo-facing guards, against the stand-in modules above
# --------------------------------------------------------------------------


class CronGuardTest(unittest.TestCase):
    def setUp(self):
        reset_calls()

    def test_denylisted_cron_is_skipped_and_others_run(self):
        self.assertIsNone(ir_cron(1, "auto_backup.ir_cron_backup_scheduler_0")._callback("backup", 3))
        self.assertEqual(CALLS, [])
        self.assertEqual(ir_cron(2, "mail.ir_cron_mail_scheduler_action")._callback("mail", 4), "ran")
        self.assertEqual(CALLS, [("cron", "mail.ir_cron_mail_scheduler_action")])

    def test_match_is_exact_not_substring(self):
        self.assertEqual(ir_cron(3, "auto_backup.ir_cron_backup_scheduler_0_local")._callback("x", 1), "ran")

    def test_extra_and_disable(self):
        with env(CRONS_EXTRA_BLOCKED_CRONS="my_mod.sync"):
            self.assertIsNone(ir_cron(4, "my_mod.sync")._callback("sync", 1))
        with env(DISABLE="crons"):
            self.assertEqual(ir_cron(1, "auto_backup.ir_cron_backup_scheduler_0")._callback("b", 1), "ran")


class ObjectstoreGuardTest(unittest.TestCase):
    def test_remote_protocols_cannot_be_opened(self):
        for protocol in ("s3", "sftp", "gcs", "odoo_remote"):
            with self.assertRaises(DevGuardBlocked) as ctx:
                FSStorage("prod_att", protocol)._get_filesystem()
            self.assertIn("prod_att", str(ctx.exception))
            self.assertIn(protocol, str(ctx.exception))

    def test_local_protocols_pass(self):
        for protocol in ("file", "odoofs", "memory"):
            self.assertEqual(FSStorage("a", protocol)._get_filesystem(), f"fs:{protocol}")

    def test_rooted_dir_is_judged_by_what_it_wraps(self):
        with self.assertRaises(DevGuardBlocked):
            FSStorage("a", "rooted_dir", '{"target_protocol": "s3"}')._get_filesystem()
        self.assertEqual(FSStorage("a", "rooted_dir", '{"target_protocol": "file"}')._get_filesystem(), "fs:rooted_dir")
        self.assertEqual(FSStorage("a", "rooted_dir", "{}")._get_filesystem(), "fs:rooted_dir")

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
        return R([Backup("local@dev", "local"), Backup("sftp://prod", "sftp"), Backup("prod_bucket", "fs_storage")])

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
            conn = IrMailServer()._connect__(host="smtp.corp", port=587, user="u", password="p",
                                             encryption="starttls", mail_server_id=9)
        self.assertEqual(CALLS, [("connect", "127.0.0.1", 2525, False, False, "none", None)])
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
            self.assertEqual(IrMailServer()._find_mail_server("a@b.c"), ("SERVER-RECORD", "notifications@corp"))
            IrMailServer()._connect__(host="smtp.corp", port=587)
        self.assertEqual(CALLS[0][:3], ("connect", "smtp.corp", 587))


class StatusTest(unittest.TestCase):
    def test_reports_what_was_patched(self):
        st = odoo_devguard.status()
        for target in ("socket.socket.connect", "ir_cron._callback", "FSStorage._get_filesystem"):
            self.assertEqual(st.get(target), "patched", target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
