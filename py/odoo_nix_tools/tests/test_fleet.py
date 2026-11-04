"""The ``repo`` commands' odoo-nix hooks (DESIGN.md §2.2, §2.7): the fleet entry schema,
``fleet_table``, ``repo_policy_values``, the audit rows A12/A13 and the doctor rows, and
``repo apply --dry-run`` on the example-org fixtures, all against the core's
``FakeGitHub`` with ``targets.clone`` and ``targets.fetch_profile`` replaced.

The addons fixture runs through ``support.ADDONS_PRODUCT``, the stand-in for core CR1
(DESIGN.md §10): ``PRODUCT`` itself reads ``[tool.odoo-nix]`` from the root
``pyproject.toml`` only, so it sees an addon repository as not opted in, and the
``repo`` commands take the fleet entry's app layer (``fleet_table``) for it instead.
"""

from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from odoo_nix_tools import fleet
from odoo_nix_tools.product import PRODUCT
from standards_core.commands.repo import audit, targets
from standards_core.common import github, repo_policy, repoconfig, schema
from standards_core.product import Product
from standards_core.testing.fakes import FakeGitHub
from support import ADDONS_PRODUCT, ORG_PROFILES, TempRepos, fixture_files, run_cli

ADDONS = "example-org/standards-addons"
PROJECT = "example-org/standards-project"
ADDONS_ENTRY = {
    "repo": ADDONS,
    "shape": "addons",
    "branches": ["develop", "18.0"],
    "private": False,
}
PROJECT_ENTRY = {
    "repo": PROJECT,
    "shape": "project",
    "branches": ["main"],
    "private": False,
}
APP = {"actor_type": "Integration", "actor_id": 123, "bypass_mode": "always"}
TARGETS = 'target-branches = ["develop", "17.0"]'
# The settings of fleet.doctor_rows' rows.
MINE = ("Actions variable", "Actions secret", "repo-policy.", "ci.github-app.")
# ci off, with the two modules that need it.
OFF = (
    'profile = "./.standards-profile"\n=>profile = "./.standards-profile"\n\n'
    + "".join(
        f"[tool.odoo-nix.{m}]\nenable = false\n\n"
        for m in ("ci", "releases", "repo-policy")
    )
)


def fleet_errors(*entries: dict[str, Any]) -> list[str]:
    doc = {"schema": 1, PRODUCT.fleet_key: list(entries)}
    return schema.Validator(PRODUCT, schema.FLEET, "fleet").errors(doc)


class Entry(unittest.TestCase):
    """data/schema/fleet-entry.schema.json, composed into the core's fleet schema."""

    def test_an_addon_and_a_project_entry(self) -> None:
        self.assertEqual(fleet_errors(ADDONS_ENTRY, PROJECT_ENTRY), [])

    def test_integration_branch_is_optional_and_may_be_given(self) -> None:
        self.assertEqual(
            fleet_errors({**ADDONS_ENTRY, "integration_branch": "develop"}), []
        )

    def test_shape_branches_and_private_are_required(self) -> None:
        for key in ("shape", "branches", "private"):
            entry = {k: v for k, v in ADDONS_ENTRY.items() if k != key}
            self.assertNotEqual(fleet_errors(entry), [], key)

    def test_the_draft_profiles_series_branches_key_is_refused(self) -> None:
        entry = {**ADDONS_ENTRY, "series_branches": ["18.0"]}
        self.assertNotEqual(fleet_errors(entry), [])

    def test_an_unknown_shape_is_refused(self) -> None:
        self.assertNotEqual(fleet_errors({**ADDONS_ENTRY, "shape": "bundle"}), [])


class FleetTable(unittest.TestCase):
    def test_wired(self) -> None:
        hooks = PRODUCT.hooks
        self.assertIs(hooks.fleet_table, fleet.fleet_table)
        self.assertIs(hooks.repo_policy_values, fleet.repo_policy_values)
        self.assertIs(hooks.doctor_rows, fleet.doctor_rows)
        self.assertEqual(sorted(PRODUCT.audit_rows), ["A12", "A13"])

    def test_integration_branch_is_the_first_branch(self) -> None:
        self.assertEqual(
            fleet.fleet_table(ADDONS, ADDONS_ENTRY, "recommended"),
            {"shape": "addons", "integration-branch": "develop"},
        )

    def test_integration_branch_wins_over_branches(self) -> None:
        entry = {**ADDONS_ENTRY, "integration_branch": "main"}
        self.assertEqual(
            fleet.fleet_table(ADDONS, entry, "recommended")["integration-branch"],
            "main",
        )

    def test_an_entry_less_target_gets_nothing(self) -> None:
        self.assertEqual(fleet.fleet_table(ADDONS, {}, "recommended"), {})

    def test_resolved_through_the_core(self) -> None:
        resolved, directory = targets.resolve_profile(
            PRODUCT, ADDONS, "recommended", ADDONS_ENTRY
        )
        self.assertIsNone(directory)
        self.assertEqual(resolved.cfg["shape"], "addons")
        self.assertEqual(resolved.cfg["integration-branch"], "develop")


class RepoPolicyValues(unittest.TestCase):
    def cfg(self, shape: str, branching: str = "develop+series") -> dict[str, Any]:
        return {
            "shape": shape,
            "series": "18.0",
            "integration-branch": "develop" if shape == "addons" else "main",
            "releases": {"enable": True, "branching": branching},
        }

    def test_an_addon_repository_protects_its_series_only(self) -> None:
        self.assertEqual(
            fleet.repo_policy_values(self.cfg("addons"), {"releases": True}, []),
            {"release_pattern": "refs/heads/18.0", "release_label": "18.0"},
        )

    def test_trunk_keeps_the_core_values(self) -> None:
        cfg = self.cfg("addons", "trunk")
        self.assertEqual(fleet.repo_policy_values(cfg, {"releases": True}, []), {})

    def test_a_project_has_no_integration_bypass(self) -> None:
        self.assertEqual(
            fleet.repo_policy_values(self.cfg("project"), {"releases": True}, []),
            {"integration_bypass": []},
        )

    def test_through_the_core_values(self) -> None:
        modules = {"releases": True, "repo-policy": True}
        cfg = {**self.cfg("addons"), "repo-policy": {"release-bypass": "integration:1"}}
        vals = repo_policy.values(PRODUCT, cfg, modules, [], release_branch="18.0")
        self.assertEqual(vals["release_pattern"], "refs/heads/18.0")
        self.assertEqual(vals["integration_bypass"][0]["actor_id"], 1)
        # A project's release branch is "" anyway; even a forced one bypasses nothing.
        cfg = {**cfg, "shape": "project", "integration-branch": "main"}
        vals = repo_policy.values(PRODUCT, cfg, modules, [], release_branch="18.0")
        self.assertEqual(vals["integration_bypass"], [])


class RepoCase(TempRepos):
    """A fake GitHub, ``targets.clone`` answering from ``self.clones`` and
    ``targets.fetch_profile`` from the example-org fixture profile; ``audit.run_tool``
    reports a clean ``sync --check``."""

    def setUp(self) -> None:
        super().setUp()
        os.environ["ODOO_NIX_OFFLINE"] = "1"
        os.environ["ODOO_NIX_ALLOW_SKEW"] = "1"
        for key in ("GH_TOKEN", "ODOO_NIX_ISSUE_TOKEN"):
            os.environ.pop(key, None)
        self.gh = FakeGitHub()
        previous = github.use(self.gh)
        self.addCleanup(github.use, previous)
        for r, default in ((ADDONS, "develop"), (PROJECT, "main")):
            self.gh.routes[("GET", f"repos/{r}")] = {
                "full_name": r,
                "default_branch": default,
                "private": False,
            }
        self.clones: dict[tuple[str, str | None], Path] = {}
        for target, fake in (
            ("clone", self._clone),
            ("fetch_profile", self._profile),
        ):
            patch = mock.patch.object(targets, target, side_effect=fake)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(audit, "run_tool", side_effect=self._tool)
        patch.start()
        self.addCleanup(patch.stop)

    def _clone(self, product, repo, branch=None, depth=1):
        return self.clones.get((repo, branch))

    def _profile(self, product, ref):
        dest = self.tmp / f"profile-{len(list(self.tmp.iterdir()))}"
        shutil.copytree(self.root_dir() / ORG_PROFILES / "example-org", dest)
        return dest

    def _tool(self, product, root, argv, spec):
        if argv[:2] == ["sync", "--check"]:
            return 0, json.dumps({"status": "clean", "files": []})
        return 0, ""

    def clone_of(
        self, fixture: str, repo: str, edit: dict[str, str] | None = None
    ) -> Path:
        """``tests/fixtures/<fixture>`` under example-org, as the clone of ``repo``;
        ``edit`` replaces text in the files it names (old → new, ``"a=>b"``)."""
        files: dict[str, str | bytes] = dict(
            fixture_files(self.root_dir(), fixture, "example-org", locks=False)
        )
        for rel, change in (edit or {}).items():
            old, _, new = change.partition("=>")
            text = files[rel].decode() if isinstance(files[rel], bytes) else files[rel]
            self.assertIn(old, text, rel)
            files[rel] = text.replace(old, new, 1)
        root = self.make_tree(files, name=f"{fixture}-{len(self.clones)}")
        self.clones[(repo, None)] = root
        return root

    def root_dir(self) -> Path:
        from support import need_root

        return need_root(self)

    def fleet_file(self, *entries: dict[str, Any]) -> str:
        path = self.tmp / "fleet.json"
        path.write_text(json.dumps({"schema": 1, "repos": list(entries)}))
        return str(path)

    def cli(self, product: Product, *argv: str) -> tuple[int, str, str]:
        return run_cli(*argv, cwd=self.tmp, product=product)


class Audit(RepoCase):
    def rows(
        self, product: Product, repo: str, *entries: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        argv = ["repo", "audit", "--format", "json"]
        argv += ["--all", "--fleet", self.fleet_file(*entries)] if entries else []
        argv += [] if entries else ["--repo", repo]
        code, out, err = self.cli(product, *argv)
        self.assertIn(code, (0, 1), err)
        doc = json.loads(out)
        return {row["id"]: row for row in doc["repos"][0]["rows"]}

    def test_an_addon_repository_on_its_series(self) -> None:
        self.clone_of("standards-addons", ADDONS)
        rows = self.rows(ADDONS_PRODUCT, ADDONS, ADDONS_ENTRY)
        self.assertEqual(rows["A12"]["status"], "green", rows["A12"])
        self.assertEqual(rows["A13"]["status"], "n/a")
        self.assertIn("addon repository", rows["A13"]["detail"])

    def test_the_fleet_does_not_list_the_series(self) -> None:
        self.clone_of("standards-addons", ADDONS)
        entry = {**ADDONS_ENTRY, "branches": ["develop", "17.0"]}
        row = self.rows(ADDONS_PRODUCT, ADDONS, entry)["A12"]
        self.assertEqual(row["status"], "red")
        self.assertIn("(17.0) do not include 18.0 (.odoo-series)", row["detail"])

    def test_dependabot_on_the_series_branch(self) -> None:
        self.clone_of(
            "standards-addons",
            ADDONS,
            {"nix/pyproject.toml": f'{TARGETS}=>target-branches = ["develop", "18.0"]'},
        )
        row = self.rows(ADDONS_PRODUCT, ADDONS, ADDONS_ENTRY)["A12"]
        self.assertEqual(row["status"], "red")
        self.assertIn("lists 18.0, which the release ruleset", row["detail"])
        self.assertIn("refs/heads/18.0", row["detail"])

    def test_dependabot_without_the_integration_branch(self) -> None:
        self.clone_of(
            "standards-addons",
            ADDONS,
            {"nix/pyproject.toml": f'{TARGETS}=>target-branches = ["17.0"]'},
        )
        row = self.rows(ADDONS_PRODUCT, ADDONS, ADDONS_ENTRY)["A12"]
        self.assertEqual(row["status"], "red")
        self.assertIn("(17.0) does not list develop", row["detail"])

    def test_no_fleet_entry_is_unknown(self) -> None:
        self.clone_of("standards-addons", ADDONS)
        row = self.rows(ADDONS_PRODUCT, ADDONS)["A12"]
        self.assertEqual(row["status"], "unknown")

    def test_a_project_on_its_series(self) -> None:
        self.clone_of("standards-project", PROJECT)
        rows = self.rows(PRODUCT, PROJECT, PROJECT_ENTRY)
        self.assertEqual(rows["A12"]["status"], "n/a")
        self.assertEqual(rows["A13"]["status"], "green", rows["A13"])
        self.assertEqual(rows["A13"]["detail"], "2 submodule(s) on 18.0")

    def test_a_submodule_off_the_series(self) -> None:
        self.clone_of(
            "standards-project",
            PROJECT,
            {".gitmodules": "server-tools.git\n\tbranch = 18.0=>server-tools.git\n"},
        )
        row = self.rows(PRODUCT, PROJECT, PROJECT_ENTRY)["A13"]
        self.assertEqual(row["status"], "red")
        self.assertIn("modules/server-tools (no branch)", row["detail"])

    def test_rows_follow_their_modules(self) -> None:
        self.clone_of(
            "standards-project",
            PROJECT,
            {"pyproject.toml": OFF},
        )
        rows = self.rows(PRODUCT, PROJECT)
        # The core's own gating: A13 is ci's (and releases needs ci, so both are off).
        self.assertEqual(rows["A13"]["status"], "n/a")
        self.assertEqual(rows["A13"]["detail"], "ci is off")


class Doctor(RepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.gh.routes.update(
            {
                ("GET", f"repos/{ADDONS}/actions/variables/EXAMPLE_CI_APP_ID"): {
                    "name": "EXAMPLE_CI_APP_ID"
                },
                ("GET", f"repos/{ADDONS}/actions/organization-secrets"): {
                    "secrets": [{"name": "EXAMPLE_CI_PRIVATE_KEY"}]
                },
            }
        )

    def rows(
        self, product: Product, repo: str
    ) -> tuple[int, dict[str, str], list[str]]:
        code, out, err = self.cli(product, "repo", "doctor", repo, "--format", "json")
        self.assertIn(code, (0, 1), err)
        doc = json.loads(out)
        mine = {
            r["setting"]: r["status"]
            for r in doc["rows"]
            if r["setting"].startswith(MINE)
        }
        return code, mine, doc["notices"]

    def test_the_app_the_release_flow_needs(self) -> None:
        self.clone_of("standards-addons", ADDONS)
        _, rows, _ = self.rows(ADDONS_PRODUCT, ADDONS)
        self.assertEqual(
            rows["Actions variable EXAMPLE_CI_APP_ID (the CI App's client ID)"], "ok"
        )
        self.assertEqual(
            rows["Actions secret EXAMPLE_CI_PRIVATE_KEY (the CI App's private key)"],
            "ok",
        )
        self.assertEqual(
            rows["repo-policy.release-bypass is the CI App (integration:123)"], "ok"
        )

    def test_a_missing_variable_and_an_unreadable_secret(self) -> None:
        self.clone_of("standards-addons", ADDONS)
        del self.gh.routes[
            ("GET", f"repos/{ADDONS}/actions/variables/EXAMPLE_CI_APP_ID")
        ]
        self.gh.routes[("GET", f"repos/{ADDONS}/actions/organization-secrets")] = 403
        code, rows, _ = self.rows(ADDONS_PRODUCT, ADDONS)
        self.assertEqual(code, 1)
        self.assertEqual(
            rows["Actions variable EXAMPLE_CI_APP_ID (the CI App's client ID)"],
            "missing",
        )
        self.assertEqual(
            rows["Actions secret EXAMPLE_CI_PRIVATE_KEY (the CI App's private key)"],
            "unknown",
        )

    def test_an_org_variable_counts(self) -> None:
        self.clone_of("standards-addons", ADDONS)
        del self.gh.routes[
            ("GET", f"repos/{ADDONS}/actions/variables/EXAMPLE_CI_APP_ID")
        ]
        self.gh.routes[("GET", f"repos/{ADDONS}/actions/organization-variables")] = {
            "variables": [{"name": "EXAMPLE_CI_APP_ID"}]
        }
        _, rows, _ = self.rows(ADDONS_PRODUCT, ADDONS)
        self.assertEqual(
            rows["Actions variable EXAMPLE_CI_APP_ID (the CI App's client ID)"], "ok"
        )

    def test_the_release_bypass_is_the_apps_numeric_id(self) -> None:
        self.clone_of(
            "standards-addons",
            ADDONS,
            {
                "nix/pyproject.toml": (
                    "[tool.odoo-nix.dependabot]=>[tool.odoo-nix.repo-policy]\n"
                    'release-bypass = "github-actions"\n\n[tool.odoo-nix.dependabot]'
                )
            },
        )
        code, rows, _ = self.rows(ADDONS_PRODUCT, ADDONS)
        self.assertEqual(code, 1)
        [(setting, status)] = [
            (s, v)
            for s, v in rows.items()
            if s.startswith("repo-policy.release-bypass")
        ]
        self.assertEqual(status, "missing")
        self.assertIn("not github-actions", setting)

    def test_no_app_configured(self) -> None:
        self.clone_of(
            "standards-addons",
            ADDONS,
            {
                "nix/pyproject.toml": (
                    "[tool.odoo-nix.dependabot]=>[tool.odoo-nix.ci.github-app]\n"
                    'app-id = ""\nprivate-key = ""\n\n[tool.odoo-nix.dependabot]'
                )
            },
        )
        _, rows, _ = self.rows(ADDONS_PRODUCT, ADDONS)
        missing = [s for s, v in rows.items() if v == "missing"]
        self.assertIn(
            "ci.github-app.app-id names the Actions variable holding the CI App's"
            " client ID",
            missing,
        )
        self.assertIn(
            "ci.github-app.private-key names the Actions secret holding the CI App's"
            " private key",
            missing,
        )

    def test_a_project_has_no_release_rows(self) -> None:
        self.clone_of("standards-project", PROJECT)
        _, rows, notices = self.rows(PRODUCT, PROJECT)
        self.assertEqual(rows, {})
        self.assertEqual(notices, [])

    def test_a_project_without_an_app_gets_ci_by_dispatch(self) -> None:
        self.clone_of(
            "standards-project",
            PROJECT,
            {
                "pyproject.toml": (
                    'profile = "./.standards-profile"\n=>'
                    'profile = "./.standards-profile"\n\n'
                    '[tool.odoo-nix.ci.github-app]\napp-id = ""\nprivate-key = ""\n'
                )
            },
        )
        _, _, notices = self.rows(PRODUCT, PROJECT)
        self.assertEqual(len(notices), 1)
        self.assertIn("dispatches ci.yml and pr-policy.yml", notices[0])


class ApplyDryRun(RepoCase):
    """``repo apply --dry-run`` on the example-org fixtures: reads, never writes."""

    def setUp(self) -> None:
        super().setUp()
        for r in (ADDONS, PROJECT):
            self.gh.routes.update(
                {
                    ("GET", f"repos/{r}/actions/permissions/workflow"): {},
                    ("GET", f"repos/{r}/labels"): [],
                    ("GET", f"repos/{r}/rulesets"): [],
                }
            )

    def apply(self, product: Product, repo: str, *argv: str) -> dict[str, Any]:
        code, out, err = self.cli(product, "repo", "apply", repo, "--dry-run", *argv)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.gh.writes(), [])
        return json.loads(out)

    def changes(self, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {c["call"]: c["diff"] for c in doc["changes"]}

    def test_an_addon_repository_without_rulesets(self) -> None:
        self.clone_of("standards-addons", ADDONS)
        self.gh.routes[("GET", f"repos/{ADDONS}/branches/develop")] = {
            "name": "develop"
        }
        doc = self.apply(ADDONS_PRODUCT, ADDONS)
        self.assertEqual(doc["status"], "ok")
        posted = [
            c["diff"]["ruleset"][1]
            for c in doc["changes"]
            if c["call"] == f"POST repos/{ADDONS}/rulesets"
        ]
        self.assertEqual(posted, ["develop", "18.0 (release automation only)"])

    def test_an_addon_repository_on_the_old_rulesets(self) -> None:
        """A repository set up with every ``*.0`` protected and the bump bypassing
        nothing: the dry run wants the series branch only, and the App past both."""
        root = self.clone_of("standards-addons", ADDONS)
        t = targets.load(ADDONS_PRODUCT, ADDONS, {}, {})
        policy = repo_policy.for_target(
            ADDONS_PRODUCT,
            t.cfg,
            t.modules,
            t.gates,
            phase="full",
            release_branch=t.release_branch,
            overrides=t.profile_dir / "templates" if t.profile_dir else None,
        )
        self.clones[(ADDONS, None)] = root
        integration, release = policy.rulesets
        self.assertEqual(
            release["conditions"]["ref_name"]["include"], ["refs/heads/18.0"]
        )
        self.assertEqual(release["bypass_actors"], [APP])
        self.assertEqual(integration["bypass_actors"], [APP])
        stale_release = {
            **release,
            "id": 2,
            "conditions": {"ref_name": {"include": ["refs/heads/*.0"], "exclude": []}},
        }
        stale_integration = {**integration, "id": 1, "bypass_actors": []}
        self.gh.routes.update(
            {
                ("GET", f"repos/{ADDONS}/branches/develop"): {"name": "develop"},
                ("GET", f"repos/{ADDONS}/rulesets"): [
                    {"id": 1, "name": integration["name"]},
                    {"id": 2, "name": release["name"]},
                    {"id": 3, "name": "hand-made"},
                ],
                ("GET", f"repos/{ADDONS}/rulesets/1"): stale_integration,
                ("GET", f"repos/{ADDONS}/rulesets/2"): stale_release,
            }
        )
        doc = self.apply(ADDONS_PRODUCT, ADDONS)
        changes = self.changes(doc)
        self.assertEqual(
            changes[f"PUT repos/{ADDONS}/rulesets/2"],
            {
                "conditions": [
                    {"ref_name": {"include": ["refs/heads/*.0"], "exclude": []}},
                    {"ref_name": {"include": ["refs/heads/18.0"], "exclude": []}},
                ]
            },
        )
        self.assertEqual(
            changes[f"PUT repos/{ADDONS}/rulesets/1"], {"bypass_actors": [[], [APP]]}
        )
        self.assertEqual(doc["unknown_rulesets"], ["hand-made"])

    def test_a_project_has_no_release_ruleset_and_no_bypass(self) -> None:
        root = self.clone_of("standards-project", PROJECT)
        self.gh.routes[("GET", f"repos/{PROJECT}/branches/main")] = {"name": "main"}
        doc = self.apply(PRODUCT, PROJECT)
        posted = [
            c["diff"]["ruleset"][1]
            for c in doc["changes"]
            if c["call"] == f"POST repos/{PROJECT}/rulesets"
        ]
        self.assertEqual(posted, ["main"])
        rc = repoconfig.load(PRODUCT, root)
        self.assertTrue(rc.modules["releases"])
        self.assertEqual(rc.release_branch, "")
        policy = repo_policy.for_target(
            PRODUCT,
            rc.cfg,
            rc.modules,
            rc.gates,
            phase="full",
            release_branch=rc.release_branch,
        )
        [integration] = policy.rulesets
        self.assertEqual(integration["bypass_actors"], [])

    def test_a_not_opted_in_addon_repository_through_its_fleet_entry(self) -> None:
        """Without CR1 ``PRODUCT`` sees no table in an addon repository: ``--phase
        provisional`` applies the integration ruleset from the fleet entry (shape,
        integration branch) and the fleet's profile."""
        self.clone_of("standards-addons", ADDONS)
        self.gh.routes[("GET", f"repos/{ADDONS}/branches/develop")] = {
            "name": "develop"
        }
        self.gh.routes[("GET", f"repos/{ADDONS}")]["default_branch"] = "main"
        fleet_path = self.fleet_file(
            {**ADDONS_ENTRY, "profile": "github:example-org/standards-profile"}
        )
        code, out, err = self.cli(
            PRODUCT,
            "repo",
            "apply",
            "--all",
            "--fleet",
            fleet_path,
            "--phase",
            "provisional",
            "--dry-run",
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.gh.writes(), [])
        doc = json.loads(out)
        changes = self.changes(doc)
        self.assertEqual(
            changes[f"POST repos/{ADDONS}/rulesets"], {"ruleset": [None, "develop"]}
        )
        self.assertEqual(
            changes[f"PATCH repos/{ADDONS}"]["default_branch"], ["main", "develop"]
        )
        t = targets.load(PRODUCT, ADDONS, ADDONS_ENTRY, {}, "github:example-org/p")
        self.assertFalse(t.opted_in)
        self.assertEqual(t.cfg["shape"], "addons")
        self.assertEqual(t.integration, "develop")


if __name__ == "__main__":
    unittest.main()
