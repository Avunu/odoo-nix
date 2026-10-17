"""odoo-nix's pr-policy check (.github/workflows/pr-policy.yml; README "Versioning").

A pull request passes when:

1. its base is the integration branch (``--base-branch``, default ``main``), or
   the head branch of another open pull request (a stacked one);
2. its title passes ``committed --commit-file`` (committed.toml) and marks no
   major bump;
3. every commit in ``git rev-list --no-merges base..head`` passes
   ``committed <sha>`` and marks no major bump.

A major bump is a ``type!:`` subject or a ``BREAKING CHANGE:`` footer. Both are
refused: an odoo-nix major release is a deliberate ``Release-As: <N>.0.0``
footer, which this check lets through.

A pull request Dependabot opened is held to every rule but one: committed's
``subject_length``. Its titles for SHA-pinned actions carry two 40-character
SHAs, so they run past the limit, and pr-policy, being required, would keep
them from ever merging. The author comes from the event's
``pull_request.user.login`` (``PR_AUTHOR``) or, on a dispatch, from the pull
request lookup; never from ``github.actor``, which whoever re-runs a job
changes.

It reads the environment the workflow passes: ``EVENT_NAME``, ``BASE_REF``,
``HEAD_SHA``, ``PR_TITLE``, ``PR_AUTHOR``, ``REF_NAME``, and ``GH_TOKEN`` for ``gh``. On a
``workflow_dispatch`` (release.yml dispatches it on the release pull request,
whose GITHUB_TOKEN push raises no event) the pull request is looked up with
``gh pr list --head $REF_NAME``; its head must be ``HEAD_SHA``. No open pull
request passes.

Exit 0 when it passes, 1 when it does not, 2 for a bad argument or environment.
Standard library only, 3.11 syntax: it runs on the runner's own python3.

Run: python3 -I lib/pr_policy.py [--base-branch main]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

_BANG = re.compile(r"^[A-Za-z]+(\([^)]*\))?!:")
_BREAKING = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)

#: Dependabot as the event names it (``dependabot[bot]``) and as ``gh`` does
#: (``app/dependabot``).
DEPENDABOT = frozenset({"dependabot[bot]", "app/dependabot"})

WHY = "an odoo-nix major release is made only with a `Release-As: <N>.0.0` footer"


class EnvError(Exception):
    """A missing tool, variable or ref: exit 2, not a policy failure."""


def message_problems(text: str) -> list[str]:
    """The major-bump markers in a commit message or title."""
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    subject = next((line for line in lines if line.strip()), "")
    out = []
    if _BANG.match(subject):
        out.append(f"{subject!r}: `!` marks a major bump, and {WHY}")
    if _BREAKING.search("\n".join(lines)):
        out.append(f"a BREAKING CHANGE footer marks a major bump, and {WHY}")
    return out


def _run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise EnvError(f"{cmd[0]} is not on PATH") from e


def git(root: str, *args: str) -> str:
    proc = _run(["git", *args], cwd=root)
    if proc.returncode != 0:
        raise EnvError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def committed(root: str, *args: str, config: str | None = None) -> tuple[bool, str]:
    """``committed`` with committed.toml, or with ``config`` when one is given."""
    proc = _run(
        ["committed", *(["--config", config] if config else []), *args], cwd=root
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def gh_json(*args: str) -> list[dict]:
    proc = _run(["gh", *args])
    if proc.returncode != 0:
        raise EnvError(f"gh {' '.join(args)}: {proc.stderr.strip() or proc.returncode}")
    data = json.loads(proc.stdout or "[]")
    return data if isinstance(data, list) else []


def base_problem(base: str, integration: str, number: str) -> str | None:
    """Check 1."""
    if base == integration:
        return None
    heads = gh_json(
        "pr", "list", "--state", "open", "--limit", "500", "--json", "headRefName"
    )
    if base in {pr.get("headRefName") for pr in heads}:
        return None
    return f"the base is {base!r}, not {integration!r}: retarget: gh pr edit {number} --base {integration}"


def without_subject_length(root: str, path: str) -> None:
    """Write committed.toml to ``path`` with ``subject_length = 0`` (no limit)."""
    with open(os.path.join(root, "committed.toml")) as f:
        text = f.read()
    text, n = re.subn(r"(?m)^subject_length\s*=.*$", "subject_length = 0", text)
    if not n:
        text += "\nsubject_length = 0\n"
    with open(path, "w") as f:
        f.write(text)


def title_problems(root: str, title: str, config: str | None = None) -> list[str]:
    """Check 2."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(title + "\n")
    try:
        ok, msg = committed(root, "--commit-file", f.name, config=config)
    finally:
        os.unlink(f.name)
    out = [] if ok else [f"title: committed: {msg}"]
    return out + [f"title: {p}" for p in message_problems(title)]


def commit_problems(
    root: str, base: str, head: str, config: str | None = None
) -> list[str]:
    """Check 3."""
    for ref in (f"origin/{base}", base):
        if (
            _run(
                ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                cwd=root,
            ).returncode
            == 0
        ):
            break
    else:
        raise EnvError(
            f"the base branch {base!r} is not fetched (actions/checkout: fetch-depth: 0)"
        )
    out = []
    for sha in git(root, "rev-list", "--no-merges", head, f"^{ref}").split():
        ok, msg = committed(root, sha, config=config)
        if not ok:
            out.append(f"commit {sha[:12]}: committed: {msg}")
        text = git(root, "log", "-1", "--format=%B", sha)
        out += [f"commit {sha[:12]}: {p}" for p in message_problems(text)]
    return out


def check_pr(root: str, integration: str, env: dict[str, str]) -> list[str]:
    head = env.get("HEAD_SHA", "")
    title = env.get("PR_TITLE", "")
    base = env.get("BASE_REF", "")
    author = env.get("PR_AUTHOR", "")
    m = re.match(r"refs/pull/(\d+)/", env.get("GITHUB_REF", ""))
    number = m[1] if m else "<n>"
    if env.get("EVENT_NAME") == "workflow_dispatch":
        ref = env.get("REF_NAME", "")
        prs = gh_json(
            "pr",
            "list",
            "--head",
            ref,
            "--state",
            "open",
            "--json",
            "number,title,baseRefName,headRefOid,author",
        )
        if not prs:
            print(f"pr-policy: no open pull request for {ref!r}; nothing to check")
            return []
        pr = prs[0]
        number = str(pr.get("number"))
        if pr.get("headRefOid") != head:
            return [
                f"stale dispatch: #{number} is at {pr.get('headRefOid')}, this run at {head}"
            ]
        title, base = pr.get("title") or "", pr.get("baseRefName") or ""
        author = (pr.get("author") or {}).get("login") or ""
        if not title or not base:
            return [
                f"#{number}: the lookup returned no title or base; refusing to check an empty value"
            ]
    if not base:
        raise EnvError(
            "BASE_REF is empty (set it from github.event.pull_request.base.ref)"
        )
    if not head:
        raise EnvError("HEAD_SHA is empty")
    out = []
    problem = base_problem(base, integration, number)
    if problem:
        out.append(problem)
    if author not in DEPENDABOT:
        return out + title_problems(root, title) + commit_problems(root, base, head)
    print(f"pr-policy: opened by {author}: committed's subject_length is not checked")
    with tempfile.TemporaryDirectory() as tmp:
        config = os.path.join(tmp, "committed.toml")
        without_subject_length(root, config)
        out += title_problems(root, title, config)
        return out + commit_problems(root, base, head, config)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--base-branch", default="main", help="the integration branch (default: main)"
    )
    args = p.parse_args(argv)
    try:
        root = git(os.getcwd(), "rev-parse", "--show-toplevel")
        found = check_pr(root, args.base_branch, dict(os.environ))
    except EnvError as e:
        print(f"pr-policy: {e}", file=sys.stderr)
        return 2
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    for problem in found:
        print(f"::error::{problem}" if gha else problem, file=sys.stderr)
    if not found:
        print("pr-policy: ok")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
