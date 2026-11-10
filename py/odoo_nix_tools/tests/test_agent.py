"""``odoo-nix agent hook`` (``ide.agents``, commands/agent.py): what Claude Code's hooks
run, and the files that wire them, rendered by sync."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from odoo_nix_tools.commands import agent
from support import SyncCase


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


class Hooks(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.org")
        git(self.root, "config", "user.name", "t")
        (self.root / agent.CONFIG).write_text("repos: []\n")
        (self.root / "a.py").write_text("x = 1\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "init")
        self.real_run = agent._run
        self.calls: list[list[str]] = []
        self.results: dict[str, tuple[int, str]] = {}

    def fake_run(self, argv: list[str], cwd: Path) -> tuple[int, str]:
        if argv[0] == "git":
            return self.real_run(argv, cwd)
        self.calls.append(argv)
        return self.results.get(argv[0] if argv[0] != "odoo-nix" else "gate", (0, ""))

    def call(self, fn, payload, prek="/bin/prek"):
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(agent, "_run", self.fake_run),
            mock.patch.object(agent.shutil, "which", return_value=prek),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = fn(self.root, payload)
        return rc, out.getvalue(), err.getvalue()


class PreBash(Hooks):
    def bash(self, command: str) -> dict:
        return {"tool_input": {"command": command}}

    def test_other_commands_pass_untouched(self) -> None:
        for cmd in ("git status", "git commit -m x", "ls", "gh pr view 3"):
            with self.subTest(cmd=cmd):
                rc, _, _ = self.call(agent.pre_bash, self.bash(cmd))
                self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [])

    def test_a_push_runs_the_gate_and_a_failure_blocks(self) -> None:
        self.results["gate"] = (1, "prek: ruff failed")
        for cmd in (
            "git push",
            "git push -u origin feat/x",
            "git -C repo push",
            "cd x && git push --force-with-lease",
            "gh pr create --fill",
            "gh pr ready 4",
        ):
            with self.subTest(cmd=cmd):
                rc, _, err = self.call(agent.pre_bash, self.bash(cmd))
                self.assertEqual(rc, agent.BLOCK)
                self.assertIn("prek: ruff failed", err)
        self.assertEqual(self.calls[0], ["odoo-nix", "gate", "lint"])

    def test_a_passing_gate_lets_the_push_through(self) -> None:
        rc, _, _ = self.call(agent.pre_bash, self.bash("git push"))
        self.assertEqual(rc, 0)

    def test_a_gate_that_cannot_run_does_not_block(self) -> None:
        self.results["gate"] = (3, "base branch not fetched")
        rc, _, err = self.call(agent.pre_bash, self.bash("git push"))
        self.assertEqual(rc, 0)
        self.assertIn("could not run", err)


class Stop(Hooks):
    def test_runs_the_hooks_on_the_changed_files_only(self) -> None:
        (self.root / "a.py").write_text("x = 2\n")
        (self.root / "new.xml").write_text("<a/>\n")
        rc, _, _ = self.call(agent.stop, {})
        self.assertEqual(rc, 0)
        argv = self.calls[0]
        self.assertEqual(argv[:5], ["/bin/prek", "run", "-c", agent.CONFIG, "--files"])
        self.assertEqual(sorted(argv[5:]), ["a.py", "new.xml"])

    def test_a_failure_goes_back_to_the_agent(self) -> None:
        (self.root / "a.py").write_text("x=2\n")
        self.results["/bin/prek"] = (1, "ruff-format....Failed")
        rc, _, err = self.call(agent.stop, {})
        self.assertEqual(rc, agent.BLOCK)
        self.assertIn("ruff-format....Failed", err)

    def test_once_per_stop_chain(self) -> None:
        (self.root / "a.py").write_text("x=2\n")
        self.results["/bin/prek"] = (1, "failed")
        rc, _, _ = self.call(agent.stop, {"stop_hook_active": True})
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [])

    def test_nothing_changed_or_no_prek_runs_nothing(self) -> None:
        self.assertEqual(self.call(agent.stop, {})[0], 0)
        (self.root / "a.py").write_text("x=2\n")
        self.assertEqual(self.call(agent.stop, {}, prek=None)[0], 0)
        self.assertEqual(self.calls, [])


class SessionStart(Hooks):
    def test_installs_the_missing_git_hooks(self) -> None:
        rc, out, _ = self.call(agent.session_start, {})
        self.assertEqual(rc, 0)
        argv = self.calls[0]
        self.assertEqual(argv[:4], ["/bin/prek", "install", "-c", agent.CONFIG])
        self.assertEqual(argv.count("--hook-type"), 2)
        self.assertIn("Installed the git hooks", out)

    def test_leaves_installed_hooks_alone(self) -> None:
        hooks = self.root / ".git" / "hooks"
        for name in agent.HOOK_TYPES:
            (hooks / name).write_text("#!/bin/sh\n# File generated by prek\n")
        rc, out, _ = self.call(agent.session_start, {})
        self.assertEqual(rc, 0)
        self.assertEqual(self.calls, [])
        self.assertNotIn("Installed", out)

    def test_without_a_config_or_prek_it_does_nothing_harmful(self) -> None:
        self.assertEqual(self.call(agent.session_start, {}, prek=None)[0], 0)
        (self.root / agent.CONFIG).unlink()
        self.assertEqual(self.call(agent.session_start, {})[0], 0)
        self.assertEqual(self.calls, [])


class Report(unittest.TestCase):
    def test_only_the_failures_remain(self) -> None:
        out = (
            "forbidden files......................................(no files to check)Skipped\n"
            "trim trailing whitespace.................................................Passed\n"
            "ruff.....................................................................Failed\n"
            "- hook id: ruff\n"
            "  x.py:1:4: E702 Multiple statements\n"
            "ruff-format..............................................................Passed\n"
        )
        self.assertEqual(
            agent._failures(out).splitlines(),
            [
                "ruff.....................................................................Failed",
                "- hook id: ruff",
                "  x.py:1:4: E702 Multiple statements",
            ],
        )


class Payload(unittest.TestCase):
    def test_bad_input_is_an_empty_payload(self) -> None:
        for text in ("", "not json", "[1]"):
            with (
                self.subTest(text=text),
                mock.patch.object(agent.sys, "stdin", io.StringIO(text)),
            ):
                self.assertEqual(agent._payload(), {})

    def test_the_payload_is_read(self) -> None:
        with mock.patch.object(agent.sys, "stdin", io.StringIO(json.dumps({"a": 1}))):
            self.assertEqual(agent._payload(), {"a": 1})

    def test_outside_a_work_tree_nothing_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            os.chdir(tmp)
            try:
                with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": tmp}):
                    self.assertIsNone(agent._root())
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()


class Rendered(SyncCase):
    """``ide.agents`` through sync (the example-org profile turns it on)."""

    def synced(self) -> Path:
        root = self.profile_fixture("standards-addons", "example-org")
        self.write(root)
        self.commit(root)
        return root

    def test_the_files_and_their_hooks(self) -> None:
        root = self.synced()
        agents = (root / "AGENTS.md").read_text()
        self.assertTrue(agents.startswith("<!-- odoo-nix:begin agents -->\n"))
        self.assertTrue(agents.endswith("<!-- odoo-nix:end agents -->\n"))
        self.assertEqual((root / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        settings = (root / ".claude/settings.json").read_text()
        # The json filter ends the file with its one newline; prettier refuses two.
        self.assertTrue(settings.endswith("}\n") and not settings.endswith("\n\n"))
        hooks = json.loads(settings)["hooks"]
        self.assertEqual(sorted(hooks), ["PreToolUse", "SessionStart", "Stop"])
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash")
        for event, name in (
            ("SessionStart", "session-start"),
            ("PreToolUse", "pre-bash"),
            ("Stop", "stop"),
        ):
            command = hooks[event][0]["hooks"][0]["command"]
            self.assertIn(f"odoo-nix agent hook {name}", command)
            self.assertIn(
                f"nix develop --no-pure-eval .#odoo-nix-lint -c odoo-nix agent hook {name}",
                command,
            )

    def test_a_repositorys_own_agents_md_stays(self) -> None:
        root = self.profile_fixture("standards-addons", "example-org")
        (root / "AGENTS.md").write_text("# Notes\n\nUse the shop vocabulary.\n")
        self.write(root)
        text = (root / "AGENTS.md").read_text()
        self.assertTrue(text.startswith("# Notes\n\nUse the shop vocabulary.\n"))
        self.assertIn("<!-- odoo-nix:begin agents -->", text)
        self.check(root)

    def test_off_takes_it_back(self) -> None:
        root = self.synced()
        profile = root / ".standards-profile" / "profile.toml"
        profile.write_text(profile.read_text().replace("agents = true\n", ""))
        self.write(root)
        for path in ("CLAUDE.md", ".claude/settings.json"):
            self.assertFalse((root / path).exists(), path)
        agents = root / "AGENTS.md"
        # The block goes; a file that held only the block stays, empty.
        self.assertEqual(agents.read_text(), "")
