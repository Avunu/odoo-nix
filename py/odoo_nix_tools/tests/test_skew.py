"""Version skew on an odoo-nix checkout (the core's rows, DESIGN.md §2.1 ``Engine``,
§5.5 ``--expect-rev``): the caller workflows sync renders name the locked odoo-nix and
this version, so a synced checkout is clean without ``ODOO_NIX_ALLOW_SKEW``; another
``--expect-rev`` (odoo-init passes it on) or a caller moved by hand is exit 3.

The fixture's flake.lock pins the fake rev ``a…a`` and no python-devops-nix under
odoo-nix, so the core's own row is skipped (as it is for an editable core).
"""

from __future__ import annotations

import os
import unittest

from support import SyncCase, git

PROJECT = "standards-project"
REV = "a" * 40
OTHER = "b" * 40


class Skew(SyncCase):
    def synced(self):
        root = self.profile_fixture(PROJECT, "recommended")
        self.write(root)
        self.commit(root)
        os.environ.pop("ODOO_NIX_ALLOW_SKEW")
        return root

    def test_synced_callers_name_the_lock(self) -> None:
        root = self.synced()
        ci = (root / ".github/workflows/ci.yml").read_text()
        self.assertIn(f"avunu/odoo-nix/.github/workflows/odoo-lint.yml@{REV}", ci)
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 0, text)
        code, text = self.sync(root, "--check", "--expect-rev", REV, ok=False)
        self.assertEqual(code, 0, text)

    def test_expect_rev(self) -> None:
        root = self.synced()
        code, text = self.sync(root, "--check", "--expect-rev", OTHER, ok=False)
        self.assertEqual(code, 3, text)
        self.assertIn("version skew", text)
        self.assertIn(OTHER, text)

    def test_a_caller_moved_by_hand(self) -> None:
        root = self.synced()
        ci = root / ".github/workflows/ci.yml"
        ci.write_text(ci.read_text().replace(REV, OTHER))
        git(root, "commit", "-qam", "move a caller")
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 3, text)
        self.assertIn(".github/workflows/ci.yml", text)
        self.assertIn("version skew", text)
        os.environ["ODOO_NIX_ALLOW_SKEW"] = "1"
        code, text = self.check(root, ok=False)
        self.assertNotEqual(code, 3, text)


if __name__ == "__main__":
    unittest.main()
