"""odoo-nix's part of the ``repo`` commands (core DESIGN.md §7; DESIGN.md §2.2, §2.7).

``fleet_table``: the app layer of a fleet repository that has not opted in yet, from its
fleet entry (``data/schema/fleet-entry.schema.json``): its shape, and its integration
branch (``integration_branch``, else ``branches[0]``).

``repo_policy_values`` (core §7.3 lets a product override any placeholder value):

an addon repository under ``develop+series``: the release ruleset protects only the
series branch ``.odoo-series`` names (``refs/heads/18.0``), not every ``*.0``, so a
maintenance branch of another series (Dependabot's second target, ``17.0``) still merges
pull requests. A project needs no override: its release branch is ``""``
(``release.BRANCHING``), so the core gives its integration ruleset no bypass actor (core
CR3, DESIGN.md §10).

an addon repository under ``series``: one integration ruleset for every series branch
(``refs/heads/*.0``: they are developed in parallel, each its own integration branch), and
a tags ruleset over every tag (``<addon>-<series>.x.y.z``), through odoo-nix's own
``repo-policy/rulesets/integration.json`` (``{integration_label}``,
``{integration_refs}``).

``AUDIT_ROWS``: A12 (an addon repository's branches against its series and Dependabot's
targets) and A13 (a project's submodules on its series).

``doctor_rows``: what the ``develop+series`` release flow needs from the repository: the
CI App's client-ID variable and private-key secret (``ci.github-app``), and a
``repo-policy.release-bypass`` naming that App by its numeric id (the ``series`` flow
needs the App's variable and secret only); and, for a project
without an App, how its ``project-update`` pull requests get CI.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from standards_core.commands.repo.audit import GREEN, NA, RED, UNKNOWN, RowSpec
from standards_core.commands.repo.doctor import MISSING, OK
from standards_core.commands.repo.doctor import UNKNOWN as DOCTOR_UNKNOWN
from standards_core.commands.repo.doctor import Row as DoctorRow
from standards_core.common import github, repo_policy
from standards_core.common.github import GitHubError

from odoo_nix_tools import discover

if TYPE_CHECKING:
    from standards_core.commands.repo.audit import Audit
    from standards_core.common.repoconfig import RepoConfig

# The release flows the App-only rows are about (release.BRANCHING).
SERIES_FLOW = "develop+series"
TAGS_FLOW = "series"
# The integration ruleset of the series branching: every series branch.
SERIES_RULESET = "series branches (*.0)"
SERIES_REFS = "refs/heads/*.0"
# A ruleset's `*` matches any characters but `/`, so `*.0` also matches release-please's
# release PR branch (`release-please--branches--18.0`, release.rp_branch), which the
# pull-request and status-check rules would then forbid it to create (HTTP 422).
SERIES_EXCLUDE = "refs/heads/release-please--*"
# repo-policy.release-bypass naming a GitHub App by its numeric id.
APP_BYPASS = re.compile(r"integration:(\d+)")


# --- the fleet entry -----------------------------------------------------------------


def fleet_table(repo: str, entry: Mapping[str, Any], ref: str) -> dict[str, Any]:
    """The app layer of a repository that has not opted in, from its fleet entry. An
    entry-less target (``repo apply <owner/repo> --profile …``) gets nothing: discovery
    has no checkout to read its shape from either, so the profile's defaults apply."""
    out: dict[str, Any] = {}
    if entry.get("shape"):
        out["shape"] = entry["shape"]
    branches = entry.get("branches") or []
    integration = entry.get("integration_branch") or (branches[0] if branches else "")
    if integration:
        out["integration-branch"] = integration
    return out


# --- repo-policy placeholders --------------------------------------------------------


def _series_flow(cfg: Mapping[str, Any]) -> bool:
    return (cfg.get("releases") or {}).get("branching") == SERIES_FLOW


def _tags_flow(cfg: Mapping[str, Any]) -> bool:
    return (cfg.get("releases") or {}).get("branching") == TAGS_FLOW


def repo_policy_values(
    cfg: Mapping[str, Any], modules: Mapping[str, bool], gates: Sequence[str]
) -> dict[str, Any]:
    """The per-series release pattern of an addon repository, and the integration and
    tags rulesets of the ``series`` branching (module docstring)."""
    shape = cfg.get("shape")
    series = cfg.get("series")
    integration = str(cfg.get("integration-branch") or "")
    out: dict[str, Any] = {
        "integration_label": integration,
        "integration_refs": [f"refs/heads/{integration}"],
        "integration_exclude": [],
    }
    if shape == "addons" and _series_flow(cfg) and series:
        out.update(release_pattern=f"refs/heads/{series}", release_label=series)
    elif shape == "addons" and _tags_flow(cfg):
        # Every series branch is an integration branch, developed in parallel, so one
        # ruleset guards them all; the tags are `<addon>-<series>.x.y.z`.
        out.update(
            integration_label=SERIES_RULESET,
            integration_refs=[SERIES_REFS],
            integration_exclude=[SERIES_EXCLUDE],
            tag_prefix="",
            tag_pattern="refs/tags/*",
        )
    return out


# --- audit rows ----------------------------------------------------------------------


def _series(a: Audit) -> tuple[str, str]:
    """The checkout's series and where it was read: ``.odoo-series`` in the clone, else
    the resolved ``series`` (an explicit one, or flake.nix's)."""
    path = Path(a.root) / discover.SERIES_FILE
    if path.is_file():
        return path.read_text().strip(), discover.SERIES_FILE
    return str(a.t.cfg.get("series") or a.t.facts.get("series") or ""), "series"


def _release_pattern(a: Audit) -> str:
    """The release ruleset's ``refs/heads/…`` pattern, or "" when there is none."""
    release = a.t.release_branch
    if not release:
        return ""
    values = repo_policy.values(
        a.product, a.t.cfg, a.t.modules, a.t.gates, release_branch=release
    )
    return str(values.get("release_pattern") or "")


def _a12(a: Audit) -> tuple[str, str]:
    """An addon repository's fleet entry lists its series branch, and Dependabot targets
    the integration branch and never a branch only the release automation moves."""
    cfg = a.t.cfg
    if cfg.get("shape") != "addons":
        return NA, "a project has no series branch"
    series, source = _series(a)
    if not series:
        return UNKNOWN, "no series"
    red: list[str] = []
    unknown: list[str] = []
    branches = list(a.t.entry.get("branches") or [])
    # Under series every listed branch is a series branch; under develop+series the
    # first is the integration branch.
    listed_series = branches if _tags_flow(cfg) else branches[1:]
    if not branches:
        unknown.append("no fleet entry branches to compare")
    elif series not in listed_series:
        listed = ", ".join(listed_series) or "none"
        red.append(
            f"the fleet's series branches ({listed}) do not include {series} ({source})"
        )
    if a.t.modules.get("dependabot"):
        integration = a.t.integration
        targets = list((cfg.get("dependabot") or {}).get("target-branches") or [])
        if integration and integration not in targets:
            red.append(
                f"dependabot.target-branches ({', '.join(targets) or 'none'}) does not"
                f" list {integration}"
            )
        pattern = _release_pattern(a)
        guarded = [
            b for b in targets if pattern and fnmatchcase(f"refs/heads/{b}", pattern)
        ]
        if guarded:
            red.append(
                f"dependabot.target-branches lists {', '.join(guarded)}, which the"
                f" release ruleset ({pattern}) keeps for the release automation: a"
                " Dependabot pull request there could never merge"
            )
    if red:
        return RED, "; ".join(red + unknown)
    if unknown:
        return UNKNOWN, "; ".join(unknown)
    return GREEN, f"{series} in branches"


def _a13(a: Audit) -> tuple[str, str]:
    """Every submodule of a project follows its series (``branch = <series>`` in
    ``.gitmodules``), so ``odoo project update`` moves each one along it."""
    if a.t.cfg.get("shape") != "project":
        return NA, "an addon repository has no submodules to pin"
    series = str(a.t.cfg.get("series") or a.t.facts.get("series") or "")
    if not series:
        return UNKNOWN, "no series"
    subs = list(a.t.facts.get("submodules") or [])
    if not subs:
        return NA, "no submodules"
    wrong = [
        f"{s['path']} ({s.get('branch') or 'no branch'})"
        for s in subs
        if s.get("branch") != series
    ]
    if wrong:
        return RED, f"not on branch = {series}: {', '.join(wrong)}"
    return GREEN, f"{len(subs)} submodule(s) on {series}"


AUDIT_ROWS: Mapping[str, RowSpec] = MappingProxyType(
    {
        "A12": RowSpec(
            "the fleet's series branches (branches[1:]) include .odoo-series;"
            " dependabot.target-branches lists the integration branch and no branch the"
            " release ruleset protects (a Dependabot PR there could never merge)",
            "releases",
            _a12,
        ),
        # Projects; n/a in an addon repository.
        "A13": RowSpec("every submodule pins `branch = <series>`", "ci", _a13),
    }
)


# --- doctor rows ---------------------------------------------------------------------


def _named(r: str, kind: str, name: str) -> str:
    """Whether the repository, or its organisation for it, has the Actions ``kind``
    (``variables`` or ``secrets``) called ``name``."""
    try:
        github.get(f"repos/{r}/actions/{kind}/{name}")
        return OK
    except GitHubError as e:
        if e.status != 404:
            return DOCTOR_UNKNOWN
    try:
        listed = github.get(f"repos/{r}/actions/organization-{kind}") or {}
    except GitHubError as e:
        return MISSING if e.status == 404 else DOCTOR_UNKNOWN
    items = listed.get(kind, []) if isinstance(listed, Mapping) else []
    return OK if any(item.get("name") == name for item in items) else MISSING


def _app_rows(r: str, cfg: Mapping[str, Any], settings: str) -> list[DoctorRow]:
    app = (cfg.get("ci") or {}).get("github-app") or {}
    where_cfg = "[tool.odoo-nix.ci.github-app] (or the org profile's [ci.github-app])"
    rows = []
    for key, kind, what in (
        ("app-id", "variables", "the CI App's client ID"),
        ("private-key", "secrets", "the CI App's private key"),
    ):
        name = app.get(key, "")
        noun = kind.removesuffix("s")
        if not name:
            rows.append(
                DoctorRow(
                    "releases",
                    f"ci.github-app.{key} names the Actions {noun} holding {what}",
                    MISSING,
                    f"{where_cfg} {key}: the bump push and the fast-forward use the App",
                )
            )
            continue
        rows.append(
            DoctorRow(
                "releases",
                f"Actions {noun} {name} ({what})",
                _named(r, kind, name),
                f"{settings}/{kind}/actions (or the organisation's)",
            )
        )
    return rows


def _bypass_row(cfg: Mapping[str, Any], settings: str) -> DoctorRow:
    bypass = str((cfg.get("repo-policy") or {}).get("release-bypass") or "")
    variable = ((cfg.get("ci") or {}).get("github-app") or {}).get("app-id", "")
    held = f"vars.{variable}" if variable else "the client-ID variable"
    where = (
        "[tool.odoo-nix.repo-policy] release-bypass (or the org profile's):"
        " integration:<the App's numeric id, from its settings page; not the client"
        f" ID {held} holds>, then `odoo-nix repo apply` ({settings}/rules)"
    )
    found = APP_BYPASS.fullmatch(bypass)
    if found:
        return DoctorRow(
            "releases",
            f"repo-policy.release-bypass is the CI App ({bypass})",
            OK,
            where,
        )
    shown = bypass or "unset"
    return DoctorRow(
        "releases",
        f"repo-policy.release-bypass is integration:<App id>, not {shown}: the bump"
        " push and the fast-forward use the CI App's token",
        MISSING,
        where,
    )


def doctor_rows(r: str, rc: RepoConfig) -> tuple[list[DoctorRow], list[str]]:
    """With ``releases`` on under ``develop+series`` and a release branch (an addon
    repository): the CI App's variable and secret exist (repository or organisation),
    and ``repo-policy.release-bypass`` is ``integration:<numeric id>``. The variable
    holds the App's *client ID* (``create-github-app-token``'s ``client-id``), which is
    not the numeric App id a ruleset bypass needs. A project without an App: a notice
    that its ``project-update`` pull requests get CI by dispatch."""
    cfg, modules = rc.cfg, rc.modules
    settings = f"https://github.com/{r}/settings"
    rows: list[DoctorRow] = []
    notices: list[str] = []
    flow = repo_policy.branching(rc.product, cfg)
    bumps = (
        bool(modules.get("releases"))
        and flow is not None
        and flow.flow == "post-merge-bump"
        and bool(rc.release_branch)
    )
    if bumps:
        rows += _app_rows(r, cfg, settings)
        rows.append(_bypass_row(cfg, settings))
    elif modules.get("releases") and _tags_flow(cfg):
        # release-please opens its PR with the App's token, so CI runs on it, and
        # pushes the manifest versions to it; nothing bypasses a ruleset.
        rows += _app_rows(r, cfg, settings)
    app = (cfg.get("ci") or {}).get("github-app") or {}
    update = (cfg.get("ci") or {}).get("project-update", "")
    if (
        modules.get("ci")
        and cfg.get("shape") == "project"
        and update
        and not (app.get("app-id") and app.get("private-key"))
    ):
        notices.append(
            "no ci.github-app: project-update opens its pull request with GITHUB_TOKEN,"
            " whose events start no workflow, so the job then dispatches ci.yml and"
            " pr-policy.yml on standards/project-update (their checks land on the pull"
            " request's head); private submodules need the App"
        )
    return rows, notices
