"""``package.json``'s js-xml group (DESIGN.md §3.1 js-xml, §7.2 test_package_json)."""

from __future__ import annotations

import json
import unittest

from support import SyncCase

PRETTIER_FORM = """{
  "private": true,
  "devDependencies": {
    "@prettier/plugin-xml": "3.4.1",
    "eslint": "9.12.0",
    "eslint-plugin-jsdoc": "50.3.1",
    "globals": "16.0.0",
    "prettier": "3.3.3"
  }
}
"""


class PackageJson(SyncCase):
    def test_created_in_prettier_form(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        self.assertEqual((root / "package.json").read_text(), PRETTIER_FORM)

    def test_a_frontend_keeps_its_own_keys(self) -> None:
        own = {
            "name": "my-frontend",
            "scripts": {"build": "vite build"},
            "devDependencies": {"vite": "^7.0.0", "prettier": "3.3.3"},
            "dependencies": {"lit": "^3.0.0"},
        }
        root = self.profile_fixture(
            "standards-project",
            "recommended",
            {"package.json": json.dumps(own, indent=4) + "\n"},
            locks=False,
        )
        self.write(root, ok=False)
        doc = json.loads((root / "package.json").read_text())
        # A new key goes before the first later key of its order the object has.
        self.assertEqual(
            list(doc), ["name", "scripts", "private", "devDependencies", "dependencies"]
        )
        self.assertEqual(doc["scripts"], own["scripts"])
        self.assertEqual(doc["dependencies"], own["dependencies"])
        self.assertEqual(doc["devDependencies"]["vite"], "^7.0.0")
        self.assertEqual(doc["devDependencies"]["eslint"], "9.12.0")

    def test_pins_reconciled_as_floors(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        path = root / "package.json"
        doc = json.loads(path.read_text())
        doc["devDependencies"]["prettier"] = "3.4.0"
        doc["devDependencies"]["eslint"] = "9.0.0"
        path.write_text(json.dumps(doc, indent=2) + "\n")
        self.write(root, ok=False)
        doc = json.loads(path.read_text())
        self.assertEqual(doc["devDependencies"]["prettier"], "3.4.0")
        self.assertEqual(doc["devDependencies"]["eslint"], "9.12.0")

    def test_layout_is_the_formatters(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        path = root / "package.json"
        path.write_text(json.dumps(json.loads(path.read_text())) + "\n")
        self.check(root)


if __name__ == "__main__":
    unittest.main()
