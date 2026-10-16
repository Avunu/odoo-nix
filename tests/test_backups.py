"""odoo-nix's side of the backup store (lib/odoo_nix_cli/backups.py and
backup_layout.py) without Odoo, click or a network: its layout and names on top
of python-devops-nix's fetch layer, against a directory laid out like the
bucket (<root>/<db>/<YYYY_MM_DD_HH_MM_SS>.dump[.zip]). The base tests the layer
itself (lib.backups.check); this pins what odoo-nix hands it.

Run: python3 -I tests/test_backups.py <dir holding odoo_nix_cli, with _backups.py vendored>
     (checks.backup-layout)
"""

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.abspath(sys.argv.pop(1)))

from odoo_nix_cli.backups import BackupError, backups  # noqa: E402

NAMES = [
    "2026_10_01_03_00_00.dump",
    "2026_10_02_03_00_00.dump",
    "2026_10_03_03_00_00.dump",
    "2026_10_04_03_00_00.dump.zip",
]


class OdooBackupsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name, "bucket")
        (self.root / "prod").mkdir(parents=True)
        (self.root / "other").mkdir()
        for name in NAMES:
            (self.root / "prod" / name).write_bytes(name.encode())
        # Not backups: must never be listed or selected.
        for junk in ("notes.txt", "2026_10_05_03_00_00.dump.partial", "latest.dump", "2026_13_01_00_00_00.dump"):
            (self.root / "prod" / junk).write_text("x")
        (self.root / "prod" / "nested").mkdir()
        (self.root / "prod" / "nested" / "2026_10_06_03_00_00.dump").write_text("x")
        self.cache = Path(tmp.name, "cache")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BACKUPS_", "ODOO_NIX_"))}
        env["ODOO_NIX_BACKUP_SOURCE"] = str(self.root)
        patcher = unittest.mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_names(self):
        self.assertEqual(backups.label, "odoo-nix")
        self.assertEqual(backups.var("BACKUP_SOURCE"), "ODOO_NIX_BACKUP_SOURCE")
        self.assertEqual(backups.var("MC"), "ODOO_NIX_MC")
        self.assertEqual(backups.alias, "odoonix")
        self.assertEqual(backups.roles, ("dump",))

    def test_lists_databases_and_only_real_backups(self):
        with backups.store() as store:
            self.assertEqual(backups.folders(store), ["other", "prod"])
            self.assertEqual([s.name for s in backups.sets(store, "prod")], NAMES)
            self.assertEqual(backups.sets(store, "other"), [])

    def test_at_takes_odoo_names_and_iso_8601(self):
        with backups.store() as store:
            for at, want in (
                (None, NAMES[3]),
                ("2026_10_02", NAMES[1]),
                ("2026_10_03_03", NAMES[2]),
                ("2026-10-02", NAMES[1]),
                ("2026-10-03T03:00", NAMES[2]),
                ("2026-10-01 03:00:00Z", NAMES[0]),
                ("2026-10", NAMES[3]),
                (NAMES[0], NAMES[0]),
            ):
                with self.subTest(at=at):
                    self.assertEqual(backups.fetch(store, "prod", dest=self.cache, at=at, keep=0).backup.name, want)
            with self.assertRaises(BackupError) as ctx:
                backups.fetch(store, "prod", dest=self.cache, at="2001")
            self.assertIn("no backup matches --at 2001", ctx.exception.message)

    def test_fetching_an_older_backup_keeps_it(self):
        # remote.fetch kept the newest KEEP files by name, so fetching an
        # older backup with two newer ones cached deleted the file it had
        # just downloaded and returned its path. The base keeps the one just
        # fetched.
        with backups.store() as store:
            backups.fetch(store, "prod", dest=self.cache)
            backups.fetch(store, "prod", dest=self.cache, at="2026_10_03")
            got = backups.fetch(store, "prod", dest=self.cache, at="2026_10_01").paths["dump"]
            self.assertTrue(got.is_file())
            self.assertEqual(got.read_bytes(), NAMES[0].encode())

    def test_a_database_without_backups_says_what_is_there(self):
        with backups.store() as store:
            with self.assertRaises(BackupError) as ctx:
                backups.fetch(store, "other", dest=self.cache)
        self.assertIn("no backups under", ctx.exception.message)
        self.assertIn("<prefix>/<database>/<YYYY_MM_DD_HH_MM_SS>.dump[.zip]", "\n".join(ctx.exception.details))

    def test_missing_credentials_name_the_way_out(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(backups.has_credentials())
            with self.assertRaises(BackupError) as ctx:
                with backups.store():
                    pass
        text = ctx.exception.render(backups.label)
        self.assertTrue(text.startswith("odoo-nix: "))
        self.assertIn("BACKUPS_BUCKET", text)
        self.assertIn("setup-backup-access", text)
        self.assertIn("ODOO_NIX_BACKUP_SOURCE", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
