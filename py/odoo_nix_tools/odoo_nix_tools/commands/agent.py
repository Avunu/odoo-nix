"""``odoo-nix agent hook EVENT`` (``ide.agents``): what Claude Code's hooks run so an agent
passes CI the first time. The pre-commit hooks are installed per clone by the dev shell's
entry, which a fresh clone, a worktree or an agent outside direnv never enters; these
events do what that entry does and run the checks CI runs.

``session-start``: install the git hooks (``prek install``) where they are missing, and
say so.

``pre-bash``: before a ``git push`` or ``gh pr create|ready``, run the lint gate
(``odoo-nix gate lint``) and refuse the command while a step fails. A gate that cannot
run (no network for the base branch, a tool missing) is reported, not a refusal.

``stop``: run the pre-commit hooks (``prek run -c .pre-commit-config.yaml --files``) on the
files the working tree changed, once per stop. They are the formatters and linters CI
runs; a failure, or a file a formatter rewrote, goes back to the agent.

The payload is Claude Code's JSON on stdin. Exit 0 lets the event through; exit 2 sends
stderr back to the agent. The events check the working tree, not the editing route, so a
file rewritten by a script is checked too.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from standards_core.commands import Command, help_text

if TYPE_CHECKING:
    from standards_core.product import Product

EVENTS = ("session-start", "pre-bash", "stop")
CONFIG = ".pre-commit-config.yaml"
HOOK_TYPES = ("pre-commit", "commit-msg")
# A push that CI would judge: `git push` (with options before it), a pull request opened
# or marked ready.
PUSH = re.compile(
    r"\b(?:git\s+(?:(?:-C|-c|--git-dir|--work-tree)\s+\S+\s+|-\S+\s+)*push"
    r"|gh\s+pr\s+(?:create|ready))\b"
)
# How much of a failing tool's output goes back to the agent.
TAIL = 12000
BLOCK = 2
GATE_FAILED = 1


def _payload() -> dict[str, Any]:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _run(argv: list[str], cwd: Path) -> tuple[int, str]:
    """``argv``'s exit status and its output, stdout and stderr together."""
    try:
        done = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError as err:
        return 127, str(err)
    return done.returncode, done.stdout + done.stderr


# prek's line for a hook that passed or had nothing to check.
QUIET = re.compile(r"\.{3,}\s*(?:\(no files to check\))?(?:Passed|Skipped)$")


def _failures(text: str) -> str:
    """``text`` (prek's report) less the lines of the hooks that passed or skipped."""
    return "\n".join(line for line in text.splitlines() if not QUIET.search(line))


def _tail(text: str) -> str:
    text = text.strip()
    return text if len(text) <= TAIL else "…\n" + text[-TAIL:]


def _root() -> Path | None:
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(top)


def _hooks_installed(root: Path, hook_type: str) -> bool:
    rc, path = _run(["git", "rev-parse", "--git-path", f"hooks/{hook_type}"], root)
    if rc != 0:
        return False
    path = path.strip()
    file = Path(path) if Path(path).is_absolute() else root / path
    try:
        return "prek" in file.read_text()
    except OSError:
        return False


def session_start(root: Path, payload: dict[str, Any]) -> int:
    if not (root / CONFIG).is_file():
        return 0
    prek = shutil.which("prek")
    if prek is None:
        print(
            "prek is not on PATH: enter the lint shell (`nix develop --no-pure-eval "
            ".#odoo-nix-lint`) to install the git hooks."
        )
        return 0
    missing = [t for t in HOOK_TYPES if not _hooks_installed(root, t)]
    if missing:
        argv = [prek, "install", "-c", CONFIG]
        for hook_type in missing:
            argv += ["--hook-type", hook_type]
        rc, out = _run(argv, root)
        if rc != 0:
            print(f"Installing the git hooks failed (exit {rc}):\n{_tail(out)}")
            return 0
        print(f"Installed the git hooks ({', '.join(missing)}): commits are checked.")
    print(
        "Before a push, CI's gates must pass: `odoo-nix gate lint` (and `odoo-nix gate "
        "test` for addon code). AGENTS.md has the commands."
    )
    return 0


def pre_bash(root: Path, payload: dict[str, Any]) -> int:
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if not PUSH.search(command):
        return 0
    rc, out = _run(["odoo-nix", "gate", "lint"], root)
    if rc == 0:
        return 0
    if rc == GATE_FAILED:
        print(
            "CI's lint gate (`odoo-nix gate lint`) fails; fix these, then push:\n\n"
            f"{_tail(out)}",
            file=sys.stderr,
        )
        return BLOCK
    print(
        f"The lint gate could not run (exit {rc}); pushing without it:\n{_tail(out)}",
        file=sys.stderr,
    )
    return 0


def _changed(root: Path) -> list[str]:
    """The files the working tree changed against HEAD (modified, added, renamed,
    untracked), still on disk."""
    rc, out = _run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"], root
    )
    if rc != 0:
        return []
    entries = out.split("\0")
    paths = [e[3:] if len(e) > 3 and e[2] == " " else e for e in entries if e]
    return [p for p in paths if (root / p).is_file()]


def stop(root: Path, payload: dict[str, Any]) -> int:
    if payload.get("stop_hook_active") or not (root / CONFIG).is_file():
        return 0
    prek = shutil.which("prek")
    files = _changed(root)
    if prek is None or not files:
        return 0
    rc, out = _run([prek, "run", "-c", CONFIG, "--files", *files], root)
    if rc == 0:
        return 0
    print(
        "The pre-commit hooks CI runs fail on the files you changed (formatters may "
        f"have rewritten some already; stage them):\n\n{_tail(_failures(out))}\n\nFix these before "
        "you finish: the commit hook and CI refuse them too.",
        file=sys.stderr,
    )
    return BLOCK


HANDLERS = {"session-start": session_start, "pre-bash": pre_bash, "stop": stop}


def run(args: argparse.Namespace) -> int:
    payload = _payload()
    root = _root()
    if root is None:
        return 0
    return HANDLERS[args.event](root, payload)


def register(sub: argparse._SubParsersAction, product: Product) -> None:
    p = sub.add_parser(
        "agent",
        help="the checks Claude Code's hooks run for an agent: session-start, pre-bash, stop",
        description=help_text(product, "agent", __doc__ or ""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    steps = p.add_subparsers(dest="step", required=True, metavar="STEP")
    h = steps.add_parser(
        "hook", help="handle one hook event (Claude Code's JSON on stdin)"
    )
    h.add_argument("event", choices=EVENTS)
    p.set_defaults(func=run)


AGENT = Command("agent", register)
