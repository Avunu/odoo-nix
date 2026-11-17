"""The jobs of the reusable workflows that can hold the CI App's key (checks.app-key-jobs).

    python app_key_jobs.py WORKFLOWS_DIR

Static, over the workflow files, and offline: git, bash and jq on PATH, and
standards_core importable (its relock.input_node is what the jq program must agree with).

- Every job that mints the App's token or reads its key runs on ubuntu-latest, written so,
  except the two the docs name as not hardened yet (odoo-test's test, odoo-deps'
  project-update); no other job joins them unnoticed.
- In the hardened jobs, odoo-nix-tools comes from standards-install's `hardened` mode
  (Avunu/odoo-nix only, py/odoo_nix_tools, standards-core from Avunu/python-devops-nix),
  before the token is minted; no `uv tool`, `uvx` or pip install of their own, no setup-uv
  with a cache, and no cache action at all.
- relock-push builds on the event's head SHA, recomputes `moved`, refuses before it applies,
  checks the patch before the token, and pushes without force; automerge recomputes
  `moved` with the same step; neither reads relock-plan's `moved`.
- The patch check script is run here on accepted and refused patches (flake.lock among the
  refused), and the jq `moved` program against standards_core's input_node.
- package (the addon's build) uses no cache; repackage runs on ubuntu-latest; upload
  checks the dispatch's repackage tag before it mints the token.
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

WORKFLOWS = Path(sys.argv[1])
APP_KEY = ("APP_PRIVATE_KEY", "create-github-app-token")
CACHES = ("actions/cache", "magic-nix-cache-action", "cache-nix-action")
UNHARDENED = {("odoo-test.yml", "test"), ("odoo-deps.yml", "project-update")}
HARDENED = {
    "odoo-release.yml": {"release"},
    "odoo-release-please.yml": {"release-please", "sync", "upload"},
    "odoo-deps.yml": {"relock-push", "automerge", "update-branches"},
}
# The jobs that install odoo-nix-tools (upload runs gh alone).
INSTALLERS = {
    "odoo-release.yml": {"release"},
    "odoo-release-please.yml": {"release-please", "sync"},
    "odoo-deps.yml": {"relock-push", "automerge", "update-branches"},
}


def load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def uses(step: dict) -> str:
    return step.get("uses", "").split("@")[0]


def index(steps: list[dict], pred) -> int:
    return next(i for i, s in enumerate(steps) if pred(s))


def token_at(steps: list[dict]) -> int:
    return index(steps, lambda s: "create-github-app-token" in s.get("uses", ""))


# 1. Who holds the key, and where it runs.
holders: dict[str, set[str]] = {}
for path in sorted(WORKFLOWS.glob("*.yml")):
    doc = yaml.safe_load(path.read_text())
    for name, job in doc["jobs"].items():
        if "uses" in job or not any(k in json.dumps(job) for k in APP_KEY):
            continue
        holders.setdefault(path.name, set()).add(name)
        if (path.name, name) in UNHARDENED:
            continue
        assert job["runs-on"] == "ubuntu-latest", (path.name, name, job["runs-on"])
hardened = {
    wf: names - {n for w, n in UNHARDENED if w == wf} for wf, names in holders.items()
}
assert {wf: n for wf, n in hardened.items() if n} == HARDENED, hardened
for wf, name in UNHARDENED:
    assert name in holders.get(wf, set()), (
        wf,
        name,
        "hardened? take it off UNHARDENED",
    )

# 2. What the hardened jobs install, and before what.
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

# 3. relock-push and automerge.
deps = load("odoo-deps.yml")
plan, push, auto = (
    deps["jobs"][n] for n in ("relock-plan", "relock-push", "automerge")
)
assert plan["permissions"] == {"contents": "read"}, plan["permissions"]
assert not any(k in json.dumps(plan) for k in APP_KEY), "relock-plan holds the key"
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
assert ids.index("moved") < refuse < download < check < token_at(steps), (
    ids,
    refuse,
    check,
)
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

# 6. The release flow's package, repackage and upload.
rp = load("odoo-release-please.yml")["jobs"]
assert rp["repackage"]["runs-on"] == "ubuntu-latest", rp["repackage"]["runs-on"]
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

print("app-key jobs:", json.dumps({k: sorted(v) for k, v in sorted(holders.items())}))
