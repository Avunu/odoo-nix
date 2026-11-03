"""PRODUCT builds against the core's contract (DESIGN.md §7.2 test_product).

Stage O1 asserts the build only: the core's ``Product.__post_init__`` refuses a product that
breaks a §3.2 rule at import, so importing ``PRODUCT`` is the main assertion. The static
conformance check (modules schema, profiles, manifest) needs the data stage O3 adds.
"""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from odoo_nix_tools import __version__
from odoo_nix_tools.product import LINT_MODULES, MODULES, PRODUCT
from standards_core.product import Product
from standards_core.scaffold.context import NS, Checkout

PACKAGE = Path(__file__).resolve().parent.parent


class ProductBuilds(unittest.TestCase):
    def test_is_a_product_with_no_problems(self) -> None:
        self.assertIsInstance(PRODUCT, Product)
        self.assertEqual(PRODUCT._problems(), [])

    def test_identity(self) -> None:
        ident = PRODUCT.identity
        self.assertEqual(ident.name, "odoo-nix")
        self.assertEqual(ident.cli, "odoo-nix")
        self.assertEqual(ident.distribution, "odoo-nix-tools")
        self.assertEqual(ident.version, __version__)
        self.assertEqual(ident.table, "odoo-nix")
        self.assertEqual(ident.env_prefix, "ODOO_NIX")
        self.assertEqual(ident.report_key, "odoo_nix")
        self.assertEqual(ident.sync_command, "odoo-init --sync")
        self.assertEqual(ident.config_file, "pyproject.toml")
        self.assertFalse(ident.config_required)
        self.assertEqual(ident.requires_key, "requires-odoo-nix")
        self.assertIn("nix/pyproject.toml", ident.opt_in_hint)
        self.assertIn(ident.docs_url, ident.description)

    def test_markers(self) -> None:
        m = PRODUCT.markers
        self.assertEqual(
            m.block_begin.format(name="inputs"), ">>> odoo-nix: inputs (managed) >>>"
        )
        self.assertEqual(
            m.block_end.format(name="inputs"), "<<< odoo-nix: inputs (managed) <<<"
        )
        self.assertEqual(
            m.html_begin.format(name="badges"), "<!-- odoo-nix:begin badges -->"
        )
        self.assertEqual(
            m.html_end.format(name="badges"), "<!-- odoo-nix:end badges -->"
        )
        self.assertTrue(m.header.startswith(m.managed))
        self.assertIn(m.local, m.header_local)

    def test_existing_odoo_nix_blocks_are_foreign(self) -> None:
        # Owned block names are kebab-case without spaces (core §5.6.1); the blocks odoo-nix
        # already writes (lib/oca_sources.py, templates/addons/nix/pyproject.toml) have a space
        # in their name, so they never parse as owned.
        owned = re.compile(
            re.escape(PRODUCT.markers.block_begin).replace(
                re.escape("{name}"), r"([a-z0-9-]+)"
            )
        )
        for foreign in (
            ">>> odoo-nix: install set (managed from modules.txt) >>>",
            ">>> odoo-nix: module sources (managed) >>>",
            ">>> odoo-nix: sdist build deps (managed) >>>",
        ):
            self.assertIsNone(owned.fullmatch(foreign), foreign)
        self.assertIsNotNone(owned.fullmatch(">>> odoo-nix: dev-shell (managed) >>>"))

    def test_engine(self) -> None:
        e = PRODUCT.engine
        self.assertEqual(e.flake_input, "odoo-nix")
        self.assertEqual(e.release_branch.format(major=2), "release-2")
        self.assertEqual(e.caller_stem, "odoo-*")
        self.assertEqual(e.init_app, "odoo-init")
        self.assertEqual(e.version_file, "version.txt")
        self.assertEqual(e.base_input, "python-devops-nix")
        self.assertEqual(
            e.install_spec.format(owner="Avunu", repo="odoo-nix", rev="abc123"),
            "odoo-nix-tools @ git+https://github.com/Avunu/odoo-nix@abc123"
            "#subdirectory=py/odoo_nix_tools",
        )

    def test_pins(self) -> None:
        p = PRODUCT.pins
        self.assertEqual(p.dir, ".odoo-nix/pins")
        self.assertEqual(dict(p.engine_pinned), {})
        self.assertEqual(p.lock_paths, ("tools/uv.lock", "package-lock.json"))
        self.assertEqual(p.managed_inputs(NS(profile_input="")), ("odoo-nix",))
        self.assertEqual(
            p.managed_inputs(NS(profile_input="github:Avunu/odoo-standards-profile")),
            ("odoo-nix", "standards-profile"),
        )

    def test_modules(self) -> None:
        mods = PRODUCT.modules
        self.assertEqual(mods.names, MODULES)
        self.assertEqual(mods.required, "dev-shell")
        self.assertLessEqual(set(LINT_MODULES), set(MODULES))
        self.assertEqual(mods.needs["ide"], ("python-lint", "js-xml"))

    def test_data_root_is_the_packaged_data(self) -> None:
        self.assertTrue((Path(PRODUCT.data_root) / "series" / "18.0.json").is_file())
        self.assertEqual(PRODUCT.roots[0], Path(PRODUCT.data_root))

    def test_pending_hooks_name_their_stage(self) -> None:
        with self.assertRaisesRegex(
            NotImplementedError, r"hooks\.discover arrives in stage O3"
        ):
            PRODUCT.hooks.discover(Checkout(Path("."), "x", {}, []), {}, {})

    def test_version_matches_pyproject(self) -> None:
        # The flake's checks.standards-version compares version.txt too; this one runs
        # wherever the package's tests do.
        project = tomllib.loads((PACKAGE / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["version"], __version__)


if __name__ == "__main__":
    unittest.main()
