"""``.ruff.toml`` and the ``.pylintrc*`` files (DESIGN.md §3.1 python-lint and pylint-odoo,
§7.2 test_ruff_toml)."""

from __future__ import annotations

import configparser
import tomllib
import unittest

from odoo_nix_tools import series
from odoo_nix_tools.context import Gen
from support import SyncCase

PARAMS = {
    "extra-select": ["ANN", "B"],
    "ignore": ["E501"],
    "per-file-ignores": {"__init__.py": ["F403"], "tests/*.py": ["S101"]},
    "extend-exclude": ["vendor"],
}
EMPTY = {"extra-select": [], "ignore": [], "per-file-ignores": {}, "extend-exclude": []}


def gen(series_name: str, shape: str, params: dict, cfg: dict | None = None) -> Gen:
    cfg = {"python-lint": params, "addon-manifest": {}, **(cfg or {})}
    data = series.effective(series_name, cfg, {"shape": shape, "addons_root": "custom"})
    return Gen({"series_data": data, "cfg": cfg, "shape": shape})


class RuffToml(unittest.TestCase):
    def test_every_rendering_parses(self) -> None:
        for name in series.known():
            for shape in ("project", "addons"):
                for params in (PARAMS, EMPTY):
                    with self.subTest(
                        series=name, shape=shape, params=bool(params["ignore"])
                    ):
                        doc = tomllib.loads(gen(name, shape, params).ruff_toml())
                        oca = series.load(name)["ruff"]
                        self.assertEqual(doc["target-version"], oca["target-version"])
                        self.assertEqual(doc["lint"]["mccabe"], oca["lint"]["mccabe"])
                        self.assertEqual(doc["lint"]["isort"], oca["lint"]["isort"])
                        self.assertNotIn("extend-exclude", doc["lint"])
                        if shape == "project":
                            self.assertEqual(
                                doc["extend-exclude"][:2], ["odoo", "modules"]
                            )
                        elif params is EMPTY:
                            self.assertNotIn("extend-exclude", doc)

    def test_parameters(self) -> None:
        doc = tomllib.loads(gen("20.0", "addons", PARAMS).ruff_toml())
        self.assertEqual(doc["extend-exclude"], ["vendor"])
        self.assertEqual(
            doc["lint"]["extend-select"], ["B", "C90", "E501", "I", "UP", "ANN"]
        )
        self.assertEqual(doc["lint"]["ignore"], ["E501"])
        self.assertEqual(doc["lint"]["extend-ignore"], ["RUF012"])
        self.assertEqual(
            doc["lint"]["per-file-ignores"]["__init__.py"], ["F401", "I001", "F403"]
        )
        self.assertEqual(doc["lint"]["per-file-ignores"]["tests/*.py"], ["S101"])


class Region(SyncCase):
    def test_region_after_mccabe_needs_a_table(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        path = root / ".ruff.toml"
        text = path.read_text()
        path.write_text(
            text.replace(
                "# odoo-nix:local-begin ruff\n",
                '# odoo-nix:local-begin ruff\n[lint.pydocstyle]\nconvention = "google"\n',
            )
        )
        self.check(root)
        doc = tomllib.loads(path.read_text())
        self.assertEqual(doc["lint"]["pydocstyle"], {"convention": "google"})
        self.assertEqual(doc["lint"]["mccabe"], {"max-complexity": 16})
        path.write_text(
            text.replace(
                "# odoo-nix:local-begin ruff\n",
                "# odoo-nix:local-begin ruff\nline-length = 100\n",
            )
        )
        code, out = self.check(root, ok=False)
        self.assertEqual(code, 2, out)
        self.assertIn("the ruff local region follows [lint.mccabe]", out)


class Pylintrc(unittest.TestCase):
    def read(self, text: str) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        return parser

    def test_both_files_per_series(self) -> None:
        org = {
            "addon-manifest": {"author": "Example Org", "licenses-allowed": ["AGPL-3"]}
        }
        for name in series.known():
            for kind in ("optional", "mandatory"):
                with self.subTest(series=name, kind=kind):
                    parsed = self.read(gen(name, "addons", EMPTY, org).pylintrc(kind))
                    odoolint = parsed["ODOOLINT"]
                    self.assertEqual(odoolint["valid-odoo-versions"], name)
                    self.assertEqual(odoolint["license-allowed"], "AGPL-3")
                    self.assertEqual(
                        odoolint["manifest-required-authors"], "Example Org"
                    )
                    enable = [
                        m.strip()
                        for m in parsed["MESSAGES CONTROL"]["enable"].split(",")
                    ]
                    self.assertEqual(len(enable), len(set(enable)))  # pylint-dedupe
                    self.assertEqual(parsed["MASTER"]["load-plugins"], "pylint_odoo")

    def test_no_author_no_required_author(self) -> None:
        text = gen("18.0", "addons", EMPTY).pylintrc("mandatory")
        parsed = self.read(text)
        self.assertNotIn("manifest-required-authors", parsed["ODOOLINT"])
        self.assertNotIn(
            "manifest-required-author,", parsed["MESSAGES CONTROL"]["enable"]
        )
        # OCA's licenses when none is set.
        self.assertIn("LGPL-3", parsed["ODOOLINT"]["license-allowed"])
        self.assertNotIn("@@", text)


if __name__ == "__main__":
    unittest.main()
