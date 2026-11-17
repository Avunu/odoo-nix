"""The jobs of the reusable workflows that can hold the CI App's key (checks.app-key-jobs).

    python app_key_jobs.py GITHUB_DIR TEMPLATES_DIR ODOO_NIX_TOOLS_DIR

Static, over .github (its workflows and dependabot.yml) and the caller templates, and offline: git, bash and jq on
PATH, and standards_core importable (its relock.input_node is what the jq program must agree
with). ODOO_NIX_TOOLS_DIR (py/odoo_nix_tools) is put on sys.path, and a stand-in `odoo-nix`
runs its CLI, for the key jobs' patch checks.

- Every job that mints the CI App's token or reads its key (APP_PRIVATE_KEY,
  AVUNU_CI_PRIVATE_KEY) runs on ubuntu-latest, written so; the set of them is pinned here,
  and none of them runs the repository's code (no nix, npm, yarn, node, git submodule).
- The jobs that run the repository's code and fetch private submodules (odoo-test's test,
  odoo-deps' project-update-plan) take SUBMODULE_PRIVATE_KEY only. Whenever it is passed,
  they first mint a metadata:read token of its installation on the owner and refuse an App
  that can do more (and a key with no client ID), before any of that code runs and
  whether or not a submodule needs a token; then a contents:read token for the owner's
  submodule repositories GITHUB_TOKEN cannot read (none: no token) fetches them.
  odoo-test.yml declares no APP_PRIVATE_KEY, and the ci.yml template passes it none.
  project-update, which runs none of it, mints the same read token to read the private
  submodules' branch tips.
- A job that calls a reusable workflow passes APP_PRIVATE_KEY, AVUNU_CI_PRIVATE_KEY or
  `secrets: inherit` only if it is allowlisted here.
- In the key jobs, odoo-nix-tools comes from standards-install's `hardened` mode
  (Avunu/odoo-nix only, py/odoo_nix_tools, standards-core from Avunu/python-devops-nix),
  before the token is minted; no `uv tool`, `uvx` or pip install of their own, no setup-uv
  with a cache, and no cache action at all.
- relock-plan runs on ubuntu-latest. relock-push builds on the event's head SHA, recomputes
  `moved`, refuses before it applies, checks the patch's paths and then its content
  (`odoo-nix verify-patch relock`) before the token, and pushes without force; automerge
  recomputes `moved` with the same step, runs only when relock-plan succeeded or was
  skipped, and reads which from its result; neither reads relock-plan's `moved`. `hold`
  turns off auto-merge with GITHUB_TOKEN when any of the three did not succeed, on this
  run's head only; its script is run here on its cases.
- project-update-plan runs on ubuntu-latest. project-update checks out the base itself,
  stages the plan's patch in the index, runs `odoo-nix verify-patch project-update`, then
  `--tips` (each moved submodule is its .gitmodules branch's tip, `git ls-remote`) before
  the token, and pushes a new branch without force.
- The patch checks are run here on accepted and refused patches (flake.lock, .gitmodules,
  workflows and lock content among the refused), the automerge relock-state step on its
  cases, and the jq `moved` program against standards_core's input_node.
- package (the addon's build) runs on ubuntu-latest with no cache; repackage runs on
  ubuntu-latest; upload checks the dispatch's repackage tag before it mints the token.
- Dependabot holds the github-actions and uv (py/odoo_nix_tools) bumps for review.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from standards_core.ci.relock import input_node

GITHUB = Path(sys.argv[1])
WORKFLOWS = GITHUB / "workflows"
TEMPLATES = Path(sys.argv[2])
TOOLS = Path(sys.argv[3]).resolve()
MAIN_KEYS = ("secrets.APP_PRIVATE_KEY", "secrets.AVUNU_CI_PRIVATE_KEY")
SUB_KEY = "secrets.SUBMODULE_PRIVATE_KEY"
CACHES = ("actions/cache", "magic-nix-cache-action", "cache-nix-action")
HARDENED = {
    "odoo-release.yml": {"release"},
    "odoo-release-please.yml": {"release-please", "sync", "upload"},
    "odoo-deps.yml": {"relock-push", "automerge", "update-branches", "project-update"},
}
# The jobs that install odoo-nix-tools (upload runs gh alone).
INSTALLERS = {
    "odoo-release.yml": {"release"},
    "odoo-release-please.yml": {"release-please", "sync"},
    "odoo-deps.yml": {"relock-push", "automerge", "update-branches", "project-update"},
}
# Run the repository's code; fetch private submodules with the read-only App only.
SUBMODULE = {("odoo-test.yml", "test"), ("odoo-deps.yml", "project-update-plan")}
# Hold the CI App's key, run none of the repository's code, and read the private
# submodules' branch tips with the read-only App.
SUBMODULE_TIPS = {("odoo-deps.yml", "project-update")}
# Callers of a reusable workflow that may pass the CI App's key: python-devops-nix's
# Dependabot workflows, whose jobs that hold it run on hosted runners and run no PR code.
PASS_KEY = {
    ("dependabot-auto-merge.yml", "auto-merge"),
    ("dependabot-auto-merge.yml", "update-branches"),
}
REFUSE_NAME = "Refuse a submodule App that can write"
REFUSE_JQ = (
    '.permissions | to_entries[] | select((.key != "contents" and .key != "metadata")'
    ' or .value != "read")'
)


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def uses(step: dict) -> str:
    return step.get("uses", "").split("@")[0]


def index(steps: list[dict], pred) -> int:
    return next(i for i, s in enumerate(steps) if pred(s))


def token_at(steps: list[dict]) -> int:
    return index(steps, lambda s: "create-github-app-token" in s.get("uses", ""))


def runs_code(step: dict) -> bool:
    """Whether a step runs the repository's code: Nix, npm and the like, or a submodule
    checkout's hooks."""
    for line in step.get("run", "").splitlines():
        line = line.strip()
        if line.startswith(("#", "echo ")):
            continue
        if re.search(
            r"(^|\$\(|&&|\|\||;|\|)\s*(\S+=\S+\s+)*(nix|npm|yarn|node)\s", line
        ):
            return True
        if "git submodule update" in line:
            return True
    return False


# 1. Who holds which key, and where it runs.
main_holders: dict[str, set[str]] = {}
sub_holders: set[tuple[str, str]] = set()
for path in sorted(WORKFLOWS.glob("*.yml")):
    doc = yaml.safe_load(path.read_text())
    for name, job in doc["jobs"].items():
        text = json.dumps(job)
        if "uses" in job:
            passes = (
                any(k in text for k in MAIN_KEYS) or job.get("secrets") == "inherit"
            )
            assert not passes or (path.name, name) in PASS_KEY, (
                path.name,
                name,
                "passes the CI App's key to a reusable workflow",
            )
            continue
        main = any(k in text for k in MAIN_KEYS)
        sub = SUB_KEY in text
        assert not (main and sub) or (path.name, name) in SUBMODULE_TIPS, (
            path.name,
            name,
            "both keys",
        )
        for s in job.get("steps", []):
            if "create-github-app-token" in s.get("uses", ""):
                key = s["with"]["private-key"]
                assert key in ("${{ " + k + " }}" for k in (*MAIN_KEYS, SUB_KEY)), (
                    path.name,
                    name,
                    key,
                )
        if main:
            main_holders.setdefault(path.name, set()).add(name)
            assert job["runs-on"] == "ubuntu-latest", (path.name, name, job["runs-on"])
            for s in job["steps"]:
                assert not runs_code(s), (path.name, name, s)
        if sub:
            sub_holders.add((path.name, name))
assert main_holders == HARDENED, main_holders
assert sub_holders == SUBMODULE | SUBMODULE_TIPS, sub_holders

# The submodule App: refused before any code runs when it can do more than read contents,
# whenever its key is passed; then a contents:read token for the private submodules only.
for wf, name in SUBMODULE:
    job = load(wf)["jobs"][name]
    steps = job["steps"]
    app = index(steps, lambda s: s.get("id") == "app")
    assert (
        steps[app]["env"]["ENABLED"] == "${{ secrets.SUBMODULE_PRIVATE_KEY != '' }}"
    ), (
        wf,
        steps[app],
    )
    t = token_at(steps)
    assert steps[t]["id"] == "app-check", (wf, steps[t])
    assert steps[t]["if"] == "steps.app.outputs.enabled == 'true'", (wf, steps[t])
    w = steps[t]["with"]
    assert w == {
        "client-id": "${{ inputs.submodule-client-id }}",
        "private-key": "${{ secrets.SUBMODULE_PRIVATE_KEY }}",
        "owner": "${{ github.repository_owner }}",
        "permission-metadata": "read",
    }, (wf, w)
    refuse = steps[t + 1]
    assert refuse["name"] == REFUSE_NAME, (wf, refuse)
    assert refuse["if"] == "steps.app.outputs.enabled == 'true'", (wf, refuse)
    assert refuse["env"] == {
        "GH_TOKEN": "${{ steps.app-check.outputs.token }}",
        "SLUG": "${{ steps.app-check.outputs.app-slug }}",
    }, refuse
    assert REFUSE_JQ in refuse["run"], refuse["run"]
    assert "exit 1" in refuse["run"], refuse["run"]
    # The fetch token: only the owner's repositories GITHUB_TOKEN cannot read, since asking
    # for one the App is not installed on is refused (HTTP 422), so a public one is never
    # asked for.
    fetch = index(steps, lambda s: s.get("id") == "app-token")
    repos = index(steps, lambda s: s.get("id") == "repos")
    assert t + 1 < repos < fetch, (wf, t, repos, fetch)
    fw = steps[fetch]["with"]
    assert fw["private-key"] == "${{ secrets.SUBMODULE_PRIVATE_KEY }}", (wf, fw)
    assert fw["client-id"] == "${{ inputs.submodule-client-id }}", (wf, fw)
    assert fw["repositories"] == "${{ steps.repos.outputs.repositories }}", (wf, fw)
    perms = {k: v for k, v in fw.items() if k.startswith("permission-")}
    assert perms == {"permission-contents": "read"}, (wf, perms)
    assert steps[fetch]["if"] == "steps.repos.outputs.repositories != ''", steps[fetch]
    assert ".visibility" in steps[repos]["run"] and "!= public" in steps[repos]["run"]
    assert steps[repos]["env"]["GH_TOKEN"] == "${{ github.token }}", steps[repos]
    # Every step that names the key comes after the `app` step and is one of the two mints.
    for i, s in enumerate(steps):
        if SUB_KEY in json.dumps(s) and i != app:
            assert i in (t, fetch), (wf, i, s)
    first_code = index(steps, runs_code)
    assert t + 1 < first_code, (wf, name, "code runs before the refusal")
    # The `app` step: a key with no client ID stops the job.
    for enabled, client, ok in (
        ("true", "Iv1.x", True),
        ("true", "", False),
        ("false", "", True),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            env = {
                **os.environ,
                "ENABLED": enabled,
                "CLIENT_ID": client,
                "SAME": "false",
                "GITHUB_OUTPUT": out,
            }
            code = subprocess.run(
                ["bash", "-c", steps[app]["run"]],
                check=False,
                env=env,
                capture_output=True,
            ).returncode
        assert (code == 0) == ok, (wf, enabled, client, code)
    # No main key, no write permission for GITHUB_TOKEN.
    assert set(job["permissions"]) == {"contents"}, job["permissions"]
    assert job["permissions"]["contents"] == "read", job["permissions"]

test_wf = load("odoo-test.yml")
call = test_wf[True]["workflow_call"]
assert set(call["secrets"]) == {"SUBMODULE_PRIVATE_KEY"}, call["secrets"]
assert "client-id" not in call["inputs"], call["inputs"]
ci_template = (TEMPLATES / "ci.yml.j2").read_text()
assert "app_secrets" not in ci_template and "app_with" not in ci_template, "ci.yml.j2"
assert "APP_PRIVATE_KEY" not in ci_template, "ci.yml.j2"
assert "secret_block(main=false, submodule=true)" in ci_template, "ci.yml.j2"
uses_template = (TEMPLATES / "_uses.j2").read_text()
assert "SUBMODULE_PRIVATE_KEY:" in uses_template, "_uses.j2"

# 2. What the key jobs install, and before what.
for wf, names in HARDENED.items():
    doc = load(wf)
    for name in names:
        steps = doc["jobs"][name]["steps"]
        installs = [
            i
            for i, s in enumerate(steps)
            if uses(s) == "Avunu/python-devops-nix/.github/actions/standards-install"
        ]
        assert len(installs) == (name in INSTALLERS[wf]), (wf, name, installs)
        for i in installs:
            w = steps[i]["with"]
            assert w.get("hardened") == "true", (wf, name, w)
            assert w.get("source") == "Avunu/odoo-nix", (wf, name, w)
            assert w.get("project") == "py/odoo_nix_tools", (wf, name, w)
            assert w.get("git-sources") == "Avunu/python-devops-nix", (wf, name, w)
            assert re.fullmatch(
                r"[0-9a-f]{40}", steps[i]["uses"].split("@")[1].split()[0]
            ), steps[i]
            assert i < token_at(steps), (wf, name, "install after the token")
        for s in steps:
            assert not any(c in uses(s) for c in CACHES), (wf, name, uses(s))
            if uses(s) == "astral-sh/setup-uv":
                assert s.get("with", {}).get("enable-cache") == "false", (wf, name, s)
            run = s.get("run", "")
            assert not re.search(r"\buv (tool|run)\b|\buvx\b|\bpip install\b", run), (
                wf,
                name,
                run,
            )
            for line in run.splitlines():
                assert (line.split() or [""])[0] not in (
                    "nix",
                    "npm",
                    "yarn",
                    "node",
                ), (wf, name, line)

# 3. relock-plan, relock-push and automerge.
deps = load("odoo-deps.yml")
plan, push, auto = (
    deps["jobs"][n] for n in ("relock-plan", "relock-push", "automerge")
)
assert plan["runs-on"] == "ubuntu-latest", plan["runs-on"]
assert plan["permissions"] == {"contents": "read"}, plan["permissions"]
assert "secrets." not in json.dumps(plan), "relock-plan holds a secret"
assert "moved" not in plan["outputs"], plan["outputs"]
steps = push["steps"]
assert steps[0]["uses"].startswith("actions/checkout@"), steps[0]
assert steps[0]["with"]["ref"] == "${{ github.event.pull_request.head.sha }}", steps[0]
assert "github.head_ref" not in json.dumps(steps[0]), steps[0]
ids = [s.get("id") for s in steps]
refuse = index(steps, lambda s: s.get("if") == "steps.moved.outputs.moved != ''")
check = index(
    steps, lambda s: s.get("name", "").startswith("Check and apply the relock patch")
)
download = index(steps, lambda s: uses(s) == "actions/download-artifact")
install = index(
    steps,
    lambda s: uses(s) == "Avunu/python-devops-nix/.github/actions/standards-install",
)
verify = index(steps, lambda s: "odoo-nix verify-patch relock" in s.get("run", ""))
assert (
    ids.index("moved") < refuse < download < check < install < verify < token_at(steps)
), (ids, refuse, check, install, verify)
# The install and the base checkout are no longer behind `inputs.auto-merge`.
assert "if" not in steps[install], steps[install]
assert "if" not in steps[install - 1], steps[install - 1]
assert steps[verify]["run"].strip() == "odoo-nix verify-patch relock --base HEAD", (
    steps[verify]
)
assert "if" not in steps[verify] and "working-directory" not in steps[verify], steps[
    verify
]
assert [uses(s) for s in steps if uses(s)] == [
    "actions/checkout",
    "actions/download-artifact",
    "actions/checkout",
    "Avunu/python-devops-nix/.github/actions/standards-install",
    "actions/create-github-app-token",
], [uses(s) for s in steps]
pushes = [s["run"] for s in steps if "git push" in s.get("run", "")]
assert len(pushes) == 1, pushes
assert '"HEAD:refs/heads/$HEAD_REF"' in pushes[0], pushes[0]
assert not re.search(r"--force|\s-f\s|\+HEAD", pushes[0]), pushes[0]
merge = next(s for s in steps if "enable-automerge" in s.get("run", ""))
assert '--head-sha "$HEAD_SHA"' in merge["run"], merge
assert merge["env"]["HEAD_SHA"] == "${{ steps.push.outputs.sha }}", merge["env"]
allow = steps[check]["env"]["ALLOW"]
script = steps[check]["run"]
moved_runs = set()
for name, job in (("relock-push", push), ("automerge", auto)):
    assert "relock-plan.outputs.moved" not in json.dumps(job), name
    js = job["steps"]
    m = [s.get("id") for s in js].index("moved")
    assert m < token_at(js), name
    moved_runs.add(js[m]["run"])
assert len(moved_runs) == 1, "one moved step"
decide = next(
    s for s in auto["steps"] if "standards-deps-automerge" in s.get("uses", "")
)
assert decide["with"]["moved"] == "${{ steps.moved.outputs.moved }}", decide["with"]
assert decide["with"]["relock"] == "${{ steps.relock.outputs.relock }}", decide["with"]
relock_step = next(s for s in auto["steps"] if s.get("id") == "relock")
assert relock_step["env"]["MOVED"] == "${{ steps.moved.outputs.moved }}", relock_step[
    "env"
]
assert relock_step["env"]["PLAN"] == "${{ needs.relock-plan.result }}", relock_step[
    "env"
]
# automerge runs only on a plan that succeeded or was skipped; a failed one is `hold`'s.
assert auto["needs"] == "relock-plan", auto["needs"]
assert (
    "(needs.relock-plan.result == 'success' || needs.relock-plan.result == 'skipped')"
    in auto["if"]
), auto["if"]


def relock_state(
    plan_result, state, empty="", moved="", files="flake.lock"
) -> str | None:
    """automerge's relock step, run with a stand-in gh; its `relock` output, or None when
    it fails (the PR is left for review)."""
    with tempfile.TemporaryDirectory() as tmp:
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        gh = os.path.join(bindir, "gh")
        Path(gh).write_text("#!/bin/sh\nprintf '%s\\n' $FILES\n")
        os.chmod(gh, 0o755)
        out = os.path.join(tmp, "out")
        Path(out).write_text("")
        env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "PLAN": plan_result,
            "STATE": state,
            "EMPTY": empty,
            "MOVED": moved,
            "FILES": files,
            "REPO": "o/r",
            "NUMBER": "1",
            "GITHUB_OUTPUT": out,
        }
        done = subprocess.run(
            ["bash", "-c", relock_step["run"]],
            env=env,
            capture_output=True,
            check=False,
        )
        if done.returncode != 0:
            return None
        found = re.search(r"^relock=(.*)$", Path(out).read_text(), re.MULTILINE)
        assert found, Path(out).read_text()
        return found.group(1)


assert relock_state("skipped", "") == ""
assert relock_state("success", "") is None, "a plan that ran and said nothing"
assert relock_state("success", "ok", "false") == "patch"
assert relock_state("success", "ok", "true") == "empty"
assert relock_state("success", "ok", "true", files="flake.lock x.py") is None
assert relock_state("success", "rollout-input-moved") is None
assert relock_state("success", "ok", "false", moved="odoo-nix") == "rollout-input-moved"
assert relock_state("skipped", "", moved="odoo-nix") == ""

# 3a. hold: a head no key job decided gets auto-merge turned off, with GITHUB_TOKEN only.
hold = deps["jobs"]["hold"]
assert hold["needs"] == ["relock-plan", "relock-push", "automerge"], hold["needs"]
assert hold["runs-on"] == "ubuntu-latest", hold["runs-on"]
assert hold["permissions"] == {"contents": "write", "pull-requests": "write"}, hold[
    "permissions"
]
assert "secrets." not in json.dumps(hold), "hold holds a secret"
hold_if = " ".join(hold["if"].split())
for want in (
    "always()",
    "github.event.pull_request.user.login == 'dependabot[bot]'",
    "inputs.auto-merge",
    "(needs.relock-plan.result != 'success' && needs.relock-plan.result != 'skipped')",
    "(needs.relock-push.result != 'success' && needs.relock-push.result != 'skipped')",
    "needs.automerge.result != 'success'",
):
    assert want in hold_if, (want, hold_if)
assert [uses(s) for s in hold["steps"] if uses(s)] == [], "hold runs gh alone"
(hold_step,) = hold["steps"]
assert hold_step["env"]["GH_TOKEN"] == "${{ github.token }}", hold_step["env"]
assert hold_step["env"]["PUSHED"] == "${{ needs.relock-push.outputs.sha }}"
assert push["outputs"]["sha"] == "${{ steps.push.outputs.sha }}", push["outputs"]


def hold_run(head, auto_merge, pushed="") -> list[str]:
    """hold's step with a stand-in gh at PR head `head`; the gh calls that change the PR."""
    with tempfile.TemporaryDirectory() as tmp:
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        log = os.path.join(tmp, "log")
        Path(log).write_text("")
        Path(bindir, "gh").write_text(
            "#!/bin/sh\n"
            'case "$*" in\n'
            '  *headRefOid*) echo "$PR_HEAD" ;;\n'
            '  *autoMergeRequest*) echo "$PR_AUTO" ;;\n'
            '  *) echo "$*" >> "$LOG" ;;\n'
            "esac\n"
        )
        os.chmod(os.path.join(bindir, "gh"), 0o755)
        env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "PR_URL": "https://github.com/o/r/pull/1",
            "HEAD_SHA": "a" * 40,
            "PUSHED": pushed,
            "PR_HEAD": head,
            "PR_AUTO": auto_merge,
            "LOG": log,
        }
        subprocess.run(
            ["bash", "-c", hold_step["run"]], env=env, check=True, capture_output=True
        )
        return Path(log).read_text().splitlines()


PR = "https://github.com/o/r/pull/1"
assert hold_run("a" * 40, "true") == [
    f"pr merge --disable-auto {PR}",
    f"pr edit {PR} --add-label needs-review",
], "this run's head, auto-merge on"
assert hold_run("a" * 40, "false") == [f"pr edit {PR} --add-label needs-review"]
assert hold_run("b" * 40, "true", pushed="b" * 40) == [
    f"pr merge --disable-auto {PR}",
    f"pr edit {PR} --add-label needs-review",
], "relock-push's commit"
assert hold_run("c" * 40, "true") == [], "a head this run is not for"

# 3b. project-update-plan and project-update.
pplan, pupd = deps["jobs"]["project-update-plan"], deps["jobs"]["project-update"]
# Its patch is pushed and auto-merged: no shared self-hosted runner makes it.
assert pplan["runs-on"] == "ubuntu-latest", pplan["runs-on"]
assert "inputs.runs-on" not in json.dumps(deps["jobs"]), "a job on runs-on"
assert pplan["permissions"] == {"contents": "read"}, pplan["permissions"]
assert not any(k in json.dumps(pplan) for k in MAIN_KEYS), "project-update-plan's key"
assert "odoo project update --no-sync" in json.dumps(pplan), "plan without --no-sync"
assert pupd["needs"] == "project-update-plan", pupd["needs"]
assert pupd["runs-on"] == "ubuntu-latest", pupd["runs-on"]
ps = pupd["steps"]
assert ps[0]["uses"].startswith("actions/checkout@"), ps[0]
assert ps[0]["with"] == {
    "ref": "${{ inputs.integration-branch }}",
    "persist-credentials": False,
}, ps[0]
same = index(ps, lambda s: s.get("name") == "The plan ran on this commit")
pinstall = index(
    ps, lambda s: uses(s) == "Avunu/python-devops-nix/.github/actions/standards-install"
)
pdownload = index(ps, lambda s: uses(s) == "actions/download-artifact")
pcheck = index(
    ps,
    lambda s: s.get("name", "").startswith("Check and stage the project-update patch"),
)
ptips = index(ps, lambda s: "--tips" in s.get("run", ""))
psub = index(ps, lambda s: s.get("id") == "sub-token")
pmain = index(ps, lambda s: s.get("id") == "app-token")
assert same < pinstall < pcheck < psub < ptips < pmain, (same, pinstall, pcheck, ptips)
assert token_at(ps) == psub, "the read token is the first"
assert pdownload < pcheck, (pdownload, pcheck)
pscript = ps[pcheck]["run"]
assert "git apply --cached" in pscript and "git apply --index" not in pscript, pscript
assert "odoo-nix verify-patch project-update --base HEAD" in pscript, pscript
tscript = ps[ptips]["run"]
assert (
    "odoo-nix verify-patch project-update --base HEAD --tips"
    ' --superproject-url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY"'
) in tscript, tscript
assert "if" not in ps[ptips], ps[ptips]
assert ps[ptips]["env"] == {
    "TOKEN": "${{ steps.sub-token.outputs.token || github.token }}"
}, ps[ptips]
sw = ps[psub]["with"]
assert sw["private-key"] == "${{ secrets.SUBMODULE_PRIVATE_KEY }}", sw
assert sw["client-id"] == "${{ inputs.submodule-client-id }}", sw
assert {k: v for k, v in sw.items() if k.startswith("permission-")} == {
    "permission-contents": "read"
}, sw
assert ps[pmain]["with"]["private-key"] == "${{ secrets.APP_PRIVATE_KEY }}", ps[pmain]
assert ps[pmain]["with"]["repositories"] == "${{ github.event.repository.name }}"
ppushes = [s["run"] for s in ps if "git push" in s.get("run", "")]
assert len(ppushes) == 1, ppushes
assert '"HEAD:refs/heads/$branch"' in ppushes[0], ppushes[0]
assert 'branch="standards/project-update-$RUN"' in ppushes[0], ppushes[0]
assert not re.search(r"--force|\s-f\s|\+HEAD", ppushes[0]), ppushes[0]
pmerge = next(s for s in ps if "enable-automerge" in s.get("run", ""))
assert pmerge["env"]["HEAD_SHA"] == "${{ steps.pr.outputs.sha }}", pmerge["env"]

# 4. The jq program against standards_core's input_node.
program = re.search(
    r"--slurpfile head \S+ '\n(.*?)'\)\"\n", moved_runs.pop(), re.DOTALL
).group(1)


def jq_moved(base: dict, head: dict) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        b, h = os.path.join(tmp, "b"), os.path.join(tmp, "h")
        Path(b).write_text(json.dumps(base))
        Path(h).write_text(json.dumps(head))
        out = subprocess.run(
            ["jq", "-rn", "--slurpfile", "base", b, "--slurpfile", "head", h, program],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    return [x for x in out.split(",") if x]


def lock(engine="a", profile="p", follows=False, extra="x", owner="Avunu") -> dict:
    nodes = {
        "root": {
            "inputs": {
                "odoo-nix": ["ocb"] if follows else "odoo-nix",
                "standards-profile": "standards-profile",
                "ocb": "ocb",
            }
        },
        "odoo-nix": {"locked": {"owner": owner, "repo": "odoo-nix", "rev": engine}},
        "standards-profile": {"locked": {"rev": profile}},
        "ocb": {"locked": {"rev": extra}},
    }
    return {"nodes": nodes, "root": "root", "version": 7}


cases = [
    (lock(), lock()),
    (lock(), lock(extra="y")),
    (lock(), lock(engine="b")),
    (lock(), lock(engine="b", profile="q")),
    (lock(), lock(profile="q")),
    (lock(), lock(follows=True)),
    (lock(), lock(owner="attacker")),
    ({"nodes": {"root": {}}, "root": "root"}, lock()),
]
for base, head in cases:
    want = [
        n
        for n in ("odoo-nix", "standards-profile")
        if input_node(base, n) != input_node(head, n)
    ]
    assert jq_moved(base, head) == want, (base, head, want)
assert jq_moved(lock(), lock(extra="y")) == []
assert jq_moved(lock(), lock(engine="b", profile="q")) == [
    "odoo-nix",
    "standards-profile",
]
assert jq_moved(lock(), lock(owner="attacker")) == ["odoo-nix"]


# 5. The patch check, run on accepted and refused patches.
def g(cwd, *args):
    return subprocess.run(
        ["git", "-C", cwd, "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def write(root, path, data: bytes, mode=0o644):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full) or root, exist_ok=True)
    Path(full).write_bytes(data)
    os.chmod(full, mode)


BASE = {
    "flake.lock": b"{}\n",
    "nix/uv.lock": b"version = 1\n",
    "nix/pyproject.toml": b"[project]\n",
    "pyproject.toml": b"[tool.odoo-nix]\n",
    ".github/workflows/ci.yml": b"name: ci\n",
}


def check_patch(change, diff_args=(), text=None) -> int:
    """relock-push's check on the patch `change(repo)` stages (or `text`), in a clean clone."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "src"), os.path.join(tmp, "dst")
        os.makedirs(src)
        g(src, "init", "-q")
        for path, data in BASE.items():
            write(src, path, data)
        g(src, "add", "-A")
        g(src, "commit", "-qm", "base")
        g(tmp, "clone", "-q", src, dst)
        if text is None:
            change(src)
            g(src, "add", "-A")
            text = g(src, "diff", "--cached", "--binary", *diff_args)
        patch = os.path.join(tmp, "x.patch")
        Path(patch).write_text(text)
        env = {**os.environ, "PATCH": patch, "ALLOW": allow, "RUNNER_TEMP": tmp}
        return subprocess.run(
            ["bash", "-c", script], check=False, cwd=dst, env=env
        ).returncode


def relock_ok(r):
    write(r, "nix/uv.lock", b"version = 1\n\x00binary\n")
    write(r, "nix/pyproject.toml", b"[project]\ndependencies = []\n")


def symlink(r):
    os.remove(os.path.join(r, "nix/uv.lock"))
    os.symlink("/etc/passwd", os.path.join(r, "nix/uv.lock"))


def rename(r):
    os.rename(os.path.join(r, "nix/uv.lock"), os.path.join(r, "nix/uv2.lock"))


assert check_patch(relock_ok) == 0, "a relock"
assert check_patch(lambda r: os.remove(os.path.join(r, "nix/uv.lock"))) == 0, (
    "a deleted lock"
)
refused = {
    "workflow": lambda r: write(r, ".github/workflows/ci.yml", b"name: x\n"),
    "flake.lock": lambda r: write(r, "flake.lock", b'{"v": 2}\n'),
    "the root pyproject": lambda r: write(
        r, "pyproject.toml", b"[tool.odoo-nix]\nx = 1\n"
    ),
    "a new file": lambda r: write(r, "nix/x.sh", b"#!/bin/sh\n"),
    "executable": lambda r: write(r, "nix/uv.lock", b"x\n", 0o755),
    "mode change": lambda r: os.chmod(os.path.join(r, "nix/uv.lock"), 0o755),
    "symlink": symlink,
    "nothing": lambda r: None,
}
for why, change in refused.items():
    assert check_patch(change) != 0, why
assert check_patch(rename, ("-M",)) != 0, "rename"
dotdot = "diff --git a/../x b/../x\nnew file mode 100644\n--- /dev/null\n+++ b/../x\n@@ -0,0 +1 @@\n+x\n"
assert check_patch(None, text=dotdot) != 0, ".."


# 5b. The key jobs' content check (`odoo-nix verify-patch`), end to end: the workflow's own
# script, then the step that runs it, with a stand-in `odoo-nix` that runs this tree's CLI.
BIN = tempfile.mkdtemp()
Path(BIN, "odoo-nix").write_text(
    f"#!{sys.executable} -I\n"
    "import sys\n"
    f"sys.path.insert(0, {str(TOOLS)!r})\n"
    "from odoo_nix_tools.cli import main\n"
    "sys.exit(main(sys.argv[1:]))\n"
)
os.chmod(os.path.join(BIN, "odoo-nix"), 0o755)
WITH_TOOLS = {**os.environ, "PATH": f"{BIN}:{os.environ['PATH']}"}

FILES = "https://files.pythonhosted.org/packages/aa/bb"
PYPROJECT = (
    b"[project]\ndependencies = [\n"
    b"    # >>> odoo-nix: install set (managed from modules.txt) >>>\n"
    b'    "odoo",\n'
    b"    # <<< odoo-nix: install set <<<\n]\n"
)
UVLOCK = (
    b"version = 1\n\n[[package]]\n"
    b'name = "babel"\nversion = "2.17.0"\nsource = { registry = "https://pypi.org/simple" }\n'
    + f'sdist = {{ url = "{FILES}/babel-2.17.0.tar.gz", hash = "sha256:11" }}\n'.encode()
)

# The install set's array closed, and tables of its own after it: the repository's
# standards config (the CI App's key as the submodule App, auto-merge-policy "all").
BREAKOUT = (
    b'    "odoo",\n'
    b'    "evil @ https://evil.example/evil-1.0-py3-none-any.whl",\n'
    b"]\n"
    b"[tool.odoo-nix.ci.submodule-app]\n"
    b'app-id = "AVUNU_CI_APP_ID"\n'
    b'private-key = "AVUNU_CI_PRIVATE_KEY"\n'
    b"[tool.odoo-nix.dependabot]\n"
    b'auto-merge-policy = "all"\n'
    b"[tool.zz]\n"
    b"x = [\n"
)
BREAKOUT_PLAIN = BREAKOUT.replace(
    b'    "evil @ https://evil.example/evil-1.0-py3-none-any.whl",\n', b""
)


def relock_push(change) -> int:
    """relock-push's patch check, then its verify-patch step, on `change(repo)`."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "src"), os.path.join(tmp, "dst")
        os.makedirs(src)
        g(src, "init", "-q")
        for path, data in {
            **BASE,
            "nix/pyproject.toml": PYPROJECT,
            "nix/uv.lock": UVLOCK,
        }.items():
            write(src, path, data)
        g(src, "add", "-A")
        g(src, "commit", "-qm", "base")
        g(tmp, "clone", "-q", src, dst)
        change(src)
        g(src, "add", "-A")
        patch = os.path.join(tmp, "x.patch")
        Path(patch).write_text(g(src, "diff", "--cached", "--binary"))
        env = {**WITH_TOOLS, "PATCH": patch, "ALLOW": allow, "RUNNER_TEMP": tmp}
        for run in (script, steps[verify]["run"]):
            code = subprocess.run(
                ["bash", "-c", run], check=False, cwd=dst, env=env
            ).returncode
            if code:
                return code
        return 0


def edit(path, old: bytes, new: bytes):
    def change(r):
        full = Path(r, path)
        data = full.read_bytes()
        assert old in data, (path, old)
        full.write_bytes(data.replace(old, new, 1))

    return change


def new_package(name, url, source='{ registry = "https://pypi.org/simple" }'):
    return edit(
        "nix/uv.lock",
        b"version = 1\n",
        f'version = 1\n\n[[package]]\nname = "{name}"\nversion = "1.0"\nsource = {source}\n'
        f'sdist = {{ url = "{url}", hash = "sha256:22" }}\n'.encode(),
    )


assert relock_push(new_package("idna", f"{FILES}/idna-1.0.tar.gz")) == 0, (
    "an honest relock"
)
assert (
    relock_push(
        edit("nix/pyproject.toml", b'    "odoo",\n', b'    "odoo",\n    "idna",\n')
    )
    == 0
), "the install set"
content_refused = {
    "outside the managed blocks": edit(
        "nix/pyproject.toml", b"[project]", b"[project]\nx = 1"
    ),
    "a direct URL in the install set": edit(
        "nix/pyproject.toml",
        b'    "odoo",\n',
        b'    "odoo",\n    "x @ https://e.example/x.whl",\n',
    ),
    "the install set breaking out": edit(
        "nix/pyproject.toml", b'    "odoo",\n', BREAKOUT
    ),
    "the install set breaking out, no URL": edit(
        "nix/pyproject.toml", b'    "odoo",\n', BREAKOUT_PLAIN
    ),
    "a git source": new_package(
        "x", f"{FILES}/x-1.0.tar.gz", '{ git = "https://e.example/x" }'
    ),
    "another index": new_package(
        "x", f"{FILES}/x-1.0.tar.gz", '{ registry = "https://e.example/simple" }'
    ),
    "a file off PyPI": new_package("x", "https://e.example/x-1.0.tar.gz"),
    "another package's file": new_package("x", f"{FILES}/evil-1.0.tar.gz"),
    "a base file's hash": edit("nix/uv.lock", b"sha256:11", b"sha256:99"),
    "a deleted lock": lambda r: os.remove(os.path.join(r, "nix/uv.lock")),
}
for why, change in content_refused.items():
    assert relock_push(change) != 0, why


# The submodule's remote: https://github.com/OCA/web is read from a local bare repository
# (git's url.<base>.insteadOf, in a global config of the test's own), whose 18.0 is TIP.
REMOTES = tempfile.mkdtemp()
g(REMOTES, "init", "-q", "--bare", "OCA/web")
g(REMOTES, "clone", "-q", "OCA/web", "work")
g(os.path.join(REMOTES, "work"), "commit", "-q", "--allow-empty", "-m", "tip")
g(os.path.join(REMOTES, "work"), "push", "-q", "origin", "HEAD:refs/heads/18.0")
TIP = g(os.path.join(REMOTES, "work"), "rev-parse", "HEAD").strip()
GITCONFIG = os.path.join(REMOTES, "gitconfig")
Path(GITCONFIG).write_text(
    f'[url "file://{REMOTES}/"]\n\tinsteadOf = https://github.com/\n'
    "[protocol]\n\tallow = always\n"
)


def project_update(change, plan=PYPROJECT) -> int:
    """project-update's check-and-stage step, then its tips step, on the patch
    `change(repo)` stages; `plan` is the base's pyproject.toml."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "src"), os.path.join(tmp, "dst")
        os.makedirs(src)
        g(src, "init", "-q")
        write(src, "pyproject.toml", plan)
        write(src, "uv.lock", UVLOCK)
        write(
            src,
            ".gitmodules",
            b'[submodule "web"]\n\tpath = modules/web\n'
            b"\turl = https://github.com/OCA/web\n\tbranch = 18.0\n",
        )
        write(src, ".github/workflows/ci.yml", b"name: ci\n")
        g(src, "add", "-A")
        g(src, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},modules/web")
        g(src, "commit", "-qm", "base")
        g(tmp, "clone", "-q", src, dst)
        change(src)
        patch = os.path.join(tmp, "x.patch")
        Path(patch).write_text(g(src, "diff", "--cached", "--binary", "HEAD"))
        env = {
            **WITH_TOOLS,
            "PATCH": patch,
            "RUNNER_TEMP": tmp,
            "TOKEN": "t",
            "GIT_CONFIG_GLOBAL": GITCONFIG,
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "acme/project",
        }
        for run in (pscript, tscript):
            code = subprocess.run(
                ["bash", "-c", run], check=False, cwd=dst, env=env
            ).returncode
            if code:
                return code
        return 0


def gitlink(path, sha):
    return lambda r: g(
        r, "update-index", "--add", "--cacheinfo", f"160000,{sha},{path}"
    )


def staged(*changes):
    def change(r):
        for c in changes:
            c(r)
        g(r, "add", "--", "pyproject.toml", "uv.lock", ".gitmodules", ".github")

    return change


def project_edit(path, old, new):
    return edit(path, old, new)


assert project_update(staged(gitlink("modules/web", TIP))) == 0, "a submodule moved"
assert (
    project_update(
        staged(
            gitlink("modules/web", TIP),
            project_edit(
                "pyproject.toml", b'    "odoo",\n', b'    "odoo",\n    "idna",\n'
            ),
        )
    )
    == 0
), "a submodule moved and relocked"
project_refused = {
    "nothing": staged(),
    "a commit that is not the branch's tip": staged(gitlink("modules/web", "2" * 40)),
    "the install set breaking out": staged(
        gitlink("modules/web", TIP),
        project_edit("pyproject.toml", b'    "odoo",\n', BREAKOUT),
    ),
    "the install set breaking out, no URL": staged(
        gitlink("modules/web", TIP),
        project_edit("pyproject.toml", b'    "odoo",\n', BREAKOUT_PLAIN),
    ),
    "a new submodule": staged(gitlink("modules/evil", "3" * 40)),
    ".gitmodules": staged(
        gitlink("modules/web", TIP),
        project_edit(
            ".gitmodules", b"https://github.com/OCA/web", b"https://e.example/web"
        ),
    ),
    "a workflow": staged(project_edit(".github/workflows/ci.yml", b"ci", b"x")),
    "outside the managed blocks": staged(
        project_edit("pyproject.toml", b"[project]", b"[project]\nx = 1")
    ),
    "a submodule removed": lambda r: g(r, "rm", "-q", "--cached", "modules/web"),
}
for why, change in project_refused.items():
    assert project_update(change) != 0, why

# 6. The release flow's package, repackage and upload.
rp = load("odoo-release-please.yml")["jobs"]
assert rp["repackage"]["runs-on"] == "ubuntu-latest", rp["repackage"]["runs-on"]
assert rp["package"]["runs-on"] == "ubuntu-latest", rp["package"]["runs-on"]
assert "secrets." not in json.dumps(rp["package"]), "package holds a secret"
for s in rp["package"]["steps"]:
    assert not any(c in uses(s) for c in CACHES), ("package", uses(s))
    assert not (
        uses(s) == "astral-sh/setup-uv"
        and s.get("with", {}).get("enable-cache") != "false"
    )
up = rp["upload"]["steps"]
only = index(up, lambda s: s.get("if") == "inputs.repackage != ''")
assert up[only]["env"] == {
    "TAG": "${{ matrix.package.tag }}",
    "REPACKAGE": "${{ inputs.repackage }}",
}, up[only]
assert '[ "$TAG" != "$REPACKAGE" ]' in up[only]["run"], up[only]
assert only < token_at(up), "the tag check before the token"

# 7. Dependabot: what the key jobs run is reviewed by a person, never auto-merged.
dependabot = yaml.safe_load((GITHUB / "dependabot.yml").read_text())
ecosystems = {(u["package-ecosystem"], u["directory"]) for u in dependabot["updates"]}
assert ("uv", "/py/odoo_nix_tools") in ecosystems, ecosystems
assert {e for e, _ in ecosystems if e == "uv"} == {"uv"}, "one uv entry, the tools'"
am = load("dependabot-auto-merge.yml")["jobs"]["auto-merge"]
held = am["with"]["exclude-ecosystems"].split()
assert {"github_actions", "uv"} <= set(held), held
review = am["with"]["review-dependencies"].split()
assert {
    "actions/create-github-app-token",
    "actions/checkout",
    "astral-sh/setup-uv",
} <= set(review), review

print(
    "app-key jobs:",
    json.dumps({k: sorted(v) for k, v in sorted(main_holders.items())}),
    "submodule App:",
    json.dumps(sorted(sub_holders)),
)
