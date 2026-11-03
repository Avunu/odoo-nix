"""odoo-nix's own generated blocks in the config files (``tests/shapes/pyproject``, copied
byte for byte from odoo-ruckus's ``pyproject.toml`` and edi-addons' ``nix/pyproject.toml``)
are foreign to the standards (DESIGN.md §2.1 Markers, core §5.6.1): their names have
spaces (``install set (managed from modules.txt)``, ``module sources (managed)``, ``sdist
build deps (managed)``), so no owned marker matches them, and sync keeps all three byte for
byte, through ``--standards`` (which adds the table) and every later run.
"""

from __future__ import annotations

import re
import unittest

from odoo_nix_tools.product import PRODUCT
from standards_core.scaffold import blocks
from support import ADDONS_PRODUCT, SHAPES, SyncCase, git, need_root

# shape → (fixture, config file, product)
CASES = {
    "ruckus.toml": ("standards-project", "pyproject.toml", PRODUCT),
    "edi-addons-nix.toml": ("standards-addons", "nix/pyproject.toml", ADDONS_PRODUCT),
}
NAMES = ("install set", "module sources", "sdist build deps")
REGION = re.compile(
    r"^[ \t]*# >>> odoo-nix: (?P<name>[a-z ]+?) \(managed.*?\) >>>$.*?"
    r"^[ \t]*# <<< odoo-nix: (?P=name)(?: \(managed\))? <<<$",
    re.MULTILINE | re.DOTALL,
)
TABLE = '\n[tool.odoo-nix]\nschema = 1\nprofile = "recommended"\n'


def regions(text: str) -> dict[str, str]:
    """Each odoo-nix block of a config file, markers included, by name."""
    return {m["name"]: m[0] for m in REGION.finditer(text)}


def shape(name: str) -> str:
    return (SHAPES / "pyproject" / name).read_text()


class Scan(unittest.TestCase):
    def test_all_foreign(self) -> None:
        for name in CASES:
            with self.subTest(shape=name):
                text = shape(name)
                self.assertEqual(sorted(regions(text)), sorted(NAMES))
                found = blocks.scan(
                    text, PRODUCT, "#", path=name, owned=("inputs", "dev-shell")
                )
                self.assertEqual(len(found), 3)
                self.assertTrue(all(f.foreign and f.closed for f in found))


class ThroughSync(SyncCase):
    def test_kept_byte_for_byte(self) -> None:
        need_root(self)
        for name, (fixture, config, product) in CASES.items():
            for profile in ("recommended", "example-org"):
                with self.subTest(shape=name, profile=profile):
                    ref = (
                        "recommended"
                        if profile == "recommended"
                        else "./.standards-profile"
                    )
                    text = shape(name) + TABLE.replace('"recommended"', f'"{ref}"')
                    root = self.profile_fixture(fixture, profile, {config: text})
                    code, out = self.write(root, product=product, ok=False)
                    self.assertIn(code, (0, 1), out)
                    self.assertEqual((root / config).read_text(), text)
                    self.commit(root)
                    self.write(root, product=product, ok=False)
                    self.assertEqual((root / config).read_text(), text)

    def test_standards_adds_the_table_after_them(self) -> None:
        need_root(self)
        for name, (fixture, config, product) in CASES.items():
            with self.subTest(shape=name):
                text = shape(name)
                root = self.fixture(fixture, {config: text})
                code, out = self.sync(
                    root,
                    "--write",
                    "--offline",
                    "--standards",
                    "recommended",
                    product=product,
                    ok=False,
                )
                self.assertIn(code, (0, 1), out)
                after = (root / config).read_text()
                self.assertTrue(after.startswith(text), after[len(text) - 200 :])
                self.assertIn("[tool.odoo-nix]", after[len(text) :])
                self.assertEqual(regions(after), regions(text))
                # Staged, as sync stages what it writes.
                self.assertIn(config, git(root, "diff", "--cached", "--name-only"))


if __name__ == "__main__":
    unittest.main()
