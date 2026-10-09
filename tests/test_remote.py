"""lib/odoo_nix_cli/remote.py without Odoo, click or a network: backup
discovery, selection, caching and the fail-safe download, against a directory
laid out like the bucket (<root>/<db>/<YYYY_MM_DD_HH_MM_SS>.dump[.zip]).

Run: python3 tests/test_remote.py <path to lib/>   (checks.remote-store)
"""
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

LIB = os.path.abspath(sys.argv.pop(1)) if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, LIB)

from odoo_nix_cli import remote

NAMES = [
    "2026_10_01_03_00_00.dump",
    "2026_10_02_03_00_00.dump",
    "2026_10_03_03_00_00.dump",
    "2026_10_04_03_00_00.dump.zip",
]


class RemoteStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name, "bucket")
        (self.root / "prod").mkdir(parents=True)
        (self.root / "other").mkdir()
        for name in NAMES:
            (self.root / "prod" / name).write_bytes(name.encode())
        # Not backups: must never be selected.
        for junk in ("notes.txt", "2026_10_05_03_00_00.dump.partial", "latest.dump"):
            (self.root / "prod" / junk).write_text("x")
        self.cache = Path(tmp.name, "cache")
        env = {k: v for k, v in os.environ.items() if not k.startswith("BACKUPS_")}
        env["ODOO_NIX_BACKUP_SOURCE"] = str(self.root)
        patcher = unittest.mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lists_databases_and_only_real_backups(self):
        with remote.store() as base:
            self.assertEqual(remote.list_databases(base), ["other", "prod"])
            self.assertEqual([n for n, _ in remote.list_backups(base, "prod")], NAMES)

    def test_pick_newest_and_at(self):
        with remote.store() as base:
            backups = remote.list_backups(base, "prod")
            self.assertEqual(remote.pick(backups, None)[0], NAMES[-1])
            self.assertEqual(remote.pick(backups, "2026-10-02")[0], NAMES[1])
            self.assertEqual(remote.pick(backups, "2026_10_03_03")[0], NAMES[2])
            with self.assertRaises(remote.RemoteError):
                remote.pick(backups, "2025")
            with self.assertRaises(remote.RemoteError):
                remote.pick([], None)

    def test_fetch_caches_and_keeps_newest_two(self):
        with remote.store() as base:
            first = remote.fetch(base, "prod", self.cache, at="2026_10_01")
            self.assertEqual(first.read_bytes(), NAMES[0].encode())
            for at in ("2026_10_02", "2026_10_03"):
                remote.fetch(base, "prod", self.cache, at=at)
            kept = sorted(p.name for p in (self.cache / "prod").iterdir())
            self.assertEqual(kept, NAMES[1:3])

    def test_fetch_uses_cache_unless_told_not_to(self):
        with remote.store() as base:
            path = remote.fetch(base, "prod", self.cache)
            path.write_bytes(b"x" * len(NAMES[-1]))  # same size, different content
            self.assertEqual(remote.fetch(base, "prod", self.cache), path)
            self.assertEqual(path.read_bytes(), b"x" * len(NAMES[-1]))
            remote.fetch(base, "prod", self.cache, use_cache=False)
            self.assertEqual(path.read_bytes(), NAMES[-1].encode())

    def test_unknown_database_has_no_backups(self):
        with remote.store() as base:
            with self.assertRaises(remote.RemoteError):
                remote.fetch(base, "other", self.cache)

    def test_missing_credentials_are_named(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(remote.has_credentials())
            with self.assertRaises(remote.RemoteError) as ctx:
                with remote.store():
                    pass
            self.assertIn("BACKUPS_BUCKET", str(ctx.exception))
            self.assertIn("setup-backup-access", str(ctx.exception))

    def test_mc_config_is_private_and_removed(self):
        env = {
            "BACKUPS_URL": "https://s3.example.invalid",
            "BACKUPS_ACCESS_KEY": "AK",
            "BACKUPS_SECRET_KEY": "s/e+c",
            "BACKUPS_BUCKET": "b",
            "BACKUPS_PREFIX": "/odoo/",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with remote.store() as base:
                self.assertEqual(base, "odoonix/b/odoo")
                config = Path(os.environ["MC_CONFIG_DIR"], "config.json")
                self.assertEqual(oct(config.stat().st_mode & 0o777), "0o600")
                self.assertIn("s/e+c", config.read_text())
                directory = config.parent
            self.assertFalse(directory.exists())
            self.assertNotIn("MC_CONFIG_DIR", os.environ)


if __name__ == "__main__":
    import unittest.mock  # noqa: F401  (used via the attribute above)

    unittest.main(verbosity=2)
