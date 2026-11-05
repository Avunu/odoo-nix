"""The Dependabot decision table (DESIGN.md §2.8; core DESIGN.md §8.3).

Rules are tried in order within the PR's ecosystem; the first that matches gives the
verdict, and no match is ``review``. ``$engine`` is the ``<owner>/<repo>`` the checkout
locks odoo-nix from; ``$rollout-inputs`` are ``odoo-nix`` and ``standards-profile``,
which move only through ``odoo-nix repo rollout`` and ``odoo-init --sync``.
"""

from __future__ import annotations

from standards_core.ci.verdict import DecisionRule

DECISION_TABLE: tuple[DecisionRule, ...] = (
    # 1, 2: the engine's reusable workflows and the core's composite actions move with
    # the locked odoo-nix; a hand-merged bump would put the callers out of step with it.
    # Dependabot names a reusable workflow `<owner>/<repo>` or `<owner>/<repo>/<path>`.
    DecisionRule(
        "github_actions", "review", names=("$engine", "Avunu/odoo-nix/*"), sticky=True
    ),
    DecisionRule(
        "github_actions",
        "review",
        names=("Avunu/python-devops-nix", "Avunu/python-devops-nix/*"),
        sticky=True,
    ),
    # 3, 4: third-party actions, SHA-pinned; the required checks decide.
    DecisionRule("github_actions", "auto", groups=("actions",)),
    DecisionRule("github_actions", "auto", ungrouped_named=True),
    # 5: odoo-nix and the standards profile move through the rollout, never Dependabot.
    DecisionRule("nix", "close", names=("$rollout-inputs",)),
    # 6: any other input (nixpkgs, ocb, an oca-* source): nix/uv.lock follows OCB and the
    # external sources, so the PR is relocked (`nix run .#relock`) before it merges.
    DecisionRule("nix", "relock"),
    # 7, 8: the locked tools follow the series data (tools/uv.lock, package-lock.json);
    # Dependabot is not configured for them, this covers a hand-added entry.
    DecisionRule("npm_and_yarn", "close", directories=("/",), sticky=True),
    DecisionRule("uv", "close", directories=("/tools",), sticky=True),
    # 9: an addon's own package.json (a local-region entry, e.g. /web_theme_carbon).
    DecisionRule("npm_and_yarn", "auto", update="minor-patch"),
    # 10: a project's submodules move with `odoo project update`, then a relock.
    DecisionRule("submodules", "relock"),
)
