"""The Dependabot decision table (DESIGN.md §2.8) through the core's ``decide``: each row,
no match, and the ``all`` policy (which never lifts a sticky review)."""

from __future__ import annotations

import unittest

from odoo_nix_tools import verdict
from odoo_nix_tools.product import PRODUCT
from standards_core.ci import verdict as core

ENGINE = "Avunu/odoo-nix"


def decide(
    ecosystem: str, names: str = "", policy: str = core.DECISION_TABLE, **kw
) -> str:
    return core.decide(
        PRODUCT,
        ecosystem,
        dependency_names=names,
        engine_repo=ENGINE,
        policy=policy,
        **kw,
    )


class DecisionTable(unittest.TestCase):
    def test_wired_and_valid(self) -> None:
        self.assertIs(PRODUCT.ci.decision_table, verdict.DECISION_TABLE)
        self.assertEqual(core.problems(PRODUCT), [])
        self.assertEqual(len(verdict.DECISION_TABLE), 10)

    def test_rows(self) -> None:
        cases = [
            # 1, 2: the engine's workflows and the core's actions, sticky.
            (("github_actions", "Avunu/odoo-nix"), {}, "review"),
            (
                ("github_actions", "Avunu/odoo-nix/.github/workflows/odoo-lint.yml"),
                {},
                "review",
            ),
            (
                (
                    "github_actions",
                    "Avunu/python-devops-nix/.github/actions/standards-install",
                ),
                {},
                "review",
            ),
            (("github_actions", "Avunu/odoo-nix"), {"group": "actions"}, "review"),
            # 3, 4: third-party actions.
            (("github_actions", "actions/checkout"), {"group": "actions"}, "auto"),
            (("github_actions", "actions/checkout"), {}, "auto"),
            # 5, 6: nix inputs.
            (("nix", "odoo-nix"), {}, "close"),
            (("nix", "standards-profile"), {}, "close"),
            (("nix", "ocb"), {}, "relock"),
            (("nix", "nixpkgs, oca-queue"), {}, "relock"),
            # 7, 8: the locked tools.
            (("npm_and_yarn", "prettier"), {"directory": "/"}, "close"),
            (("uv", "ruff"), {"directory": "/tools"}, "close"),
            # 9: an addon's own package.json.
            (
                ("npm_and_yarn", "lodash"),
                {
                    "directory": "/web_theme_carbon",
                    "update_type": "version-update:semver-patch",
                },
                "auto",
            ),
            (
                ("npm_and_yarn", "lodash"),
                {
                    "directory": "/web_theme_carbon",
                    "update_type": "version-update:semver-major",
                },
                "review",
            ),
            # 10: submodules.
            (("submodules", "odoo"), {}, "relock"),
            # no match.
            (("pre_commit", "ruff-pre-commit"), {}, "review"),
            (("uv", "requests"), {"directory": "/"}, "review"),
        ]
        for (ecosystem, names), kw, want in cases:
            with self.subTest(ecosystem=ecosystem, names=names, **kw):
                self.assertEqual(decide(ecosystem, names, **kw), want)

    def test_policy_all(self) -> None:
        self.assertEqual(decide("pre_commit", "x", policy=core.ALL), "auto")
        self.assertEqual(decide("github_actions", ENGINE, policy=core.ALL), "review")
        self.assertEqual(
            decide("uv", "ruff", policy=core.ALL, directory="/tools"), "close"
        )
        self.assertEqual(decide("nix", "ocb", policy=core.ALL), "relock")


if __name__ == "__main__":
    unittest.main()
