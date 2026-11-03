"""Branching models (DESIGN.md §2.2).

``develop+series`` (the default): pull requests go to ``develop``; after a merge the CI App
bumps each changed addon's version and fast-forwards the series branch ``.odoo-series``
names. A project has no release branch. ``trunk``: one ``main``, no release flow. The
``odoo-series`` version scheme and the manifest release tool arrive in stage O7.
"""

from __future__ import annotations

from types import MappingProxyType

from standards_core.product import Branching

BRANCHING = MappingProxyType(
    {
        "develop+series": Branching(
            name="develop+series",
            flow="post-merge-bump",
            integration=lambda cfg: "develop",
            release_branch=lambda cfg, facts: (
                str(facts.get("series") or "") if facts.get("shape") == "addons" else ""
            ),
            # Narrowed to the checkout's own series by hooks.repo_policy_values (O8).
            release_pattern="refs/heads/*.0",
            release_label="*.0",
            tags=False,
        ),
        "trunk": Branching(
            name="trunk",
            flow="none",
            integration=lambda cfg: "main",
            release_branch=lambda cfg, facts: "",
        ),
    }
)
