"""``eslint.config.cjs``: the generated configs are not linted (DESIGN.md §3.1 js-xml)."""

from __future__ import annotations

import json
import re
import unittest

from odoo_nix_tools import series
from odoo_nix_tools.context import Gen


def render(series_name: str, exclude: list[str]) -> str:
    cfg = {"js-xml": {"exclude": exclude}, "addon-manifest": {}}
    shape = {"shape": "addons", "addons_root": "."}
    data = series.effective(series_name, cfg, shape)
    return Gen({"series_data": data, "cfg": cfg, "shape": "addons"}).eslint_config()


def ignores(body: str) -> list[str]:
    found = re.search(r"const config = \[\{\n    ignores: (\[.*\]),\n\}, \{", body)
    assert found, body[:200]
    return json.loads(found.group(1))


class EslintConfig(unittest.TestCase):
    def test_generated_configs_are_ignored(self) -> None:
        for name in series.known():
            with self.subTest(series=name):
                self.assertEqual(
                    ignores(render(name, [])), ["eslint.config.cjs", "prettier.config.cjs"]
                )

    def test_exclude_follows_the_generated_configs(self) -> None:
        body = render("18.0", ["static/dist/"])
        self.assertEqual(
            ignores(body),
            ["eslint.config.cjs", "prettier.config.cjs", "static/dist/**"],
        )
        self.assertEqual(body.count("const config = [{"), 1)
