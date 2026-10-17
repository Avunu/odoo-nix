"""lib/pr_policy.py, the pr-policy check, against throwaway git repositories:
conventional commits through the real `committed` and committed.toml, the
refusal of `!` and BREAKING CHANGE, a `Release-As` major let through, the base
rule, and a dispatch's pull-request lookup (`gh` stood in by a script).

Run: python3 -I tests/test_pr_policy.py <lib/pr_policy.py> <committed.toml>
     (checks.pr-policy; needs git and committed on PATH)
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

POLICY = Path(sys.argv.pop(1)).resolve()
CONFIG = Path(sys.argv.pop(1)).resolve()
# Loaded by path: in the store the file is <hash>-pr_policy.py.
_spec = importlib.util.spec_from_file_location("pr_policy", POLICY)
pr_policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr_policy)


class Repo:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        shutil.copy(CONFIG, root / "committed.toml")
        self.commit("chore: start")
        self.git("checkout", "-q", "-b", "topic")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")


class PrPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repo(Path(self.tmp.name) / "repo")

    def check(self, title: str, **env: str) -> list[str]:
        head = self.repo.git("rev-parse", "HEAD")
        base = {
            "EVENT_NAME": "pull_request",
            "BASE_REF": "main",
            "HEAD_SHA": head,
            "PR_TITLE": title,
        }
        return pr_policy.check_pr(str(self.repo.root), "main", {**base, **env})

    def test_conventional_passes(self):
        self.repo.commit("feat(devenv): a thing")
        self.repo.commit("fix: another\n\nRelease-As: 2.0.0")
        self.assertEqual(
            self.check("feat(release): release odoo-nix with release-please"), []
        )

    def test_release_please_and_dependabot_titles(self):
        self.repo.commit("chore(main): release 1.0.0")
        self.assertEqual(self.check("chore(main): release 1.0.0"), [])
        self.assertEqual(
            self.check(
                "fix(deps): bump the nix group across 1 directory with 3 updates"
            ),
            [],
        )

    def test_bang_title(self):
        self.repo.commit("feat: fine")
        found = self.check("feat(devenv)!: rename")
        self.assertEqual(len(found), 1, found)
        self.assertIn("`!` marks a major bump", found[0])

    def test_bang_commit(self):
        self.repo.commit("feat!: rename")
        found = self.check("feat: rename")
        self.assertEqual(len(found), 1, found)
        self.assertTrue(found[0].startswith("commit "), found)

    def test_breaking_footer(self):
        self.repo.commit("feat: rename\n\nBREAKING CHANGE: the old name is gone")
        found = self.check("feat: rename")
        self.assertTrue(any("BREAKING CHANGE" in p for p in found), found)

    def test_not_conventional(self):
        self.repo.commit("Rename the thing")
        self.repo.commit("feat(nonsense): a scope odoo-nix lacks")
        found = self.check("rename the thing")
        self.assertEqual(sum("committed" in p for p in found), 3, found)

    def test_merge_commits_skipped(self):
        self.repo.commit("feat: one")
        self.repo.git("checkout", "-q", "main")
        self.repo.commit("fix: on main")
        self.repo.git("checkout", "-q", "topic")
        self.repo.git("merge", "-q", "--no-edit", "main")
        self.assertEqual(self.check("feat: one"), [])

    # Dependabot's title for SHA-pinned actions: two 40-character SHAs.
    LONG = (
        "fix(deps): bump the github-actions group across 1 directory with 2 updates "
        "from 3d3c42e5aac5ba805825da76410c181273ba90b1 "
        "to 25dd0e34f4fe68f24cc83900b1fe3fe149efef98"
    )

    def test_dependabot_long_title_passes(self):
        self.repo.commit(self.LONG)
        self.assertEqual(self.check(self.LONG, PR_AUTHOR="dependabot[bot]"), [])

    def test_long_title_from_a_person_fails(self):
        self.repo.commit(self.LONG)
        found = self.check(self.LONG, PR_AUTHOR="someone")
        self.assertEqual(len(found), 2, found)
        self.assertTrue(all("too long" in p for p in found), found)

    def test_dependabot_is_held_to_the_other_rules(self):
        bang = self.LONG.replace("fix(deps):", "fix(deps)!:")
        self.repo.commit(bang)
        found = self.check(bang, PR_AUTHOR="dependabot[bot]")
        self.assertEqual(len(found), 2, found)
        self.assertTrue(all("`!` marks a major bump" in p for p in found), found)
        self.assertFalse(any("too long" in p for p in found), found)
        found = self.check("chore(nonsense): x", PR_AUTHOR="dependabot[bot]")
        self.assertTrue(any("committed" in p for p in found), found)

    def test_dispatch_takes_dependabot_from_the_lookup(self):
        head = self.repo.commit(self.LONG)
        self.fake_gh(
            f'[{{"number": 8, "title": "{self.LONG}", "baseRefName": "main", '
            f'"headRefOid": "{head}", "author": {{"login": "app/dependabot", "is_bot": true}}}}]'
        )
        env = {
            "EVENT_NAME": "workflow_dispatch",
            "BASE_REF": "",
            "PR_TITLE": "",
            "REF_NAME": "topic",
        }
        # PR_AUTHOR from the environment is ignored on a dispatch: the lookup decides.
        self.assertEqual(self.check("", **env, PR_AUTHOR="someone"), [])

    def test_dispatch_by_a_person_keeps_the_limit(self):
        head = self.repo.commit(self.LONG)
        self.fake_gh(
            f'[{{"number": 8, "title": "{self.LONG}", "baseRefName": "main", '
            f'"headRefOid": "{head}", "author": {{"login": "someone", "is_bot": false}}}}]'
        )
        env = {
            "EVENT_NAME": "workflow_dispatch",
            "BASE_REF": "",
            "PR_TITLE": "",
            "REF_NAME": "topic",
        }
        found = self.check("", **env, PR_AUTHOR="dependabot[bot]")
        self.assertEqual(len(found), 2, found)

    def test_message_problems(self):
        self.assertEqual(
            pr_policy.message_problems("chore: x\n\nRelease-As: 2.0.0"), []
        )
        self.assertEqual(len(pr_policy.message_problems("fix(deps)!: x")), 1)
        self.assertEqual(
            len(pr_policy.message_problems("fix: x\n\nBREAKING-CHANGE: y")), 1
        )
        self.assertEqual(
            pr_policy.message_problems("# feat!: a comment line\nfix: x"), []
        )

    def fake_gh(self, output: str) -> None:
        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\n")
        gh.chmod(0o755)
        path = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}:{path}"
        self.addCleanup(os.environ.__setitem__, "PATH", path)

    def test_other_base(self):
        self.repo.commit("feat: one")
        self.repo.git("branch", "release-1", "main")
        self.fake_gh('[{"headRefName": "some-other-pr"}]')
        found = self.check("feat: one", BASE_REF="release-1")
        self.assertEqual(len(found), 1, found)
        self.assertIn("gh pr edit", found[0])

    def test_dispatch(self):
        head = self.repo.commit("chore(main): release 1.0.0")
        self.fake_gh(
            f'[{{"number": 7, "title": "chore(main): release 1.0.0", "baseRefName": "main", "headRefOid": "{head}"}}]'
        )
        env = {
            "EVENT_NAME": "workflow_dispatch",
            "BASE_REF": "",
            "PR_TITLE": "",
            "REF_NAME": "topic",
        }
        self.assertEqual(self.check("", **env), [])
        found = self.check("", **{**env, "HEAD_SHA": "0" * 40})
        self.assertEqual(len(found), 1, found)
        self.assertIn("stale dispatch", found[0])


if __name__ == "__main__":
    unittest.main()
