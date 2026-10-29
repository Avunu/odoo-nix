"""`odoo ui`: the spec the dev shell writes, lib/odoo_nix_cli/tui.py (the
store's plugin) over a workspace and the real OCA data, the command catalogs
the shell builds, and the TUI itself driven headless (textual's run_test).

Run: python -I tests/test_tui.py <modules> <spec.json>
  <modules>   the TUI's modules (lib.tui.command's passthru.modules)
  <spec.json> the spec the shell wrote (lib.tui.script's passthru.spec)
with the TUI's interpreter (lib.tui.command's passthru.python). The checks'
`tui` builds both from the 19.0 fixture's shell.
"""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

if len(sys.argv) < 3:
    sys.exit("usage: test_tui.py <modules> <spec.json>")
sys.path.insert(0, sys.argv.pop(1))
SPEC = json.loads(Path(sys.argv.pop(1)).read_text())

from devtui import commands, plugin, spec
from devtui.app import DevTui
from devtui.store import StoreView
from odoo_nix_cli.__main__ import tui_argv
from textual.widgets import DataTable, Input

MANIFEST = """{
    "name": "Acme Thing",
    "summary": "A third-party module",
    "version": "19.0.1.0.0",
    "depends": ["base"],
    "license": "LGPL-3",
}
"""


class TuiTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "modules.txt").write_text("web_dark_mode\n")
        # An OCA repository already in the workspace, and a third-party one.
        (self.root / "modules" / "web").mkdir(parents=True)
        thing = self.root / "modules" / "acme-addons" / "acme_thing"
        thing.mkdir(parents=True)
        (thing / "__manifest__.py").write_text(MANIFEST)
        (thing / "README.md").write_text("# Acme\n\nIt does things.\n")
        own = self.root / "custom" / "acme_own"
        own.mkdir(parents=True)
        (own / "__manifest__.py").write_text('{"name": "Our Own", "application": True}')
        self.spec = spec.load(SPEC, {"root": str(self.root)})
        self.product = plugin.load(self.spec)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_spec(self):
        self.assertEqual(self.spec.cli, "odoo")
        self.assertEqual(self.spec.root, str(self.root))
        self.assertEqual(self.spec.site.process, "odoo")
        self.assertIn("19.0", self.spec.banner.title)
        self.assertIn("odoo ui", [c.command for c in self.spec.banner.commands])

    def test_catalog(self):
        c = self.product.catalog()
        items = c.by_id
        self.assertGreater(len(items), 1000)
        self.assertTrue(
            all(i.version.startswith("19.0.") for i in c.items if "local" not in i.tags)
        )
        thing = items["acme_thing"]
        self.assertEqual(
            (thing.title, thing.group, thing.license),
            ("Acme Thing", "acme-addons", "LGPL-3"),
        )
        self.assertEqual(items["acme_own"].group, "custom")
        self.assertIn("application", items["acme_own"].tags)
        self.assertEqual(items["web_dark_mode"].group, "web")
        base = next(b for b in c.bundles if b.id == "base")
        self.assertEqual(base.title, "Base")
        self.assertIn("web_responsive", base.members)
        self.assertEqual(c.bundle_noun, "stack")
        self.assertEqual(self.product.installed(), {"web_dark_mode"})

    def test_closure(self):
        # account_financial_report (account-financial-reporting) depends on
        # date_range (server-ux) and report_xlsx (reporting-engine).
        closure = self.product.closure(["account_financial_report"], [])
        self.assertIn("date_range", closure.brings)
        self.assertIn("report_xlsx", closure.brings)
        repos = next(n for n in closure.notes if "new OCA repositor" in n)
        for repo in ("account-financial-reporting", "server-ux", "reporting-engine"):
            self.assertIn(repo, repos)
        # web is already in the workspace.
        closure = self.product.closure(["web_dark_mode"], [])
        self.assertIn(
            "Every repository needed is already in the workspace.", closure.notes
        )
        closure = self.product.closure([], ["base"])
        self.assertTrue(any(n.startswith("Stacks base:") for n in closure.notes))

    def test_command_lines(self):
        self.assertEqual(
            [s.argv for s in self.product.add(["a", "b"], ["base"])],
            [
                ("odoo", "module", "add-bundle", "base"),
                ("odoo", "module", "add", "a", "b"),
            ],
        )
        self.assertEqual(
            [s.argv for s in self.product.remove(["a"])],
            [("odoo", "module", "remove", "a")],
        )
        self.assertEqual(
            self.product.after_add()[0].argv,
            ("devtui:rebuild", "odoo", "db", "provision"),
        )
        form = self.product.forms()[0]
        self.assertEqual(
            form.build({"url": "acme/addons"}), ["odoo", "module", "add", "acme/addons"]
        )
        self.assertEqual(
            form.build({"url": "acme/addons", "branch": "main"}),
            ["odoo", "module", "add", "acme/addons", "main"],
        )

    def test_local_readme(self):
        item = self.product.catalog().by_id["acme_thing"]
        self.assertIn("It does things.", self.product.detail(item))

    def test_command_catalogs(self):
        roots = [commands.load_file(s.file) for s in self.spec.commands]
        own, odoo_bin = roots
        self.assertEqual((own.name, own.source), ("odoo", "odoo-nix"))
        paths = {c.path for c in own.walk()}
        for path in (
            ("db", "migrate"),
            ("db", "provision"),
            ("module", "add"),
            ("project", "update"),
            ("ui",),
        ):
            self.assertIn(path, paths)
        shell = next(c for c in own.walk() if c.path == ("shell",))
        self.assertTrue(shell.interactive)
        server = next(c for c in odoo_bin.walk() if c.path == ("server",))
        self.assertTrue(server.raw and server.interactive)


class DispatchTest(unittest.TestCase):
    """What `odoo …` hands the TUI (odoo_nix_cli.__main__)."""

    def test_ui(self):
        self.assertEqual(tui_argv(["ui"], tty=False, menu=False), [])
        self.assertEqual(
            tui_argv(["ui", "--only", "store"], tty=False, menu=True),
            ["--only", "store"],
        )

    def test_bare_at_a_terminal(self):
        store = ["--only", "store"]
        self.assertEqual(tui_argv([], tty=True, menu=True), [])
        self.assertEqual(tui_argv(["module", "add"], tty=True, menu=True), store)
        self.assertEqual(tui_argv(["module", "add-bundle"], tty=True, menu=True), store)

    def test_not_the_tuis(self):
        for argv in (["module", "add", "web_dark_mode"], ["module", "add", "--help"]):
            self.assertIsNone(tui_argv(argv, tty=True, menu=True), argv)
        for tty, menu in ((False, True), (True, False)):
            for argv in ([], ["module", "add"], ["module", "add-bundle"]):
                self.assertIsNone(tui_argv(argv, tty=tty, menu=menu), argv)


class AppTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # unittest runs the loop in debug mode, which logs every callback over
        # 0.1s: a textual frame often is one.
        asyncio.get_running_loop().slow_callback_duration = 60

    async def test_store(self):
        root = Path(tempfile.mkdtemp())
        try:
            (root / "modules.txt").write_text("")
            data = {k: v for k, v in SPEC.items() if k != "stack"}
            app = DevTui(data, {"root": str(root)})
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.press("4")
                view = app.query_one(StoreView)
                view.query_one("#store-search", Input).value = "web dark mode"
                table = view.query_one("#store-table", DataTable)
                for _ in range(100):
                    await pilot.pause(0.05)
                    if view.rows and view.rows[0].id == "web_dark_mode":
                        break
                self.assertEqual(view.rows[0].id, "web_dark_mode")
                table.focus()
                await pilot.press("space")
                self.assertEqual(view.adds, ["web_dark_mode"])
        finally:
            shutil.rmtree(root)

    async def test_store_alone(self):
        # The picker a bare `odoo module add` opens (`--only store`).
        root = Path(tempfile.mkdtemp())
        try:
            (root / "modules.txt").write_text("")
            data = {k: v for k, v in SPEC.items() if k != "stack"}
            app = DevTui(data, {"root": str(root)}, only="store")
            async with app.run_test(size=(160, 50)) as pilot:
                self.assertEqual(list(app.query("TabPane")), [])
                table = app.query_one(StoreView).query_one("#store-table", DataTable)
                for _ in range(100):
                    await pilot.pause(0.05)
                    if app.focused is table:
                        break
                self.assertIs(app.focused, table)
                self.assertGreater(table.row_count, 100)
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], "-v"])
