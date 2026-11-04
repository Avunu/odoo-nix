"""``odoo-nix policy`` with odoo-nix's product (DESIGN.md §7.2 test_policy).

- ``pr_checks``: a version moved by hand in a pull request to ``develop`` under
  ``develop+series`` is refused; other manifest edits, new addons, other bases and the
  ``trunk`` branching are not.
- ``committed_argv``: ``tools/.bin/committed`` when the dev shell linked it.
- odoo-nix's own pull requests, ``policy --pr --major-free`` (the pr-policy workflow,
  which lib/pr_policy.py ran before), through the real ``committed`` and odoo-nix's
  ``committed.toml``: ``!`` and ``BREAKING CHANGE`` refused, ``Release-As`` let through,
  Dependabot's long subjects, the base rule and a dispatch's lookup. Skipped without
  ``committed`` on ``PATH``.
"""

from __future__ import annotations

import os
import shutil
import unittest

from odoo_nix_tools import policy
from odoo_nix_tools.product import PRODUCT
from standards_core.commands import policy as core_policy
from support import ADDONS_PRODUCT, SyncCase, TempRepos, git, need_root, run_cli


class CommittedArgv(TempRepos):
    def test_linked_or_path(self) -> None:
        root = self.tmp / "repo"
        root.mkdir()
        self.assertEqual(policy.committed_argv(root), ["committed"])
        bin_dir = self.tmp / "store-bin"
        bin_dir.mkdir()
        exe = bin_dir / "committed"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        (root / "tools").mkdir()
        (root / "tools/.bin").symlink_to(bin_dir)
        self.assertEqual(
            policy.committed_argv(root), [str(root / "tools/.bin/committed")]
        )
        self.assertIs(PRODUCT.hooks.committed_argv, policy.committed_argv)


class PrChecks(SyncCase):
    """``hooks.pr_checks`` on the addons fixture under example-org (releases on,
    develop+series)."""

    def setUp(self) -> None:
        super().setUp()
        self.root = self.profile_fixture("standards-addons", "example-org")
        git(self.root, "branch", "-m", "develop")
        git(self.root, "checkout", "-q", "-b", "topic")
        self.assertIs(PRODUCT.hooks.pr_checks, policy.pr_checks)

    def edit(self, path: str, old: str, new: str, message: str = "feat: x") -> None:
        file = self.root / path
        file.write_text(file.read_text().replace(old, new))
        git(self.root, "commit", "-q", "-am", message)

    def checks(self, base: str = "develop") -> list[str]:
        rules = core_policy.rules_for(
            ADDONS_PRODUCT, self.root, major_free=False, base_branch="main"
        )
        head = git(self.root, "rev-parse", "HEAD").strip()
        pr = core_policy.pr_context(
            self.root,
            rules,
            base=base,
            head_sha=head,
            head_ref="topic",
            title="feat: x",
            author="someone",
        )
        return policy.pr_checks(pr)

    def test_a_hand_version_edit_is_refused(self) -> None:
        self.edit("fixture_a/__manifest__.py", "18.0.1.0.0", "18.0.1.1.0")
        found = self.checks()
        self.assertEqual(len(found), 1, found)
        self.assertTrue(
            found[0].startswith("fixture_a/__manifest__.py: version moved by hand")
        )
        self.assertIn("18.0.1.0.0 → 18.0.1.1.0", found[0])

    def test_against_the_merge_base(self) -> None:
        # The integration branch moved on (a bump after the PR branched): the PR's
        # version is still the merge-base's, so nothing was moved by hand.
        git(self.root, "checkout", "-q", "develop")
        self.edit(
            "fixture_b/__manifest__.py",
            "18.0.1.0.0",
            "18.0.1.0.1",
            "chore(release): bump fixture_b",
        )
        git(self.root, "checkout", "-q", "topic")
        self.edit("fixture_b/__manifest__.py", '"Tools"', '"Hidden"')
        self.assertEqual(self.checks(), [])

    def test_other_edits_and_new_addons_pass(self) -> None:
        self.edit("fixture_a/__manifest__.py", '"Tools"', '"Hidden"')
        new = self.root / "fixture_c/__manifest__.py"
        new.parent.mkdir()
        new.write_text('{"name": "C", "version": "18.0.1.0.0", "license": "AGPL-3"}\n')
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "feat(fixture_c): add")
        self.assertEqual(self.checks(), [])

    def test_a_stacked_base_is_not_checked(self) -> None:
        git(self.root, "branch", "other", "develop")
        self.edit("fixture_a/__manifest__.py", "18.0.1.0.0", "18.0.1.1.0")
        self.assertEqual(self.checks(base="other"), [])

    def switch(self, line: str) -> None:
        config = self.root / "nix/pyproject.toml"
        text = config.read_text()
        config.write_text(
            text.replace("[tool.odoo-nix]\n", f"[tool.odoo-nix]\n{line}\n", 1)
        )
        git(self.root, "commit", "-q", "-am", "chore: switch")
        self.edit("fixture_a/__manifest__.py", "18.0.1.0.0", "18.0.9.0.0")

    def test_trunk(self) -> None:
        self.switch('releases.branching = "trunk"')
        self.assertEqual(self.checks(base="main"), [])

    def test_releases_off(self) -> None:
        self.switch("releases.enable = false")
        self.assertEqual(self.checks(), [])


@unittest.skipUnless(shutil.which("committed"), "committed is not on PATH")
class MajorFree(TempRepos):
    """odoo-nix's own pr-policy: ``odoo-nix policy --pr --major-free`` with
    committed.toml."""

    LONG = (
        "fix(deps): bump the github-actions group across 1 directory with 2 updates "
        "from 3d3c42e5aac5ba805825da76410c181273ba90b1 "
        "to 25dd0e34f4fe68f24cc83900b1fe3fe149efef98"
    )

    def setUp(self) -> None:
        super().setUp()
        config = need_root(self) / "committed.toml"
        if not config.is_file():
            self.skipTest("odoo-nix's committed.toml is not available")
        self.root = self.make_tree({"committed.toml": config.read_text()}, commit=False)
        for key, value in (("user.name", "Test"), ("user.email", "t@example.invalid")):
            git(self.root, "config", key, value)
        self.commit("chore: start")
        git(self.root, "checkout", "-q", "-b", "topic")
        for key in ("GITHUB_ACTIONS", "PR_AUTHOR", "HEAD_REF", "GITHUB_HEAD_REF"):
            os.environ.pop(key, None)

    def commit(self, message: str) -> str:
        git(self.root, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.root, "rev-parse", "HEAD").strip()

    def check(self, title: str, **env: str) -> tuple[int, str]:
        os.environ.update(
            {
                "EVENT_NAME": "pull_request",
                "BASE_REF": "main",
                "HEAD_SHA": git(self.root, "rev-parse", "HEAD").strip(),
                "PR_TITLE": title,
                "PR_AUTHOR": "",
                "REF_NAME": "topic",
                **env,
            }
        )
        code, out, err = run_cli(
            "policy", "--pr", "--major-free", "--base-branch", "main", cwd=self.root
        )
        return code, out + err

    def fake_gh(self, output: str) -> None:
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\n")
        gh.chmod(0o755)
        os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

    def test_conventional_passes(self) -> None:
        self.commit("feat(devenv): a thing")
        self.commit("fix: another\n\nRelease-As: 2.0.0")
        code, out = self.check("feat(release): release odoo-nix with release-please")
        self.assertEqual(code, 0, out)

    def test_bang_title_and_commit(self) -> None:
        self.commit("feat!: rename")
        code, out = self.check("feat(devenv)!: rename")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("`!` marks a major bump"), 2, out)

    def test_breaking_footer(self) -> None:
        self.commit("feat: rename\n\nBREAKING CHANGE: the old name is gone")
        code, out = self.check("feat: rename")
        self.assertEqual(code, 1, out)
        self.assertIn("BREAKING CHANGE", out)

    def test_not_conventional(self) -> None:
        self.commit("Rename the thing")
        self.commit("feat(nonsense): a scope odoo-nix lacks")
        code, out = self.check("rename the thing")
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("committed:"), 3, out)

    def test_dependabot_long_subjects(self) -> None:
        self.commit(self.LONG)
        code, out = self.check(self.LONG, PR_AUTHOR="dependabot[bot]")
        # The commit's author is not Dependabot, so its subject is held to the limit.
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("title:"), 0, out)
        code, out = self.check(self.LONG, PR_AUTHOR="someone")
        self.assertEqual(code, 1, out)
        self.assertIn("title: committed", out)

    def test_other_base(self) -> None:
        self.commit("feat: one")
        git(self.root, "branch", "release-1", "main")
        self.fake_gh('[{"headRefName": "some-other-pr"}]')
        code, out = self.check("feat: one", BASE_REF="release-1")
        self.assertEqual(code, 1, out)
        self.assertIn("gh pr edit", out)

    def test_dispatch_looks_the_pull_request_up(self) -> None:
        head = self.commit("feat: one")
        self.fake_gh(
            f'[{{"number": 8, "title": "feat: one", "baseRefName": "main", '
            f'"headRefOid": "{head}", "author": {{"login": "someone"}}}}]'
        )
        code, out = self.check(
            "", EVENT_NAME="workflow_dispatch", BASE_REF="", PR_TITLE=""
        )
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
