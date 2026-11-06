# odoo-nix-tools: design contract

Status: binding for the odoo-nix standards work (plan B1-B7, C, D and "Amendments (2026-11-03)", which win
where they conflict). Written 2026-11-03 against:

- the core contract `python-devops-nix/standards/DESIGN.md` ("core §n" below), being implemented in
  `pdn-standards-core/standards` (stage 1 committed as `18e734e`; stage-2 files in its working tree at review
  time). Where this design needs the contract to change, §10 says how;
- odoo-nix at `feat/standards` on top of addons mode (`55155d0 feat(addons): externalSources and addons mode`,
  `078f208`, `bd59032 fix(devenv): stop seeding Odoo.serverConfigPath`);
- the generated series data `odoo_nix_tools/data/series/{18.0,19.0,20.0}.json` (OCA template `v1.48`,
  commit `a7ac6253`) and its generator `scripts/gen_series_data.py`;
- the targets: the 10 `Avunu/*-addons` repositories (branch `feat/odoo-standards`), two private
  client projects, called project A and project B here (`feat/odoo-standards`), and the draft
  `Avunu/odoo-standards-profile` (`profile.toml`, `fleet.json`, `scripts/check.sh`).

Revised the same day after an independent review (2 blocking, 6 major, 10 moderate items and minor ones). Each
item was checked against the core code, the targets and the tools before it was resolved; §11 logs each item and
its resolution. The core changes this design needs are listed with exact proposals in §10 ("Core change
requests"); nothing here silently diverges from the core contract.

Terms are the core's (§0 of core): *product* = odoo-nix-tools, *engine* = the `odoo-nix` flake input,
*checkout* = the repository being synced. "Shape" is `project` or `addons`. Paths without a root are relative
to `py/odoo_nix_tools/odoo_nix_tools/` when they name Python or `data/`, else to the odoo-nix repository root.

---

## 0. Decisions this design rests on, and what it needs from the core

### 0.1 Fixed inputs

| Topic | Decision (source) |
|---|---|
| Rules | OCA-aligned, per series, from `data/series/<series>.json`; every deviation is applied in code and listed in `series.DEVIATIONS` (§3.0) |
| Tools | **Locked**: `tools/pyproject.toml` + `tools/uv.lock` built by Nix (uv2nix) and linked as `tools/.venv`; root `package.json` + `package-lock.json` built by Nix (`importNpmLock`) and linked as `node_modules`; every hook `language: system`; editor, shell and CI run the same binaries; Dependabot never moves them (user decision, plan B3) |
| READMEs | Markdown `README.md` per addon; `oca-gen-addon-readme` is never rendered (plan "Decisions") |
| Editor | Pylance and ty off, Odoo LS on; `Odoo.serverConfigPath` is forbidden and never seeded (`bd59032`) |
| Config file | `[tool.odoo-nix]` lives in odoo-nix's own uv project file: root `pyproject.toml` in a project, `nix/pyproject.toml` in addons mode. Addon repositories have no root `pyproject.toml` (verified: none of the 10 has one) |
| Inputs block | owns `odoo-nix` and `standards-profile` only; `ocb`/`oca-*`/other addon-repo inputs stay with addons mode (Amendments; core §5.6.4) |
| Release flow | `develop+series`: PRs to `develop`, post-merge `chore(release): bump <addons>` with the CI App, fast-forward of the series branch named in `.odoo-series` once checks are green; `mirror.yml` retired; no strict checks; projects keep releases off (Amendments) |
| Adoption precondition | an addon repository opts in only once its addons-mode files are tracked (the `feat/dev-env` PR merged, or `odoo-init --addons` in the same run): `develop` of all 10 repositories has no `flake.nix` and no `nix/` today (`git ls-tree develop`, verified) (§3.4 preflight, §8.2) |
| Pending sign-off | deviation `drop-external-deps` (§3.0) goes beyond the two hooks the user agreed to skip (`oca-gen-addon-readme`, `oca-update-pre-commit-excluded-addons`); it stays `proposed` until the user decides (review item P3-7) |

### 0.2 Core asks (gaps between the core contract and Odoo's needs)

Each ask names the smallest change. The exact core proposals are in §10 ("Core change requests"); this table is
the summary.

| # | Gap (core text) | Ask | Fallback until it lands |
|---|---|---|---|
| C1 | `Identity.config_file: str` is one path (core §3.1), `config.resolve` takes the checkout root as `config_path.parent` and the default lock as "beside" it (stage-2 code, `common/config.py:583`), and `commands/config.py:66` finds the file with `find_up(identity.config_file)`. Odoo needs `pyproject.toml` (project) or `nix/pyproject.toml` (addons mode, root = its parent's parent). Core §4.4 and §13 item 5 settled addon repositories as "`--standards` creates the root file", which the user decision rules out | CR1 (§10): `Hooks.config_file: Callable[[Path], str] \| None`, `Identity.config_paths`, an explicit `root` in `config.resolve`, and every caller through `pyproject.config_path` | none acceptable: addons-mode adoption depends on it. Until CR1 lands, `PRODUCT` passes no `config_file` hook (the field does not exist, so passing it would be a `TypeError` at import) and the addons fixture is skipped; the project fixture proceeds |
| C2 | — (withdrawn) | none: core `fleet-entry-core` already has `branches` and `Target.branches` reads `entry["branches"]` (core §4.1, §7.1). The profile's `fleet.json` renames `series_branches` to `branches: ["develop", "18.0"]` (integration first), the product schema `$ref`s the core `branches`, and `integration_branch` becomes optional (core §7.1: `integration_branch`, else `branches[0]`) | — |
| C3 | Core §2.5 gives odoo `sync.rollout_steps = []` | none: odoo-nix sets `(("nix", "run", "--no-pure-eval", ".#relock"),)` (the field exists). A new odoo-nix can change the install set (`078f208` puts `packaging` in every install set: "a project's next relock adds it") | — |
| C4 | `profile validate FILE --templates DIR` (core §6.2); the profile repo's `scripts/check.sh` runs `profile validate --profile-path DIR` | none in the core: `check.sh` changes (§4.4) | — |
| C5 | A throwaway checkout (`profile validate`, conformance render part) cannot carry a `tools/uv.lock` that matches every profile's module set | CR2 (§10): `ctx.options["throwaway"] = True` in throwaway renders | the lock-consistency check (§3.4) compares as a subset (rendered ⊆ locked) instead of equality, so one lock built with every tool satisfies every profile |
| C6 | `integration_bypass` is rendered whenever `releases` is on under `post-merge-bump` (core §7.3), so a project that inherits `releases` and turns `repo-policy` on would let the App bypass the pull-request rules on `main` | CR3 (§10): also require a non-empty release branch | `hooks.repo_policy_values` returns `integration_bypass: []` for `shape == "project"` (§2.2) |

---

## 1. Package layout

### 1.1 Tree

```
py/odoo_nix_tools/
├── pyproject.toml                 flit; release-please extra-file
├── README.md                      install, commands, link to docs/standards
├── DESIGN.md                      this file
├── uv.lock                        dev lock (pytest, ty); Dependabot `uv` entry, standards-core ignored
├── scripts/gen_series_data.py     exists; never shipped (flit packs odoo_nix_tools/ only)
├── tests/                         unittest suites, run by the package's check phase (§7.2)
│   ├── support.py                 run_cli(PRODUCT, *argv), make_tree(files), git(root, *args)
│   ├── shapes/                    target-shaped files: public addon repos' copies, synthetic project ones
│   │   ├── vscode/{project-b-settings.json, project-b-extensions.json, project-a-settings.json, project-a-extensions.json}
│   │   ├── flakes/{project-b.nix, project-a.nix, edi-addons.nix, vertical-auto-repair-addons.nix}
│   │   ├── pyproject/{project-b.toml, edi-addons-nix.toml}   foreign odoo-nix blocks, kept byte for byte
│   │   └── icons/{ok-128.png, wide-200x100.png, heavy-150k.png}
│   └── test_*.py                  §7.2
└── odoo_nix_tools/
    ├── __init__.py                __version__ (release-please generic marker)
    ├── __main__.py                `python -m odoo_nix_tools` → cli.main()
    ├── cli.py                     main() -> int: standards_core.cli.main(PRODUCT, extra_commands=EXTRA)
    ├── product.py                 PRODUCT (§2)
    ├── series.py                  SeriesData, load(), effective(), DEVIATIONS (§3.0)
    ├── discover.py                config_file(), load_checkout(), facts(), derive(), new_target_table() (§2.3, §2.4)
    ├── manifests.py               literal(), replace_version(), version_problem()
    ├── context.py                 template_globals(), render_helpers(), gates(), url_placeholders(), Gen
    ├── precommit.py               hooks(ctx) -> list[Hook] (§3.3)
    ├── groups.py                  TOOLS (TomlGroups), PACKAGE (JsonGroups) (§3.2)
    ├── release.py                 OdooSeries (VersionScheme), ManifestTool (ReleaseTool), BRANCHING
    ├── checks.py                  preflight(), notices(), checks() (§3.4)
    ├── policy.py                  pr_checks(), committed_argv()
    ├── fleet.py                   fleet_table(), AUDIT_ROWS, doctor_rows(), repo_policy_values()
    ├── verdict.py                 DECISION_TABLE
    ├── bootstrap.py               phase_a_before() (project submodules), reexec_argv(), reentry_argv()
    ├── fixtures.py                FIXTURES, write()
    ├── pngsize.py                 png_size(data) -> tuple[int, int] (IHDR; no Pillow)
    ├── commands/
    │   ├── __init__.py            EXTRA: tuple[Command, ...] = (CHECK, GATE, RATCHET)
    │   ├── gate.py                `gate lint|test` (§6.1)
    │   ├── check.py               `check manifests|icons|submodules` (§6.2)
    │   └── ratchet.py             `ratchet coverage` (§6.3)
    └── data/
        ├── README.md              what each file is and who reads it
        ├── series/{18.0,19.0,20.0}.json        generated (exists)
        ├── tool-pins.json         odoo-nix's own pins: prek, coverage, checklog-odoo, manifestoo
        ├── ide/vscode.json        the settings/extensions data shared with modules/devenv.nix's seed
        ├── profiles/{minimal.toml, recommended@2.3.toml}
        ├── schema/{modules.schema.json, fleet-entry.schema.json, gate-report.schema.json}
        ├── manifest.d/{00-dev-shell,10-editorconfig,20-python,30-js-xml,40-ide,50-tests,
        │               60-hygiene,70-commits,80-github,90-addons}.json
        └── templates/             §3.5
```

### 1.2 `pyproject.toml`

```toml
# odoo-nix-tools: one self-contained distribution, import name odoo_nix_tools, console script
# `odoo-nix`. It serves the Nix dev shell and odoo-init (lib/standards/package.nix) and the
# no-Nix CI jobs, which install it with
#   uv tool install "odoo-nix-tools @ git+https://github.com/Avunu/odoo-nix@<rev>#subdirectory=py/odoo_nix_tools"
# Every file read at run time lives under odoo_nix_tools/data/.
[build-system]
requires = ["flit_core >=3.4,<4"]
build-backend = "flit_core.buildapi"

[project]
name = "odoo-nix-tools"
# release-please moves this, version.txt and odoo_nix_tools/__init__.py together.
version = "2.2.0"
description = "odoo-nix's standards tools: managed files, profiles, gates and release steps for Odoo repositories"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    # The engine. Its sha equals flake.lock's python-devops-nix rev and every
    # Avunu/python-devops-nix/...@sha in .github/** (checks.standards-core-pins).
    "standards-core @ git+https://github.com/Avunu/python-devops-nix@<sha>#subdirectory=standards",
]

[project.scripts]
odoo-nix = "odoo_nix_tools.cli:main"

[project.urls]
Documentation = "https://github.com/Avunu/odoo-nix/tree/main/docs/standards"
Source = "https://github.com/Avunu/odoo-nix/tree/main/py/odoo_nix_tools"

[tool.flit.module]
name = "odoo_nix_tools"
```

- No direct runtime dependency beyond `standards-core` (which brings `jinja2`, `tomlkit`, `packaging`,
  `pyyaml`): icons use `pngsize.py` (PNG IHDR), manifests use `ast.literal_eval`.
- Until the core is pushed, development installs the core editable into the dev env (`uv pip install -e
  ../pdn-standards-core/standards`) and Nix builds with `--override-input python-devops-nix
  path:/home/batonac/Development/.claude-wt/pdn-standards-core` (plan "Execution mechanics"). No
  `[tool.uv.sources]` ships in this file.
- `__init__.py`: `__version__ = "2.2.0"  # x-release-please-version`.
- `release-please-config.json` (`packages["."]`) gains:
  ```json
  "extra-files": [
    {"type": "generic", "path": "py/odoo_nix_tools/odoo_nix_tools/__init__.py"},
    {"type": "toml", "path": "py/odoo_nix_tools/pyproject.toml", "jsonpath": "$.project.version"}
  ]
  ```
- `checks.standards-version` (§7.3) asserts `version.txt` == `[project].version` == `__version__`.
- `identity.version` is `__version__`; odoo-nix-tools and odoo-nix share one version, so
  `requires-odoo-nix` (core §4.5) and the re-exec rule (`engine.version_file = "version.txt"`, core §6.3 step 8)
  compare the same number.
- odoo-nix's own prek runs with `--config .pre-commit-config.yaml` (`j178/prek-action` `extra-args`, and the dev
  shell's `prek install -c`): prek 0.5.7 runs every tracked nested `.pre-commit-config.yaml` as a workspace
  project, and a root `exclude` does not stop that (verified with a throwaway repository: a nested config under a
  plain directory ran, one inside a submodule did not, and `-c` ran the root config only). Without it, the synced
  fixtures' managed configs (entries under their own `tools/.venv`) would run in odoo-nix's own lint job.
- odoo-nix's own `ruff.toml`, `.pre-commit-config.yaml` and `ty.toml` exclude `^tests/fixtures/standards-`;
  `ty.toml` adds `py/odoo_nix_tools` to `extra-paths`; `.github/dependabot.yml` gains a `uv` entry for
  `/py/odoo_nix_tools` ignoring `standards-core` (moved by `nix run .#bump-base`, core §10.3).

### 1.3 `README.md` (package)

Sections: what the tool is (one paragraph, the two shapes); install (Nix: `nix run github:Avunu/odoo-nix#odoo-nix
-- --help`; no Nix: the `uv tool install` line above); commands (core `sync`, `config`, `profile`, `policy`, `ci`,
`repo`, `data-path`, `pin-path`; product `gate`, `check`, `ratchet`); exit codes (core §6.2 table); a link to
`docs/standards/`. No content that duplicates `docs/standards/`.

---

## 2. The Product instance

### 2.1 `product.py`

```python
"""odoo-nix's product: every value standards-core reads (core DESIGN.md §3)."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from standards_core.product import (
    CiConfig,
    Engine,
    FirstOptIn,
    HeaderKind,
    Hooks,
    Identity,
    JsonStyle,
    Markers,
    Modules,
    Paths,
    Pins,
    Product,
    Schemas,
    SyncHooks,
)
from standards_core.scaffold.handlers import TomlMergeHandler
from standards_core.scaffold.jsonmerge import JsonGroupsHandler

from odoo_nix_tools import (
    __version__,
    bootstrap,
    checks,
    context,
    discover,
    fixtures,
    fleet,
    groups,
    policy,
    release,
    verdict,
)

DATA = Path(str(files("odoo_nix_tools") / "data"))
DOCS = "https://github.com/Avunu/odoo-nix/tree/main/docs/standards"

MODULES = (
    "dev-shell",
    "editorconfig",
    "python-lint",
    "pylint-odoo",
    "addon-manifest",
    "js-xml",
    "ide",
    "tests",
    "workflow-lint",
    "shell-lint",
    "nix-lint",
    "hygiene",
    "commits",
    "releases",
    "packaging",
    "dependabot",
    "ci",
    "repo-policy",
    "readme",
    "icons",
)
LINT_MODULES = (
    "python-lint",
    "pylint-odoo",
    "addon-manifest",
    "js-xml",
    "workflow-lint",
    "shell-lint",
    "nix-lint",
    "hygiene",
    "packaging",
    "icons",
)

OPT_IN_HINT = (
    "this repository has not opted in to odoo-nix's standards: add a [tool.odoo-nix] table to "
    "pyproject.toml (a project) or nix/pyproject.toml (addons mode), or run "
    "`nix run github:Avunu/odoo-nix#odoo-init -- --sync --standards recommended`"
)

PRODUCT = Product(
    identity=Identity(
        name="odoo-nix",
        cli="odoo-nix",
        distribution="odoo-nix-tools",
        version=__version__,
        table="odoo-nix",
        env_prefix="ODOO_NIX",
        report_key="odoo_nix",
        sync_command="odoo-init --sync",
        opt_in_hint=OPT_IN_HINT,
        docs_url=DOCS,
        config_file="pyproject.toml",  # the project value; hooks.config_file picks per shape (CR1)
        # config_paths=("pyproject.toml", "nix/pyproject.toml"),   # CR1: every file the table may live in
        config_required=False,  # a missing file reads {}: exit 2 with the hint; --standards creates the
        # table (a project's root file; an addon repo's nix/pyproject.toml must
        # already exist, §3.4 preflight)
        description=f"odoo-nix's standards tools for Odoo projects and addon repositories. See {DOCS}.",
    ),
    markers=Markers(
        managed="odoo-nix:managed",
        header="odoo-nix:managed — generated by odoo-nix (`odoo-init --sync`);",
        header_local="edit only inside the odoo-nix:local region.",
        local="odoo-nix:local",
        block_begin=">>> odoo-nix: {name} (managed) >>>",
        block_end="<<< odoo-nix: {name} (managed) <<<",
        html_begin="<!-- odoo-nix:begin {name} -->",
        html_end="<!-- odoo-nix:end {name} -->",
    ),
    engine=Engine(
        flake_input="odoo-nix",
        repo="Avunu/odoo-nix",
        release_branch="release-{major}",
        url_key="dev-shell.odoo-nix-url",
        install_spec="odoo-nix-tools @ git+https://github.com/{owner}/{repo}@{rev}#subdirectory=py/odoo_nix_tools",
        caller_stem="odoo-*",
        init_app="odoo-init",
        version_file="version.txt",
        tool_python="3.12",
        base_input="python-devops-nix",
    ),
    pins=Pins(
        dir=".odoo-nix/pins",
        engine_pinned={},
        lock_paths=("tools/uv.lock", "package-lock.json"),
        managed_inputs=lambda ctx: (
            ("odoo-nix",) + (("standards-profile",) if ctx.profile_input else ())
        ),
    ),
    modules=Modules(
        names=MODULES,
        needs={
            # tools/.venv is built for any module of TOOLS_MODULES (§3.1), so no lint module needs python-lint
            "ide": (
                "python-lint",
                "js-xml",
            ),  # ruff.path names tools/.venv/bin/ruff; prettier.prettierPath
            # names ./node_modules/prettier
            "releases": (
                "commits",
                "ci",
            ),  # levels come from conventional commits; the flow is a ci caller
            "repo-policy": ("ci",),  # required checks are the ci gates
        },
        github_only=("dependabot", "ci", "repo-policy", "releases", "workflow-lint"),
        app_only=("shape", "series", "untested"),
        required="dev-shell",
    ),
    data_root=DATA,
    hooks=Hooks(
        load_checkout=discover.load_checkout,
        discover=discover.facts,
        gates=context.gates,
        template_globals=context.template_globals,
        render_helpers=context.render_helpers,
        derive=discover.derive,
        url_placeholders=context.url_placeholders,
        preflight=checks.preflight,
        notices=checks.notices,
        checks=checks.checks,
        committed_argv=policy.committed_argv,  # tools/.bin/committed when linked, else PATH (§5.2)
        new_target_table=discover.new_target_table,
        semantic_compare=lambda ctx: (
            True
        ),  # YAML/JSON whole files compare as data: prettier owns layout
        pr_checks=policy.pr_checks,
        write_fixture=fixtures.write,
        fleet_table=fleet.fleet_table,
        doctor_rows=fleet.doctor_rows,
        repo_policy_values=fleet.repo_policy_values,  # §2.2: per-series release pattern, project bypass
        # config_file=discover.config_file,         # CR1: added in the commit that pins the core with CR1
    ),
    sync=SyncHooks(
        phase_a_before=bootstrap.phase_a_before,
        required_tools=("uv", "npm"),  # odoo-init has both on its PATH (§5.1)
        reexec_argv=bootstrap.reexec_argv,  # the locked engine's odoo-init, not .#odoo-init (§2.5)
        reentry_argv=bootstrap.reentry_argv,
        rollout_steps=(("nix", "run", "--no-pure-eval", ".#relock"),),  # C3
    ),
    ci=CiConfig(
        gates=("pr-policy", "lint", "test"),
        check_context="ci / {gate}",
        contexts=(
            ("ci / lint", "ci.yml"),
            ("ci / test", "ci.yml"),
            ("ci / pr-policy", "pr-policy.yml"),
        ),
        labels={
            "dependencies": (
                "0366d6",
                "Pull requests that update a dependency",
                "dependabot",
            ),
            "needs-review": (
                "d93f0b",
                "A dependency update the decision table leaves to a person",
                "dependabot",
            ),
        },
        decision_table=verdict.DECISION_TABLE,
        ci_workflow="ci.yml",
        nightly_workflow="",
        arg_aliases={},
    ),
    paths=Paths(
        never_write=frozenset(
            {"odoo", "modules", ".odoo-nix", ".devenv", ".direnv", "node_modules"}
        ),
        not_source=(
            "odoo",
            "modules",
            ".odoo-nix",
            ".devenv",
            ".direnv",
            ".venv",
            "node_modules",
            "tools",
            "nix",
            "setup",
        ),
        github_marks=(".github",),
    ),
    schemas=Schemas(),
    header_kinds={"js": HeaderKind("//"), "md": HeaderKind("<!--", "-->")},
    jsonc_globs=(".vscode/*.json",),
    json_style=JsonStyle(
        indent="  ", tab_width=2, width=80, trailing_commas="none"
    ),  # prettier's form
    jinja_filters={
        "regex_alt": context.regex_alt,
        "path_prefix_regex": context.path_prefix_regex,
    },
    handlers={
        "tools-pyproject": TomlMergeHandler("tools-pyproject", groups.TOOLS),
        "package-json": JsonGroupsHandler("package-json", groups.PACKAGE),
    },
    version_schemes={"odoo-series": release.OdooSeries()},
    branching=release.BRANCHING,  # "develop+series" first (the default), then "trunk"
    release_tool=release.ManifestTool(),
    first_opt_in=checks.FIRST_OPT_IN,  # §2.6
    fixtures=fixtures.FIXTURES,  # {"project": …, "addons": …}
    fleet_key="repos",
    self_repo="Avunu/odoo-nix",
    audit_rows=fleet.AUDIT_ROWS,  # A12, A13 (§2.7)
    help=context.HELP,
)
```

Notes on values:

- **Core fields only.** Every keyword above exists in the core's stage-1 `product.py` (verified field by field).
  The two CR1 fields stay commented out until the core commit that adds them is pinned; `Product(...)` with an
  unknown field is a `TypeError` at import, which `test_product` catches.
- **Env prefix `ODOO_NIX`.** The core reads `ODOO_NIX_{SYNC_RESULT,SYNC_LOCK_CHANGED,SYNC_REEXEC,SYNC_REENTERED,
  URL_OVERRIDE,ALLOW_SKEW,CI,LOCKED_REV,FETCH_TOKEN,PIN_URL,OFFLINE,DEBUG,EXPECT_REV,ISSUE_TOKEN}`. odoo-nix
  already exports `ODOO_NIX_HTTP_PORT`, `ODOO_NIX_RESTORE_*`, `ODOO_NIX_LOCAL_ADDONS`, `ODOO_NIX_RAW_ODOO`,
  `ODOO_NIX_DEVGUARD`, `ODOO_NIX_TEST_ALLOW_SKIP`; none collides. `ODOO_NIX_CI` is shared on purpose: odoo-nix's
  CI mode (`modules/devenv.nix` ciMode, "set to anything but "", 0 or false") and the core's `<P>_CI` mean the
  same thing. New odoo-nix names: `ODOO_NIX_COVERAGE_RCFILE` (§6.1.2), `ODOO_NIX_AUDIT_TOKEN` (profile repo).
- **Markers.** Every existing odoo-nix block in the targets has a space in its name and therefore is foreign
  (core §5.6.1): `# >>> odoo-nix: install set (managed from modules.txt) >>>`/`# <<< odoo-nix: install set <<<`,
  `# >>> odoo-nix: module sources (managed) >>>`/`# <<< odoo-nix: module sources <<<`,
  `# >>> odoo-nix: sdist build deps (managed) >>>`/`# <<< odoo-nix: sdist build deps (managed) <<<`
  (`lib/oca_sources.py:44-47`, `templates/addons/nix/pyproject.toml`, project B's `pyproject.toml`).
  Owned names are kebab-case without spaces (`inputs`, `dev-shell`, `addons-table`).
- **Caller glob `odoo-*`** matches the five reusable workflows; `fleet-audit.yml` is called only by the profile
  repository and is not a skew row.
- **Pins dir** `.odoo-nix/pins`: one gitignored runtime directory in both shapes (addons mode already ignores
  `/.odoo-nix/`; the project gitignore block adds it, §3.1).

### 2.2 Version scheme, release tool and branching (`release.py`)

```python
SERIES_VERSION = re.compile(r"^(?P<series>\d+\.0)\.(?P<x>\d+)\.(?P<y>\d+)\.(?P<z>\d+)$")
EXEMPT = ("tests/**", "README.md", "README.rst", "readme/**", "i18n/**", "i18n_extra/**",
          "static/description/**")


class OdooSeries:
    """`<series>.x.y.z` per addon: `!`/BREAKING → x, feat → y, fix/perf → z (plan Amendments)."""

    name = "odoo-series"

    def valid(self, version: str, cfg: Mapping[str, Any], facts: Facts) -> str | None:
        # None, or "version 17.0.1.0.0 is not 18.0.x.y.z" (prefix must equal facts["series"])
    def bump(self, version: str, level: Level, cfg: Mapping[str, Any], facts: Facts) -> str:
        # major: x+1, y=z=0; minor: y+1, z=0; patch: z+1. 18.0.1.2.3 + minor → 18.0.1.3.0
    def message_problems(self, text: str, cfg: Mapping[str, Any], facts: Facts) -> list[str]:
        # ["Release-As has no meaning here: each addon's version moves in `ci bump`"] when a
        # Release-As footer is present; [] otherwise
    def tag_problem(self, tag: str, cfg: Mapping[str, Any], facts: Facts) -> str | None:
        # "odoo-series releases make no tags" when tag != "", else None


class ManifestTool:
    name = "odoo-manifest"
    commit_subject = "chore(release): bump {units}"

    def units(self, root: Path, ctx: NS) -> list[ReleaseUnit]:
        # [ReleaseUnit(a["name"], f"{a['path']}/", f"{a['path']}/__manifest__.py")
        #  for a in ctx.discover["addons"] if a["installable"]], sorted by name
    def read_version(self, text: str, unit: ReleaseUnit) -> str | None:  # manifests.literal(text).get("version")
    def write_version(self, text: str, unit: ReleaseUnit, version: str) -> str:
        # manifests.replace_version: the one string-literal value of the top-level "version" key, located
        # through ast (lineno/col_offset/end_col_offset), replaced with the same quote character; every other
        # byte kept. No "version" key, or a non-literal value → ValueError naming unit.version_file
    def exempt(self, unit: ReleaseUnit, path: str) -> bool:
        # globs.match(EXEMPT, path.removeprefix(unit.path))


BRANCHING = {
    "develop+series": Branching(
        name="develop+series", flow="post-merge-bump",
        integration=lambda cfg: "develop",
        release_branch=lambda cfg, facts: facts.get("series", "") if facts.get("shape") == "addons" else "",
        release_pattern="refs/heads/*.0", release_label="*.0", tags=False),   # overridden per checkout, below
    "trunk": Branching(
        name="trunk", flow="none",
        integration=lambda cfg: "main",
        release_branch=lambda cfg, facts: ""),
}


def repo_policy_values(cfg: Mapping, modules: Mapping, gates: Sequence[str]) -> dict[str, Any]:  # fleet.py
    """Core §7.3 lets this override any value. Two overrides:
    - addons under develop+series: release_pattern = f"refs/heads/{cfg['series']}", release_label =
      cfg["series"], so the release ruleset protects only the series branch `.odoo-series` names. A maintenance
      branch of another series (the two-branch Dependabot case, 17.0) is not App-only, so its PRs can merge;
    - shape project: integration_bypass = [] (CR3 fallback): a project inherits `releases` from the Avunu
      profile, has no release branch, and must never let the App bypass the pull-request rules on main/master.
    """
```

`preflight` (§3.4) refuses `releases` under `develop+series` when the integration branch matches `^\d+\.0$`
(a repository whose `origin/HEAD` is a series branch, as odoo-studio's `18.0`): its integration branch would equal
its release branch, and the release ruleset would block every pull-request merge. Such a repository first creates
`develop` and moves its default branch there.

The flow (core §8.2) for an addons repository: `odoo-release.yml` runs `standards-release-ff` with `bump: true`,
`release-branch: <series>`, `base: origin/<series>`, `wait-checks: 900`, the CI App token. `ci bump` reads units
from `ManifestTool`, levels from `conventional.parse`, writes manifests, commits `chore(release): bump
edi_import_router, import_preview` to `develop` and pushes; `ci fast-forward` moves `18.0` when the required
contexts on that commit are green (push-triggered `ci.yml` and `pr-policy.yml`, §6.4). A project's
`release_branch` is `""`, so neither the release caller nor the release ruleset is rendered there.

### 2.3 Discovery (`discover.py`)

```python
def config_file(root: Path) -> str: ...
def load_checkout(root: Path) -> Checkout: ...
def facts(
    checkout: Checkout, cfg: Mapping[str, Any], modules: Mapping[str, bool]
) -> dict[str, Any]: ...
def derive(cfg: dict[str, Any], checkout: Checkout | None) -> None: ...
def new_target_table(
    root: Path, checkout: Checkout, args: argparse.Namespace, profile: str
) -> dict[str, Any]: ...
```

All read `checkout.tracked` and tracked contents only (core §3.4), iterate sorted, never the clock.

**`config_file(root)`** (CR1), from `repo.ls_files(root)` and file text:

1. root `pyproject.toml` has the opt-in line (`^[ \t\n\v\f\r]*\[{1,2}tool\.odoo-nix[].].*`, core §2.2) → `pyproject.toml`;
2. `nix/pyproject.toml` has it → `nix/pyproject.toml`;
3. both → `ConfigError` (exit 2): "both pyproject.toml and nix/pyproject.toml open [tool.odoo-nix]: keep the one of
   this repository's shape";
4. neither (not opted in; `--standards` creates the table there) → `nix/pyproject.toml` when the files say addons
   mode (rule 2 of the shape precedence below), else `pyproject.toml`.

**`load_checkout(root)`** wraps `default_load_checkout(PRODUCT)` and adds `extra = {"flake": <comment-stripped
flake.nix text or "">, "gitlinks": {path: sha} from git ls-files -s mode 160000, "config_path": config_file(root)}`.
Name: the core rule (`[project].name` of the config file → table `repo` → origin → `root.name`). Two target
consequences: project A's `[project].name` is `"odoo-workspace"`, so the checkout is named `odoo-workspace` (its
tools project `odoo-workspace-tools`); its only remote is `upstream`, so `new_target_table` writes `repo` (below)
for the URL placeholders. In an addon repository the config file is `nix/pyproject.toml`, whose `[project].name`
is the `@PROJECT_NAME@` odoo-init rendered (`edi-addons`, verified), so the name comes from there, not from origin.

**Shape precedence** (`facts["shape"]`):

1. explicit `[tool.odoo-nix] shape` (`"project"` | `"addons"`);
2. addons signals, any of: `addons.enable = true` or `addons = { enable = true` in the comment-stripped
   `flake.nix` (`nixattrs.strip_nix_comments`, then a regex); `layout.customDir = "."`; a tracked
   `*/__manifest__.py` at the root;
3. project signals: a gitlink at `odoo` (mode 160000), or a tracked `modules.txt`;
4. none → `ConfigError` (exit 2): "cannot tell this repository's shape: set [tool.odoo-nix] shape".

Signals of both kinds without an explicit shape: rule 2 wins, with the notice "both addons-mode and project
signals; using addons (set shape to choose)".

**Series precedence** (`facts["series"]`, `^\d+\.0$`, must have `data/series/<series>.json`):

1. tracked `.odoo-series` (stripped);
2. a literal `odooSeries = "18.0"` in `flake.nix` (`lib.fileContents ./.odoo-series` is rule 1);
3. the installable addons' manifest versions: the first two components; they must agree (else exit 2 listing
   the addons per series);
4. the integration branch name, when it matches `^\d+\.0$`.

None → exit 2 "cannot tell the Odoo series: add .odoo-series". A series without data → exit 2 "odoo-nix-tools
2.x knows series 18.0, 19.0, 20.0". The `ocb` lock node's `original.ref` and every `.gitmodules` `branch` are
not sources; disagreement with them is a `checks` item (§3.4). An explicit `[tool.odoo-nix] series` (app-only)
overrides all four (for a repository on `main` whose code targets 20.0, plan C fleet note).

**Fact keys** (core facts `gitmodules`, `github_workflows` plus):

| Key | Type | Value |
|---|---|---|
| `shape` | str | above |
| `series` | str | above |
| `series_sources` | dict | `{"odoo-series": "18.0" \| None, "flake": …, "manifests": {…}, "branch": …, "ocb-lock": …}` for the agreement check |
| `config_file` | str | `config_file(root)` |
| `lock_dir` | str | `"nix"` (addons) \| `"."` (project) |
| `addons_root` | str | `"."` (addons); project: the `layout.customDir = "…"` literal in `flake.nix`, else `"custom"` |
| `addons` | list[dict] | one per tracked `<addons_root>/<name>/__manifest__.py`, sorted by name: `{name, path, installable (default True), license, author (str), website, version, depends, has_py, has_js, has_xml, has_tests (a tracked tests/__init__.py), readme ("README.md"\|"README.rst"\|None), icon: {"present": bool, "width", "height", "bytes"}, packaged (tracked pyproject.toml or setup.py), whool (pyproject.toml whose build-backend is "whool.buildapi"), package_json (tracked package.json)}`. A manifest that `ast.literal_eval` cannot read is exit 2 naming it |
| `installable` | list[str] | names with `installable` true |
| `not_installable` | list[str] | the rest (rendered into the pre-commit exclude, §3.3) |
| `submodules` | list[dict] | from tracked `.gitmodules`, sorted by path: `{path, url, branch \| None, shallow, gitlink: bool}` |
| `flake` | dict | `{present, addons_mode, self_submodules, lock_dir_literal, external_sources (bool), inputs: nixattrs.flake_input_specs(text)}` |
| `has_sh`, `has_nix`, `has_js`, `has_xml`, `has_py` | bool | any tracked file of that kind outside `paths.not_source` (`*.sh`, `*.nix`, `*.js`, `*.xml`, `*.py`) |
| `root_package_json` | bool | tracked `package.json` at the root |
| `addon_package_json` | list[str] | addon directories with their own `package.json` (`web_theme_carbon`, `shopfloor_repair_mobile/static`) |
| `dev_group_ruff` | bool | `ruff` in the config file's `[dependency-groups].dev` (notice) |
| `vscode` | dict | `{"settings": bool, "extensions": bool}` tracked |

**`derive(cfg, checkout)`** (core §4.4 step 8), in place, `checkout` may be `None`:

- `cfg.setdefault("shape", facts.shape)`, `cfg.setdefault("series", facts.series)` (so `odoo-nix config series`
  works in CI, §6.4);
- when the checkout's table has no `integration-branch` and the shape is `project`, set it to `"main"`
  (step 7 gave the branching default `develop`; a project has no develop+series flow). project B gets `master`
  from `--standards` (origin/HEAD), project A keeps `main`;
- `dependabot.target-branches`: `[]` → `[cfg["integration-branch"]]`;
- `addon-manifest.licenses-allowed`: `[]` → `[org.license]` when `org.license` is set, else stays `[]`
  (OCA's list, §3.1 pylint-odoo).

**`new_target_table(root, checkout, args, profile)`**: returns `{"repo": "<owner>/<name>"}` when the
checkout has no `origin` remote and exactly one other remote (project A: `upstream` →
its repository), else `{}`. The core prepends `schema`, `profile` and appends `integration-branch`
when `origin/HEAD` names another branch (project B: `master`; edi-addons: `origin/HEAD -> origin/develop`, the
default, so nothing).

### 2.4 Template context (`context.py`)

`template_globals(checkout, resolved, base_ctx) -> dict` adds (none shadows a core key, core §3.5):

| Key | Value |
|---|---|
| `shape`, `series`, `addons_root`, `lock_dir`, `config_file` | the facts |
| `addons`, `installable`, `not_installable` | the facts |
| `series_data` | `series.effective(series, cfg, facts)`: the series file with every deviation applied (§3.0) |
| `tools` | `{name: requirement}` for the live `tools/pyproject.toml` groups, from `series_data.tools` + `data/tool-pins.json` |
| `node_tools` | `{package: version}` for `package.json` (prettier, @prettier/plugin-xml, eslint, eslint-plugin-jsdoc, globals) |
| `hooks` | `precommit.hooks(...)`: the rendered hook list (§3.3) |
| `tools_python` | `series_data.python.default_language_version` (`python3.12` in all three files) |
| `odoo_python` | `lib/odoo-presets.json` `requiresPython` of the series (`>=3.11` for 18.0, `>=3.12` else), copied into `data/series` consumers by `series.load` |
| `ide` | `data/ide/vscode.json` |
| `website` | `addon-manifest.website` with url placeholders applied, or `""` |
| `scopes` | sorted addon names + `commits.extra-scopes` when `commits.scopes == "addons"` |

`render_helpers(ctx, current) -> {"gen": Gen(ctx)}`; `Gen` has `pylintrc(kind: Literal["optional", "mandatory"])
-> str`, `eslint_config() -> str`, `ruff_toml() -> str`, `exclude_block() -> str` (pure functions of `ctx`).

`gates(modules, cfg, facts) -> list[str]` in `ci.gates` order: `pr-policy` when `commits` or `releases` is on;
`lint` when any of `LINT_MODULES` is on; `test` when `tests` is on and `installable − untested` is non-empty.

`url_placeholders(ctx) -> (("repo_name", repo.partition("/")[2]), ("repo", repo))`: the Avunu profile's
`docs-url = "https://docs.avunu.net/{repo_name}/"` and `website = "https://github.com/{repo}"`.

### 2.5 Phase hooks (`bootstrap.py`)

```python
def phase_a_before(plan: Plan, runner: Runner, args: argparse.Namespace) -> None:
    """A project with submodules not checked out (`git submodule status` lines starting `-`) runs
    `nix run github:<owner>/<repo>/<locked odoo-nix rev>#bootstrap -- <root>` (the app lib/bootstrap.sh
    builds; it reads flake.lock, never evaluates the project). Offline or --skip-lock: a notice
    "submodules are not checked out; nix may fail to evaluate the flake (self.submodules)" and nothing runs.
    Addons mode: nothing (no submodules; OCB is coreSource)."""


def reexec_argv(passthrough: list[str]) -> list[str]:
    """["nix", "run", f"github:{owner}/{repo}/{rev}#odoo-init", "--", "--sync", *passthrough], with owner,
    repo and rev from flake.lock's odoo-nix node (`flakelock.engine_rev`). The locked engine's own app: the
    project flake is never evaluated, so a project re-execs without its submodules."""


def reentry_argv(passthrough: list[str]) -> list[str]:
    """The same app with `--phase b` (odoo-init accepts the hidden `--phase` and passes it on, §5.5). Only a
    no-Nix install (`uv tool install`) without uv or npm on PATH gets here: odoo-init and the dev shell have
    both."""
```

No `phase_a_after`, `post_write` or `phase_b_after`: managed JSON is written in prettier's form
(`json_style`), managed YAML is compared as data, and the locks are core lock steps (`uv-lock`, `npm-lock`).
`required_tools = ("uv", "npm")`: `odoo-init` carries `pkgs.uv` and `pkgs.nodejs` on its `runtimeInputs` (§5.1;
today it has uv only, `lib/init.nix:47-52`), and the dev shell has `uv` and `cfg.nodejs`, so phase B never re-enters
the full dev shell (which would build the Odoo environment and, in a project, need the submodules). The lock format
does not depend on the node version (`npm install --package-lock-only` writes `lockfileVersion: 3` from npm 7 on).

### 2.6 First opt-in (`checks.FIRST_OPT_IN`)

| Path | Hint | `legacy` (replaced silently) |
|---|---|---|
| `.pre-commit-config.yaml` | "Move your own hooks into the `# odoo-nix:local-begin hooks` region of the managed file, and your own exclude alternatives into its `exclude` region," | — |
| `.envrc` | "Put your own lines in the `# odoo-nix:local-begin envrc` region," | `templates/project/.envrc` (the bootstrap `if` + `use flake . --no-pure-eval`); `templates/addons/.envrc` / project A / all 10 addon repos: `use flake . --no-pure-eval\n`; project B: `# The Python env is built from these, so rebuild the shell when they change.\nwatch_file pyproject.toml uv.lock modules.txt\nuse flake . --no-pure-eval\n` |
| `.ruff.toml` | "Move your own rules into python-lint's extra-select, ignore and per-file-ignores, or the local region," | — |
| `.github/dependabot.yml` | "Move your own update entries into the `updates` local region," | — |

`flake.nix` is covered by the inputs block's `claims` (core §5.6.4), not by this list.

### 2.7 Fleet, audit and doctor (`fleet.py`)

`data/schema/fleet-entry.schema.json`:

```json
{
  "$comment": "One entry of an odoo-nix fleet.json (docs/standards/fleet.md).",
  "type": "object",
  "additionalProperties": false,
  "required": ["repo", "shape", "branches", "private"],
  "properties": {
    "repo": {"$ref": "core.schema.json#/$defs/fleet-entry-core/properties/repo"},
    "shape": {"enum": ["project", "addons"]},
    "branches": {"$ref": "core.schema.json#/$defs/fleet-entry-core/properties/branches"},
    "integration_branch": {"$ref": "core.schema.json#/$defs/fleet-entry-core/properties/integration_branch"},
    "private": {"$ref": "core.schema.json#/$defs/fleet-entry-core/properties/private"},
    "documentation": {"$ref": "core.schema.json#/$defs/fleet-entry-core/properties/documentation"},
    "profile": {"$ref": "core.schema.json#/$defs/fleet-entry-core/properties/profile"}
  }
}
```

An addon entry is `{"repo": "Avunu/edi-addons", "shape": "addons", "branches": ["develop", "18.0"], "private":
false}`: `branches[0]` is the integration branch (core §7.1), the rest are series branches (`scripts/check_fleet.py`:
for addons, `branches[1:]` match `^\d+\.0$` and `branches[0]` does not). No product hook is needed: core
`Target.branches` reads `entry["branches"]`.

```python
def fleet_table(repo: str, entry: Mapping[str, Any], ref: str) -> dict[str, Any]:
    return {
        "shape": entry["shape"],
        "integration-branch": entry.get("integration_branch") or entry["branches"][0],
    }


AUDIT_ROWS = {
    "A12": RowSpec(
        "the fleet's series branches (branches[1:]) include .odoo-series; dependabot.target-branches "
        "lists the integration branch and no branch the release ruleset protects (a Dependabot PR "
        "there could never merge)",
        "releases",
        _a12,
    ),
    "A13": RowSpec(
        "every submodule pins `branch = <series>`", "ci", _a13
    ),  # projects; n/a for addons
}


def doctor_rows(repo: str, rc: RepoConfig) -> tuple[list[DoctorRow], list[str]]:
    """With releases on under develop+series: the Actions variable named by ci.github-app.app-id and the
    secret named by ci.github-app.private-key exist (org or repo); repo-policy.release-bypass is
    `integration:<id>` with a numeric id (the bump push and the fast-forward need it, core §7.3).
    The variable holds the App's *client ID* (`mirror.yml` passes `vars.AVUNU_CI_APP_ID` as
    `create-github-app-token`'s `client-id`), which is not the numeric App id the ruleset bypass needs; the
    row says so when release-bypass is missing. A project without an App (project B blanks ci.github-app): a
    notice that `project-update` PRs get CI by dispatch (§6.4)."""
```

### 2.8 Dependabot decision table (`verdict.py`)

| # | ecosystem | condition | verdict |
|---|---|---|---|
| 1 | github_actions | names `$engine` (`Avunu/odoo-nix`) | review, sticky |
| 2 | github_actions | names `Avunu/python-devops-nix/*` | review, sticky |
| 3 | github_actions | group `actions` | auto |
| 4 | github_actions | `ungrouped_named` | auto |
| 5 | nix | names `$rollout-inputs` (`odoo-nix`, `standards-profile`) | close |
| 6 | nix | any | relock (an addon-repo input move needs `nix run .#relock`: `nix/uv.lock` follows OCB and the external sources) |
| 7 | npm_and_yarn | directory `/` | close, sticky (the locked JS tools; Dependabot is not configured for them, this covers a hand-added entry) |
| 8 | uv | directory `/tools` | close, sticky |
| 9 | npm_and_yarn | `minor-patch` (an addon's own `package.json` from a local region, e.g. `/web_theme_carbon`) | auto |
| 10 | submodules | any | relock |

No match → review (core §8.3).

---

## 3. Module registry v1

### 3.0 Series data and deviations (`series.py`)

```python
@dataclass(frozen=True)
class SeriesData:
    series: str
    raw: Mapping[str, Any]  # the JSON file
    tools: Mapping[
        str, Tool
    ]  # OCA pins + data/tool-pins.json for the null-version tools
    hooks: tuple[Mapping, ...]  # after deviations
    exclude: tuple[Mapping, ...]  # alternatives after deviations
    ruff: Mapping[str, Any]
    pylint: Mapping[str, Any]
    files: Mapping[
        str, str
    ]  # .editorconfig, eslint.config.cjs, prettier.config.cjs bodies
    esm_globs: tuple[str, ...]
    deviations: tuple[str, ...]  # ids applied, for docs and `profile show --explain`


def load(
    series: str,
) -> Mapping[str, Any]: ...  # functools.cache; schema_version must be 1
def effective(series: str, cfg: Mapping, facts: Facts) -> SeriesData: ...
```

`DEVIATIONS` (each id is tested by `test_series`, and `docs/standards/managed-files.md` lists it by hand, its ids and `Applies` column held to it by `test_series.Docs`; O9-19):

| Id | Applies | Change (data fact it changes) |
|---|---|---|
| `esm-static` | series ≥ 18.0 | `eslint_esm_globs` (`["**/*.esm.js", "**/*test.js"]` in all three files) gains `"**/static/src/**/*.js"`, `"**/static/tests/**/*.js"`: Odoo ≥ 18.0 loads these as ES modules |
| `github-per-hook` | always | the global alternative `^.github/` (`moved_to_per_hook: true`) leaves the top-level exclude; every OCA-derived hook gets `^\.github/` in its own `exclude`, so actionlint, zizmor and check-yaml see `.github/` |
| `drop-gen-readme` | always | hook `oca-gen-addon-readme` dropped (Markdown READMEs; OCA's own CI already SKIPs it: `ci.pre_commit_skip`) |
| `drop-excluded-addons` | always | hook `oca-update-pre-commit-excluded-addons` dropped: the engine renders the `# NOT INSTALLABLE ADDONS` region from discovery; that hook also rewrites `.pre-commit-config.yaml` (`rewrites_pre_commit_config: true`), `.gitignore` and `.coveragerc` |
| `drop-external-deps` | always (**proposed, pending the user's sign-off**, §0.1) | hook `oca-gen-external-dependencies` dropped: it writes a root `requirements.txt` that nothing in odoo-nix's uv model reads (addons mode derives the lock from manifests, `lib/oca_sources.py --roots=local`). If declined, the hook stays (entry `tools/.venv/bin/oca-gen-external-dependencies`) and `requirements.txt` is tracked as OCA does |
| `prettier-vscode` | always | the `prettier` hook gets `^\.vscode/` in its exclude, as `check-json` does: prettier would rewrite the editor's JSONC files (project B's 4-space `settings.json` to 2 spaces; a final newline and spaces into the one-line `extensions.json`), undoing what jsonc-merge preserves |
| `addons-dir` | shape project | `oca-fix-manifest-website` gets `--addons-dir=<addons_root>` before its URL argument (its click option defaults to `.`, `tools/fix_manifest_website.py:15`, so in a project with addons in `custom/` it would do nothing) |
| `forbid-contributing` | `hygiene.forbid-contributing == false` | the `obsolete dotfiles` hook's `files` regex loses the alternative `CONTRIBUTING\.md\|` (an exact substring edit; its absence from a series file is a `RuntimeError`, so a template change is noticed) |
| `no-readme-fix` | 20.0 | `oca-checks-odoo-module` loses `--fix` (20.0's hook can rename `README.md` → `README.rst`) |
| `stage-names` | 18.0 | `stages` `commit`/`push`/`merge-commit` → `pre-commit`/`pre-push`/`pre-merge-commit` (pre-commit-hooks v4.6.0's manifest uses the old names) |
| `pylint-dedupe` | always | duplicate messages in the `.pylintrc*` enable lists are written once, first occurrence kept |
| `required-author` | `addon-manifest.author == ""` | `manifest-required-authors` is not written and `manifest-required-author` leaves both enable lists (pylint-odoo would otherwise require OCA's default author) |
| `system-language` | always | every hook is `language: system` (or `fail`); `additional_dependencies`, `rev`, `default_language_version` dropped; `entry` is the locked executable (§3.3); every other key (`pass_filenames: false` of `oca-fix-manifest-website` and `whool-init`, `always_run`, `files`) is kept from the data |
| `locks-excluded` | always | top-level exclude gains `(^\|/)(uv\|flake)\.lock$\|(^\|/)package-lock\.json$` |
| `odoo-nix-pins` | always | `manifestoo`, `checklog-odoo`, `coverage` (null in OCA data) and `prek` come from `data/tool-pins.json` |
| `node-runtime` | 19.0, 20.0 | the shell's node is the preset's (`nodejs_24`), not OCA's `default_language_version.node` (`22.9.0`/`22.23.2`); 18.0 matches (`nodejs_22`) |

Placeholders: `@@org_name@@` → `addon-manifest.author`; `@@repo_website@@` → the rendered `addon-manifest.website`;
`@@org_slug@@`/`@@repo_slug@@` appear only in the dropped readme hook. A placeholder left in rendered output is a
`RuntimeError` (a product bug).

### 3.1 Modules

"P" = project, "A" = addons. "rec" and "Avunu" are the resolved values under `recommended@2.3` and the Avunu
profile. Strategies are core §5. Every entry lives in `data/manifest.d/<nn>-<area>.json`.

| Module | Shapes | rec / Avunu | Managed files (strategy, phase) | Parameters (default) | Series data used |
|---|---|---|---|---|---|
| **dev-shell** | P, A | on / on | `flake.nix` block `inputs` (sentinel, anchor `nix-attrset inputs`, `claims: nix-inputs`, phase a, **no** `seed_template`: preflight refuses a checkout without its shape's `flake.nix`, §3.4); `.envrc` (whole, `shell`, local region `envrc`, phase a); `.gitignore` block `dev-shell` (sentinel, anchor `eof`, `absorb`) | `odoo-nix-url` (`""` → `github:Avunu/odoo-nix/release-{major}`) | — |
| **editorconfig** | P, A | on / on | `.editorconfig` (whole, `ini`, local region `editorconfig`) | — | `files[".editorconfig"]` + a `[*.{nix,sh}]` `indent_size = 2` section |
| **python-lint** | P, A | on / on | `.ruff.toml` (whole, `toml`, local region `ruff`); its share of the tools project (below) | `extra-select` [], `ignore` [], `per-file-ignores` {}, `extend-exclude` [] | `ruff` (target-version, lint/format/isort/mccabe/per-file-ignores); `tools.ruff` |
| *(tools project)* | P, A | — | `tools/pyproject.toml` (toml-merge `tools-pyproject`) and `tools/uv.lock` (`uv-lock`, `relock_when: ["tools/pyproject.toml"]`, no `floors`), both with `module: TOOLS_MODULES` = every module that puts a tool in it: `python-lint`, `pylint-odoo`, `addon-manifest`, `hygiene`, `tests`, `packaging`, `icons`, and the pre-commit modules that need `prek` (`js-xml`, `workflow-lint`, `shell-lint`, `nix-lint`, `commits`). With `python-lint` off and `tests` on, the lock and `tools/.venv/bin/coverage` still exist | — | `tools.*`, `data/tool-pins.json` |
| **pylint-odoo** | P, A | on / on | `.pylintrc`, `.pylintrc-mandatory` (whole, `ini`); tools group `pylint-odoo` | `optional-run` (true: the `--exit-zero` hook on `.pylintrc`) | `pylint.sections`, `pylint.messages`, `pylint.odoolint`; `tools.{pylint-odoo, odoo-pre-commit-hooks}` |
| **addon-manifest** | P, A | on / on | no file; tools group `addon-manifest` | `author` "", `licenses-allowed` [] (→ `org.license`, else OCA's `license-allowed`), `website` "" | `pylint.odoolint` (`manifest-required-authors`, `license-allowed`, `valid-odoo-versions` = series); `tools.{maintainer-tools, manifestoo}` |
| **js-xml** | P, A | on / on | `package.json` (json-merge `package-json`); `package-lock.json` (`npm-lock`, `relock_when: ["package.json"]`); `prettier.config.cjs`, `eslint.config.cjs` (whole, `js`) | `exclude` [] (path prefixes, e.g. `carbon_ui/frontend/`, `static/dist/`) | `files["prettier.config.cjs"]`, `files["eslint.config.cjs"]` (rules, globals), `eslint_esm_globs`; npm `tools` |
| **ide** | P, A | **off** / on | `.vscode/settings.json`, `.vscode/extensions.json` (jsonc-merge) | — | none (`data/ide/vscode.json`) |
| **tests** | P, A | on / on | tools group `tests` (`[tool.coverage.*]` and the coverage/checklog pins); `checklog-odoo.cfg` (seed) | `initial-floor` 0, `goal` 80 (shown, never a gate), `checklog` true | `reference_files["checklog-odoo.cfg"]` |
| **workflow-lint** (GH) | P, A | on / on | `.github/zizmor.yml` (whole, `yaml`) | — | — |
| **shell-lint** | P, A | on / on | none (hook when `has_sh`) | — | — |
| **nix-lint** | P, A | on / on | none (hooks when `has_nix`) | — | — |
| **hygiene** | P, A | on / on | `.git-blame-ignore-revs` (`blame-ignore-revs` seed); tools group `hygiene` | `forbid-contributing` true (deviation `forbid-contributing`, §3.0) | pre-commit-hooks hooks and the three `fail` hooks |
| **commits** | P, A | **off** / on | `committed.toml` (whole, `toml`, local region `committed`) | `convention` "conventional" \| "odoo", `scopes` "addons" \| "any", `extra-scopes` [], `extra-types` []; core `allow-stacked`, `pr-allowed-bases`, `subject-length` | — |
| **releases** (GH) | A (inert in P) | off / on | `.github/workflows/release.yml` (via ci templates) | core `branching` ("develop+series"), `version-scheme` (**"odoo-series"**: the product schema overrides the core default "semver"), `tag-prefix` (unused), `tool` | — |
| **packaging** | A (inert in P) | off / on | none: the `whool-init` hook writes `<addon>/pyproject.toml`; tools group `packaging` | — | `tools.{whool, manifestoo-core}` |
| **dependabot** (GH) | P, A | on / on | `.github/dependabot.yml` (whole, `yaml`, local region `updates`) | core `auto-merge` true, `auto-merge-policy` "decision-table", `update-branches` false; `schedule` "weekly", `cooldown-days` 7, `target-branches` [] (→ `[integration-branch]`) | — |
| **ci** (GH) | P, A | on / on | `.github/workflows/{ci,pr-policy,deps}.yml` (whole, `yaml`); `release.yml` when releases is live | core `github-app`, `schedules`; `runs-on` `["ubuntu-latest"]`, `test-timeout-minutes` 60, `project-update` `"0 6 * * 1"` (P only) | — |
| **repo-policy** (GH) | P, A | off / on | none (`odoo-nix repo apply`) | core params | — |
| **readme** | P, A | off / on | root `README.md` block `addons-table` (sentinel, `comment: html`, anchor `eof`, `when: cfg.readme["addons-table"]`) | `addons-table` false, `required` true | — |
| **icons** | P, A | off / on | none (`odoo-nix check icons`) | `min-size` 128, `max-bytes` 102400, `src-icon` "templates/addon-icon.png" (in the profile directory) | `tools.maintainer-tools` (`oca-gen-addon-icon`) |

Shape gating: `releases` and `packaging` are inert in a project (every entry has `when: shape == "addons"`;
`release_branch` is `""`), with the notice "<module> applies to addon repositories; it does nothing in a
project". The Avunu profile turns both on and projects A and B inherit them (project B overrides `packaging` off;
neither overrides `releases`), so inert-with-notice is required rather than an error.

#### dev-shell

- **Inputs block** (`templates/flake/inputs.nix.j2`), body:
  ```nix
  odoo-nix.url = "{{ engine.url }}";
  {% if profile_input %}
  standards-profile = {
    url = "{{ profile_input }}";
    flake = false;
  };
  {% endif %}
  ```
  Claimed: `odoo-nix`, `standards-profile`. Not claimed: `nixpkgs` (its `follows` stays hand-written; both target
  shapes have it), `self` (`self.submodules = true;` in projects A and B is never an input, core §5.6.4), `ocb` and
  every other addons-mode input (the vertical-auto-repair flake has 25: OCA, Avunu addon repos, muk-it).
  No `seed_template`: a seed duplicated odoo-init's scaffold, and a seeded copy of `templates/addons/flake.nix`
  carried a hand-written `odoo-nix.url = "github:Avunu/odoo-nix"` outside any block, so its own first sync hit the
  claims rule (exit 2), and it had no `oca-*` inputs. The flake comes from `odoo-init` (`--addons` for addon
  repositories, §5.5), and preflight refuses a checkout without it (§3.4). odoo-init's templates
  (`templates/{project,addons}/flake.nix`) change to `odoo-nix.url = "github:Avunu/odoo-nix/release-@MAJOR@"`, the
  URL the block renders, so a freshly scaffolded flake's definition is *equal* and moves into the block silently
  (core §5.6.4) instead of needing `--force`.
- **`.envrc`** (`templates/envrc.j2`):
  ```sh
  # odoo-nix:managed — generated by odoo-nix (`odoo-init --sync`); edit only inside the odoo-nix:local region.
  watch_file {{ config_file }} {{ lock_dir ~ "/uv.lock" if lock_dir != "." else "uv.lock" }} {{ "modules.txt" if shape == "project" else ".odoo-series" }} tools/pyproject.toml tools/uv.lock package.json package-lock.json
  {% if shape == "project" %}<the bootstrap `if` block of templates/project/.envrc, verbatim>{% endif %}
  # odoo-nix:local-begin envrc
  # odoo-nix:local-end envrc
  use flake . --no-pure-eval
  ```
- **`.gitignore` block** (`templates/gitignore/dev-shell.j2`): both shapes `/odoo.conf`, `/odools.toml`, `/.venv`,
  `/.devenv/`, `/.direnv/`, `/.odoo-nix/`, `/tools/.venv`, `/tools/.bin`, `/node_modules`, `/result`, `/result-*`; plus
  `__pycache__/`, `*.py[cod]`. No trailing slash on the links (`odoo-nix` convention: git records a symlink as a
  file). `absorb` removes the identical hand lines (all 10 addon repos' `/.odoo-nix/` … `/result-*`, project A's and
  project B's `/odoo.conf`, `/odools.toml`, `/.venv`, `/.devenv/`, `/.direnv/`). The addon repos' `node_modules/`
  (trailing slash) is not identical and stays; it does not match the `node_modules` link, which `/node_modules`
  does. `absorb` never removes comments (core §5.6.3), so the addon repositories' two comment paragraphs
  ("# odoo-nix addons mode: links the dev shell makes …", "# devenv state: …") are left with nothing under them;
  `notices` names them ("<path>:<line>: this comment's lines moved into the dev-shell block; delete it") until CR4
  (§10) lands, and the adoption's `style:` commit deletes them (§8.2).

#### The shared `tools/pyproject.toml`

`groups.TOOLS: TomlGroups`. Each key path belongs to exactly one group (core §5.3: "each group owns its keys"), so
`[project].dependencies`, which every tool module contributes to, is owned by one group, `deps`, and per-module
membership is decided *by package name* inside `reconcile`, not by group retraction:

| Group | `on(ctx, group)` | Keys (path → value) |
|---|---|---|
| `project` | any module of `TOOLS_MODULES` on | `("project","name")` → `f"{name}-tools"`; `("project","version")` → `"0"`; `("project","requires-python")` → `odoo_python`; `("tool","uv","package")` → `false` |
| `deps` | any module of `TOOLS_MODULES` on | `("project","dependencies")` → the requirements of the live modules, in this order: `prek==<tool-pins.prek>` (the pre-commit config is live, §3.3); `ruff==…` (python-lint); `pylint-odoo==…`, `oca-odoo-pre-commit-hooks==…` (pylint-odoo); `pre-commit-hooks==…` (hygiene); `oca-maintainers-tools @ git+https://github.com/oca/maintainer-tools@<rev>` (addon-manifest with `website` set, or icons; one item), `manifestoo==<pin>` (addon-manifest); `whool==…`, plus `manifestoo-core>=1.16.1` on 20.0 (packaging, shape addons); `coverage==<pin>`, `checklog-odoo==<pin>` (tests) |
| `tests` | module on | tables `tool.coverage.run` = `{source = [addons_root], branch = true, parallel = true, data_file = ".odoo-nix/coverage/.coverage", omit = [".odoo-nix/*", "*/tests/*", "*/migrations/*", "*/upgrades/*", "*/__manifest__.py"]}` (addons mode's `source = ["."]` would otherwise reach OCB and the external sources through the `.odoo-nix/` links), `tool.coverage.report` = `{show_missing = true, skip_covered = true}`; `seeds`: `("tool","coverage","report","fail_under")` = `initial-floor`, written once when missing, then owned by the repository (raised by `ratchet coverage --raise`) |

- **`reconcile(ctx, ("project","dependencies"), have, rendered)`** merges by normalised package name (PEP 503;
  `packaging.Requirement`, which also parses `name @ url`). `KNOWN` = every package of the series' `tools` plus
  `data/tool-pins.json`. Then:
  - a known name in `rendered`: the rendered item, except that a hand-raised `==` pin at or above it is kept
    (floor semantics, plan B2); a git URL requirement is always the rendered one;
  - a known name not in `rendered`: removed. Its module is off (or not in this shape), and names odoo-nix pins
    are odoo-nix's in this file; this is the per-module retraction the single key cannot get from the core;
  - an unknown name: a hand-added extra, kept in its place after the rendered items.

  `baseline` stays false. When every module of `TOOLS_MODULES` is off, the core's whole-key rule applies: the list
  is deleted when it equals the render and was on in history, else left with the turn-off warning.
- `canon_tables = ("project", "tool.uv", "tool.coverage.run", "tool.coverage.report")`.
- `problems`: `[tool.ruff]` here → "move [tool.ruff] to .ruff.toml".
- `requires-python` is the Odoo interpreter's floor so the lock also resolves `coverage` for it (§5.3);
  the tools environment itself is built with `tools_python` (3.12).
- `[tool.ruff*]` in the config file is refused by a `checks` item (§3.4): ruff reads `.ruff.toml` before
  `pyproject.toml` in a directory, so the table would be silently ignored.

`.ruff.toml` (`Gen.ruff_toml()`): the top-level keys first, `target-version`, `fix` and `extend-exclude`
(`["odoo", "modules"]` in a project, whose submodules are not gitignored, plus the param; omitted when empty), then
the series `ruff` tables in OCA's layout (`[lint]` extend-select + `extra-select`, `extend-safe-fixes`, `exclude`,
`ignore`, `[format]`, `[lint.per-file-ignores]` merged with the param, `[lint.isort]`, `[lint.isort.sections]`,
`[lint.mccabe]`), then the local region `ruff` last. Anything after `[lint.mccabe]` belongs to that table in TOML,
so a non-empty region must open with a table header line (`[...]`): otherwise `Gen` raises `ConfigError` (exit 2)
"the ruff local region follows [lint.mccabe]: start it with a table header, or use python-lint's parameters".
`test_ruff_toml` parses every rendering with `tomllib` and checks each key's table. Addons mode needs no exclude:
`.odoo-nix/` is gitignored and ruff respects `.gitignore`.

#### pylint-odoo

`Gen.pylintrc(kind)` writes `[MASTER] load-plugins=pylint_odoo`, `score=n`; `[IMPORTS] deprecated-modules=` from
the data; `[ODOOLINT]` with `readme-template-url` (OCA's), `manifest-required-authors=<author>` only when set,
`manifest-required-keys`, `manifest-deprecated-keys`, `license-allowed=<licenses-allowed or OCA's>`,
`valid-odoo-versions=<series>`; `[MESSAGES CONTROL] disable=all`, `enable=` deduplicated. `missing-readme`
stays: stage O3 verifies against the pinned pylint-odoo that a `README.md` satisfies it; if it does not, the
`readme` module's Markdown rule removes it from both lists as deviation `readme-markdown`.

#### js-xml

- `groups.PACKAGE: JsonGroups`, one group `js-xml`: `("private",)` → `true`; `("devDependencies", pkg)` → exact
  version for the five npm tools of the series (18.0: prettier 3.3.3, @prettier/plugin-xml 3.4.1, eslint 9.12.0,
  eslint-plugin-jsdoc 50.3.1, globals 16.0.0). `reconcile`: a hand-raised exact version is kept. A missing file
  is created as `{"private": true, "devDependencies": {…}}` in `json_style`. `key_order[()]` =
  `("name", "private", "devDependencies")`.
- In addons mode the root is a `lib/node.nix` candidate (`rootAndAddons customKey` with `customDir = "."`,
  `lib/addons.nix:213-218`), so the managed root `package.json` would become an npm target. The standards shell
  adds `"."` to the effective `nodeExcludes` (§5.2). Projects are unaffected (candidates are `custom` and its
  addons).
- `prettier.config.cjs`: header `// odoo-nix:managed …; do not edit.`, then the series body verbatim.
- `eslint.config.cjs`: header, the series body with the ESM `files:` list replaced by
  `effective.esm_globs`, and, when `exclude` is non-empty, a first config object `{ignores: ["<p>**", …]}`.
- The `prettier`/`eslint` hooks get the `exclude` prefixes as `^(?:<p1>|<p2>)` (escaped).

#### ide

`data/ide/vscode.json` (also read by `modules/devenv.nix`'s seed, §5.5):

```json
{
  "seed": {
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
    "python.analysis.extraPaths": [".devenv/state/pythonpath"],
    "files.watcherExclude": {"**/.devenv/**": true, "**/.direnv/**": true},
    "search.exclude": {"**/.devenv/**": true, "**/.direnv/**": true}
  },
  "seed_extensions": ["Odoo.odoo"],
  "managed": {
    "set": {
      "python.languageServer": "None",
      "ty.diagnosticMode": "off",
      "ty.disableLanguageServices": true,
      "ruff.path": ["${workspaceFolder}/tools/.venv/bin/ruff"],
      "[python]": {"editor.defaultFormatter": "charliermarsh.ruff", "editor.formatOnSave": true},
      "[xml]": {"editor.defaultFormatter": "esbenp.prettier-vscode", "editor.formatOnSave": true},
      "[javascript]": {"editor.defaultFormatter": "esbenp.prettier-vscode", "editor.formatOnSave": true},
      "prettier.requireConfig": true,
      "prettier.prettierPath": "./node_modules/prettier",
      "files.watcherExclude": {"**/.odoo-nix/**": true, "**/tools/.venv/**": true, "**/node_modules/**": true},
      "search.exclude": {"**/.odoo-nix/**": true, "**/tools/.venv/**": true, "**/node_modules/**": true}
    },
    "union": {"recommendations": {"ensure": ["Odoo.odoo", "charliermarsh.ruff", "esbenp.prettier-vscode",
                                             "dbaeumer.vscode-eslint"], "opposite": "unwantedRecommendations"}},
    "forbidden": [["Odoo.serverConfigPath"]],
    "never": [["Odoo.selectedProfile"], {"prefix": "python-envs."}]
  }
}
```

`managed.set` holds only leaves the devenv seed does not write: `python.defaultInterpreterPath` and the
`.devenv`/`.direnv` excludes are the seed's (`seed`), so retracting `ide` (which deletes every `set` leaf still
equal to the render, core §5.5) never removes what the shell seeded and will not seed again into an existing
file. `test_ide_real` asserts `set` and `seed` share no leaf.

`templates/ide/settings.json.j2` renders `{set, forbidden, never}`; `extensions.json.j2` renders `{union}`. Real
shapes the editor must keep (`tests/shapes/vscode/`): project B settings (4-space indent, `git.detectSubmodules`,
`python-envs.defaultEnvManager`, `Odoo.selectedProfile`), project A settings (2-space, inline
`"python.analysis.extraPaths": [".devenv/state/pythonpath"]`, `git.ignoreLimitWarning`), both `extensions.json`
one-line with no final newline (project A keeps `bierner.lit-html`). `python-envs.defaultEnvManager` gets a notice
("overrides the interpreter; remove it", plan D.4), never an edit. The preserved layout lasts beyond the first
`prek run` because prettier skips `.vscode/` (deviation `prettier-vscode`, §3.0).

#### tests

`checklog-odoo.cfg` seed = the series' `reference_files["checklog-odoo.cfg"]` (OCA's `[checklog-odoo] ignore=`
list). Gate behaviour in §6.1.2; ratchet in §6.3.

#### workflow-lint, shell-lint, nix-lint, hygiene

- `.github/zizmor.yml`: `rules.unpinned-uses.config.policies."*": hash-pin` (odoo-nix's own `.github/zizmor.yml`).
- Hooks are in §3.3; `.git-blame-ignore-revs` uses the core's blame handler.

#### commits

`committed.toml` (`templates/committed.toml.j2`): `style = "conventional"` (or `"none"` plus the `odoo` subject
regex `^\[(ADD|FIX|IMP|REF|REM|MOV|REL|MERGE|I18N|CLA|PERF|UPD|REV)\] [a-z0-9_,]+: ` checked by `policy` when
`convention = "odoo"`), `allowed_types` = `[build, chore, ci, docs, feat, fix, perf, refactor, revert, style, test,
*extra-types]`, `allowed_scopes` = `scopes` (§2.4) when `scopes = "addons"`, `subject_length`, then the local
region. `releases` on with `convention = "odoo"` → preflight exit 2 (levels need conventional commits).

#### dependabot

`templates/github/dependabot.yml.j2`, one entry per `(ecosystem, branch)` for `branch` in
`dependabot.target-branches`, ecosystems `github-actions` (`/`) and `nix` (`/`), each with `schedule.interval`,
`cooldown.default-days`, `commit-message.prefix: "chore(deps)"`, `groups.actions` (github-actions), `cooldown.exclude:
["ocb"]` (nix: a cooldown locks an odoo/odoo commit inside one of OCB's merges, which has no OCB `pyproject.toml`), and
ignores:

```yaml
    ignore:
      - dependency-name: "odoo-nix"            # nix: moved by `odoo-nix repo rollout` / odoo-init --sync
      - dependency-name: "standards-profile"
```
```yaml
    ignore:
      - dependency-name: "Avunu/odoo-nix/*"    # github-actions: the caller pins move with the engine
      - dependency-name: "Avunu/python-devops-nix/*"
```

No `uv`, `npm`, `pre-commit` or `gitsubmodule` entry: the tools locks follow series data, and projects move
submodules with the scheduled `odoo project update` job (§6.4). The local region `updates` holds a repository's
own entries (an addon's `package.json`, another branch); a region entry with the same
`(ecosystem, directory, target-branch)` as a managed one is exit 2 (core §5.2).

#### ci

Callers `templates/github/workflows/{ci,pr-policy,release,deps}.yml.j2`, modelled on frappe-nix's
(`data/templates/.github/workflows/ci.yml.j2`): one caller job per gate, each named `ci`, so contexts read
`ci / lint`, `ci / test`, `ci / pr-policy`; `uses: Avunu/odoo-nix/.github/workflows/odoo-<gate>.yml@<locked rev> #
v<version>` (the `uses` macro with the core `pin` fallback); `on.push.branches: [<integration>]` in `ci.yml` and
`pr-policy.yml` (core conformance for `post-merge-bump`); `runs-on: {{ cfg.ci["runs-on"] | yaml_json }}`.
`release.yml` only when `releases` is live (addons). `deps.yml` per shape (§6.4). Built-in retire rules for
`ci`: `.travis.yml`, `.t2d.yml`, and workflows whose content contains `oca_run_tests`, `ghcr.io/oca/oca-ci` or
`pre-commit/action`. `checks`: every submodule pins `branch = <series>` (projects).

#### repo-policy

Core rendering (core §7.3) with `Branching("develop+series")`: `integration.json` protects `refs/heads/develop` with
`{integration_bypass}` = the App (`release-bypass = "integration:<id>"`); `release-branch.json` protects
`refs/heads/<series>` ("18.0 (release automation only)", through `repo_policy_values`, §2.2) with the same actor;
no `tags.json`. In a project, `integration_bypass` is `[]` (§2.2). Required checks = `gates`. Strict checks off
(Amendments). `private: true` in the fleet blocks `--phase full`.

#### readme

`checks`: every installable addon has `README.md` or `README.rst` (`readme.required`); 4 of the 37 fleet addons
lack one (`edi_purchase_order_import`, `shopfloor_mobile_base_theme_carbon`, `fleet_vehicle_simplify`,
`repair_service_productivity`), project B 1 of 4. Optional root block
`addons-table`: `| [name](name/README.md) | summary | license |` rows from manifests, sorted.

#### icons

`odoo-nix check icons` (§6.2); none of the 37 fleet addons nor project B's 4 has `static/description/icon.png`.
No icon hook is rendered (OCA's data has none); `check icons --fix` passes `--addons-dir=<addons_root>` to
`oca-gen-addon-icon` (or the failing addon directories), never relying on a default.

#### packaging

`checks` (shape addons): every installable addon has a tracked whool `pyproject.toml`; each appears as
`odoo-addon-<name>` in `nix/pyproject.toml`'s `module sources` block (a packaged local addon is an editable path
source after `odoo project relock`, `lib/oca_sources.py`), else "nix/uv.lock predates <addon>/pyproject.toml: run
`odoo project relock`". None of the 37 has one today.

### 3.2 Retire rules (built-in, `manifest.d`)

| Module | Rule |
|---|---|
| python-lint | `.flake8`, `.isort.cfg`, root `ruff.toml`; `setup.cfg` with `only_sections: ["flake8", "isort", "tool:isort", "pycodestyle", "pylint", "pep8"]` |
| js-xml | `.prettierrc`, `.prettierrc.{json,yml,yaml,js,cjs,mjs,toml}`, `.eslintrc`, `.eslintrc.{json,yml,yaml,js,cjs}`, `eslint.config.{js,mjs,ts}`, `prettier.config.{js,mjs}` |
| ci | `.travis.yml`, `.t2d.yml`; `.github/workflows/*.yml` `contains` `oca_run_tests` \| `ghcr.io/oca/oca-ci` \| `pre-commit/action` |
| dev-shell | `oca_dependencies.txt`, `test-requirements.txt` with `when: shape == "addons" and discover.flake.external_sources` (converted by `externalSources`) |

The Avunu profile adds `.github/workflows/mirror.yml` (module `releases`).

### 3.3 The locked-tools `.pre-commit-config.yaml`

Entry: path `.pre-commit-config.yaml`, strategy `whole`, header `yaml`, local regions `hooks` and `exclude`, module list
`[python-lint, pylint-odoo, addon-manifest, js-xml, workflow-lint, shell-lint, nix-lint, hygiene, commits,
packaging]` (live while any is on), template `templates/pre-commit-config.yaml.j2`, first-opt-in listed.

`precommit.hooks(ctx) -> list[Hook]`:

```python
@dataclass(frozen=True)
class Hook:
    id: str  # OCA's id ("obsolete dotfiles" keeps its space; ids may repeat: pylint_odoo)
    name: str
    entry: str  # locked executable + OCA entry args: "tools/.venv/bin/ruff check --force-exclude"
    language: Literal["system", "fail"]
    module: str
    args: tuple[str, ...] = ()
    files: str | None = None
    exclude: str | None = None
    types: tuple[str, ...] = ()
    types_or: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    pass_filenames: bool | None = None
    always_run: bool | None = None
    require_serial: bool | None = None
    verbose: bool | None = None
```

Rules:

1. Start from `series_data.hooks` (OCA order, keys from `HOOK_KEYS`), apply `DEVIATIONS`.
2. Keep a hook when its module is on: fail hooks → `hygiene`; `whool-init` → `packaging` (addons);
   `oca-fix-manifest-website` → `addon-manifest` with `website` set (args `[<rendered website>]`);
   `oca-checks-odoo-module`, `oca-checks-po`, `pylint_odoo` → `pylint-odoo` (`pylint_odoo` with `.pylintrc` only
   when `optional-run`); `prettier`, `eslint` → `js-xml`; pre-commit-hooks ids → `hygiene`; `ruff`/`ruff-check`,
   `ruff-format` → `python-lint`.
3. `entry`: a `tool` from `tools/uv.lock` → `tools/.venv/bin/<entry>`; from `package-lock.json` →
   `node_modules/.bin/<entry>`; a Nix tool → `tools/.bin/<entry>` (rule 5); `fail` hooks keep their message.
   Relative paths resolve from the repository root, where prek runs hooks, so a hook works from any client that
   has the links (shell entry, or the lint shell, creates them, §5.2), including a commit from VS Code or another
   GUI client outside direnv: no hook depends on PATH.
4. Every OCA-derived hook's `exclude` = `^\.github/` joined with OCA's own exclude by `|` (and `^\.vscode/` for
   `prettier`, deviation `prettier-vscode`).
5. odoo-nix's hooks, appended after OCA's. Locked Python tools come from `tools/.venv`; the Nix tools from
   `tools/.bin`, a gitignored link to a `buildEnv` of the engine's `nixTools` (§5.2):

   | Module | id | entry | selection |
   |---|---|---|---|
   | hygiene | `check-json` | `tools/.venv/bin/check-json` | `types: [json]`, `exclude: ^\.vscode/` (JSONC) |
   | hygiene | `check-yaml` | `tools/.venv/bin/check-yaml` | `types: [yaml]` (sees `.github/`) |
   | workflow-lint | `actionlint` | `tools/.bin/actionlint` | `files: ^\.github/workflows/.*\.ya?ml$` |
   | workflow-lint | `zizmor` | `tools/.bin/zizmor --offline --config .github/zizmor.yml` | `files: ^\.github/(workflows/.*\.ya?ml\|dependabot\.ya?ml)$`. `--offline`: with `GH_TOKEN` set (CI, `gh auth` shells) zizmor would otherwise run its online audits, so results would differ between a laptop and CI |
   | shell-lint (`has_sh`) | `shellcheck` | `tools/.bin/shellcheck` | `types: [shell]` |
   | nix-lint (`has_nix`) | `nixfmt` | `tools/.bin/nixfmt` (nixfmt-rs) | `types: [nix]` |
   | nix-lint | `statix` | `tools/.bin/statix check` | `files: \.nix$`, `pass_filenames: false` |
   | nix-lint | `deadnix` | `tools/.bin/deadnix --fail` | `types: [nix]` |
   | commits | `committed` | `tools/.bin/committed --commit-file` | `stages: [commit-msg]` |

6. Top-level `exclude` (`Gen.exclude_block()`): `(?x)`, then `# NOT INSTALLABLE ADDONS`, one `^<path>/|` per
   `not_installable` addon (project paths are `custom/<addon>/`), `# END NOT INSTALLABLE ADDONS`, then every
   alternative of `series_data.exclude` except `^.github/`, each under its OCA comment, then the local region
   `exclude` (`# odoo-nix:local-begin exclude` / `# odoo-nix:local-end exclude`, indented inside the block
   scalar: under `(?x)` those lines are regex comments, and core regions accept an indented marker,
   `regions.py:36-37`), then `# odoo-nix: locks` and the `locks-excluded` alternative (last, so it carries no
   trailing `|`). Each region line is an alternative ending in `|`; project A's tracked `^artifacts/|` (`.eml`,
   `.html`, `.json`, `.pdf` samples that trailing-whitespace, `mixed-line-ending --fix=lf` and prettier would
   rewrite) and `^docs/|` go there. It applies to every hook, unlike `js-xml.exclude` (prettier and eslint only).
   No `default_language_version`.
7. After the managed `- repo: local` block: `# odoo-nix:local-begin hooks` / `# odoo-nix:local-end hooks` for
   further `- repo:` items. A region hook whose `id` equals a managed one is exit 2.

Dropped: `oca-gen-addon-readme`, `oca-update-pre-commit-excluded-addons`, `oca-gen-external-dependencies`.

Rendered for edi-addons (18.0, Avunu), abridged:

```yaml
# odoo-nix:managed — generated by odoo-nix (`odoo-init --sync`); edit only inside the odoo-nix:local region.
# Every hook runs a locked tool: tools/.venv (tools/uv.lock), node_modules (package-lock.json) or
# tools/.bin (the engine's Nix tools). Shell entry runs `prek install -c .pre-commit-config.yaml`;
# CI runs `odoo-nix gate lint`.
exclude: |
  (?x)
  # NOT INSTALLABLE ADDONS
  # END NOT INSTALLABLE ADDONS
  # Files and folders generated by bots, to avoid loops
  ^setup/|/static/description/index\.html$|
  # We don't want to mess with tool-generated files
  .svg$|/tests/([^/]+/)?cassettes/|^.copier-answers.yml$|^eslint.config.cjs|^prettier.config.cjs|
  # Maybe reactivate this when all README files include prettier ignore tags?
  ^README\.md$|
  # Library files can have extraneous formatting (even minimized)
  /static/(src/)?lib/|
  # Repos using Sphinx to generate docs don't need prettying
  ^docs/_templates/.*\.html$|
  # Don't bother non-technical authors with formatting issues in docs
  readme/.*\.(rst|md)$|
  # Ignore build and dist directories in addons
  /build/|/dist/|
  # Ignore test files in addons
  /tests/samples/.*|
  # You don't usually want a bot to modify your legal texts
  (LICENSE.*|COPYING.*)|
  # odoo-nix:local-begin exclude
  # odoo-nix:local-end exclude
  # odoo-nix: locks
  (^|/)(uv|flake)\.lock$|(^|/)package-lock\.json$
repos:
  - repo: local
    hooks:
      - id: forbidden-files
        name: forbidden files
        entry: found forbidden files; remove them
        language: fail
        files: \.rej$
        exclude: ^\.github/
      # … en-po-files, "obsolete dotfiles" …
      - id: whool-init
        name: whool-init
        entry: tools/.venv/bin/whool init --exit-non-zero-on-changes
        language: system
        pass_filenames: false
        always_run: true
        exclude: ^\.github/
      - id: oca-fix-manifest-website
        name: oca-fix-manifest-website
        entry: tools/.venv/bin/oca-fix-manifest-website
        args: ["https://github.com/Avunu/edi-addons"]   # a project: ["--addons-dir=custom", "<url>"]
        language: system
        pass_filenames: false
        files: (__manifest__\.py|__openerp__\.py|__terp__\.py)$
        exclude: ^\.github/
      # … oca-checks-odoo-module, oca-checks-po, prettier (node_modules/.bin/prettier, exclude
      #   ^\.github/|^\.vscode/), eslint, pre-commit-hooks (stages pre-commit/pre-push/manual), ruff,
      #   ruff-format, pylint_odoo ×2 …
      - id: actionlint
        name: actionlint
        entry: tools/.bin/actionlint
        language: system
        files: ^\.github/workflows/.*\.ya?ml$
      # … zizmor, nixfmt, statix, deadnix, committed …
  # odoo-nix:local-begin hooks
  # odoo-nix:local-end hooks
```

### 3.4 `checks.py`

```python
def preflight(checkout: Checkout, resolved: Resolved) -> None:
    # ConfigError (exit 2): series without data; releases on with commits.convention == "odoo";
    # a flake `lockDir = "<x>"` literal other than "nix" in addons mode; the config file is not the shape's
    # (a project opted in through nix/pyproject.toml, or the reverse); an `untested` name that is not an addon;
    # releases live under develop+series with an integration branch matching ^\d+\.0$ (§2.2);
    # the shape's files are not tracked: no flake.nix (either shape), or, for addons, no nix/pyproject.toml
    # holding odoo-nix's `install set` and `module sources` blocks: "this repository has no addons-mode
    # flake.nix and nix/pyproject.toml: run `odoo-init --addons` first (or add --addons to this run)". Without
    # it, --standards would create a nix/pyproject.toml holding only the table, and the next `odoo project
    # relock` would skip both blocks ("sentinel block not found; skipped", lib/oca_sources.py:132-136) and
    # exit 1 (:224-228), because relock seeds the file only when it is missing (workspace/relock.py:76,
    # workspace/update.py:80).

def notices(plan: Plan) -> list[str]:
    # inert releases/packaging in a project; dev_group_ruff ("[dependency-groups].dev lists ruff; hooks and
    # the editor use tools/.venv/bin/ruff"); python-envs.* in .vscode/settings.json; shape signals of both kinds;
    # comment paragraphs the .gitignore absorb emptied (§3.1 dev-shell, until CR4); tracked files with unstaged
    # changes that this run writes ("sync stages the files it writes: your own changes in <path> are staged
    # too; commit or stash them first", until CR5; a real project checkout had 26 such entries).

def checks(plan: Plan) -> list[Item]:  # wanted == current; exit 1 (drift) under --check and phase B
    # readme: an installable addon without README.md/README.rst
    # ci (project): a submodule without `branch = <series>`
    # packaging (addons): an addon without a whool pyproject.toml, or missing from nix/pyproject.toml's sources
    # python-lint: [tool.ruff*] in the config file
    # dev-shell: series sources disagree (.odoo-series, flake odooSeries literal, manifests, ocb lock ref,
    #            a ^\d+\.0$ integration branch): "series 18.0 (.odoo-series) but flake.lock's ocb follows 19.0"
    # tools project (TOOLS_MODULES): the lock is stale. tools/uv.lock's root package
    #            ([[package]] whose source is `virtual = "."`) lists [package.metadata] requires-dist as
    #            tables ({ name, specifier?, git?, … }, as in nix/uv.lock today); as a set of (normalised
    #            name, specifier, source) it must equal tools/pyproject.toml's [project].dependencies, else
    #            "tools/uv.lock predates tools/pyproject.toml: run `uv lock --project tools`". Once CR2 lands:
    #            equality, and rendered ⊆ locked when ctx.options["throwaway"]. Until then rendered ⊆ locked
    #            everywhere (a lock with extra tools is benign; a missing tool is what breaks a hook) (§0.2 C5).
    # js-xml: package-lock.json's packages[""].devDependencies must equal package.json's devDependencies,
    #            else "package-lock.json predates package.json: run `npm install --package-lock-only …`".
```

Why the lock checks: the core `UvLockHandler` reports only a missing lock or a floor shortfall (core §5.1), and
manifest floors are static JSON (core §4.3), so they cannot hold per-series pins (`floors: "uv"` is therefore not
used). Without these items a hand-edited `tools/pyproject.toml` or `package.json` with a stale lock passes
`--check`, and uv2nix/importNpmLock silently build the old tools. The Nix side adds the same guard at evaluation
(`lockAudit`, §5.3).

### 3.5 Templates (`data/templates/`)

`envrc.j2`, `flake/inputs.nix.j2`, `gitignore/dev-shell.j2`, `editorconfig.j2`, `ruff.toml.j2`, `pylintrc.j2`, `pylintrc-mandatory.j2`,
`pre-commit-config.yaml.j2`, `prettier.config.cjs.j2`, `eslint.config.cjs.j2`, `ide/settings.json.j2`,
`ide/extensions.json.j2`, `checklog-odoo.cfg.j2`, `committed.toml.j2`, `github/dependabot.yml.j2`,
`github/zizmor.yml.j2`, `github/workflows/{ci,pr-policy,release,deps}.yml.j2`, `readme/addons-table.md.j2`,
`git-blame-ignore-revs.j2`. `overridable: true` on `editorconfig`, `github/zizmor.yml` and the readme block.

---

## 4. Built-in profiles and the Avunu profile

### 4.1 `profiles/minimal.toml`

```toml
# odoo-nix built-in profile `minimal`. Frozen for all of odoo-nix 2.x: it never turns a module on.
schema = 1
name = "minimal"
description = "The odoo-nix dev shell only: the flake.nix inputs block, .envrc and the .gitignore block."

[org]
dev-docs-url = "https://github.com/Avunu/odoo-nix/tree/main/docs/standards"

[dev-shell]
enable = true

[editorconfig]
enable = false
[python-lint]
enable = false
[pylint-odoo]
enable = false
[addon-manifest]
enable = false
[js-xml]
enable = false
[ide]
enable = false
[tests]
enable = false
[workflow-lint]
enable = false
[shell-lint]
enable = false
[nix-lint]
enable = false
[hygiene]
enable = false
[commits]
enable = false
[releases]
enable = false
[packaging]
enable = false
[dependabot]
enable = false
[ci]
enable = false
[repo-policy]
enable = false
[readme]
enable = false
[icons]
enable = false
```

### 4.2 `profiles/recommended@2.3.toml`

`2.3` is the plan's `2.M`; the release PR of the first odoo-nix minor that ships odoo-nix-tools fixes the
number here, in the file name, in the profile's `extends`/`requires-odoo-nix` and in its flake pin.

```toml
# odoo-nix built-in profile `recommended@2.3`, the first `recommended` snapshot. Frozen once v2.3.0 is
# tagged: a later minor that changes `recommended` adds recommended@2.<minor>.toml.
schema = 1
name = "recommended"
description = "Vendor-neutral Odoo standards: OCA's per-series lint and format rules with locked tools, tests with coverage, Dependabot and CI. Nothing that needs an organisation's values, editor taste or repo admin."

[org]
publisher = ""
email = ""
copyright-holder = ""
license = ""
github-owner = ""
docs-url = ""
dev-docs-url = "https://github.com/Avunu/odoo-nix/tree/main/docs/standards"
support-url = ""
repo-url = "https://github.com/{repo}"

[dev-shell]
enable = true
odoo-nix-url = ""

[editorconfig]
enable = true

[python-lint]
enable = true
extra-select = []
ignore = []
per-file-ignores = {}
extend-exclude = []

[pylint-odoo]
enable = true
optional-run = true

[addon-manifest]
enable = true
author = ""
licenses-allowed = []
website = ""

[js-xml]
enable = true
exclude = []

[ide]
enable = false

[tests]
enable = true
initial-floor = 0
goal = 80
checklog = true

[workflow-lint]
enable = true
[shell-lint]
enable = true
[nix-lint]
enable = true

[hygiene]
enable = true
forbid-contributing = true

[commits]
enable = false
convention = "conventional"
scopes = "addons"
extra-scopes = []
extra-types = []
allow-stacked = true
pr-allowed-bases = []
subject-length = 100

[releases]
enable = false
branching = "develop+series"
version-scheme = "odoo-series"

[packaging]
enable = false

[dependabot]
enable = true
auto-merge = true
auto-merge-policy = "decision-table"
update-branches = false
schedule = "weekly"
cooldown-days = 7
target-branches = []

[ci]
enable = true
runs-on = ["ubuntu-latest"]
test-timeout-minutes = 60
project-update = "0 6 * * 1"
github-app = { app-id = "", private-key = "" }
schedules = {}

[repo-policy]
enable = false

[readme]
enable = false
addons-table = false
required = true

[icons]
enable = false
min-size = 128
max-bytes = 102400
src-icon = "templates/addon-icon.png"
```

With an empty `[org]`, every org-dependent rule is skipped: `uses` keys with `?` (core §4.3), `required-author`
deviation (no author), no website hook, `licenses-allowed` falls back to OCA's list. `test_profiles` renders both
fixtures under this profile and asserts no `@@…@@` and no empty `org.*` value reaches a file.

### 4.3 `data/schema/modules.schema.json`

`$defs.module-name.enum` = `MODULES`; `$defs.modules.<m>` for every module, each with `enable` and the parameters
in §3.1/§4.2 (types, enums, defaults equal to `recommended@2.3`, so `minimal` resolves the same parameter values).
Core modules add only product keys (`ci.runs-on`, `ci.test-timeout-minutes`, `ci.project-update`,
`dependabot.{schedule,cooldown-days,target-branches}`, `commits.{convention,scopes,extra-scopes,extra-types}`) and
override `releases.version-scheme.default` = `"odoo-series"`. `org-extra`: none. `profile-extra`: none.
`app-extra`:

```json
{
  "properties": {
    "shape": {"enum": ["project", "addons"]},
    "series": {"type": "string", "pattern": "^\\d+\\.0$"},
    "untested": {"type": "array", "items": {"type": "object", "additionalProperties": false,
      "required": ["addon", "reason"],
      "properties": {"addon": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                     "reason": {"type": "string", "minLength": 10}}}}
  },
  "required": []
}
```

### 4.4 The Avunu profile against this schema

`/home/batonac/Development/odoo-standards-profile/profile.toml`, key by key:

| Key (profile) | Schema | Note |
|---|---|---|
| `schema`, `name`, `description`, `extends = "recommended@2.3"`, `requires-odoo-nix = ">=2.3,<3"` | core | valid |
| `[org]` `publisher`, `email`, `copyright-holder`, `license = "AGPL-3"`, `github-owner`, `docs-url = "https://docs.avunu.net/{repo_name}/"`, `dev-docs-url`, `repo-url` | core org | `{repo_name}` needs `url_placeholders` (§2.4); `license` also feeds `licenses-allowed` only when that is empty (it is not: `["AGPL-3", "LGPL-3"]`) |
| `[addon-manifest]` `author`, `licenses-allowed`, `website = "https://github.com/{repo}"` | product | valid; all 37 fleet manifests already have `Avunu LLC` and `https://github.com/Avunu/<repo>` |
| `[ide] enable` | product | valid |
| `[commits]` `enable`, `convention`, `scopes = "addons"`, `extra-scopes`, `allow-stacked = false` | core + product | valid. The plan's `extra-types` and the profile's `extra-scopes` are two different keys; both defined |
| `[releases]` `enable`, `branching = "develop+series"` | core (enum = `BRANCHING` keys) | valid; `version-scheme` comes from the product default |
| `[packaging] enable` | product | valid (inert in projects) |
| `[dependabot]` `auto-merge-policy = "all"`, `update-branches = true` | core | valid |
| `[ci] runs-on`, `[ci.github-app]` `app-id`, `private-key` | product + core | valid. `app-id` names the Actions variable (`AVUNU_CI_APP_ID`), which holds the App's **client ID** (`mirror.yml:43` passes it as `client-id`); the callers pass it as `client-id` too (§6.4) |
| `[repo-policy]` `enable`, `required-approvals = 0` | core | **missing** `release-bypass = "integration:<numeric App id>"`: under `develop+series` the bump push and the fast-forward use the App token, and both rulesets need that actor (core §7.3). The numeric App id is a different value from the client ID in `AVUNU_CI_APP_ID` and is in no file read; the profile must add it |
| `[readme]` `enable`, `addons-table` | product | valid |
| `[icons] enable` | product | valid |
| `[[retire]] paths = [".github/workflows/mirror.yml"], module = "releases"` | core `retire-item` | valid |

Other profile-repository changes this design implies:

- `fleet.json`: `"integration_branch": "develop", "series_branches": ["18.0"]` → `"branches": ["develop", "18.0"]`
  in all 10 entries (C2 withdrawn); `scripts/check_fleet.py` follows (§2.7).
- `README.md` says an addons repository puts `[tool.odoo-nix]` in "the repository's root `pyproject.toml`"; it is
  `nix/pyproject.toml`.
- `scripts/check.sh`: `[ -f "$fixture/pyproject.toml" ]` and `copy_fixture`'s `sed` on `$2/pyproject.toml` must use
  `pyproject.toml` for `standards-project` and `nix/pyproject.toml` for `standards-addons`; `profile validate
  --profile-path "$profile"` becomes `profile validate "$profile/profile.toml" --templates "$profile/templates"`
  (C4).

---

## 5. Nix integration in odoo-nix

### 5.1 `lib/standards/package.nix`

```nix
# odoo-nix-tools (py/odoo_nix_tools) against the locked nixpkgs' python3, with standards-core from
# python-devops-nix (core DESIGN.md §10.3). Called with python3Packages.callPackage.
{ lib, base, pkgs, python, buildPythonPackage, flit-core, unittestCheckHook, git, coreRev }:
let
  src = ../../py/odoo_nix_tools;
  standardsCore = base.standards.package { inherit pkgs python; rev = coreRev; };
in
buildPythonPackage {
  pname = "odoo-nix-tools";
  inherit ((lib.importTOML (src + "/pyproject.toml")).project) version;
  pyproject = true;
  src = lib.fileset.toSource {
    root = src;
    fileset = lib.fileset.difference
      (lib.fileset.unions [ (src + "/pyproject.toml") (src + "/README.md") (src + "/odoo_nix_tools") (src + "/tests") ])
      (lib.fileset.fileFilter (f: f.hasExt "pyc") src);
  };
  build-system = [ flit-core ];
  dependencies = [ standardsCore ];          # pythonRuntimeDepsCheck stays on
  nativeCheckInputs = [ unittestCheckHook git ];
  unittestFlagsArray = [ "-s" "tests" "-v" ];
  preCheck = ''export HOME="$TMPDIR" GIT_CONFIG_GLOBAL=/dev/null'';
  pythonImportsCheck = [ "odoo_nix_tools" "odoo_nix_tools.cli" "odoo_nix_tools.product" ];
  meta = { description = "odoo-nix's standards tools"; license = lib.licenses.mit; mainProgram = "odoo-nix"; };
}
```

`coreRev = inputs.python-devops-nix.rev` (`_source.json`, the skew row of core §9.4).

The CLI wrapper (frappe's `tools/frappe-nix.nix` pattern): `odoo-nix` = `makeWrapper ${lib.getExe pkg}
$out/bin/odoo-nix --suffix PATH : ${makeBinPath [ git gh ]}`, so the package's Python closure never lands on a
dev shell's PATH or PYTHONPATH. `flake.nix` exposes `packages.<system>.{odoo-nix, odoo-nix-tools}` and
`apps.<system>.odoo-nix`.

`lib/init.nix` adds the package to odoo-init's interpreter (`extraPackages = ps: [ (cliModule ps) odooNixTools ]`)
and puts the wrapper and `pkgs.nodejs` on `runtimeInputs` (beside today's `pkgs.git` and `pkgs.uv`), so phase B's
`npm install --package-lock-only` runs without re-entering a shell (§2.5). Boundary (plan B1): odoo-init's
`odoo_nix_cli` may import `odoo_nix_tools` (`discover`, `manifests`, `series`), never the reverse. The `odoo` CLI
(`lib/cli.nix`) never imports it: that interpreter is Odoo's own with the project environment prefixed onto
`PYTHONPATH` (`lib/cli.nix:112`), Python 3.14 for 20.0, and `odoo_nix_tools` would pull `standards_core`,
jinja2, tomlkit and pyyaml into Odoo's environment (§6.1.2 reads what it needs with `tomllib`).

`flake.nix` also exposes `packages.<system>.committed` (the engine's nixpkgs `committed`) and
`lib.standards.lintShell` (§5.2), which the reusable workflows use without evaluating the project flake (§6.4).

### 5.2 `lib/standards/shell.nix`

```nix
# What the standards add to an odoo-nix dev shell, all gated on the [tool.odoo-nix] opt-in line of the
# shape's config file. A shell that has not opted in is byte for byte today's.
{ pkgs, lib, cfg, addonsMode, odooNix, odooInit, tools }:
let
  configFile = if addonsMode then cfg.workspaceRoot + "/${cfg.addons.lockDir}/pyproject.toml"
               else cfg.workspaceRoot + "/pyproject.toml";
  optInLine = line: builtins.match "[[:space:]]*\\[{1,2}tool\\.odoo-nix[].].*" line != null;
  optedIn = builtins.pathExists configFile
    && builtins.any (l: builtins.isString l && optInLine l) (builtins.split "\n" (builtins.readFile configFile));
  nixTools = [ pkgs.committed pkgs.actionlint pkgs.zizmor pkgs.shellcheck pkgs.nixfmt-rs pkgs.statix pkgs.deadnix ];
  nixToolsEnv = pkgs.buildEnv { name = "odoo-nix-standards-tools"; paths = nixTools; };   # tools/.bin
  links = ''<tools/.venv, tools/.bin and node_modules link logic, below>'';
in
{
  inherit optedIn;
  nodeExcludes = lib.optional (optedIn && addonsMode && builtins.pathExists (cfg.workspaceRoot + "/package.json")) ".";
  apps = lib.optionalAttrs optedIn {
    odoo-init = { type = "app"; program = lib.getExe odooInit; meta.description = "odoo-init --sync / --check / --standards"; };
    odoo-nix = { type = "app"; program = lib.getExe odooNix; meta.description = "odoo-nix standards tools"; };
  };
  devShells = lib.optionalAttrs optedIn {
    odoo-nix-lint = pkgs.mkShell {          # CI's lint gate and pr-policy: no Odoo, no PostgreSQL
      packages = [ odooNix tools.prek pkgs.git ] ++ nixTools;
      shellHook = links;
    };
  };
  devenvModule = {
    key = "odoo-nix:lib/standards/shell.nix";
    packages = lib.optionals optedIn ([ odooNix odooInit tools.prek ] ++ nixTools);
    enterShell = lib.mkIf optedIn (links + ''
      if [ -f "$DEVENV_ROOT/.git-blame-ignore-revs" ] && [ "$(git -C "$DEVENV_ROOT" config --get blame.ignoreRevsFile || true)" != .git-blame-ignore-revs ]; then
        git -C "$DEVENV_ROOT" config blame.ignoreRevsFile .git-blame-ignore-revs || true
      fi
      case "''${ODOO_NIX_CI:-}" in ""|0|false)
        if [ -f "$DEVENV_ROOT/.pre-commit-config.yaml" ] && ! grep -qF "${tools.prek}" "$DEVENV_ROOT/.git/hooks/pre-commit" 2>/dev/null; then
          (cd "$DEVENV_ROOT" && prek install -c .pre-commit-config.yaml --hook-type pre-commit --hook-type commit-msg >/dev/null) || true
        fi ;;
      esac
    '');
  };
}
```

`prek install -c .pre-commit-config.yaml` records `--config=".pre-commit-config.yaml"` in the hook script (verified
with prek 0.5.7), so a commit never runs prek's workspace mode over nested configs (§1.2 bullet, §6.1.1).

`links` (shared by the shell and the lint shell; refuses a real directory exactly as `ideSetup` does for `.venv`,
`modules/devenv.nix`). It is anchored on `root="$(git rev-parse --show-toplevel)"`, not `$DEVENV_ROOT`, which the
plain `mkShell` lint shell does not set:

- `tools/.venv` → `tools.toolsEnv` when `tools/uv.lock` exists, else removed if it is a dangling link;
- `tools/.bin` → `${nixToolsEnv}/bin` (always, once opted in);
- `node_modules` → `${tools.nodeModules}/node_modules` when `package-lock.json` exists.

Each link is also registered as an indirect GC root (`nix-store --add-root <link> -r <store path>`), so a
garbage collection between shell entries does not leave the hooks of a GUI commit dangling.

`tools.prek` is `tools.toolsEnv`'s `bin/prek` (the lock's pin) when the lock pins it, else `pkgs.prek`.

`lib.standards.lintShell { system, root }` (engine flake output) builds the same lint shell from a plain path:
`root` is the checkout, read only through `lib.fileset` (`tools/pyproject.toml`, `tools/uv.lock`,
`package.json`, `package-lock.json`), with the engine's own nixpkgs, uv2nix and node. It is what CI uses (§6.4),
because evaluating a project flake needs its submodules (`self.submodules = true`).

### 5.3 `lib/standards/tools.nix`

```nix
# The checkout's locked tools: tools/uv.lock (uv2nix), package-lock.json (importNpmLock), and coverage
# from the same lock built for Odoo's interpreter. The Python set is assembled the way lib/python.nix
# assembles the Odoo one, so the tools get the same package fixes and the same stale-lock guard.
{ pkgs, lib, base, uv2nix, pyproject-nix, pyproject-build-systems, workspaceRoot, toolsPython, odooPython,
  nodejs }:
let
  pythonLib = base.python;
  toolsDir = workspaceRoot + "/tools";
  hasLock = builtins.pathExists (toolsDir + "/uv.lock");
  workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = toolsDir; };
  # setuptools-scm needs .git, which a fetchGit tree lacks; the version uv recorded is 0.1.dev1+g<rev>.
  maintainerTools = final: prev: lib.optionalAttrs (prev ? oca-maintainers-tools) {
    oca-maintainers-tools = prev.oca-maintainers-tools.overrideAttrs (old: {
      env = (old.env or { }) // { SETUPTOOLS_SCM_PRETEND_VERSION = "0.1.dev1"; };
    });
  };
  setFor = python: (pkgs.callPackage pyproject-nix.build.packages { inherit python; }).overrideScope
    (lib.composeManyExtensions [
      pyproject-build-systems.overlays.default
      (workspace.mkPyprojectOverlay { sourcePreference = "wheel"; })
      (pythonLib.overrides { inherit pkgs; })          # the shared package fixes (lib/python.nix:291)
      maintainerTools
    ]);
  lockAudit = pythonLib.lockAudit {                     # lib/python.nix:314's guard, for tools/
    rootPyproject = toolsDir + "/pyproject.toml";
    workspaceRoot = toolsDir;
    label = "odoo-nix standards tools";
    hasPackage = name: (setFor toolsPython) ? ${name};
    relock = "\n  tools/pyproject.toml changed and tools/uv.lock was not regenerated:\n\n      uv lock --project tools\n";
  };
  npmRoot = lib.fileset.toSource { root = workspaceRoot; fileset = lib.fileset.unions
    [ (workspaceRoot + "/package.json") (workspaceRoot + "/package-lock.json") ]; };
in
{
  toolsEnv = if hasLock
    then lockAudit.assertCurrent ((setFor toolsPython).mkVirtualEnv "odoo-nix-tools-env" workspace.deps.default)
    else null;
  coverage = if hasLock then (setFor odooPython).coverage or null else null;   # site-packages for raw-odoo.nix
  nodeModules = if builtins.pathExists (workspaceRoot + "/package-lock.json")
    then pkgs.importNpmLock.buildNodeModules { inherit nodejs npmRoot; } else null;
}
```

- `toolsPython` = `pkgs.python312` (`series_data.python.default_language_version`); `odooPython` = `cfg.python`
  (18.0: `python311`, `lib/odoo-presets.json`). `tools/pyproject.toml`'s `requires-python` is the Odoo floor so
  the universal lock carries a 3.11 `coverage` (§3.1).
- uv2nix, pyproject-nix and pyproject-build-systems are odoo-nix's own inputs (`flake.nix:31-46`), visible to
  consumers through `lib.mkFlake`'s `inputs = self.inputs // inputs`.
- **maintainer-tools** is a setuptools-scm `git` source in `tools/uv.lock` (cached dist-info
  `oca_maintainers_tools-0.1.dev1+g31bdbd8e4`, verified). uv2nix fetches it by the locked commit without `.git`,
  so the build needs `SETUPTOOLS_SCM_PRETEND_VERSION`. Its `Requires-Dist` (verified) brings selenium, twine,
  pypandoc, erppeek, setuptools-odoo, github3-py, towncrier and an unpinned `whool` into the closure; the
  unpinned `whool` is resolved by the lock, and with `packaging` on it is the same pin as the `whool==…` item.
- **sdist build dependencies.** The Odoo set gets them from `[tool.uv.extra-build-dependencies]`, which
  `odoo-nix-build-deps update` (`lib/build-deps.nix`, python-devops-nix `lib.python.buildDeps`) keeps in step
  with the lock between sentinels. The tools project uses the same mechanism: phase B's `uv-lock` step for
  `tools/` is followed by `odoo-nix-build-deps update tools/pyproject.toml tools/uv.lock` (a second lock step of
  the entry; its sentinel block has a space in its name, so it is foreign to toml-merge, which owns only
  `tool.uv.package` in that table). Stage O6's `standards-prek-*` checks build
  the env for every series' tool set, so a closure member without a wheel shows up there, not in a consumer.
- `lockAudit` fails evaluation with the sentence above when `tools/pyproject.toml` declares a dependency the
  lock predates: the Nix counterpart of the `--check` item (§3.4).

### 5.4 Changes in `modules/devenv.nix`, `lib/raw-odoo.nix` and `flake.nix`

- `modules/devenv.nix`:
  - `standards = import ../lib/standards/shell.nix { … tools = import ../lib/standards/tools.nix { … }; }`;
  - `devenv.shells.default.imports = [ standards.devenvModule ]`;
  - `nodeLib`'s `excludes = cfg.nodeExcludes ++ standards.nodeExcludes`;
  - `apps = standards.apps` and `devShells = standards.devShells` merged into perSystem (the `apps.relock`
    pattern at `modules/devenv.nix:1740`);
  - `packages.odoo-nix-tools-env` / `packages.odoo-nix-node-modules` when present (CI cache warm-up);
  - `vscodeSettingsFile`/`vscodeExtensionsFile` read `seed`/`seed_extensions` from
    `../py/odoo_nix_tools/odoo_nix_tools/data/ide/vscode.json` (one data file, plan B3);
  - an assertion: opted in with `addons.enable` and `addons.lockDir != "nix"` → "odoo-nix's standards read
    [tool.odoo-nix] from nix/pyproject.toml; keep addons.lockDir = \"nix\"" (through `odoo-nix.removals`-style
    throw, as perSystem has no `assertions`).
- `lib/raw-odoo.nix` gains `coverage ? null` (a coverage built for `python`) and, only when it is non-null:
  ```sh
  if [ -n "''${ODOO_NIX_COVERAGE_RCFILE:-}" ]; then
    export PYTHONPATH="${coverage}/${sitePackages}''${PYTHONPATH:+:$PYTHONPATH}"
    set -- -m coverage run --rcfile="$ODOO_NIX_COVERAGE_RCFILE" --parallel-mode <odoo-bin or launcher> "$@"
    exec ${python} "$@"
  fi
  ```
  before the existing `exec` lines. The dev shell passes `standards.tools.coverage` when `tests` is on; builtOdoo
  and the NixOS service pass `null` (production never measures).
- `flake.nix`: `packages.<system>.{odoo-nix, odoo-nix-tools}`, `apps.<system>.odoo-nix`; `checks` of §7.3;
  `lib.odoo-nix-src` is not needed (the profile repo uses `"${odoo-nix}"`).

### 5.5 `odoo-init --sync | --check | --standards | --profile-path` (`lib/odoo_nix_cli/init`)

- `args.py`: new switches `--sync`, `--check`, `--offline`; valued `--standards <profile>`, `--profile-path <dir>`,
  `--only <paths>`, `--format <text|json|github>`, `--expect-rev <rev>`, hidden `--phase <a|b|all>`;
  `InitArgs.standards_mode` = any of `--sync`, `--check`, `--standards`, `--profile-path`. `--standards`/
  `--profile-path` alone mean `--sync`. `--sync` with `--check` is a usage error (exit 1, odoo-init's own code).
- `command.py`: before `decide_mode`, a standards run bypasses the scaffold pipeline, **unless** `--addons` or
  `--migrate` is also given: then the scaffold pipeline runs to completion first (it writes the addons-mode
  `flake.nix`, `.odoo-series`, `nix/pyproject.toml` and the first lock), and the standards run follows in the
  same process, so `odoo-init --addons --migrate --standards <profile>` (plan D.2) meets the preflight
  precondition (§3.4) in one command:
  ```python
  if st.args.standards_mode:
      if st.args.addons or st.args.migrate:
          code = run_scaffold(st)  # today's pipeline
          if code:
              sys.exit(code)
      from odoo_nix_tools.cli import main as standards_main

      sys.exit(
          standards_main(
              ["sync", "--check" if st.args.check else "--write", *passthrough(st.args)]
          )
      )
  ```
  `passthrough` maps `--standards`, `--profile-path`, `--force`, `--dry-run`, `--skip-lock`, `--offline`,
  `--only`, `--format`, `--expect-rev`, `--phase` one to one. Exit codes are then the core's (0/1/2/3). Fix the
  docstring at `command.py:11-12` ("odoo-nix has no --sync or --check, so frappe-nix's 3 is not used") and
  `docs/reference/scaffolder.md:51` to say the standards flags use the shared table.
- Re-exec after phase A's lock (core §6.3 step 8) runs the **locked engine's** app,
  `nix run github:<owner>/<repo>/<rev>#odoo-init -- --sync <argv>` (`sync.reexec_argv`, §2.5), not
  `.#odoo-init`: evaluating the project flake would need a project's submodules, and the engine app needs only
  the lock.
- `templates/{project,addons}/flake.nix` write `odoo-nix.url = "github:Avunu/odoo-nix/release-@MAJOR@"` (the URL the
  inputs block renders, §3.1 dev-shell) and are lint-clean once rendered: the project template's unused `self` in
  `{ self, odoo-nix, ... }@inputs` goes (deadnix flags it; `self.submodules` lives in `inputs`, not in the outputs'
  arguments). A new check `templates-nix-lint` renders both templates with sample values and runs nixfmt, statix
  and deadnix on them (odoo-nix's own nix-lint skips `templates/`, `flake.nix:136-143`, because the placeholders do
  not parse).

---

## 6. Gates, commands and workflows

### 6.1 `odoo-nix gate lint|test` (`commands/gate.py`)

```python
def register(sub: argparse._SubParsersAction, product: Product) -> None: ...


# odoo-nix gate {lint,test} [--base SHA] [--expect-rev REV] [--format text|github]
#                           [--report PATH (default .odoo-nix/gate/<gate>.json)]


@dataclass(frozen=True)
class Step:
    name: str
    module: str | None  # skipped (with reason) when off
    run: Callable[[GateContext], StepResult]


@dataclass
class StepResult:
    status: Literal["passed", "failed", "skipped"]
    reason: str = ""
    seconds: float = 0.0
```

Every step runs; exit 1 when any failed, 2 for configuration, 3 for environment. The report follows
`data/schema/gate-report.schema.json`; with `$GITHUB_STEP_SUMMARY` a table is appended.

#### 6.1.1 `gate lint` (run in the lint shell: locally `nix develop --no-pure-eval .#odoo-nix-lint`, in CI the engine's `lib.standards.lintShell`, §6.4)

| Step | Module | Command |
|---|---|---|
| `sync-check` | always | `odoo-nix sync --check [--expect-rev]` |
| `prek` | any pre-commit module | `tools/.venv/bin/prek run --all-files --show-diff-on-failure -c .pre-commit-config.yaml` (always `-c`: without it prek's workspace mode would also run any tracked nested config, §1.2; `standards-prek-*` plants one in the fixture to prove it is not run) |
| `manifests` | addon-manifest | `odoo-nix check manifests` |
| `icons` | icons | `odoo-nix check icons` |
| `submodules` | ci, shape project | `odoo-nix check submodules` |
| `ratchet` | tests | `odoo-nix ratchet coverage --base <base>` (base: `--base`, else the PR merge-base; skipped on push/schedule) |

#### 6.1.2 `gate test` (run in `ODOO_NIX_CI=1 nix develop --no-pure-eval -c odoo-nix gate test`)

| Step | Command |
|---|---|
| `modules` | `installable − untested` (facts and cfg); none → every later step skipped, "no tested addon" |
| `postgres` | under `ODOO_NIX_CI`: a throwaway cluster the way `odoo-test-<major>` gets one (`tests/series.nix:190-204`, postgresqlTestHook): `initdb` into `.odoo-nix/test/pg`, `pg_ctl start -o "-k <sock> -c listen_addresses=''"`, a superuser role; the next step passes `--db-host=<sock>`. Outside CI: the running devenv PostgreSQL |
| `odoo-test` | `odoo test --all --fresh-db --coverage tools/pyproject.toml --log .odoo-nix/test/odoo.log` (below) |
| `checklog` | `tools/.venv/bin/checklog-odoo .odoo-nix/test/odoo.log` with `checklog-odoo.cfg` (when `tests.checklog`) |
| `coverage` | `tools/.venv/bin/coverage combine` then `coverage report --rcfile=tools/pyproject.toml` (exit non-zero below `fail_under`), `coverage xml -o .odoo-nix/coverage/coverage.xml`. Every coverage process runs from the repository root with `COVERAGE_FILE=<root>/.odoo-nix/coverage/.coverage` exported (the gate and `odoo test --coverage` both set it), so the data file does not depend on whether coverage resolves `data_file` against the current directory or the rcfile's (`tools/`). Whether `[run] source` resolves the same way is verified at O2 (`odoo-test-ci-18` asserts every measured file is under `addons_root`); if it resolves against `tools/`, the `tests` group writes `source` as `../<addons_root>` |
| `manifestoo` | `tools/.venv/bin/manifestoo --select-addons-dir <addons_root> --addons-path <odoo.conf addons_path> check-licenses`, then `check-dev-status` (addon-manifest on) |

`odoo test` redesign (`lib/odoo_nix_cli/commands/__init__.py` `test_cmd`):

```
odoo test [MODULES] [DATABASE] [--all] [--fresh-db] [--keep-db] [--coverage RCFILE] [--log PATH]
```

- `MODULES DATABASE` with neither `--all` nor `--fresh-db`: today's behaviour (`-u` on an existing database),
  but through `subprocess.Popen` + tee instead of `os.execv`, so the log file is written and the exit code
  reported after.
- `--all`: the modules are `ODOO_NIX_LOCAL_ADDONS`' installable addons (addons mode) or `custom/`'s (project), minus
  `[[tool.odoo-nix.untested]]`, read with `tomllib` from the shape's config file (root `pyproject.toml`, else
  `nix/pyproject.toml`); installability is `ast.literal_eval` of each manifest. Never through `odoo_nix_tools`
  (§5.1: the `odoo` CLI runs in Odoo's interpreter). `odoo-nix gate test` computes the same list from discovery and
  passes it explicitly, so the two agree by test (`test_gate`), not by shared code.
- `--fresh-db`: a database `odoo_nix_test_<pid>` created by `-i <modules>`, dropped afterwards unless
  `--keep-db`; `--test-enable --test-tags /<m1>,/<m2>,…` (own addons only; dependencies' tests do not run);
  ≥ 19.0 adds `--with-demo`; < 19.0 passes `--without-demo=` so a project's `without_demo = true` (project A's
  settings) does not reach the test database; `--stop-after-init --workers=0`.
- `--coverage RCFILE` sets `ODOO_NIX_COVERAGE_RCFILE=RCFILE` for the child (the hook in `lib/raw-odoo.nix`).
- The tour-prerequisite refusal (`ODOO_NIX_TEST_ALLOW_SKIP`) is unchanged.

### 6.2 `odoo-nix check manifests|icons|submodules` (`commands/check.py`)

```python
def manifests(ctx: CheckContext) -> list[str]:
    # only what pylint-odoo cannot: website == rendered addon-manifest.website (when set); version prefix ==
    # series; a ^\d+\.0$ integration branch == series; .odoo-series == series
def icons(ctx: CheckContext, fix: bool) -> list[str]:
    # static/description/icon.png present, square, ≥ min-size px, ≤ max-bytes (pngsize.png_size on the bytes).
    # --fix: tools/.venv/bin/oca-gen-addon-icon for each failing addon with --src-icon=<pin-path standards-profile>/<src-icon>
    # (flags checked against the pinned maintainer-tools at stage O7); no src-icon file → exit 2
def submodules(ctx: CheckContext) -> list[str]:
    # every .gitmodules entry has branch = <series> (projects; project A 72 entries, project B 24, all 18.0 today)
```

Exit 0, 1 with one line per problem, 2, 3. `--format github` annotates `file=<addon>/__manifest__.py`.

### 6.3 `odoo-nix ratchet coverage` (`commands/ratchet.py`)

- `--base SHA`: R1 `fail_under(head) ≥ fail_under(base)` from `tools/pyproject.toml`; R2 `untested` addons(head) ⊆
  untested(base). Skipped when the base's config file has no `[tool.odoo-nix]` (the adoption PR sets the start).
- `--raise`: after a coverage run, sets `fail_under` to `floor(measured)` when that is higher (tomlkit, value only);
  never lowers. Not a gate step; developers and a scheduled job commit it.

### 6.4 Reusable workflows (`odoo-nix/.github/workflows/`) and callers

All pin actions by SHA (`ci-pins`), pass inputs through `env:`, clear `$RUNNER_TEMP` on self-hosted runners
(odoo-nix `check.yml` pattern), and use `runs-on: ${{ github.event.pull_request.head.repo.fork && 'ubuntu-latest'
|| fromJSON(inputs.runs-on) }}`. The composite actions are
`Avunu/python-devops-nix/.github/actions/standards-*@<sha> # v1.3.x`.

| Workflow | Job (check) | Steps |
|---|---|---|
| `odoo-lint.yml` | `lint` | checkout (fetch-depth 0, **no submodules**); Nix + cache; `rev=$(jq -r '.nodes[.nodes.root.inputs["odoo-nix"]].locked.rev' flake.lock)` and owner/repo the same way; `nix develop --impure --expr 'let e = builtins.getFlake "github:<owner>/<repo>/<rev>"; in e.lib.standards.lintShell { system = builtins.currentSystem; root = /. + builtins.getEnv "PWD"; }' -c odoo-nix gate lint --format github`. The project flake is never evaluated: with `self.submodules = true` (project A: 72 submodules, among them the private odoo-studio) Nix would read the submodules to evaluate it. The CLI is the locked engine's own build, so no install and no skew |
| `odoo-test.yml` | `test` | checkout **with submodules** (`submodules: recursive`), using the App token when `ci.github-app` is set (installed on every private submodule's repository: odoo-studio for project A), else `GITHUB_TOKEN` (public submodules only; a private one fails the checkout with that hint); Nix + cache; `ODOO_NIX_CI=1 nix develop --no-pure-eval -c odoo-nix gate test --format github`; upload `.odoo-nix/test/odoo.log` and `coverage.xml`. Tests need the code, so this job cannot avoid the submodules |
| `odoo-pr-policy.yml` | `pr-policy` (`if: github.event_name != 'push'`: skipped, so green, on the push run that the bump commit needs) | checkout (fetch-depth 0, no submodules); `standards-install` (`cli: odoo-nix`, `engine-input: odoo-nix`, `env-prefix: ODOO_NIX`, `install-spec` = `engine.install_spec`); committed from the locked engine (`nix profile install github:<owner>/<repo>/<rev>#committed`, §5.1; `--inputs-from .` would fetch the project flake and its submodules); `standards-pr-policy` (`integration: <input>`) |
| `odoo-release.yml` | `release` (concurrency `release`, no cancel) | App token (`actions/create-github-app-token` with **`client-id`** = the input, as `mirror.yml:43` does; contents + workflows write); checkout with it, **`ref: <integration>`** (the branch head, not `github.sha`: a push-triggered run of an older merge would otherwise bump a stale tree and have its push rejected), fetch-depth 0; `standards-install`; `series=$(odoo-nix config series)`; `standards-release-ff` (`bump: true`, `release-branch: $series`, `sha` = the checked-out head, `wait-checks: 900`, `token`). A push still rejected (a merge in the seconds between checkout and push) is exit 1 under the core (§8.2 step 6) until CR6 (§10) |
| `odoo-deps.yml` | `relock-plan`, `relock-push`, `automerge`, `update-branches` (addons); `project-update` (projects) | frappe-nix `app-deps.yml`'s graph: a Dependabot nix PR's relock runs `nix run --no-pure-eval .#relock` with no write token, a second job applies its patch with the App token; `standards-deps-automerge` with the decision table (`policy` from `dependabot.auto-merge-policy`); `standards-update-branches` on push when `update-branches`. **project-update**: checkout with submodules (the token rule of `odoo-test.yml`); on `schedule: <ci.project-update>`, `nix develop --no-pure-eval -c odoo project update` (each submodule to the tip of its `.gitmodules` branch, then relock), commit `chore(deps): update submodules`, push `standards/project-update`, `gh pr create` with the App token; auto-merge only when `dependabot.auto-merge`. **Without an App** (project B blanks `ci.github-app`): the PR is opened with `GITHUB_TOKEN`, whose events start no workflow, so the job then runs `gh workflow run ci.yml --ref standards/project-update` and the same for `pr-policy.yml` (`actions: write`; a `workflow_dispatch` from `GITHUB_TOKEN` does start a run), whose check runs land on the PR's head commit |
| `fleet-audit.yml` | `audit` | checkout the profile repo; `standards-install` (the profile repo's `flake.lock` pins odoo-nix); `standards-fleet-audit` (`fleet`, `issue-repo`, `audit-token: secrets.AUDIT_TOKEN`) |

Callers in a checkout (§3.1 ci): `ci.yml` (top-level **`name: ci`**, which `workflow_run` matches by name;
`on: push [integration], pull_request, workflow_dispatch`; jobs `lint`, `test`, each `name: ci`), `pr-policy.yml`
(`name: pr-policy`; `on: pull_request [opened, edited, synchronize, reopened], push [integration],
workflow_dispatch`), `release.yml` (`on: push [develop], workflow_run (workflows: [ci]) completed on develop,
workflow_dispatch`; secrets `APP_PRIVATE_KEY: ${{ secrets.<private-key name> }}`, input `client-id: ${{
vars.<app-id name> }}`), `deps.yml` (`on: pull_request` + `push [integration]` when update-branches + `schedule`
for project-update). Conformance's CI part (core §11.4) and `test_fixtures_render` assert the `name:` keys. odoo-nix's own `pr-policy.yml` switches from `lib/pr_policy.py` to `odoo-nix policy --pr
--major-free` (plan B5); `lib/pr_policy.py`, `tests/test_pr_policy.py` and `checks.pr-policy` are deleted.

---

## 7. Fixtures and tests

### 7.1 Fixtures (`tests/fixtures/`)

`standards-project/` (a project; `[tool.odoo-nix]` in `pyproject.toml`, `profile = "recommended"`):

```
pyproject.toml           odoo-init's template shape: install-set and module-sources foreign blocks, a dev group with ruff
modules.txt              one OCA module
.gitmodules              odoo (branch 18.0) and modules/server-tools (branch 18.0); no gitlinks (a fixture
                         cannot hold them: shape comes from modules.txt)
flake.nix                templates/project/flake.nix with `self.submodules = true;` and a hand-written
                         `odoo-nix.url = "github:Avunu/odoo-nix";` plus `nixpkgs.follows`
.envrc                   the template's (a legacy text)
.gitignore               the template's (absorbed lines)
.vscode/settings.json    2-space, Odoo.serverConfigPath set (must be removed), python-envs.defaultEnvManager
.vscode/extensions.json  {"recommendations":["Odoo.odoo"]} with no final newline
custom/fixture_sale/     __manifest__.py (LGPL-3, "Fixture LLC"), models/*.py, static/src/js/*.js,
                         views/*.xml, tests/test_*.py, README.md, static/description/icon.png (128×128)
custom/fixture_legacy/   installable False (rendered into the NOT INSTALLABLE region)
flake.lock               committed, with fixed nodes for every input the rendered inputs block and the hand-written
                         ones define (odoo-nix at a fixed rev with `original` = the rendered release-2 URL, nixpkgs
                         follows); `lock_problems` is clean. The checks set ODOO_NIX_ALLOW_SKEW=1 (no caller SHA
                         or core rev can match a fixed fake rev)
```

Locks are per profile, not per fixture: one `tools/uv.lock` cannot match the dependency sets of `minimal` (none),
`recommended@2.3` and `example-org` (which adds packaging, icons and the website hook's maintainer-tools). They live
in `tests/fixtures/standards-locks/<fixture>/<profile>/{tools/uv.lock,package-lock.json}` (18.0 only: both
fixtures are 18.0), written by `nix run .#relock-standards-fixtures` (an app, needs network; it syncs a copy of the
fixture under the profile and runs the two lock commands there). The tests and checks copy the profile's locks
into the fixture copy before `--check`.

`standards-addons/` (addons mode; `[tool.odoo-nix]` in `nix/pyproject.toml`, `profile = "recommended"`):

```
nix/pyproject.toml       templates/addons/nix/pyproject.toml rendered (both foreign blocks), with the table appended
.odoo-series             18.0
flake.nix                templates/addons/flake.nix rendered: `ocb` and one `oca-queue` input (unclaimed)
flake.lock               as above (plus `ocb` and `oca-queue` nodes)
.envrc, .gitignore       templates/addons' (legacy text; absorbed lines incl. /.odoo-nix/)
fixture_a/               __manifest__.py 18.0.1.0.0, whool pyproject.toml, tests, README.md, icon
fixture_b/               __manifest__.py, whool pyproject.toml, static/src/js, README.md, icon
.github/workflows/mirror.yml   the addon repos' file (retired by the example-org profile)
```
with `[tool.odoo-nix.dependabot] target-branches = ["develop", "17.0"]` (two-branch case: 17.0 is a maintenance
branch the per-series release ruleset does not cover, §2.2) and a local-region entry for `17.0`'s npm directory.
Both fixtures are clean under every profile they are rendered with (`--check` exits 0). Planted defects live in
separate variants built by the tests from a clean copy: `standards-addons` minus `fixture_b/README.md` (a readme
`checks` item, exit 1 under example-org), a hand-edited `tools/pyproject.toml` (the stale-lock item), an unpinned
`uses:` in `.github/` (zizmor), a nested `.pre-commit-config.yaml` under `fixture_a/` (must not run, §6.1.1).

`profiles/example-org/`: `profile.toml` extending `recommended@2.3` with every module on, `[org]` filled,
`addon-manifest.author`/`website`, `releases.branching = "develop+series"`, `repo-policy.release-bypass =
"integration:123"`, `[[retire]]` mirror.yml, `[[extra-files]]` `SECURITY.md`, `templates/addon-icon.png`
(128×128), `templates/editorconfig` override.

**`product.fixtures`** (shipped in the package, used by `profile validate` and the conformance render part) are
`Fixture(table, files)` built from the two fixture trees by `fixtures.py` at import (`files` = path → text). They
carry the `flake.lock` and the `example-org` locks (the superset: every tool module on), since a throwaway cannot
run `uv lock` offline and an org profile's module set is not known in advance. The stale-lock item compares
`rendered ⊆ locked` under a throwaway (§3.4; everywhere until CR2), so one superset lock passes for every profile.
The npm lock is the same for every profile that has `js-xml` on (one group).

### 7.2 Unit tests (`py/odoo_nix_tools/tests/`, run in the package's check phase)

| Test | Covers |
|---|---|
| `test_product` | `PRODUCT` builds; `standards_core.testing.conformance.check(PRODUCT) == []` (static part; render and CI parts as the core grows) |
| `test_series` | each file loads (`schema_version` 1); every `DEVIATIONS` id changes exactly its fact on the right series; no placeholder survives `effective` with an org; pins of `tool-pins.json` fill every null-version tool |
| `test_discover` | `config_file` four cases; shape precedence (explicit, flake `addons.enable`, root manifest, odoo gitlink, `modules.txt`, none → 2, both → addons + notice); series precedence and the no-data refusal; addon facts on copies of edi-addons (`web_theme_carbon` package.json), a synthetic project addon (no website, `description`), shopfloor (LGPL-3 addon); `new_target_table` with an `upstream`-only remote |
| `test_precommit` | 18/19/20 hook lists against OCA's reference `.pre-commit-config.yaml` minus the dropped three; `^.github/` per hook; stage names (18.0); `--fix` gone (20.0); not-installable region; module gating; entries resolve to `tools/.venv/bin`/`node_modules/.bin` |
| `test_tools_groups` | `tools/pyproject.toml` from nothing; a hand-raised ruff pin kept, a lower one raised, a hand-added unknown tool kept in place; pylint-odoo turned off removes `pylint-odoo` and `oca-odoo-pre-commit-hooks` by name while python-lint stays on; `fail_under` seeded once and never overwritten; the `deps` group owns `[project].dependencies` alone |
| `test_ruff_toml` | every `.ruff.toml` rendering parses with `tomllib`; `extend-exclude` is top-level; a region not opening with a table header is exit 2 |
| `test_lock_checks` | the stale-lock items for `tools/uv.lock` (root `requires-dist` tables) and `package-lock.json` (`packages[""].devDependencies`), equality and subset modes |
| `test_package_json` | created in prettier form; a frontend's own scripts kept; pins reconciled as floors |
| `test_ide_real` | the four `tests/shapes/vscode/*` files: managed leaves set, `Odoo.serverConfigPath` deleted, `python-envs.*` and `Odoo.selectedProfile` untouched, inline arrays stay inline, no final newline stays absent, 4-space indent kept |
| `test_flake_block` | `tests/shapes/flakes/*`: project-b (`''${ODOO_NIX_HTTP_PORT:-8069}`, `self.submodules`), project-a, edi-addons (`ocb`, `oca-*` unclaimed), vertical-auto-repair (25 inputs): first opt-in diff exit 2, `--force`, idempotent second run, `lock_problems` clean |
| `test_foreign_blocks` | `tests/shapes/pyproject/*` keep the install-set, module-sources and sdist-build-deps blocks byte for byte through sync |
| `test_release` | `OdooSeries` arithmetic (`18.0.1.2.3` + minor → `18.0.1.3.0`), prefix refusal; `ManifestTool.write_version` byte-preserving on real manifest shapes (single and double quotes, trailing comma, comments); `exempt` |
| `test_checks` | each `checks` item, `preflight` refusal and notice |
| `test_policy` | `pr_checks`: a hand version edit in a PR to develop under post-merge-bump |
| `test_gate` | step selection per module/shape; failure aggregation; report JSON against its schema (subprocess faked) |
| `test_check_cmds` | manifests (website template, series), icons (`pngsize` on the three PNGs), submodules |
| `test_ratchet` | R1, R2, the not-opted-in base, `--raise` never lowers |
| `test_fleet` | entry schema (`branches`, `integration_branch` optional); `fleet_table`; A12/A13 rows with `FakeGitHub`; `repo_policy_values` (release pattern per series, `integration_bypass` `[]` in a project) |
| `test_fixtures_render` | both fixtures × `minimal`, `recommended@2.3`, `example-org`, each with that profile's locks copied in and `ODOO_NIX_ALLOW_SKEW=1`: `sync --write --offline` then `--check` exit 0; second write byte-identical; `minimal` after `recommended` retracts every block and jsonc leaf (and no seed-owned `.vscode` leaf); the defect variants exit 1; exit codes 2/3; `ci.yml`/`pr-policy.yml` carry their `name:` |
| `test_preflight_addons` | an addon repository at `develop`'s shape (no `flake.nix`, no `nix/`) is exit 2 with the `odoo-init --addons` hint; `--addons --standards` scaffolds then syncs (§5.5); a series integration branch under develop+series is exit 2 |
| `test_cli` | `--help` snapshot; `--version` == `version.txt` |

### 7.3 Flake checks (`flake.nix`, `tests/standards/*.nix`)

| Check | What |
|---|---|
| `standards-unit` | the package build's check phase (above) on `python3`, and the suite again on `python311` (core floor) |
| `standards-conformance` | `base.standards.conformance { product = odooNixTools; module = "odoo_nix_tools.product:PRODUCT"; }` |
| `standards-core-pins` | `base.standards.pins { src = self; product = "odoo-nix"; owner = "Avunu"; }` |
| `standards-version` | `version.txt` == `py/odoo_nix_tools/pyproject.toml` version == `__version__` |
| `standards-fixtures-{project,addons}` | offline `odoo-nix sync --check` on a copy of each fixture under each built-in profile and example-org, with that profile's locks and `ODOO_NIX_ALLOW_SKEW=1` |
| `standards-prek-{project,addons}` | in a copy of each fixture synced under example-org, with `tools/.venv`, `tools/.bin` and `node_modules` linked (the env built from the example-org locks): `prek run --all-files -c .pre-commit-config.yaml` exits 0 (managed files are clean under their own hooks); with the defect variants planted, `prek run zizmor --all-files -c …` reports the unpinned `uses:` in `.github/` (it sees `.github/`), and the nested config under `fixture_a/` does not run |
| `standards-prettier-stable` | the locked prettier `--check` on every managed JSON/YAML/JS of both synced fixtures |
| `standards-shell-eval` | a non-opted-in addons and project shell evaluate to today's derivations (drv path equality); opted in: `apps.odoo-init`, `devShells.odoo-nix-lint`, `nodeExcludes` contains `"."` in addons mode; `lib.standards.lintShell` evaluates over a plain fixture path |
| `templates-nix-lint` | `templates/{project,addons}/flake.nix` rendered with sample values pass nixfmt, statix and deadnix (§5.5) |
| `odoo-test-ci-18` (Linux) | `odoo test --all --fresh-db --coverage` on the 18.0 fixture addon writes coverage data under `COVERAGE_FILE`, every measured file under `addons_root`; a planted `_logger.warning` makes checklog fail |
| `workflows` (extended) | actionlint + zizmor over `tests/fixtures/standards-*/.github` after sync |

`nix run .#relock-standards-fixtures` (an app, never a check) rewrites `tests/fixtures/standards-locks/` for each
fixture × profile (18.0 only).

---

## 8. Adoption mechanics

### 8.1 What `odoo-init --standards <profile>` writes

0. Preflight (§3.4): an addon repository must already track its addons-mode `flake.nix` and `nix/pyproject.toml`
   (or the run includes `--addons`, §5.5); a project its `flake.nix` and root `pyproject.toml`.
1. The table, in `config_file(root)` (CR1), with `tomlkit` (`add_table`, core §4.4):
   ```toml
   [tool.odoo-nix]
   schema = 1
   profile = "github:Avunu/odoo-standards-profile/v1"
   # integration-branch = "<origin/HEAD>" only when it differs from the default (project B: "master")
   # repo = "<owner>/<name>" only when there is no origin remote (project A: its `upstream`)
   ```
2. Phase A: the `flake.nix` inputs block (`odoo-nix.url = "github:Avunu/odoo-nix/release-2"`, `standards-profile`
   with `flake = false`), `.envrc`, the `.gitignore` block; `nix flake lock`; second build with the locked profile;
   re-exec under the locked odoo-nix when `version.txt` differs.
3. Phase B: every live managed file; `uv lock --project tools`; `npm install --package-lock-only
   --ignore-scripts --no-audit --no-fund`; retire rules; staging. Remaining `checks` items are reported (exit 1).

A first run on any target exits 2 with the inputs-block diff, because every target's `odoo-nix.url` differs from the
rendered one (`github:Avunu/odoo-nix` in projects A and B, `github:Avunu/odoo-nix/feat/addons-mode` in the 10 addon
repos). The adopter reads the diff and reruns with `--force`, which also replaces a differing first-opt-in file.
A repository scaffolded by an odoo-init that carries the §5.5 template change opts in without `--force` (equal
definitions move silently).

Sync stages the files it writes (core §6.3). In a dirty tree that stages the adopter's own edits in those files
too (a real project checkout had 26 changed entries, among them
`.vscode/settings.json`, `flake.nix` and `flake.lock`); `notices` names them (§3.4) until CR5, and the adoption
steps commit or stash first.

### 8.2 An addon repository (the 10 `Avunu/*-addons`)

**Precondition:** the `feat/dev-env` PR is merged, so `develop` tracks the addons-mode files. Today `develop` has no
`flake.nix` and no `nix/` in any of the 10 (`git ls-tree develop`, verified), and preflight refuses there (§3.4).
Running on `develop` before the merge needs `odoo-init --addons --standards <profile>` (§5.5).

Starting point (branch `feat/odoo-standards` = the open `feat/dev-env` PR): addons-mode `flake.nix`, `.odoo-series`
(`18.0`), `nix/pyproject.toml` + `nix/uv.lock`, `.envrc` `use flake . --no-pure-eval`, the addons `.gitignore`,
`.github/workflows/mirror.yml`, `LICENSE`, root `README.md`; no `.vscode`, `.pre-commit-config.yaml`, `tools/`
or `package.json`. `origin/HEAD` → `develop`.

| Collision | Outcome |
|---|---|
| `odoo-nix.url` outside the block | differs → exit 2 diff, `--force` moves it into the block; `nixpkgs.follows`, `ocb`, `oca-*`, Avunu and muk-it inputs stay where they are |
| `.envrc` | legacy text → replaced silently |
| `.gitignore` | the addons-mode lines are absorbed into the block; `node_modules/`, `*.egg-info/`, `.ruff_cache/` stay; the two emptied comment paragraphs get a notice and are deleted in the `style:` commit |
| `.github/workflows/*` callers | `release.yml`'s App token uses `client-id` (as `mirror.yml` does); the profile adds `release-bypass = "integration:<numeric App id>"` |
| Nix lint | statix and deadnix are clean on the addons-mode flake (verified: `{ ... }:` module lambdas are not statix's `empty_pattern`, and the flake has no unused argument) |
| `nix/pyproject.toml` dev group `ruff` | notice; the template keeps it (non-opted-in repos still use it) |
| `mirror.yml` | retired by the profile's `[[retire]]` (module releases) in the same sync that adds `release.yml` |
| addon `package.json` (`web_theme_carbon`, `shopfloor_repair_mobile/static`) | not managed; `package-lock.json` is excluded from prettier by `locks-excluded`; a Dependabot npm entry for it goes in the `updates` region |
| `shopfloor-app-addons/LICENSES/` | excluded by OCA's `(LICENSE.*\|COPYING.*)` alternative |
| per-addon READMEs with long unwrapped lines | prettier (`proseWrap: "always"`, OCA) rewraps them in the `style:` commit; the root `README.md` is excluded (`^README\.md$`) |

Then, per plan D.3: `prek run -a` (`style:` commit), manual lint fixes, the 4 missing READMEs, 37 icons
(`odoo-nix check icons --fix` once the profile ships `templates/addon-icon.png`), whool `pyproject.toml` per addon
(the `whool-init` hook) followed by `odoo project relock`, then `odoo-nix repo apply` (needs the profile's
`release-bypass`). Ordering across repositories: `web-addons`, `edi-addons`, `fleet-addons`, `repair-addons`,
`shopfloor-app-addons` before `vertical-auto-repair-addons`, which takes them as inputs at `18.0`.

### 8.3 A project (projects A and B)

| Item | project A (`main`, private) | project B (`master`, private) |
|---|---|---|
| Config file | root `pyproject.toml` (`[project].name = "odoo-workspace"`) | root `pyproject.toml` |
| Table extras | `repo = "<owner>/<name>"` (only remote is `upstream`); `integration-branch` derived `main` | `integration-branch = "master"` from origin/HEAD; the client's overrides of plan D.4 (`org`, `addon-manifest`, `ci.runs-on`, blank `ci.github-app`, `dependabot.auto-merge = false`, `repo-policy` off, `packaging` off, one addon in `untested`) |
| Overrides (plan Amendments) | `repo-policy` off, `dependabot.auto-merge = false`, `releases` off | `releases` inherited on → inert with a notice (or set off) |
| flake.nix | `self.submodules = true;` stays (never an input); `odoo-nix.url = "github:Avunu/odoo-nix"` → block (`--force`); `nixpkgs.follows` stays | same; the `''${ODOO_NIX_HTTP_PORT:-8069}` indented string is lexed correctly (core §5.6.2) |
| `.envrc` | `use flake . --no-pure-eval` → legacy, replaced (gains the bootstrap block and `watch_file`) | the `watch_file … use flake` text → legacy, replaced |
| `.gitignore` | `/odoo.conf`, `/odools.toml`, `/.venv`, `/.devenv/`, `/.direnv/` absorbed; `odoo.log`, `docs/.obsidian`, `/.odoo-nix-backup/` stay | the same lines absorbed; a local-notes directory line stays |
| `.vscode` | 2-space settings with inline array; `git.ignoreLimitWarning` kept; extensions keeps `bierner.lit-html` | 4-space settings; `python-envs.defaultEnvManager` → notice (plan D.4: delete before adoption); `Odoo.selectedProfile` untouched |
| Submodules | 72 `.gitmodules` entries, all `branch = 18.0` (OCB, OCA, the 10 Avunu addon repos, odoo-studio, muk-it) → `check submodules` clean | 24 entries, all `branch = 18.0` |
| Updates | `deps.yml` `project-update` job weekly; no Dependabot gitsubmodule | same, without auto-merge |
| Addons | 3 in `custom/` today (the "31" in the task predates `chore/split-addons-repos`) | 4 in `custom/`, LGPL-3, the client as author, no website, each with the deprecated `description` key (pylint `manifest-deprecated-key`), 3 READMEs, no icon, a demo-data addon without tests |
| Dev group `ruff` | `[dependency-groups].dev` lists `ruff` → notice; drop it by hand | same |
| Nix lint (`nix-lint` is on in `recommended`) | `{ self, odoo-nix, ... }@inputs` with `self` unused: deadnix fails (verified); drop `self` in the `style:` commit | same |
| Hook excludes | `^artifacts/\|` and `^docs/\|` in the `.pre-commit-config.yaml` `exclude` local region (tracked `.eml`/`.html`/`.json`/`.pdf` samples and planning notes that whitespace fixers and prettier would rewrite) | — |
| CI | `odoo-test.yml` and `project-update` check out the submodules with the CI App token (odoo-studio is private); `odoo-lint.yml` needs none (§6.4) | no App: `project-update` dispatches CI on its PR (§6.4); `releases` inherited → inert, and `integration_bypass` `[]` should `repo-policy` ever be turned on |
| Before adoption | — | commit the dirty tree; delete the tracked `error.log` |

Rollouts for projects are manual: `nix flake update standards-profile && nix run .#odoo-init -- --sync`.

### 8.4 Hand-written pre-commit and OCA copier files (odoo-studio, later)

An existing `.pre-commit-config.yaml` is refused with its diff unless `--force` (its own hooks go to the `hooks`
region); `.prettierrc.json` and `eslint.config.mjs` are retired by the js-xml rules; an OCA `test.yml`/
`pre-commit.yml` is retired by the ci `contains` rules; `.ruff.toml` with odoo-studio's typing extras is refused
with its diff, and the extras move to `python-lint.extra-select = ["ANN", "FA", "PGH003", "PYI", "TC"]`.
odoo-studio's `origin/HEAD` is `18.0`: before `releases` can be on it needs a `develop` default branch (preflight,
§2.2).

---

## 9. Implementation stages (odoo-nix)

Each stage is a commit series on `feat/standards` that leaves `nix flake check` green with the checks it lists.
"Core n" = the core stage it needs (core §12).

| Stage | Needs | Delivers | Tests / checks |
|---|---|---|---|
| **O0** | — | done: `Odoo.serverConfigPath` removed, odools diagnostic filter (`bd59032`); `gen_series_data.py` and `data/series/*.json` | — |
| **O1** | core 1 | `py/odoo_nix_tools/{pyproject.toml, README.md}`, `__init__.py`, `product.py` with identity, markers, engine, pins (other fields stubbed); `lib/standards/package.nix`; `packages.odoo-nix-tools`; release-please extra-files. No `cli.py` yet: it goes through `standards_core.cli`, which is core stage 2 | `standards-unit` (`test_product` build-only), `standards-version` |
| **O2** | none (parallel with O1) | `odoo test` redesign (subprocess + tee, `--all` reading `untested` with `tomllib`, `--fresh-db`, `--with-demo`/`--without-demo=`, `--coverage` with `COVERAGE_FILE`, `--log`); `lib/raw-odoo.nix` coverage hook (coverage from nixpkgs for the Odoo interpreter until O6 swaps in the tools lock's); checklog run; the `source` resolution check (§6.1.2) | `odoo-test-ci-18`; `test_odoo_*` additions in `tests/test_tui.py`/new `tests/test_odoo_test.py` |
| **O3** | core 2; **CR1** for the addons fixture | `cli.py` (`--version`), `packages.odoo-nix`, `apps.odoo-nix`; `series.py` + `DEVIATIONS`, `discover.py`, `context.py`, `modules.schema.json`, `fleet-entry.schema.json`, `profiles/{minimal,recommended@2.3}.toml`, fixtures trees, `profile show/list`, `config`. `profile show`, `config` and `derive` on the addons fixture read `nix/pyproject.toml`, which needs CR1 (core `config.resolve` takes the root from the config file's parent today); without CR1 the addons cases are skipped with that reason | `test_cli`, `test_series`, `test_discover`, `test_profiles`; `standards-conformance` (static) |
| **O4** | core 3, 4 (CR1 for the addons fixture) | `manifest.d` + templates for whole/seed/toml-merge/json-merge/uv-lock/npm-lock: editorconfig, `.ruff.toml`, `.pylintrc*`, `.pre-commit-config.yaml`, `tools/pyproject.toml` groups, `package.json`, `prettier/eslint` configs, `committed.toml`, `dependabot.yml`, zizmor, workflow callers (text), `checklog-odoo.cfg`; retire rules; first opt-in; `checks.py`; `odoo-nix sync --check / --write --offline` | `test_precommit`, `test_tools_groups`, `test_package_json`, `test_checks`, `test_fixtures_render` (whole/merge files); `standards-fixtures-*`; conformance render part |
| **O5** | core 5 | sentinel entries (flake inputs with claims, no seeds; `.gitignore`, README table), jsonc-merge `.vscode`, `data/ide/vscode.json` shared with `modules/devenv.nix`'s seed; the addons-shape preflight | `test_flake_block`, `test_foreign_blocks`, `test_ide_real`, `test_preflight_addons`; fixtures re-rendered |
| **O6** | core 6 | `odoo-init --sync/--check/--standards/--profile-path/--phase` and `--addons --standards` (§5.5); `pkgs.nodejs` on odoo-init's PATH; `bootstrap.{phase_a_before,reexec_argv,reentry_argv}`; skew; `lib/standards/{tools,shell}.nix` (overrides, `lockAudit`, maintainer-tools override, `tools/.bin`, GC roots, `git rev-parse` anchoring, `prek install -c`); `lib.standards.lintShell`, `packages.committed`; consumer `apps.odoo-init`/`apps.odoo-nix`, `devShells.odoo-nix-lint`, `nodeExcludes`; the raw-odoo coverage hook on the tools lock's coverage; odoo-init templates' release URL and lint fixes; `relock-standards-fixtures` app | `standards-shell-eval`, `standards-prek-*`, `standards-prettier-stable`, `templates-nix-lint`; `tests/odoo-init.sh` cases for the new flags |
| **O7** | core 7 | `release.py` (scheme, `ManifestTool`, `BRANCHING`), `verdict.py`, `policy.py`, `commands/{gate,check,ratchet}.py`, `pngsize.py`; `odoo-{lint,test,pr-policy,release,deps}.yml`; odoo-nix's own `pr-policy.yml` on `odoo-nix policy --pr --major-free`, `lib/pr_policy.py` removed | `test_release`, `test_policy`, `test_gate`, `test_check_cmds`, `test_ratchet`; conformance CI part (push triggers under post-merge-bump); `workflows` extended |
| **O8** | core 8 | `fleet.py` (`fleet_table`, A12/A13, doctor rows, `repo_policy_values`); `fleet-audit.yml` | `test_fleet`; `repo apply --dry-run` on the example-org fixture under `FakeGitHub` |
| **O9** | core 9 | composite-action and `standards-core` pins at one sha (`bump-base`), `standards-core-pins`; `docs/standards/{README,profiles,modules,managed-files,ci,versioning,fleet}.md`, `docs/development/editors.md` rewrite, `conventions.md` note; release-PR job re-rendering the fixtures; freeze `recommended@2.3`; release 2.3 | `standards-core-pins`; the plan's pre-release end-to-end on a fresh clone of an addon repo |

Profile repository follow-ups (after O9, plan C): `release-bypass` (the numeric App id), `fleet.json` with
`branches` (§2.7), README config-file path, `check.sh` per §4.4, `templates/addon-icon.png`, then the snapshots
(`check.sh --update`).

---

## 10. Core change requests

Changes the core contract (`pdn-standards-core/standards/DESIGN.md`) must make for this design. Each names the
core text it changes, the exact proposal and what odoo-nix does until it lands. CR1 is blocking for addon
repositories; CR2 and CR3 have product fallbacks; CR4-CR6 are improvements with product fallbacks; CR7 is text
only; CR8 (added at O7) has a product fallback. None is applied here: the core is being implemented separately and is not edited from this repository.

### CR1: the config file is per checkout (blocking for addons mode)

**Why.** The user decision puts `[tool.odoo-nix]` in odoo-nix's own uv project file: root `pyproject.toml` in a
project, `nix/pyproject.toml` in addons mode; addon repositories have no root `pyproject.toml`. Core §4.4 and §13
item 5 instead settled "`config_required = False`, and `--standards` creates the root file". The stage-1/2 core code
reads one fixed path and also derives the checkout root from the file's location:

- `common/pyproject.py:55` `config_path(product, root)` = `root / identity.config_file`;
- `common/config.py:583` `resolve()` sets `root = config_path.resolve().parent` and (`:283`) the default lock to
  `root / "flake.lock"`, so `nix/pyproject.toml` would resolve with root `nix/` and look for `nix/flake.lock`;
- `commands/config.py:66` finds the file with `repo.find_up(identity.config_file)`, and its `--pyproject`/`--lock`
  help says the lock is "beside the" config file.

**Proposal.**

1. `product.py`:
   ```python
   @dataclass(frozen=True)
   class Identity:
       ...
       config_file: str = "pyproject.toml"  # the default file holding [tool.<table>], relative to the root
       config_paths: tuple[
           str, ...
       ] = ()  # every file the table may live in; () → (config_file,)
       config_required: bool = True


   @dataclass(frozen=True)
   class Hooks:
       ...
       # root → the config file relative to the root, from tracked files and their text only (§3.4);
       # None → identity.config_file. Must return one of identity.config_paths when those are set.
       config_file: Callable[[Path], str] | None = None
   ```
2. `pyproject.config_path(product, root)` returns `root / (hooks.config_file(root) if hooks.config_file else
   identity.config_file)`, and every core read and write of the table goes through it: `config_text`, `load`,
   `context.default_load_checkout`, `repoconfig.load`, `sync` (`_create_table`/`add_table`: with
   `config_required = False` it creates the *file* only when its directory exists; a product preflight may refuse
   first), `rollout.set_profile_ref`, `fixtures.throwaway` (the commit holds what `write_fixture` wrote),
   `targets.load` (the opted-in test on a clone), and the help texts of `config`/`profile` (`--pyproject`).
3. `config.resolve(product, config_path, *, root: Path | None = None, lock_path=None, profile_dir=None,
   checkout=None)`: `root` defaults to `config_path.resolve().parent` (unchanged for one-file products), and
   the default lock is `root / "flake.lock"`. `repoconfig.load` and every caller that has a checkout pass
   `root=checkout.root`.
4. `commands/config.resolve_args` (and `profile show`): without `--pyproject`, the root is the nearest directory
   `d` at or above the current directory, up to the work-tree root, for which `config_path(product, d)` is a file,
   else the work-tree root; the file is `config_path(product, root)`. With `--pyproject F`, the root is the nearest
   ancestor `d` of `F` with `config_path(product, d) == F`, else `F`'s parent. The `--lock` default is
   `root / "flake.lock"` ("beside the checkout's flake.nix").
5. `engine.history` walks commits that changed any of `identity.config_paths or (identity.config_file,)` (plus
   `flake.lock` and an in-repo profile, as now). `_committed_doc(rev)` and the defaults' HEAD read
   (`defaults.head_version`'s config read) take the first of those paths whose text at `rev` has the opt-in line,
   else the current `config_path`.
6. Text: §4.4 "`--standards <profile>` creates the table in `config_path(product, root)`, and the file when it is
   missing, its directory exists and `identity.config_required` is false"; §13 item 5's resolution amended the same
   way.
7. Kit stub (§11.1): the `bundle` shape keeps its table in `kit/pyproject.toml` (a generated project file, as
   odoo's `nix/pyproject.toml`), with `Identity.config_paths = ("pyproject.toml", "kit/pyproject.toml")` and a
   `hooks.config_file`. `test_kit` adds: `config` and `profile show` from the root and from `kit/`, both resolving
   the root and its `flake.lock`; `sync --check`; retraction after a commit (history reads `kit/pyproject.toml`);
   `repo rollout`'s `set_profile_ref` on that file; `--standards` refused by the stub's preflight when `kit/` is
   missing.

**Until it lands:** `PRODUCT` sets neither field (§2.1), and the addons fixture and every addon-repository
command are skipped or refused; no product-side workaround exists (two `Product` objects chosen per checkout
would still hit `resolve()`'s root rule).

### CR2: `ctx.options["throwaway"]` in throwaway renders

**Why.** `profile validate` and the conformance render part sync a throwaway checkout built from
`product.fixtures` under profiles whose module sets are not known in advance, and cannot run `uv lock` offline.
odoo-nix's stale-lock item (§3.4) must then accept a superset lock there, and only there.

**Proposal.** `scaffold.fixtures.throwaway` and `testing.conformance` set `options["throwaway"] = True` in the
sync they run (core §3.5 `options` row: `{"force": bool, "throwaway": bool, **sync.options(args)}`); it is
`False` in every other sync. Lock handlers keep their behaviour; products may read the flag.

**Until it lands:** the stale-lock item compares `rendered ⊆ locked` everywhere.

### CR3: no integration bypass without a release branch

**Why.** Core §7.3 renders `integration_bypass` = the release-bypass actor whenever `releases` is on and the flow
is `post-merge-bump`. A project inherits `releases` (on) from the Avunu profile and has no release branch
(`release_branch` is `""`), so turning `repo-policy` on there would let the App bypass the pull-request and
status-check rules on `main`/`master`.

**Proposal.** §7.3 `integration_bypass` row: "`bypass_actors(release_bypass)` when `releases` is on, the
`Branching.flow` is `post-merge-bump` **and the checkout's release branch is non-empty** (the condition that adds
`release-branch.json`), else `[]`". `test_repo_policy` adds the empty-release-branch case.

**Until it lands:** `hooks.repo_policy_values` returns `integration_bypass: []` when `cfg["shape"] == "project"`
(§2.2).

### CR4: `absorb` takes a comment paragraph its lines leave empty (improvement)

**Why.** Absorbing the addon repositories' `.gitignore` lines leaves their comment paragraphs ("# odoo-nix addons
mode: links the dev shell makes …") with nothing under them (core §5.6.3: comments are never absorbed).

**Proposal.** §5.6.3 `absorb`: "a paragraph (lines between blank lines, outside every block and foreign region)
whose non-comment lines were all absorbed loses its comment lines too; `--check` reports them with the absorbed
lines". `test_blocks` adds it.

**Until it lands:** a product notice names the emptied paragraphs (§3.4), and the adoption commit deletes them.

### CR5: sync does not stage a file that had the user's changes (improvement)

**Why.** Core §6.3 stages every touched path. In a dirty tree (a real project checkout: 26 changed entries,
`.vscode/settings.json` among them) that stages the user's own edits together with sync's.

**Proposal.** §6.3: "paths with unstaged changes when the run starts (`git diff --name-only`) are written but not
staged; the final report lists them as 'left unstaged: it had changes of yours'". `test_sync` adds it.

**Until it lands:** a product notice (§3.4), and the adoption steps commit or stash first (§8.1).

### CR6: a bump push rejected because the branch moved is not a failure (improvement)

**Why.** Core §8.2 step 6 makes a rejected `git push origin HEAD:<integration>` exit 1. Under the
`post-merge-bump` flow the new integration head that caused the rejection triggers its own release run, which
recomputes the bump, so the red run reports nothing actionable.

**Proposal.** §8.2 step 6: "a push rejected as non-fast-forward is exit 0 with `bumped` empty and the notice
'<integration> moved since <sha>; the run for its new head bumps'; any other push failure stays exit 1".
`test_bump` adds it.

**Until it lands:** `odoo-release.yml` checks out `ref: <integration>` (not `github.sha`) under a non-cancelling
`release` concurrency group, which leaves only the seconds between checkout and push (§6.4).

### CR7: text corrections in the core contract

- §2.5 `repo/rollout.py`: "(Frappe value `[["nix","run","--no-pure-eval",".#relock"]]`; odoo `[]`)" → odoo also
  sets the relock step (§0.2 C3: a new odoo-nix can change the install set).
- §5.6.2 "A product whose checkouts may lack the file (odoo addon repositories have no `flake.nix`) ships a
  `seed_template`": odoo-nix ships none and refuses such a checkout in preflight (§3.1 dev-shell); keep the sentence
  for the kit stub without naming odoo.
- §5.3 and §4.3: odoo's `tools/pyproject.toml` entry is `module: TOOLS_MODULES` (every module that contributes a
  tool, §3.1), not `["python-lint", "tests"]`, and its `[project].dependencies` is one group (`deps`) reconciled by
  package name.
- §4.1 `fleet-entry-core`: unchanged; the odoo fleet uses `branches` (C2 withdrawn).

### CR8: the conformance CI part turns on what `releases` and `ci` need (added at O7)

**Why.** Core §11.4's CI part renders each fixture with `releases.enable`, `releases.branching = "<name>"` and
`ci.enable` prepended to its table (stage-7 `testing/conformance._bump_fixture`). odoo-nix's `releases` needs
`commits` (`modules.needs`, §2.1: levels come from conventional commits), which no built-in profile turns on, so the
render exits 2 ("module releases needs module commits, which is off") and the part reports the product as
non-conformant, though the product's own rule is what refused it.

**Proposal.** §11.4 CI part: "… with `releases.enable`, `releases.branching = "<name>"`, `ci.enable` and
`<m>.enable = true` for every `m` in `modules.needs["releases"]` and `modules.needs["ci"]` (transitively) prepended to
its table, each only when the table does not set it". `test_conformance` adds a stub whose `releases` needs a module
off in every built-in profile.

**Until it lands:** the shipped project fixture's table is `commits.enable = true` (`scripts/gen_fixture_data.py`
`TABLE`; `test_fixtures_render` asserts it), so every render of it, under every profile and in the CI part, has
conventional commits on.

---

## 11. Review log

Review of 2026-11-03: 2 blocking, 6 major, 10 moderate and 10 minor items. Each was checked against the core code
(`pdn-standards-core/standards`, stage 1 committed plus the stage-2 files in its working tree), odoo-nix at
`feat/standards`, the 10 addon repositories, projects A and B, the profile draft and the tools themselves before it
was resolved. 27 were accepted (some refined), 1 was accepted in part (P2-12: the statix half did not reproduce),
none was rejected outright. The critique's "what checks out" list was not re-litigated.

| # | Item | Verified | Resolution |
|---|---|---|---|
| P0-1 | `PRODUCT` passes `Hooks(config_file=…, target_branches=…)`, which the core lacks | yes: core `product.py` `class Hooks` (line 339) has neither; only `Identity.config_file: str` (line 121). Also found: `config.resolve` derives root and lock from the config file's parent (`config.py:583`, `:283`) and `config` finds it with `find_up` (`commands/config.py:66`), so a `nix/pyproject.toml` would resolve with root `nix/` | Accepted. C1 → **CR1** (§10) with the exact field, every call site (including the root/lock and `find_up` ones the critique did not list) and kit-stub tests; `PRODUCT` keeps the CR1 fields commented out until the core pins it (§2.1). C2 withdrawn: fleet `branches` (`["develop","18.0"]`), product schema `$ref`s the core, `target_branches` deleted (§0.2, §2.7, §4.4) |
| P0-2 | Opting in an addon repository without addons-mode files breaks the relock; seeded flake trips claims | yes: `develop` of all 10 has no `flake.nix`/`nix/` (`git ls-tree`); relock seeds only a missing file (`workspace/relock.py:76`, `update.py:80`); `_replace_block` warns and the sync returns 1 (`oca_sources.py:132-136`, `:224-228`); `templates/addons/flake.nix` has `odoo-nix.url = "github:Avunu/odoo-nix"` outside a block and no `oca-*` | Accepted, with the refuse option: preflight refuses an addons checkout without tracked `flake.nix` and a `nix/pyproject.toml` holding both foreign blocks, with the `odoo-init --addons` hint (§3.4); `odoo-init --addons/--migrate --standards` scaffolds first (§5.5); seed templates dropped (§3.1, §3.5); odoo-init's templates render the release-branch URL so a fresh flake opts in silently (§5.5); the merged `feat/dev-env` PR is the explicit precondition (§0.1, §8.2) |
| P1-3 | `tools.nix` not feasible: no overrides, `lockAudit`, build deps; maintainer-tools scm version; closure; stale locks undetected; `floors: "uv"` inert | yes: `lib/python.nix:291,314`; cached dist-info `oca_maintainers_tools-0.1.dev1+g31bdbd8e4` and its `Requires-Dist` (selenium, twine, pypandoc, erppeek, setuptools-odoo, unpinned whool); core `UvLockHandler` checks only missing/floors | Accepted. `tools.nix` reuses `pythonLib.overrides` and `lockAudit`, overrides `SETUPTOOLS_SCM_PRETEND_VERSION`, gets sdist build deps through the `odoo-nix-build-deps` block (§5.3); `--check` items compare `tools/uv.lock`'s root `requires-dist` (tables, as in `nix/uv.lock`) and `package-lock.json`'s `packages[""].devDependencies` with their manifests (§3.4); `floors: "uv"` dropped (§3.1) |
| P1-4 | "No PATH dependency" false for Nix-provided hooks; rule-5 table inconsistent | yes: §3.3 rule 5 entries were bare names | Accepted. `tools/.bin` link to a `buildEnv` of `nixTools`, gitignored, GC-rooted; every Nix hook's entry is `tools/.bin/<tool>`; rule 5 rewritten (§3.1 dev-shell, §3.3, §5.2); `committed_argv` prefers `tools/.bin/committed` |
| P1-5 | CI lint evaluates a `self.submodules = true` flake after a checkout without submodules; `--inputs-from .` too | yes: project A's `flake.nix`, 72 `.gitmodules` entries incl. private `odoo-studio` | Accepted. `odoo-lint.yml` builds `lib.standards.lintShell` from the locked engine over the checkout path (`--impure --expr`); `pr-policy` installs `committed` from the locked engine (`packages.committed`); `odoo-test.yml` and `project-update`, which need the code, check out submodules with the App token (§5.1, §5.2, §6.4) |
| P1-6 | `tools/pyproject.toml` modelling: (a) one dependencies key across groups; (b) lock tied to python-lint; (c) ide needs js-xml | yes: core §5.3 "each group owns its keys"; §3.1 row; `prettier.prettierPath` | Accepted. (a) one `deps` group owns the key; `reconcile` merges by package name against the known tool set (§3.1); (b) both entries list `TOOLS_MODULES`, and `pylint-odoo → python-lint` is no longer needed (§2.1, §3.1); (c) `needs["ide"] = ("python-lint", "js-xml")` (§2.1) |
| P1-7 | Ruleset/branch logic: `*.0` blocks other series; series integration branch; projects inherit the bypass | yes: `release_pattern="refs/heads/*.0"`; odoo-studio's `origin/HEAD` is `18.0`; core §7.3 bypass condition | Accepted. `repo_policy_values`: `release_pattern = refs/heads/<series>`, `integration_bypass = []` in a project (§2.2); preflight refuses develop+series on a `^\d+\.0$` integration branch (§2.2, §3.4); A12 rewritten (§2.7); core fix proposed as **CR3** |
| P1-8 | prek workspace mode may run submodules' configs | partly: with prek 0.5.7 a nested config in a tracked plain directory runs, one inside a submodule does not; a root `exclude` does not stop discovery; `-c` limits the run to the root config; `prek install -c` records `--config` in the hook | Accepted for all nested configs, not just submodules: `-c .pre-commit-config.yaml` in the gate, `prek install` and odoo-nix's own `prek-action` (whose synced fixtures would otherwise run); `standards-prek-*` plants a nested config (§1.2, §5.2, §6.1.1, §7.3) |
| P2-9 | `oca-fix-manifest-website`/`oca-gen-addon-icon` default to `--addons-dir=.`; example lacks `pass_filenames: false` | yes: `fix_manifest_website.py:15` `default="."`; series data has `pass_filenames: false` | Accepted. Deviation `addons-dir` (projects); `check icons --fix` always passes the directory; the example and the `system-language` row keep `pass_filenames: false` (§3.0, §3.1 icons, §3.3) |
| P2-10 | Repositories cannot extend the top-level exclude | yes: project A tracks `artifacts/` (2 `.eml`, 3 `.html`, 3 `.json`, 1 `.pdf`, …) and `docs/` | Accepted as a local region `exclude` inside the `(?x)` block scalar (markers are regex comments there; core regions accept indented markers, `regions.py:36-37`); project A's entries in §8.3 (§3.3 rule 6, rendered example) |
| P2-11 | `.ruff.toml` layout puts top-level keys and the region after `[lint.mccabe]` | yes (TOML table scoping) | Accepted. Top-level keys first; the region last and required to open with a table header (exit 2 otherwise); `test_ruff_toml` parses every rendering (§3.1, §7.2) |
| P2-12 | `nix-lint` fails on the targets (statix `empty_pattern`, deadnix unused `self`); templates unlinted | **in part**: statix reports nothing on the edi-addons flake or `templates/addons/flake.nix` (its `empty_pattern` does not flag these module lambdas; it does flag a non-module `({ ... }: 1)`); deadnix flags `self` in project A's and project B's flakes; `templates/project/flake.nix` has the same unused `self`; odoo-nix's nix-lint skips `templates/` (`flake.nix:136-143`) | Accepted for deadnix and templates; no `statix.toml` and no deadnix flag change needed. Template fix and a `templates-nix-lint` check (§5.5, §7.3); adoption rows drop `self` (§8.3); the addon flakes are recorded as clean (§8.2) |
| P2-13 | Phase B re-enters the full dev shell for npm; re-exec evaluates the project flake | yes: odoo-init `runtimeInputs` are sources, git, uv (`lib/init.nix:47-52`) | Accepted. `pkgs.nodejs` on odoo-init's PATH; `reexec_argv`/`reentry_argv` run the locked engine's `odoo-init` (§2.1, §2.5, §5.1, §5.5) |
| P2-14 | `links` anchored on `$DEVENV_ROOT`, unset in the lint shell | yes (`mkShell` sets no `DEVENV_ROOT`) | Accepted. `root="$(git rev-parse --show-toplevel)"` (§5.2) |
| P2-15 | Release job: `github.sha` checkout; `workflow_run` name; `client-id`; numeric App id | yes: `mirror.yml:43` `client-id: ${{ vars.AVUNU_CI_APP_ID }}`; core §8.2 step 6 makes a rejected push exit 1 | Accepted. `ref: <integration>`, `name: ci`/`name: pr-policy`, `client-id`, the numeric id named in §4.4 and the doctor row (§2.7, §4.4, §6.4); the remaining race is **CR6** |
| P2-16 | Fixtures and tests contradict each other (README defect vs exit 0; no `flake.lock`; one lock for three profiles; packaged fixtures without locks) | yes (§7.1/§7.2 as written) | Accepted. Clean fixtures plus defect variants; committed `flake.lock` and `ALLOW_SKEW` in checks; locks per fixture × profile; `product.fixtures` carry the superset lock, which the subset comparison accepts; **CR2** for the exact rule (§7.1, §7.2, §7.3) |
| P2-17 | Stage gating off by one (O1 `cli.py`; O3 needs C1) | yes: core §12 puts `cli.py` in stage 2; `config.resolve`'s root rule | Accepted. `cli.py`/`test_cli`/`packages.odoo-nix` move to O3; O3 needs CR1 for the addons fixture (§9) |
| P2-18 | `odoo test --all` would import `odoo_nix_tools` into Odoo's interpreter | yes: `lib/cli.nix:112` prefixes the target env; 20.0 is `python314` | Accepted. `tomllib` + `ast` in `odoo_nix_cli`; the gate passes the list explicitly; boundary note in §5.1 (§6.1.2) |
| P3-a | project B without an App: `project-update` PRs never get CI | yes: plan D.4 blanks `ci.github-app`; GITHUB_TOKEN events start no workflow | Accepted. The job dispatches `ci.yml`/`pr-policy.yml` on its branch; doctor notice (§2.7, §6.4, §8.3) |
| P3-b | zizmor runs online audits with `GH_TOKEN` | yes (zizmor's online audits use `GH_TOKEN`) | Accepted. `--offline` in the hook (§3.3) |
| P3-c | `absorb` leaves `.gitignore` comment paragraphs empty | yes: edi-addons `.gitignore` has two such paragraphs | Accepted. Notice now, core **CR4**, deletion in the adoption commit (§3.1, §3.4, §8.2) |
| P3-d | Retracting `ide` deletes leaves equal to the devenv seed | yes: `python.defaultInterpreterPath` and the `.devenv`/`.direnv` excludes were in both `seed` and `set` | Accepted. `set` holds only non-seed leaves; `test_ide_real` asserts no overlap (§3.1 ide) |
| P3-e | prettier reformats `.vscode/*.json` | yes: OCA's prettier `files` includes `json`, and `.vscode/` is not in its exclude | Accepted. Deviation `prettier-vscode` (§3.0, §3.3) |
| P3-f | `forbid-contributing` has no stated edit of OCA's regex | yes | Accepted. Deviation `forbid-contributing`: exact removal of `CONTRIBUTING\.md\|`, `RuntimeError` if absent (§3.0) |
| P3-g | `drop-external-deps` goes beyond the agreed skips | yes: plan "Decisions" and the task name only the readme and excluded-addons hooks | Accepted as an open question: marked "proposed, pending sign-off", with the behaviour if declined (§0.1, §3.0) |
| P3-h | `relock-standards-fixtures` says three series; fixtures are 18.0 | yes | Accepted. Per fixture × profile, 18.0 only (§7.1, §7.3) |
| P3-i | Sync stages user edits in a dirty tree | yes: a project checkout had 26 changed entries incl. `.vscode/settings.json`, `flake.nix`, `flake.lock` | Accepted. Product notice now, core **CR5**, adoption commits first (§3.4, §8.1) |
| P3-j | coverage `data_file`/`source` resolution with `--rcfile=tools/pyproject.toml` | not settled by reading; left to a test | Accepted. `COVERAGE_FILE` set absolutely by the gate and `odoo test`; `source` resolution asserted by `odoo-test-ci-18` at O2, with the `../<addons_root>` fallback (§6.1.2, §7.3, §9) |

Found while verifying (not in the critique):

| Finding | Resolution |
|---|---|
| The checkout name in addons mode comes from `nix/pyproject.toml`'s `[project].name` (`edi-addons`), not origin; project A's is `odoo-workspace` | §2.3 corrected |
| uv records the root's `requires-dist` as tables (`{ name, specifier?, directory?, git? }`), not requirement strings | the stale-lock item compares (name, specifier, source) sets (§3.4) |
| odoo-nix's own `prek-action` would run the synced fixtures' nested configs | `extra-args: -c .pre-commit-config.yaml` (§1.2) |
| Core §2.5, §5.6.2, §5.3 describe odoo values this design no longer uses | **CR7** text corrections |

---

## 14. Implementation notes

Deviations from the text above, per stage, each with the reason and when it closes.

### O1 (identity, package, version)

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O1-1 | §1.2 `standards-core @ git+…@<sha>` | the placeholder sha is `97f7b5e7ba08c989ec6e4f6f0b027478013c0434`, the core's stage-2 commit on `pdn-standards-core` branch `feat/standards-core` | the core is not on GitHub yet, so `uv tool install` of odoo-nix-tools fails to fetch it until that commit (or its successor) is pushed. Nix builds never read this line (pythonRuntimeDepsCheck matches the name only). Closes when the core is published: the sha becomes flake.lock's python-devops-nix rev (`bump-base`, `checks.standards-core-pins`, O9) |
| O1-2 | §1.2 `[project.scripts] odoo-nix = "odoo_nix_tools.cli:main"`; §5.1 `meta.mainProgram = "odoo-nix"`, `pythonImportsCheck` with `odoo_nix_tools.cli` | left out (a comment in `pyproject.toml` marks the spot) | `cli.py` is O3 (§9); a console script that names a missing module would install a broken `odoo-nix`. O3 adds all three |
| O1-3 | §1.1 `uv.lock` (dev lock) | not added | it cannot resolve the unpublished sha of O1-1. Until then, development runs the suites with the core on the path: `PYTHONPATH=. uv run --no-project --with-editable ../../../pdn-standards-core/standards python -m unittest discover -s tests` (from `py/odoo_nix_tools`). The lock and its Dependabot `uv` entry (§1.2) come with the published core |
| O1-4 | §2.1 `PRODUCT` | identity, markers, engine and pins as written. The plain-data fields that need no other module carry their §2.1 values now: `modules`, `paths`, `ci` (without `decision_table`), `sync.required_tools`/`rollout_steps`, `header_kinds`, `jsonc_globs`, `json_style`, `semantic_compare`, `fleet_key`, `self_repo`. The four hooks the core requires (`load_checkout`, `discover`, `gates`, `template_globals`) are placeholders that raise `NotImplementedError("odoo-nix: hooks.<x> arrives in stage O3 …")`; every other hook, `handlers`, `version_schemes`, `branching`, `release_tool`, `first_opt_in`, `fixtures`/`write_fixture`, `audit_rows`, `help` and `jinja_filters` keep the core defaults | "other fields stubbed" (§9 O1): their modules (`discover`, `context`, `checks`, `release`, …) and the core's `scaffold.handlers`/`scaffold.jsonmerge` (core stages 3/4) do not exist yet. Mappings are `MappingProxyType`s (the core's read-only convention). Each later stage replaces its placeholders |
| O1-5 | §5.1 `{ …, coreRev }`, `coreRev = inputs.python-devops-nix.rev` | `coreRev ? null`; flake.nix passes `inputs.python-devops-nix.rev or null` | a `path:` override (the development wiring) has no `rev`; with `null` the core package simply writes no `_source.json`. A locked GitHub input always has one |
| O1-6 | §5.1 `unittestFlagsArray` | `unittestFlags` | nixpkgs' unittest hook marks `unittestFlagsArray` obsolete (a compatibility layer) |
| O1-7 | §5.1 "Called with python3Packages.callPackage" | flake.nix `odooNixTools = pkgs: python: python.pkgs.callPackage ./lib/standards/package.nix { inherit pkgs base; coreRev = …; }` | one builder for both interpreters `standards-unit` needs |
| O1-8 | §7.3 `standards-unit` | a script check that depends on the package built on `python3` (3.14 in the locked nixpkgs) and on `python311`; each build's check phase runs `tests/` | the suite runs inside the builds, so the check only has to depend on both |
| O1-9 | §7.3 `standards-version` | an eval check (`lib.checks.mk … eval`, expected/actual): `version.txt` against `pyproject.toml`'s `[project].version` and the `__version__ = "…"` line of `__init__.py` | nothing to build; a mismatch prints the JSON diff (verified with a planted `2.2.1`) |
| O1-10 | §7.2 `test_product`: `conformance.check(PRODUCT) == []` | O1 is build-only (§9): `PRODUCT._problems() == []` and the identity/markers/engine/pins/modules values; the static conformance check is not asserted | it reports today only the data O3 adds: `schema/modules.schema.json`, `schema/fleet-entry.schema.json`, `profiles/minimal.toml`. O3 adds the assertion |
| O1-11 | — | `flake.nix` `envVars.exceptions` gains `"ODOO_NIX"` | the env-vars convention check reads the `env_prefix="ODOO_NIX"` literal as a variable outside `ODOO_NIX_*` |
| O1-12 | §1.2 odoo-nix's `ty.toml` adds `py/odoo_nix_tools` to `extra-paths` | done in O1 (the comment names `standards_core` with the other build-time modules ty cannot resolve). The `^tests/fixtures/standards-` excludes of `ruff.toml`, `.pre-commit-config.yaml` and `ty.toml` wait for those fixtures (O3/O4) | — |
| O1-13 | — | the Python code blocks of this file were reformatted by odoo-nix's `ruff-format` hook (layout only; it formats Markdown code blocks, as the core's own hook does for its DESIGN.md) | `prek run --all-files` (the lint job) would otherwise fail once this file is tracked |
| O1-14 | §9 "each stage leaves `nix flake check` green" | green only with the development override (`--override-input python-devops-nix git+file:…/pdn-standards-core?ref=feat/standards-core`). Against the committed lock (python-devops-nix `c07df3e`, no `lib.standards`), `packages.odoo-nix-tools` and `checks.standards-unit` fail to evaluate | the lock may not carry the local override (plan "Execution mechanics"). Closes when the core is published and the lock moves to it |

### O2 (`odoo test`, the coverage hook, checklog)

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O2-1 | §6.1.2 `odoo test [MODULES] [DATABASE] [--all] [--fresh-db] [--keep-db] [--coverage RCFILE] [--log PATH]` | as written, with the argument rules made explicit: with `--all` a lone argument is DATABASE and two are a usage error; `--fresh-db` with DATABASE, and `--keep-db` without `--fresh-db`, are usage errors (exit 2); `--fresh-db` refuses (exit 1) when `odoo_nix_test_<pid>` already exists instead of testing on it. Odoo's own server start creates the fresh database (`odoo-bin -d <new> -i …`); the CLI drops it in a `finally`, so a failed run drops it too. On that path the CLI first unpins `db_name` in its in-process config (`odooenv.clear_db_name`): the dev shell writes `db_name = <dbName>` with no `dbfilter`, and through 19.0 `exp_drop` refuses any name outside `list_dbs()`, which that pin narrows to the one database, so the test database was otherwise left behind. A drop that still answers False is reported (`✗ did not drop the test database …`), not passed over; the run's exit code stands | the design leaves these cases open; the probe (`odoo_db.exists`) logs one PostgreSQL `FATAL: database … does not exist` line, which is the server's, not Odoo's log. Not changed at O2: `odoo_db.drop` on 18/19 still passes `exp_drop`'s answer through, so `odoo db drop <other>` under a pinned `db_name` says "does not exist" (pre-existing, `test_odoo_db.py` asserts the pass-through) |
| O2-2 | §6.1.2 "through `subprocess.Popen` + tee instead of `os.execv`" | `Popen` always (the exit code is reported after: `✗ odoo test: Odoo exited N`, then the same code; an Odoo killed by signal N, Popen's `-N`, is `✗ … killed by signal N` and exit 128+N, the shell's convention); the tee (stdout and stderr merged, in order, into `--log` and stdout) only with `--log`. Without it the child keeps the terminal, so Odoo's colours stay | nothing to tee into without a log |
| O2-3 | §6.1.2 `--coverage RCFILE` sets `ODOO_NIX_COVERAGE_RCFILE` (and `COVERAGE_FILE`) | also: `COVERAGE_FILE` is set to `<root>/.odoo-nix/coverage/.coverage` only when not already exported (the gate's wins); an exported relative one is made absolute against the repository root, where the raw odoo-bin runs (`cd "$REPO_ROOT"`), so the CLI deletes and finds the data where coverage writes it from any directory; the data a former run left for that data file (`<file>`, `<file>.*`) is deleted first; a run Odoo passes (exit 0) without any data file is exit 1 "no coverage data was written …: this Odoo has no coverage hook" | combining stale data would misstate coverage; an `odoo` whose raw odoo-bin has no hook (builtOdoo, services.odoo-nix) would otherwise ignore `--coverage` silently |
| O2-4 | §5.4 "The dev shell passes `standards.tools.coverage` when `tests` is on" | stage O2's value (§9): `modules/devenv.nix` passes nixpkgs' `cfg.python.pkgs.coverage` to `lib/raw-odoo.nix` in every dev shell, opted in or not, so `odoo test --coverage` works in any project | O6 swaps in the tools lock's coverage and gates it on the opt-in; `standards-shell-eval` (O6) then compares non-opted-in shells against that stage's derivations, not O1's |
| O2-5 | §5.4 the hook "before the existing `exec` lines" | `lib/raw-odoo.nix` takes `coverage ? null`; when null the text is byte for byte the old one (builtOdoo's derivations do not change; the `cli-*` and `service-*` derivations do, as the `odoo` CLI package in them changed, and were built on 18.0, 19.0 and 20.0 at O2); when set, a block before the plain runs makes the same entry-point choice (the tree's `odoo-bin`, or the launcher with the tree first on `PYTHONPATH`) and runs it as `python -m coverage run --rcfile="$ODOO_NIX_COVERAGE_RCFILE" --parallel-mode …`, with coverage's site-packages prefixed onto `PYTHONPATH` | checked by `raw-odoo` (stand-in trees, both entry points, unset variable, no coverage) and `odoo-test-ci-18` (the real Odoo) |
| O2-6 | §6.1.2 / §11 P3-j: "Whether `[run] source` resolves the same way is verified at O2 … if it resolves against `tools/`, the `tests` group writes `source` as `../<addons_root>`" | verified: with `--rcfile=tools/pyproject.toml` and Odoo run from the repository root, `source = ["custom"]` measures `custom/…` (coverage resolves relative `source` against the current directory, not the rcfile's). `odoo-test-ci-18` asserts every measured file is under `custom/` and that a planted module there is covered. The fallback is not needed: the `tests` group (O4) writes `source = [addons_root]` as §3.1 says | — |
| O2-7 | §9 O2 "checklog run" | `odoo-test-ci-18` runs checklog-odoo 1.0 (built in `tests/series.nix` from the PyPI wheel: it is not in nixpkgs) with the series' `reference_files["checklog-odoo.cfg"]` over the test log: the clean log passes, a log with a planted `_logger.warning` fails and names it. Finding for the `tests` module: the dev guard's banners (`WARNING odoo_devguard[...] …`, written raw to stderr, not in Odoo's log format) are continuation lines of the preceding Odoo record for checklog, so OCA's ignore list needs no odoo-nix addition | the gate's `checklog` step (O7) runs the tools lock's checklog-odoo; `data/tool-pins.json` (O4) pins `checklog-odoo==1.0` |
| O2-8 | §7.3 `odoo-test-ci-18` | a `tests/series.nix` check on the 18.0 series only (Linux): a copy of the 18.0 fixture workspace as `$REPO_ROOT` (its odoo.conf pins `db_name = odoo_dev`, as the dev shell writes it, so the drop is checked under that pin), the dev shell's raw odoo-bin shape (`lib/raw-odoo.nix` with coverage) over OCB and the test environment, `lib/cli.nix` around it, `tools/pyproject.toml` with §3.1's `tests` group, a planted `[[tool.odoo-nix.untested]]` addon. Run 1 is the gate's `odoo test --all --fresh-db --coverage tools/pyproject.toml --log .odoo-nix/test/odoo.log` (database dropped, fixture tests passed, data beside `COVERAGE_FILE`'s default, `coverage combine/json/report`, checklog clean); run 2 adds `--keep-db` and the planted warning (fixture installed, untested addon not, checklog fails) | two fresh installs of `base` take about 10 s each on 18.0 |
| O2-9 | §9 O2 "`test_odoo_*` additions in `tests/test_tui.py` / new `tests/test_odoo_test.py`" | both: `tests/test_odoo_test.py` (33 cases: command lines, `--all` in a project, addons mode and a workspace `customDir`, untested, fresh/keep/drop (under a pinned `db_name` too, and a refused drop reported), the demo flag per series, refusals, the log, the coverage variables (a relative `COVERAGE_FILE` too), exit codes (a signal too); a stand-in `odoo` whose `list_dbs`/`exp_drop` gate on a pinned `db_name` as 18.0's do, and a recording raw odoo-bin that "creates" the database an `-i` run names) runs as the new check `odoo-test-unit` on every preset interpreter with click and rich; `tests/test_tui.py` asserts the TUI form of `odoo test` (MODULES optional, the new options) | — |
| O2-10 | — | `lib/odoo_nix_cli/testrun.py` holds the pieces (standard library and `tomllib` only, never `odoo_nix_tools`, §5.1); `odoo db provision`'s addons-mode install set now uses its `installable_addons` (same behaviour); `docs/development/commands.md` and `docs/reference/troubleshooting.md` describe the new options | — |

### O3 (CLI, discovery, series data, schemas, profiles, fixtures)

Built and tested against the core's committed stage 4 (`pdn-standards-core` `feat/standards-core`, `86ef679`), which
has no CR1, CR2-CR6.

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O3-1 | §2.1 `hooks.config_file=discover.config_file`, `Identity.config_paths` | `discover.config_file` exists with the four cases of §2.3 and is tested directly; `PRODUCT` passes neither field (still commented out). `discover` itself reads `extra["config_path"]` (`nix/pyproject.toml` in addons mode) for the table's `shape`/`series`/`integration-branch` and `dev_group_ruff`, so the facts are right on the addons fixture today. The cases that go through the core's resolution of the addons fixture (`profile show`, `config`, `derive` with the core's checkout) are skipped with the CR1 reason (`tests/support.py` `HAS_CR1`), and one test records today's gap (the table in `nix/pyproject.toml` is not seen) | CR1 (§10). Closes in the commit that pins a core with CR1: uncomment both fields; the skips lift themselves |
| O3-2 | §9: `release.py` (`BRANCHING`) is O7 | `release.BRANCHING` (`develop+series`, `trunk`) lands now; `OdooSeries` and `ManifestTool` stay O7. `modules.schema.json` spells `releases.version-scheme` as `{"enum": ["semver", "odoo-series"], "default": "odoo-series"}` | the core composes `releases.branching`'s enum and default and the integration-branch default from `product.branching`: without it an addons checkout resolved `integration-branch = "main"`. A product property replaces the core's whole node, so the enum is spelled out; it equals the composed one once O7 registers `odoo-series` |
| O3-3 | §4.2 `github-app = { app-id = "", private-key = "" }` | the product schema overrides `ci.github-app`: same object, names may be `""` (`^([A-Za-z_][A-Za-z0-9_]*)?$`), default `{"app-id": "", "private-key": ""}` | the core's pattern refuses `""`, so `recommended@2.3` as written did not validate. `""` means no App (project B blanks it). Core follow-up: the doctor/notice code should treat `""` as unset |
| O3-4 | §1.1 `pngsize.py` (O7), `manifests.py` | `pngsize.png_size` and `manifests.literal` now; `replace_version`/`version_problem` stay O7 | the addon facts need the icon size and the manifests |
| O3-5 | §1.1 `data/tool-pins.json` (O4 per O2-7) | now: `prek==0.5.7`, `coverage==7.16.2` (nixpkgs', the one O2's coverage hook uses), `checklog-odoo==1.0`, `manifestoo==1.2`, `manifestoo-core>=1.16.1` (a floor, as §3.1 writes it; `Tool.version` is `None` for a range) | deviation `odoo-nix-pins` and `test_series` need them. O4's lock may move them |
| O3-6 | §2.4 `odoo_python` "from `lib/odoo-presets.json` … copied by `series.load`" | `data/odoo-presets.json`, a byte copy of `lib/odoo-presets.json`; `test_series` asserts equality (in the Nix build too, through `$ODOO_NIX_TOOLS_REPO`) | a `uv tool install` of the subdirectory has no `lib/`. Whoever edits the presets copies the file (the test fails otherwise) |
| O3-7 | §3.0 `SeriesData` | as written plus `node` (the node major: OCA's, or the preset's under `node-runtime`), `odoo_python`, `tools_python`; `tools` are `Tool` records; `files` holds the three whole bodies only (`.pylintrc*`/`.ruff.toml` come from the parsed data, so their placeholders never matter). `DEVIATIONS` are `Deviation(id, applies, fields, change, status)`; `build(series, cfg, facts, skip=…)` builds without chosen deviations (how `test_series` proves each changes exactly its `fields`), `effective` = `build` + the no-placeholder check. `drop-external-deps` is applied with `status="proposed"`. With `addon-manifest.website = ""` `effective` drops `oca-fix-manifest-website` (the module rule of §3.3 rule 2, applied early so no `@@repo_website@@` is left) | testability; the user's sign-off on P3-7 decides `drop-external-deps` |
| O3-8 | §2.3 fact keys | as written plus `shape_signals` (`{"addons": [...], "project": [...]}`, in words) and `shape_notice` (the "both kinds" notice), which `checks.notices` (O4) prints. Series rule 3 counts only installable manifests whose version is `<n>.0.x.y.z`; rule 4 reads the resolved `integration-branch` (else the table's). An addon's `has_py` ignores `__init__.py` and `__manifest__.py`; `package_json` and `addon_package_json` skip `node_modules/` | a notice cannot be raised from `discover`; a non-series version (`1.0.0`) is `version_problem`'s to report (O7), not a series vote |
| O3-9 | §2.4 `template_globals` keys `hooks`, `ide`; `Gen` methods | `hooks` (needs `precommit.py`, O4) and `ide` (`data/ide/vscode.json`, O5) are not added yet; `tools` is `context.live_tools`, the `deps` group's ordered requirements (O4's `groups.TOOLS` reuses it); `Gen` has no methods yet (`pylintrc`, `eslint_config`, `ruff_toml`, `exclude_block` come with their files in O4); `HELP` is empty | they render the O4/O5 managed files and are tested with them |
| O3-10 | §1.1 `commands/__init__.py` `EXTRA = (CHECK, GATE, RATCHET)` | `EXTRA = ()` | the commands are O7 |
| O3-11 | §7.1 fixtures | `tests/fixtures/standards-{project,addons}` as listed, except: no `standards-locks/` (the relock app and the locks are O4/O6); no `product.fixtures`/`fixtures.py` (O4, the conformance render part); the addons fixture's Dependabot local-region entry for 17.0 waits for the managed `dependabot.yml` (O4). Each `flake.lock` is the core's `fakes.flake_lock` of the flake with the rendered `github:Avunu/odoo-nix/release-2` URL (rev `a…a`; owner and repo lower-cased, as `input_spec` compares them). The example-org profile is `tests/fixtures/standards-profiles/example-org/` (§7.1 says `profiles/example-org/`), with `requires-odoo-nix = ">=2.2,<3"` (the package is 2.2.0 until the release) and without the `editorconfig` template override, which needs O4's template name. Real manifest shapes for `test_discover` are copies in `tests/shapes/manifests/` (edi-addons' `web_theme_carbon` from `Avunu/avunu-odoo-addons`, which holds it locally) | the root `standards-` prefix keeps every standards tree under one lint exclude |
| O3-12 | §7.2 `test_cli` "`--help` snapshot; `--version` == `version.txt`" | the snapshot (`tests/snapshots/help.txt`) compares the help's words: argparse lays the command column out differently on 3.11 and 3.14. `--version` is compared with `pyproject.toml`'s version always and with `version.txt` when the tree is available | the package build has no `version.txt` of its own |
| O3-13 | §5.1 `preCheck` | also `export ODOO_NIX_TOOLS_REPO=<fileset: version.txt, lib/odoo-presets.json, tests/fixtures/standards-*>`; `tests/support.py` falls back to the working tree two directories up, else skips | the suites read files outside the package |
| O3-14 | §5.1 the wrapper | `lib/standards/cli.nix` (`runCommand` + `makeWrapper`, `--suffix PATH` git and gh), `packages.odoo-nix`, `apps.odoo-nix`; `pyproject.toml` gains `[project.scripts]`, `package.nix` `mainProgram` and `pythonImportsCheck` `odoo_nix_tools.cli` (closes O1-2). `lib/init.nix` is untouched | odoo-init's use of the package is O6 |
| O3-15 | §1.2 the `^tests/fixtures/standards-` excludes | `.pre-commit-config.yaml`'s top-level `exclude` and `ruff.toml`'s `extend-exclude`; `ty.toml` already excludes `tests/fixtures` (closes O1-12) | the synced fixtures carry their own managed `.ruff.toml` and hooks (O4) |
| O3-16 | §2.3 `nixattrs.strip_nix_comments`, `nixattrs.flake_input_specs` | `engine.strip_nix_comments`, `engine.flake_input_specs` | `scaffold/nixattrs.py` is in the core's uncommitted stage-5 tree only; its `engine` re-exports both names, so the code works before and after |
| O3-17 | §7.3 `standards-conformance` | `base.standards.conformance` with the python3 package; it runs `conformance.check(PRODUCT)`, whose render part is a no-op until `product.fixtures` (O4), so it is the static part. `test_product` and `test_profiles` assert the static part too (closes O1-10) | — |
| O3-18 | §9 "`nix flake check` green" | as O1-14: green with the development override (`standards-unit` 92 tests on 3.11 and 3.14 with 2 CR1 skips, `standards-conformance`, `standards-version`, `nix flake check --no-build`) | — |

### O4 (managed files, retire rules, first opt-in, checks, fixtures)

Built and tested against the core's committed stage 5 (`pdn-standards-core` `feat/standards-core`, `96626c4`; stage 4
`86ef679` when the stage began, and green on both), which has CR2 and CR5 but not CR1's `Hooks.config_file`.

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O4-1 | §3.4 the stale-lock items are `checks` items | they are the lock handlers' own problem: `checks.ToolsLock` (`tools-uv-lock`, a `UvLockHandler`) and `checks.NodeLock` (`node-npm-lock`, an `NpmLockHandler`) return the same text from `lock_problem` (`tools_lock_problem`, `node_lock_problem` in `checks.py`). Equality, and `rendered ⊆ locked` only when `ctx.options["throwaway"]` (CR2 is in the core since stage 3) | as a lock problem the item carries the lock command: `--check` reports drift (exit 1), `--write` reruns `uv lock --project tools` / `npm install --package-lock-only …`, and `--write --offline` names the command instead of failing. A `checks` item could only report |
| O4-2 | §3.1 locks are command seeds (left when their module is off) | both lock handlers retract their lock once every module of the entry is off and was on (`engine.was_on`); `groups.ToolsPyproject` and `groups.PackageJson` delete their file when the merge leaves it empty; `TOOLS.extra` drops the seeded `fail_under` with tests off while it still equals `tests.initial-floor` | turning every tool module off (`minimal` after `recommended`) otherwise left an empty `package.json` (`{}`), a `tools/pyproject.toml` holding only `fail_under = 0` and orphan locks. A hand-raised `fail_under` stays the checkout's |
| O4-3 | §3.1 the `deps` group "when every module is off, the core's whole-key rule applies" | with every tool module off the group renders what `HEAD`'s modules rendered (`ctx.previous`), so the core deletes the list while it is still that | the current render is empty then, and the whole-key rule compares with the render |
| O4-4 | §3.1 `tool.coverage.report` as a table value | written as its two keys (`show_missing`, `skip_covered`); `tool.coverage.run` stays an exact table | a dict value is an exact table in the core, which would delete the `fail_under` seed beside them |
| O4-5 | §3.1 dev-shell, readme and ide entries; §3.4 notices | O4 ships the `whole`/`seed`/`toml-merge`/`json-merge`/lock entries only (§9): the flake inputs block, the `.gitignore` block, the README addons table and the `.vscode` files are O5's (fragment `40-ide.json` does not exist yet; `00-dev-shell.json` holds `.envrc`, `90-addons.json` the addons retire rule). The emptied-`.gitignore`-paragraph notice waits for that block; the unstaged-changes notice is dropped: CR5 is in the core (sync leaves such a file unstaged and says so) | — |
| O4-6 | §3.1 icons `src-icon` default `"templates/addon-icon.png"`; §7.1 example-org's `templates/addon-icon.png`; §9 the profile follow-up `templates/addon-icon.png` | default `"assets/addon-icon.png"` (schema and `recommended@2.3`); example-org's icon is `assets/addon-icon.png` | the core's `check_overrides` refuses (exit 2) any file under an org profile's `templates/` that is neither an overridable template nor an `[[extra-files]]` template, so an icon there broke every sync under the profile. The Avunu profile follow-up becomes `assets/addon-icon.png` |
| O4-7 | §7.1 `product.fixtures` from both fixture trees, built at import | `fixtures.FIXTURES = {"project": …}` read from `data/fixtures/project.json` (path → text; `config_file`; `table`), generated by `scripts/gen_fixture_data.py` from `tests/fixtures/standards-project` without its `[tool.odoo-nix]` table, plus the `example-org` locks; binary files (the icons) are left out. `test_fixtures_render` compares the shipped file with a fresh generation (the generator ships in the package build's source for that) | a `uv tool install` of the subdirectory has no `tests/fixtures`. The addons fixture joins once CR1 lands: under today's core its table in `nix/pyproject.toml` is not seen, so the conformance render part would fail on it |
| O4-8 | §7.2/§7.3 the addons fixture under every profile | `tests/support.py` `ADDONS_PRODUCT`: `PRODUCT` with `identity.config_file = "nix/pyproject.toml"` and a `load_checkout` reading it (`discover.load_checkout(root, product)`). The engine resolves with the checkout's root (core stage 2), so this stand-in for CR1's per-checkout choice syncs the addons fixture; `test_fixtures_render`, `test_checks` and `checks.standards-fixtures-addons` run through it. It is `PRODUCT` itself once the core has CR1 | the CLI (`odoo-nix sync` in an addon repository) still needs CR1; O3-1's skips stay for `profile show`/`config` |
| O4-9 | §7.1 the locks written by `nix run .#relock-standards-fixtures` | `scripts/relock_fixtures.py` (network): syncs each fixture under `recommended` and `example-org` and runs the two lock commands; `minimal` has no tools, so no locks. O6's app wraps the script | the app is O6 (§9) |
| O4-10 | §7.1 the addons fixture with a Dependabot local-region entry for 17.0 | the entry is a test edit (`test_dependabot_branches_and_local_region`), not in the tree. The fixture's `nix/pyproject.toml` blocks now list `odoo-addon-fixture_a`/`_b` (install set and module sources) | a filled region in the clean fixture is exit 2 under `minimal` (dependabot off: the file is retracted, and its region holds content). The blocks keep the packaging check clean under example-org |
| O4-11 | §7.2 `test_lock_checks`; `test_fixtures_render`'s zizmor and nested-config variants | `test_lock_checks` is `test_checks.LockChecks`; the zizmor and nested-config variants need prek and the linked tools, which are O6's `standards-prek-*` | — |
| O4-12 | §7.3 `standards-conformance = base.standards.conformance { … }` | a `scriptCheck` running the same `python -m standards_core.testing.conformance odoo_nix_tools.product:PRODUCT`, with git on `PATH` and `HOME` | the core helper runs without git, and the render part's throwaway checkouts need it ("EnvError: git is not on PATH"). Core follow-up: `tools = [ pkgs.git ]` in `lib.standards.conformance` |
| O4-13 | §3.5 templates; §6.4 callers | as listed, plus `github/workflows/_uses.j2` (the `uses` macro with the core `pin` fallback, and the App's `client-id`/`APP_PRIVATE_KEY` lines). The callers' inputs are the interface O7's reusable workflows take: `integration-branch`, `runs-on` (all), `test-timeout-minutes` and the App (test), `release-branch` and the App (release), `shape`, `auto-merge`, `auto-merge-policy`, `update-branches`, `merge-method` and the App (deps); a `ci.schedules.ci` cron is honoured as in frappe-nix. `release.yml` is live with `releases` when the checkout has a release branch (`when: branches.release`) | the reusable workflows are O7 |
| O4-14 | §3.3 `precommit.hooks(ctx)` | `precommit.hooks(data, modules, cfg, facts)` (`template_globals` passes them); the YAML is written by `precommit.hooks_yaml` / `Gen.hooks_yaml` (plain scalars when they read back as the same string, else double-quoted; lists as flow sequences), and `Gen` also has `editorconfig`, `checklog`, `prettier_config` and `pylint_sections` | quoting regular expressions is easier to get right, and to test (`test_precommit.Yaml`), in Python |
| O4-15 | §3.1 `.editorconfig` "+ a `[*.{nix,sh}]` `indent_size = 2` section" | that section also sets `indent_style = space` | OCA's first section, which sets the style, does not match `.nix` or `.sh` |
| O4-16 | §3.1 committed.toml | `allowed_scopes` only with `scopes = "addons"`; `convention = "odoo"` writes `style = "none"` without `allowed_types` | committed has no rule for Odoo's tags; `odoo-nix policy` checks them (O7) |
| O4-17 | §2.3 `shape_notice` | `discover._resolve` computes the notice from the checkout's own table | `derive` copies the discovered shape into `cfg`, which made every later discovery read it as explicit and drop the notice (an O3 bug, found by `test_checks.Notices`) |
| O4-18 | §3.4 `checks` items | `Item(path, "check", None, None, problem, DRIFT, module=…)`; the series-without-data refusal stays discovery's (`series_of`, exit 2) | — |
| O4-19 | §9 "`nix flake check` green" | as O1-14: green with the development override (`standards-unit` 164 tests on 3.11 and 3.14 with the 2 O3 CR1 skips, `standards-conformance` with the render part, `standards-version`, `standards-fixtures-{project,addons}`, `nix-lint`, `env-vars`, `shared-config`, `ci-pins`, `dependabot`, `nix flake check --no-build`) | — |

### O5 (sentinel blocks, the editor files, the addons-shape preflight)

Built and tested against the core's committed stage 6 (`pdn-standards-core` `feat/standards-core`, `d3a5e3c`; its
working tree's uncommitted stage-7 `ci` command is not in it), which has CR2, CR4 and CR5 but not CR1's
`Hooks.config_file`.

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O5-1 | §7.1 the project fixture's `flake.nix` with a hand-written `odoo-nix.url = "github:Avunu/odoo-nix";` | both fixtures' `flake.nix` write `odoo-nix.url = "github:Avunu/odoo-nix/release-2";` (the URL the block renders and §5.5's odoo-init templates will write), so the definition moves into the block silently. The differing hand-written URL (first opt-in: exit 2 with the diff, `--force`, then refused "outside the managed block" after opt-in) is tested on the four real flakes in `test_flake_block` | the conformance render part and `profile validate` sync `product.fixtures` without `--force`, and §7.1 wants every fixture clean under every profile; with the hand-written URL every fixture sync was exit 2 |
| O5-2 | §7.1 fixture trees | both fixtures gain a root `README.md`; `example-org` sets `readme.addons-table = true` | the README block needs its file to be the checkout's: on a checkout without one the block's `eof` anchor creates `README.md` holding only the block, and retracting the block (the core never deletes the file) leaves it empty. Every target has a root README. Core follow-up: a sentinel file sync created and the retraction leaves empty could go with its block |
| O5-3 | §3.1 ide `union.recommendations.ensure` = `["Odoo.odoo", "charliermarsh.ruff", "esbenp.prettier-vscode", "dbaeumer.vscode-eslint"]` | without `Odoo.odoo` | the core's jsonc retraction removes every `ensure` item, so with it turning `ide` off deleted the recommendation the dev shell seeds (`seed_extensions`), the `union` half of review item P3-d. The seed recommends it; `test_ide_real` asserts `set`/`seed` and `ensure`/`seed_extensions` share nothing |
| O5-4 | §3.4 notices: the `.gitignore` comment paragraphs `absorb` empties (until CR4); §8.2 "the two emptied comment paragraphs get a notice and are deleted in the `style:` commit" | no notice: core CR4 (stage 5) makes `absorb` take such a paragraph and its blank line (`test_blocks` asserts edi-addons' two go) | closes the CR4 fallback |
| O5-5 | §3.4 `preflight` order and cases | the shape's own files are checked first (no `flake.nix`; addons: no tracked `nix/pyproject.toml` with both foreign blocks), so an addon repository at `develop`'s shape hears the `odoo-init --addons` hint before anything about its table. New refusal: the file the core reads the table from (`checkout.extra["core_config"]`, `engine.config_file`) is not the shape's: "an addon repository keeps [tool.odoo-nix] in nix/pyproject.toml, and this odoo-nix-tools reads it from pyproject.toml only …: nothing was written". `discover._extra` is `discover.checkout_extra` | without CR1, `odoo-nix sync --write --standards …` in an opted-out addon repository passed preflight and created `[tool.odoo-nix]` in a new root `pyproject.toml` (preflight's own config-file check reads discovery's choice, `nix/pyproject.toml`, which agreed with the shape). Lifts itself once `hooks.config_file` is wired (CR1): the core then reads `nix/pyproject.toml` there |
| O5-6 | §7.2 `test_preflight_addons` "`--addons --standards` scaffolds then syncs (§5.5)" | a skipped case naming stage O6 | odoo-init's standards flags are O6 (§9) |
| O5-7 | §3.1 readme "`\| [name](name/README.md) \| summary \| license \|` rows from manifests, sorted" | a header row (`\| Addon \| Summary \| License \|`, `\| --- \| --- \| --- \|`), then one row per installable addon, sorted by name: the link is `<path>/README.md` or `README.rst` as tracked, `<path>/` without either; cells are one line with `\|` escaped (product filter `md_cell`). Discovery's addon facts gain `summary` (whitespace collapsed). The entry has `uses: ["readme.addons-table"]` and `overridable: true` (§3.5) | a Markdown table needs its header row to render; the path is the addon's (`custom/<name>` in a project). The root `README.md` is excluded from prettier (§8.2), so the table is not re-padded |
| O5-8 | §3.1 dev-shell inputs block | as written, with `uses: ["dev-shell.odoo-nix-url"]`; the core inserts the block before the `inputs` set's closing `};`, after the hand-written inputs (in an addon repository after `ocb` and the sources) | the design names no position; the core's `nix-attrset` anchor has one |
| O5-9 | §1.1 `tests/shapes/` | as listed, plus `shapes/gitignore/{project-b,project-a,edi-addons}.gitignore` and `shapes/README.md` (sources and commits); a new suite `test_blocks` (the `.gitignore` block on the shape files, the README table) besides §7.2's four. The flake shapes are left out of nix-lint (`flake.nix` `nixLintIgnore` and `nixFiles`) | the project flakes carry the unused `self` deadnix reports (§8.3), which they test: they would fail `checks.nix-lint` |
| O5-10 | §7.2 `test_flake_block` "`lock_problems` clean" | `engine.stale_inputs` over `fakes.flake_lock` of the synced flake is `[]` (and over the repository's own lock exactly `odoo-nix`, which phase A's `nix flake lock` moves), then `sync --check` exit 0 once the lock follows the flake | `lock_problems` itself skips `odoo-nix` under `ODOO_NIX_ALLOW_SKEW=1`, which every fixture sync needs |
| O5-11 | §5.4 `vscodeSettingsFile`/`vscodeExtensionsFile` read `seed`/`seed_extensions` | `ideData = lib.importJSON ../py/odoo_nix_tools/odoo_nix_tools/data/ide/vscode.json`; both files are `builtins.toJSON` of it. Their store paths are unchanged (`r6wayzkd…-odoo-nix-vscode-settings.json`, `l6wl87ax…-odoo-nix-vscode-extensions.json`, evaluated before and after on an addons-mode consumer), so no dev shell changes. `test_ide_real.Data.test_devenv_reads_the_same_file` skips in the package build, whose tree has no `modules/` | adding `modules/devenv.nix` to the build's fileset would rebuild the package on every module edit |
| O5-12 | §3.1 ide retraction "the file is never deleted" | as the core does it: a `.vscode/settings.json` sync created for `ide` (the addons fixture has none) is left as `{\n}\n`, its `extensions.json` with an empty `recommendations` array | core behaviour (jsonc `retract` removes an emptied object, not an emptied array, and keeps the file). Core follow-up, as O5-2 |
| O5-13 | §9 "`nix flake check` green" | as O1-14: green with the development override (`standards-unit` 194 tests on 3.11 and 3.14, 4 skips: the 2 O3 CR1 ones, O5-6, O5-11; `standards-conformance` with the render part; `standards-fixtures-{project,addons}`; `standards-version`; `nix-lint`, `env-vars`, `shared-config`, `dependabot`, `ci-pins`, `check-names`; `nix flake check --no-build`) | — |

### O6 (odoo-init's standards flags, the phase hooks, the dev-shell tools, the lint shell)

Built and tested against the core's committed stage 6 (`pdn-standards-core` `feat/standards-core`, `d3a5e3c`). The
branch moved to stage 7 (`7223ab4`) while this stage was built; under it `test_fixtures_render`'s conformance render
part fails ("module releases needs module commits" for the project fixture under `develop+series`), which is the
core-7 stage's (O7) to take up. The development override is therefore pinned by revision:
`--override-input python-devops-nix 'git+file:///…/pdn-standards-core?rev=d3a5e3c4f94c501c57f9a44db698339dc1e60f92'`.

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O6-1 | §5.5 "`--addons` … the scaffold pipeline runs first (it writes the addons-mode `flake.nix`, `.odoo-series`, `nix/pyproject.toml` and the first lock)"; §3.4's hint "`odoo-init --addons`" | odoo-init had no `--addons`: `lib/odoo_nix_cli/init/addons.py` adds it. It writes `templates/addons` (`flake.nix`, `nix/pyproject.toml`, `.envrc`, `.gitignore` merged as migrate merges it) where missing, `.odoo-series` (series from `--version`, `.odoo-series`, a `^\d+\.0$` branch checked out, or the root addons' manifests; exit 5 otherwise), stages only what it wrote, then `nix run --no-pure-eval .#relock` (skipped under `--skip-lock`; a failure is a warning). A `flake.nix`/`nix/pyproject.toml` that is not odoo-nix's is exit 4, or with `--force` kept and odoo-nix's written beside it (`<file>.odoo-nix`, nothing locked); an odoo-nix project is exit 6; `--addons --init` is a usage error. odoo-init's config gains `addonsTemplate` and `odooNixMajor` (`@MAJOR@`, from `version.txt`); `template.render` takes the template | the precondition of §8.2 and the preflight hint name a command that did not exist. `docs/reference/scaffolder.md` and `docs/scaffolding/addons-repository.md` describe it |
| O6-2 | §7.2 `test_preflight_addons` "`--addons --standards` scaffolds then syncs" | in `tests/odoo-init.sh` (`checks.scaffold`): the scaffold runs and is staged, then the sync refuses with O5-5's CR1 text (exit 2, no root `pyproject.toml`). The unit case stays skipped, naming the scaffold check | `odoo_nix_cli` is not in the package build. Closes with CR1: the case then expects exit 0 and the table in `nix/pyproject.toml` |
| O6-3 | §5.5 `args.py` | as written, plus: `--only` repeatable (`--only a,b --only=c`); a hidden `--throwaway` (the core's `passthrough(init=True)` emits it on a re-exec); `InitArgs.sync_argv()` builds `odoo-nix sync`'s command line; a TARGET_DIR is entered before the sync. The flags are listed in `--help` (`--phase` and `--throwaway` are not) | — |
| O6-4 | §2.5 `reexec_argv`/`reentry_argv` with "owner, repo and rev from flake.lock's odoo-nix node (`flakelock.engine_rev`)" | `bootstrap.engine_ref(root)` reads the node with `flakelock.locked_pin`: `github:<owner>/<repo>/<rev>` (`?host=` off github.com), `git+<url>?rev=<rev>` for a `git` node; the engine's `ODOO_NIX_URL_OVERRIDE` (self-tests) wins. Without a locked engine (no lock, a `path:` node) the core's defaults stand (`nix run --no-pure-eval .#odoo-init`). `phase_a_before` says the notice there too, and otherwise runs `nix run <engine>#bootstrap -- <root>` as a checked step (exit 3 when it fails) | `test_bootstrap` (fake `nix`, real git, a gitlink left uninitialized) |
| O6-5 | §2.5 / §9 "skew" | the core's three rows (stage 6) need no product code: `test_skew` shows a synced project clean without `ODOO_NIX_ALLOW_SKEW` (its callers name the lock's rev and this version through `caller_stem = "odoo-*"`), exit 3 for another `--expect-rev` and for a caller moved by hand. odoo-init passes `--expect-rev` on | — |
| O6-6 | §5.3 maintainer-tools "setuptools-scm … `SETUPTOOLS_SCM_PRETEND_VERSION = "0.1.dev1"`" | it builds with hatchling + hatch-vcs (its `[build-system]`), which uv2nix does not supply for a `git` source: the override adds both (`resolveBuildSystem`) and pretends the version uv recorded (`old.version`, `0.1.dev1264+g31bdbd8e4`) | the build failed with `No module named 'hatchling'` |
| O6-7 | §5.3 `toolsEnv` | also `venvIgnoreCollisions = [ "requirements/*" ]` | pylint-odoo and oca-odoo-pre-commit-hooks both install a top-level `requirements/requirements.txt` with different contents |
| O6-8 | §5.3 `lockAudit { rootPyproject = toolsDir + "/pyproject.toml"; … }` | `rootPyproject` left to its default (the core's `lockAudit` takes the parsed table, which the default reads from `workspaceRoot`), `lock = "tools/uv.lock"` | — |
| O6-9 | §5.3 sdist build dependencies: a second lock step `odoo-nix-build-deps update tools/pyproject.toml tools/uv.lock` | not added | no tools lock holds an sdist-only package (every locked tool has a wheel; maintainer-tools is a `git` source, O6-6). Closes when a pinned tool needs it |
| O6-10 | §5.3 `coverage = (setFor odooPython).coverage or null` | `null` unless the lock has `coverage` (the tests module) | — |
| O6-11 | §5.2 "`tools.prek` is `tools.toolsEnv`'s `bin/prek`" | a one-link package (`bin/prek` → the venv's), so the shell's PATH gets prek, not the whole venv's `bin/`. Finding: nixpkgs' prek links aws-lc's `libcrypto.so` by soname, and the dev shell's `LD_LIBRARY_PATH` (OpenSSL's) shadows it: `symbol lookup error … EVP_aead_aes_128_gcm_tls13` inside an odoo-nix shell. The lock's prek (a wheel) links no libcrypto. The `pkgs.prek` fallback is used only without a tools lock, which no profile with a managed `.pre-commit-config.yaml` has | — |
| O6-12 | §5.2 the hook check `grep -qF "${tools.prek}" .git/hooks/pre-commit` | greps the resolved path (`readlink -f`), with the hook's path from `git rev-parse --git-path hooks/pre-commit` | prek records its `current_exe` (symlinks resolved), not the store path the shell names; a worktree's `.git` is a file |
| O6-13 | §5.2 `shell.nix { pkgs, lib, cfg, addonsMode, odooNix, odooInit, tools }` | `{ pkgs, lib, workspaceRoot, configFile, addonsMode, odooNix, odooInit, tools }`, returning also `lintShell`, `links`, `tools`, `nixTools`, `nixToolsEnv`. Each link is made a GC root (`nix-store --add-root --indirect --realise`) when it changes and `nix-store` is on PATH; a real directory in its place is left alone with ideSetup's warning | one function for the dev shell, `lib.standards.lintShell` and the checks (`flake.nix` `standardsShellFor`, which can read the tools from another directory: `toolsRoot`) |
| O6-14 | §5.4 the dev shell's config file `<addons.lockDir>/pyproject.toml` | always `nix/pyproject.toml` in addons mode; opted in with another `lockDir` throws §5.4's sentence | the table's place does not follow `lockDir` (§3.4) |
| O6-15 | §5.4 "The dev shell passes `standards.tools.coverage` when `tests` is on" | opted in with a lock that has coverage: the lock's; otherwise nixpkgs' (O2-4), never `null` | `odoo test --coverage` keeps working in every shell, and a shell that has not opted in keeps O2's raw odoo-bin |
| O6-16 | §5.2 "A shell that has not opted in is byte for byte today's" | verified against O5 (`022eec0`) by evaluating both trees: the raw odoo-bin, the Python environments and every package but one are identical; `odoo-nix-cli` differs (lib/cli-package.nix copies all of `lib/odoo_nix_cli`, and odoo-init's code changed), and with it the dev CLI, `odoo ui` and the shell entry that name them. That is a change of the shared package, not of the standards' additions | as O2-5 |
| O6-17 | §7.3 `standards-shell-eval` (one check, drv path equality) | six eval checks, `standards-shell-eval-{project-unchanged,addons-unchanged,opted-in,addons-opted-in,node-excludes,lint-shell}` (Linux). "Unchanged" compares a non-opted-in shell with the internal option `standardsShell = false` (no additions at all) by what it is made of: its packages' drv paths, `enterShell`, `env`, the dev CLI's drv path, the apps', dev shells' and packages' names. New fixture `tests/fixtures/standards-shell-addons` (an opted-in addon repository with a root `package.json`); the opted-in project's entry is read from `shell.nix` itself | pure evaluation has no working directory, which devenv's shell derivation reads; `standards-project` has no `uv.lock`, which the whole entry would need |
| O6-18 | §7.3 `standards-prek-*` "`prek run --all-files -c .pre-commit-config.yaml` exits 0 (managed files are clean under their own hooks)" | `prek run -c .pre-commit-config.yaml --files <what sync wrote>`; the nested config is checked with a planted file under the addon; zizmor with `--all-files` | under example-org the fixtures' own addons break the profile's addon rules (`manifest-required-author` "Example Org", LGPL-3 not allowed, no `website`): the adopter's code, which the gate reports, not the managed files. The fixture's `.vscode/extensions.json` (no final newline on purpose, §7.1) gets one before the sync, as the adoption's `style:` commit would |
| O6-19 | §7.1 the locks directory | each profile's directory also holds the manifests the locks were made from (`tools/pyproject.toml`, `package.json`), so `tools.nix` builds the tools from it without import-from-derivation; the tests and checks copy only the locks (`support.LOCK_FILES`); `relock_fixtures.py` writes both. The manifests were copied from offline syncs, the locks were not regenerated | the synced fixture is a build output, which evaluation cannot read |
| O6-20 | — | found by the prek and prettier checks and fixed: `release.yml`'s `workflow_run` trigger (zizmor `dangerous-triggers`, high) carries `# zizmor: ignore[dangerous-triggers]` and the reason (ci's runs on the integration branch only; odoo-release.yml checks out that branch); example-org's `SECURITY.md.j2` starts with a blank line (prettier puts one after the Markdown header comment; core follow-up: the `md` header could end with one); the project fixture's `flake.nix` drops the unused `self` (deadnix), as the template does, and `data/fixtures/project.json` is regenerated | — |
| O6-21 | §7.3 `standards-prettier-stable` "every managed JSON/YAML/JS" | what sync wrote, minus `.vscode/` (deviation `prettier-vscode`), `eslint.config.cjs` and `prettier.config.cjs` (OCA's exclude keeps prettier off them; prettier would rewrite OCA's `eslint.config.cjs`), and the locks | the hook never formats them |
| O6-22 | §5.5 `templates-nix-lint` | `sed` fills the placeholders with sample values; `nixfmt --check`, `statix check --config statix.toml`, `deadnix --fail`. Note: a project scaffolded now follows `github:Avunu/odoo-nix/release-2`, which must exist on GitHub before this odoo-init is released (O9) | — |
| O6-23 | §5.1 `lib/init.nix` | `lib/standards/packages.nix` builds odoo-nix-tools, the `odoo-nix` wrapper and odoo-init once, for `flake.nix` and `modules/devenv.nix` alike; odoo-init's interpreter carries odoo-nix-tools (built with its test suite, so the first opted-in shell builds it once) | — |
| O6-24 | §9 `relock-standards-fixtures` | `tests/standards/relock-fixtures.nix`: in the work tree, `relock_fixtures.py` then `gen_fixture_data.py`, with the locked core and nixpkgs' uv and node. Not run in this stage (network) | — |
| O6-25 | §9 "`nix flake check` green" | as O1-14, with the override pinned to core stage 6: `standards-unit` (210 tests on 3.11 and 3.14, 4 skips: the 2 O3 CR1 ones, O6-2, O5-11), `standards-conformance`, `standards-fixtures-{project,addons}`, `standards-prek-{project,addons}`, `standards-prettier-stable`, `standards-shell-eval-*`, `templates-nix-lint`, `standards-version`, `scaffold`, `odoo-init-unit`, `nix-lint`, `env-vars`, `check-names`, `shared-config`, `command-flags`, `dependabot`, `ci-pins`, `option-paths`, `config-blocks`, `workflows`, `tui`, `relock`, `bootstrap`, `raw-odoo`, `odoo-test-unit`, `pr-policy`, `addons-mode-shell`; `nix flake check --no-build` | — |

### O7 (release, policy, decision table, gates, checks, ratchet, reusable workflows)

Built and tested against the core's committed stage 7 (`pdn-standards-core` `feat/standards-core`, `7223ab4`: CI
steps, `policy`, conventional commits, the CI conformance part, CR6), which still has no CR1 `Hooks.config_file`. The
core's stage 8 (repo policy commands, `3874a69`) is committed since, but O7 stays pinned to stage 7 by revision:
`--override-input python-devops-nix 'git+file:///…/pdn-standards-core?rev=7223ab496fc347d7a7b38387f8c4ccd92769b3dd'`.
Under `3874a69` only `test_cli`'s help snapshot fails, because stage 8 adds `repo`; O8 regenerates it.

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O7-1 | §11.4 (core) the CI part over `product.fixtures` | O6's open failure ("module releases needs module commits" for the project fixture under `develop+series`) is the core's `_bump_fixture`, which turns on `releases` and `ci` but not what odoo-nix's `releases` needs: **CR8** (§10). Fallback: the shipped project fixture's table is `commits.enable = true` (`scripts/gen_fixture_data.py` `TABLE`, `data/fixtures/project.json` regenerated), so the render and CI parts render committed.toml and the pr-policy caller under every profile | closes with CR8: `TABLE` goes back to `""` |
| O7-2 | §6.4 the reusable workflows use `Avunu/python-devops-nix/.github/actions/standards-*@<sha>` (`standards-install`, `standards-pr-policy`, `standards-release-ff`, `standards-deps-automerge`, `standards-update-branches`) | the steps are inline, and the CLI is the locked engine's Nix build: `nix build <engine>#odoo-nix` (from flake.lock's `odoo-nix` node: `github:<owner>/<repo>/<rev>` or `git+<url>?rev=<rev>`) on `$GITHUB_PATH`, `ODOO_NIX_EXPECT_REV` exported. `odoo-lint.yml` runs `lib.standards.lintShell` as written | the composite actions are core stage 9 and do not exist yet; `standards-install`'s `uv tool install` of the git spec cannot resolve the unpublished core either (O1-1). Every job already needs Nix (committed, the relock, the lint shell), and the engine's own build has no skew. O9 (`bump-base`) decides whether to swap the actions in |
| O7-3 | §6.4 pr-policy: committed by `nix profile install github:<o>/<r>/<rev>#committed` | `nix build --no-link --print-out-paths <engine>#committed` onto `$GITHUB_PATH` | a self-hosted runner's profile outlives the job |
| O7-4 | §6.4 `odoo-test.yml` / `project-update`: "checkout with submodules, using the App token" | checkout without submodules; the App token is scoped to this repository and the same-owner repositories `.gitmodules` names (`repositories:`); then `git submodule sync/update --init --recursive` authenticated by a header given to that step's git only (`GIT_CONFIG_COUNT`/`KEY_0`/`VALUE_0`, masked) | zizmor's `github-app` audit (high) refuses an owner-wide token (`owner:` without `repositories:`), and a token for every repository of the installation is more than the job needs. A nested submodule of another private repository would need its own entry: none of the targets has one |
| O7-5 | §6.4 `odoo-release.yml` | as written (`ref: <integration>`, `client-id`, contents + workflows write, `ci bump --base origin/<series> --push`, then `ci fast-forward --wait-checks 900`), plus: the job is skipped for a `workflow_run` whose ci run did not succeed; without the App it is exit 1 naming `ci.github-app` and `repo doctor`; `release-branch` must equal `odoo-nix config series`; the bump commit is the App's bot's (`<app-slug>[bot]`, id from `gh api /users/<slug>%5Bbot%5D`); the push authenticates by the same step-local header as O7-4, never persisted (`persist-credentials: false`); a rejected non-fast-forward push is exit 0 in the core (CR6, stage 7) | zizmor's `artipacked` audit flags persisted credentials; the rest is what the flow needs to be green on the targets |
| O7-6 | §6.4 `odoo-deps.yml` "`relock-plan`, `relock-push`, `automerge`, `update-branches` (addons); `project-update` (projects)" | `relock-plan`/`relock-push` and `project-update` per shape as written; `automerge` and `update-branches` run in both shapes (a project's Dependabot github-actions PRs get the table's verdict too; its nix PRs are not relocked here, so their `relock` verdict leaves them to a person until `project-update` relocks). The core's `ci sweep` is not wired (the odoo callers have no relock schedule to tell it apart from) | the callers render `deps.yml` in both shapes with the same inputs (O4-13) |
| O7-7 | §6.1 `Step(name, module: str \| None, run)`, `StepResult(status, reason, seconds)` | `Step(name, modules: tuple[str, ...], run)` (any of them on runs the step; `()` always) and `StepResult` also records `command` (the command lines run) and `exit` (the code that failed it). The report (`data/schema/gate-report.schema.json`, validated with the core's `schema.Validator` in `test_gate`): `schema`, `gate`, `status` (`passed`/`failed`/`invalid`/`error`), `exit`, `odoo_nix` (`version`, `expect_rev`), `steps[]` (`name`, `modules`, `status`, `reason`, `seconds`, `command`, `exit`) | the `prek` step is turned on by any of eight modules |
| O7-8 | §6.1 "exit 1 when any failed, 2 for configuration, 3 for environment" | only odoo-nix's own codes pass a 2 or a 3 on, the highest first: the in-process `odoo-nix …` sub-steps and the gate's own `EnvError`/`ConfigError` (a missing `tools/.venv/bin/<tool>`, a command not on PATH, a base branch not fetched, an unreadable `odoo.conf`). An external tool (prek, coverage, checklog-odoo, manifestoo, odoo, initdb, pg_ctl) that exits non-zero is a failed step, exit 1, its own code kept in the step's `exit` (`StepResult.internal`, not in the report, tells them apart): coverage exits 2 when the total is under `fail_under`, which is a failure, not the configuration (`test_gate` `test_coverage_under_fail_under_is_a_failure`, `test_an_external_tools_2_or_3_is_a_failure`). The `odoo-nix …` sub-steps (`sync --check`, `check …`, `ratchet …`) run in-process through the core's CLI from the checkout's root; external tools as subprocesses; tests fake both through one runner | the wrapped `odoo-nix`'s interpreter cannot be re-run as `python -m odoo_nix_tools` reliably (the Nix wrapper puts the package on `sys.path` in the script) |
| O7-9 | §6.1.2 `gate test` | `odoo [--db-host <sock> --db-user odoo] test <m1,m2,…> --fresh-db --coverage tools/pyproject.toml --log .odoo-nix/test/odoo.log` (the list explicit, as §6.1.2 says, never `--all`); the CI cluster is `initdb -U odoo --auth=trust` into `.odoo-nix/test/pg` and `pg_ctl -o "-k <sock> -c listen_addresses=''" -w start`, the socket in a short temp directory (a socket path is at most 107 bytes), stopped after the last step even when one failed; `coverage combine`, `report` and `xml` all take `--rcfile=tools/pyproject.toml`; manifestoo's addons path is `[options] addons_path` of `$ODOO_RC`, else `./odoo.conf`; `COVERAGE_FILE` is exported as `<root>/.odoo-nix/coverage/.coverage` unless already set. `test_gate.AgreesWithOdooTestAll` compares `gate.tested` with `lib/odoo_nix_cli/testrun.all_modules` (loaded by path) on both fixtures | the dev shell's `odoo` takes `--db-host`/`--db-user` before the subcommand |
| O7-10 | §6.3 `ratchet coverage --raise` "after a coverage run" | `--total PCT` gives the measured total; without it `tools/.venv/bin/coverage report --rcfile=tools/pyproject.toml --format=total --precision=2`, read as the first stdout line that is a number whatever the exit code (under `fail_under` coverage prints the total, then `Coverage failure: …`, and exits 2; `--raise` then leaves the floor as it is). R1 compares as numbers (a missing `fail_under` is 0); R2 reads `[[tool.odoo-nix.untested]]` from the shape's config file (`discover.config_file`) at the work tree and at the base, so it works on an addon repository before CR1 | testability; a scheduled job that has the number passes it |
| O7-11 | §6.2 `check icons --fix` "flags checked against the pinned maintainer-tools at stage O7" | checked against maintainer-tools `0.1.dev1264+g31bdbd8e4` (`tools/gen_addon_icon.py`): `--addon-dir` (repeatable), `--addons-dir`, `--src-icon`, `--commit/--no-commit`, and it skips an addon whose `icon.png` or `icon.svg` exists. So `--fix` adds missing icons only (`--no-commit`, `--src-icon=<org profile dir>/<icons.src-icon>`, one `--addon-dir` per addon, never a default directory), stages them (discovery reads tracked files), and a wrong icon stays reported. A built-in profile, or an org profile without the file, is exit 2 | — |
| O7-12 | §6.2 `check manifests` / `check icons` | an icon problem is reported against `<addon>/__manifest__.py` (as §6.2's `--format github` says; a directory gets no annotation in the GitHub UI), and `--fix` takes the addon directory from it. `check manifests`: per installable addon; `.odoo-series` is compared only when the file exists; the integration-branch row only for a `^\d+\.0$` branch | — |
| O7-13 | §7.2 `test_policy`: "a hand version edit in a PR to develop under post-merge-bump" | `policy.pr_checks` compares each changed `__manifest__.py`'s version at the merge-base of the base branch and the head (not the base's tip, which a bump may have moved since), only when `releases` is on, its branching's flow is `post-merge-bump` and the base is the integration branch. A new addon, another manifest key, a stacked base, `trunk` and releases off pass | — |
| O7-14 | §2.8 rows 1-2 "names `$engine`" / "names `Avunu/python-devops-nix/*`" | row 1 names `$engine` and `Avunu/odoo-nix/*`; `odoo-deps.yml` passes `--engine-repo` as the locked `odoo-nix` node's `<owner>/<repo>` (a `git` node: from a `github.com` URL, else empty, and the core leaves `$engine` out); row 2 `Avunu/python-devops-nix` and `Avunu/python-devops-nix/*` | Dependabot names a reusable workflow or composite action `<owner>/<repo>` or `<owner>/<repo>/<path>`, and the core expands `$engine` only as a whole name |
| O7-15 | §6.4 odoo-nix's own `pr-policy.yml` on `odoo-nix policy --pr --major-free` | this tree's `nix build .#odoo-nix .#committed`, then `odoo-nix policy --pr --major-free --base-branch main`. lib/pr_policy.py's cases moved to `test_policy.MajorFree` (the real committed and committed.toml: `lib/standards/package.nix` gains `committed` in `nativeCheckInputs`, and `repoFiles` gains `committed.toml` and `lib/odoo_nix_cli/testrun.py`). Texts are the core's ("a odoo-nix major is made only with a `Release-As: <N>.0.0` footer") | the core's `--major-free` mode is lib/pr_policy.py's rules; `uv tool install` of the package cannot resolve the unpublished core (O1-1) |
| O7-16 | §1.1 `tests/shapes/icons/{ok-128.png, wide-200x100.png, heavy-150k.png}` | made by `tests/support.py` (`png`, `ICONS`: flat 128×128, flat 200×100, 224×224 noise of about 150 kB), not kept as files | no binary in the tree for three synthetic images |
| O7-17 | §7.2 suites | as listed, plus `test_verdict` (each decision-table row through the core's `decide`, and the `all` policy); `test_release` also runs `odoo-nix ci bump` end to end on the addons fixture (levels per addon, exempt paths, `!`, a hand edit, `--dry-run`) and asserts `modules.schema.json`'s `releases.version-scheme` enum is `["semver", *version_schemes]` (O3-2's spelled-out enum, now equal to the composed one); `tests/snapshots/help.txt` regenerated (core stage 7 adds `ci` and `policy`) | — |
| O7-18 | §7.3 `workflows` (extended) "actionlint + zizmor over `tests/fixtures/standards-*/.github` after sync" | `tests/standards/fixtures.nix` `workflowsScript`, run by `checks.workflows` after odoo-nix's own `.github`: each fixture synced under example-org, zizmor over its `.github`, then its callers rewritten to `./.github/workflows/odoo-*.yml` with this tree's reusable workflows copied in, and actionlint, which then checks every caller's inputs and secrets against the workflow it calls (verified: an undefined input fails it) | a caller that names an input the reusable workflow lacks would otherwise pass every check and fail only on GitHub |
| O7-19 | §9 "`nix flake check` green" | as O1-14, with the override pinned to core stage 7: `standards-unit` (296 tests on 3.11 and 3.14, 4 skips: the 2 O3 CR1 ones, O6-2, O5-11), `standards-conformance` (static, render and CI parts), `standards-fixtures-{project,addons}`, `standards-prek-{project,addons}`, `standards-prettier-stable`, `standards-shell-eval-*`, `templates-nix-lint`, `standards-version`, `workflows`, `scaffold`, `odoo-init-unit`, `odoo-test-unit`, `nix-lint`, `env-vars`, `check-names`, `shared-config`, `command-flags`, `dependabot`, `ci-pins`, `option-paths`, `config-blocks`, `tui`, `relock`, `relock-stale-lock`, `bootstrap`, `bootstrap-lock-*`, `raw-odoo`, `addons-mode-shell`; `nix flake check --no-build`. `checks.pr-policy` is gone with lib/pr_policy.py | — |

### O8 (fleet hooks, audit and doctor rows, fleet-audit.yml)

Built and tested against the core's committed stage 8 (`pdn-standards-core` `feat/standards-core`, `3874a69`: the
`repo` commands `targets`, `apply`, `audit`, `doctor`, `rollout`, and `common/repo_policy.py`), pinned by revision:
`--override-input python-devops-nix 'git+file:///…/pdn-standards-core?rev=3874a69b55d66faf93518efbd35ddb0f8b21efd6'`.
The unit suites are also green on the core's stage 9 (`cf07670`), whose library changes (`"<command>:summary"` help
keys, `testing/pins.py`) leave odoo-nix's help unchanged. Stage 8 has CR3 and `config.resolve(root=…)` but still no
CR1 `Hooks.config_file`.

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O8-1 | §2.2 `repo_policy_values`: "shape project: `integration_bypass = []` (CR3 fallback)" | kept, though CR3 landed in core stage 8 (`repo_policy.values` renders the bypass only with a non-empty release branch, so a project's `""` already gives `[]`) | the override still holds when a caller passes a project a release branch (`test_fleet.RepoPolicyValues.test_through_the_core_values`), and costs nothing. It can go with a §2.2 text change once CR3 is in the published core |
| O8-2 | §2.2 the addons override `release_pattern = refs/heads/<series>`, `release_label = <series>` | given when `cfg["shape"] == "addons"`, `releases.branching == "develop+series"` and `cfg["series"]` is set (derive fills it from the checkout); otherwise the core's values (`refs/heads/*.0`) stay. A repository that has not opted in has no `series` in its configuration (no checkout to derive it from), but only `--phase provisional` applies to it, which renders no release ruleset | the hook gets `cfg`, `modules` and `gates`, not the facts |
| O8-3 | §2.7 `fleet_table` returns `entry["shape"]` and `entry.get("integration_branch") or entry["branches"][0]` | each key only when the entry has it: `repo apply <r> --profile <p>` without a fleet entry passes `{}` (the core sets `integration-branch` from the entry itself too) | a `KeyError` there would be exit 3 for an entry-less target |
| O8-4 | §2.7 A12 (module `releases`) | the series is `.odoo-series` in the clone, else the resolved `series`; a project is `n/a` (it inherits `releases`, but has no series branch); without fleet entry `branches` (`repo audit --repo <r>` with no `--fleet`) the fleet half is `unknown`; the Dependabot half only with `dependabot` on: `target-branches` (derive's default `[integration]`) must list the integration branch, and no entry may match the release ruleset's pattern (`fnmatch` of `refs/heads/<branch>` against `repo_policy.values(…, release_branch=…)["release_pattern"]`) whenever the checkout has a release branch, whether or not `repo-policy` is on (the series branch is moved only by the release automation either way). Any red half is red, naming each problem | the design names the checks, not their edge cases |
| O8-5 | §2.7 A13 (module `ci`): "every submodule pins `branch = <series>`; projects; n/a for addons" | from discovery's `submodules` facts (`.gitmodules`, gitlink or not); `n/a` for an addon repository and for a project without submodules; red lists `path (branch)` for each one off the series, `(no branch)` when unset | — |
| O8-6 | §2.7 `doctor_rows` | rows (module `releases`) when `releases` is on, its branching's flow is `post-merge-bump` and the checkout has a release branch (an addon repository under develop+series): `Actions variable <app-id>` and `Actions secret <private-key>`, each looked up on the repository, then in `repos/{r}/actions/organization-{variables,secrets}` (`unknown` when GitHub refuses to say); a blank `ci.github-app.app-id`/`private-key` is its own `missing` row; `repo-policy.release-bypass` `ok` only as `integration:<digits>`, else `missing`, its `where` saying the numeric id comes from the App's settings page and is not the client ID the variable holds. The notice for a project is given when `ci` is on, `ci.project-update` is not `""` and `ci.github-app` is incomplete | the core's own release rows (Actions may create pull requests, the bypass actor may fast-forward) stay beside these |
| O8-7 | §6.4 `fleet-audit.yml`: `standards-install`, then `standards-fleet-audit` | the steps are inline, as O7-2: the profile repository's checkout, Nix, `odoo-nix` built from its flake.lock's `odoo-nix` node, `gh`, `git` and `uv` from that odoo-nix's nixpkgs (`nix build --inputs-from <engine> nixpkgs#<tool>`), then `odoo-nix repo audit --all --fleet <fleet> --against <against> --format md --out $RUNNER_TEMP/scorecard.md [--issue --issue-repo <issue-repo>]` with `GH_TOKEN` = `secrets.AUDIT_TOKEN` (else the job token, with a notice) and `ODOO_NIX_ISSUE_TOKEN` = the job token, the scorecard appended to the job summary; the job's exit is the audit's. Inputs `fleet` (`fleet.json`), `issue-repo`, `against`, `runs-on`; secret `AUDIT_TOKEN`; job permissions `contents: read`, `issues: write`. A caller is in the file's header | core stage 9's `standards-fleet-audit` exists now, but `standards-install`'s `uv tool install` of the git spec still cannot resolve the unpublished core (O1-1); O9 (`bump-base`) decides whether to swap the actions in |
| O8-8 | core §7.4 A4/A9 run `sync --check` from the tools each checkout pins | unchanged (no `hooks.tool_spec`, which §2.1 does not list): `uv tool run --from <engine.install_spec at the locked rev>`. Until the core is published (O1-1) that spec does not resolve, so on GitHub A4 and A9 read `unknown` ("sync --check gave no report") | closes with the published core |
| O8-9 | §2.7, §9 the fleet commands on addon repositories | without CR1, `PRODUCT` reads `[tool.odoo-nix]` from the root `pyproject.toml` only, so it sees an addon repository as not opted in: `repo apply` takes the fleet entry's app layer (`fleet_table`) and the fleet's profile, and only `--phase provisional` applies (`--phase full` is the core's exit 2 "no table yet"); `repo audit` rows read "not opted in"; `repo doctor` refuses it. `test_fleet` runs the opted-in addons cases through `support.ADDONS_PRODUCT` (the CR1 stand-in, O4-8) and the provisional path through `PRODUCT` | closes with CR1 |
| O8-10 | §7.2 `test_fleet`; §9 "`repo apply --dry-run` on the example-org fixture under `FakeGitHub`" | `tests/test_fleet.py` (33 tests): the entry schema through the composed fleet schema (`branches`, `integration_branch` optional, `shape`/`branches`/`private` required, the draft's `series_branches` refused); `fleet_table`, also through `targets.resolve_profile`; `repo_policy_values`, alone and through `repo_policy.values`; A12/A13 through `repo audit --format json` (green, each red case, `unknown` without a fleet entry, `n/a` by shape and by module); the doctor rows through `repo doctor <owner/repo>` (repository and organisation variables and secrets, a 403, the bypass, a blank App, a project's notice); `repo apply --dry-run` on both fixtures under example-org (rulesets posted, a repository on the old `*.0`/no-bypass rulesets gets the two `PUT`s it needs and its hand-made ruleset listed, a project's integration ruleset without bypass and no release ruleset) and on a not-opted-in addon repository from a fleet file. Every case has `targets.clone` and `targets.fetch_profile` replaced and `audit.run_tool` faked; no case writes to the fake GitHub in a dry run. `tests/snapshots/help.txt` regenerated (core stage 8 adds `repo`) | — |
| O8-11 | §9 "`nix flake check` green" | as O1-14, with the override pinned to core stage 8: `standards-unit` (329 tests on 3.11 and 3.14, the same 4 skips as O7), `standards-conformance`, `standards-fixtures-{project,addons}`, `standards-prek-{project,addons}`, `standards-prettier-stable`, `standards-shell-eval-*`, `templates-nix-lint`, `standards-version`, `workflows` (actionlint and zizmor now over `fleet-audit.yml` too), `scaffold`, `odoo-init-unit`, `odoo-test-unit`, `odoo-test-ci-18`, `nix-lint`, `env-vars`, `check-names`, `shared-config`, `command-flags`, `dependabot`, `ci-pins`, `option-paths`, `config-blocks`, `tui`, `relock`, `relock-stale-lock`, `bootstrap`, `bootstrap-lock-*`, `raw-odoo`, `addons-mode-shell`; `nix flake check --no-build`. The development suite (`uv run --no-project --with-editable …/pdn-standards-core/standards`) is green on core stages 8 and 9 | — |

### O9 (pins at one commit, the stage-10 follow-ups, composite actions, docs, release plumbing)

Built and tested against the core's stage 10 (`2a96bf1b0e5006cf738e8dd16a5604e8dba8333a`, `feat/standards-core`),
which is public on github.com/Avunu/python-devops-nix (draft PR #58, not merged, not released). Every pin names that
commit and no local override is left: `flake.nix` keeps `url = "github:Avunu/python-devops-nix"`, and `flake.lock`,
the `standards-core` URL, `.github/**` and the dev `uv.lock` carry no `path:`/`git+file:` source. The release (2.3)
is not part of this stage's work: no tag, no version bump, `version.txt` and the release-please manifest stay 2.2.0.

| # | Design text | As implemented | Why / closes |
|---|---|---|---|
| O9-1 | §9 O9 "composite-action and `standards-core` pins at one sha (`bump-base`)"; core §10.3 "the product's `bump-base` rewrites all three, plus the dev `uv.lock`" | `apps.bump-base` (`lib/standards/bump-base.nix`, `lib/standards/bump_base.py`): `nix run .#bump-base -- REV [COMMENT]`, REV a 40-hex commit or a tag or branch of Avunu/python-devops-nix (`git ls-remote`, an annotated tag's peeled commit first). It runs `nix flake lock --override-input python-devops-nix github:Avunu/python-devops-nix/<sha>` (the lock's `original` stays flake.nix's ref-less `{owner, repo, type}`, so a later `nix flake lock` keeps the commit; verified), rewrites the `standards-core @ git+…@<sha>` line and every non-comment `Avunu/python-devops-nix/…@<sha>` in `.github/**` with COMMENT as its version comment (`ci-pins` needs one), then `uv lock --project py/odoo_nix_tools --upgrade-package standards-core`. Run once: flake.lock `c07df3e` → `2a96bf1`; pyproject `97f7b5e` → `2a96bf1`; `autofix.yml`/`check.yml` (`65cb6ea`, a `ci/pr-feedback` commit on no branch of the core's main line) and `dependabot-auto-merge.yml` (`0c9a3a0`) → `2a96bf1`, where the same actions and workflows exist (pre-commit-autofix's prek-action moves 3.0.2 → 3.1.0), comment `python-devops-nix#58 (feat/standards-core, unreleased)` | closes O1-1, O1-14 (and the "with the development override" of every later stage's green line) |
| O9-2 | §7.3 `standards-core-pins = base.standards.pins { … }`; core §10.3 reachability "in the product's CI" | the flake check as written (offline, green: `flake.lock, 1 standards-core URL(s) and 18 .github reference(s) agree`). Reachability: `apps.standards-core-pins` (the same module on the work tree, extra arguments passed on) and check.yml's job `standards-core-pins` (`nix run .#standards-core-pins -- --reachable https://github.com/Avunu/python-devops-nix`, in `report`'s `needs`). The check is not weakened: when the module answers "is on neither main nor a v* tag", the job adds an `::error::` that this is expected until the pull request carrying the commit merges and is released (today python-devops-nix#58, v1.3.0), then `nix run .#bump-base -- <tag>` | **CI's `standards-core-pins` job is expected red until python-devops-nix#58 merges and v1.3.0 is released**; `nix run .#standards-core-pins -- --reachable …` reproduces it locally (exit 1, `2a96bf1b0e50 is on neither main nor a v* tag`). Then `nix run .#bump-base -- v1.3.0` |
| O9-3 | §1.1 `uv.lock` "dev lock (pytest, ty)"; §1.2 the Dependabot `uv` entry | `py/odoo_nix_tools/uv.lock` locks the package's own dependencies (standards-core from git at the pin, with jinja2, tomlkit, packaging, pyyaml), no dev group: the suites are `unittest`, and ty is off for this code (odoo-nix's `ty.toml`). `uv run --locked python -m unittest discover -s tests` runs the suites (green on 3.11). `.github/dependabot.yml` gains the `uv` entry (`/py/odoo_nix_tools`, weekly, `chore(deps)`, `standards-core` ignored; `flake.nix` passes `dependabot.development` so the conventions check expects that prefix) and, per plan §0.3, ignores `python-devops-nix` in the nix entry and `Avunu/python-devops-nix*` in the github-actions entry: a lone bump of one of the three pins is red under `standards-core-pins`, so they move together through `bump-base` | closes O1-3 |
| O9-4 | core §14 Stage 10 product follow-ups 1-3, 5 (CR1) | `PRODUCT` sets `Identity.config_paths = ("pyproject.toml", "nix/pyproject.toml")` and `Hooks.config_file = discover.config_file`. `config_file` answers in every directory the core asks about and never raises: one file opening the table is that file (read by its text, also outside git); both is the default `pyproject.toml`; neither falls back to the shape signals from `git ls-files`, and outside git (an `EnvError` from `repo.ls_files`) to the default. Both files opening the table is refused by `discover.load_checkout` at the checkout's root (exit 2 for `sync`; `config`/`profile show` resolve without a checkout there, the core's `checkout_or_none`). Deleted: `tests/support.py` `ADDONS_PRODUCT`, `product_for`, `HAS_CR1`/`NEEDS_CR1` (every suite runs `PRODUCT`), `discover`'s `core_config` extra and `_config_doc` (discovery reads `checkout.config`, which the core now loads from the hook's file), `checks.preflight`'s "reads it from pyproject.toml only" refusal, `test_preflight_addons.test_without_cr1_an_addon_repository_is_refused`, `test_profiles.test_addons_fixture_without_cr1_is_not_opted_in` and the two CR1 skips; `test_fleet`'s not-opted-in test now removes the table first, and a new test asserts the opted-in addons fixture reads `nix/pyproject.toml` (`opted_in`, its Dependabot targets). `tests/odoo-init.sh`'s `--addons --standards` case expects exit 0 and the table in `nix/pyproject.toml`. New `test_discover` cases: both files, outside git, an addon directory and `nix/` asked directly | closes O3-1, O4-8, O5-5, O6-2 (the shell half; the unit case stays odoo-init's), O8-9 |
| O9-5 | core §14 Stage 10 follow-up 4; §7.1 the addons fixture's `[tool.odoo-nix.dependabot]`; CR8 | `fixtures.NAMES = ("project", "addons")`; `scripts/gen_fixture_data.py` takes the table's body after `schema`/`profile` from the tree, `[tool.odoo-nix.*]` subtables allowed (any other header after the table is refused), so the shipped addons table is the tree's `[tool.odoo-nix.dependabot]` subtable and the project's is `""` (the CR8 fallback `commits.enable = true` is gone: the core's `_bump_fixture` turns on what `releases` needs). `data/fixtures/addons.json` is new; `test_fixtures_render.ShippedFixtures.test_product_fixtures` covers both; `tests/standards/fixtures.nix` drops `addonsCli` (both fixtures run `packages.odoo-nix`). The conformance render and CI parts pass on both fixtures | closes O4-7, O7-1 |
| O9-6 | §10 CR2-CR6 "until it lands" | CR3: `fleet.repo_policy_values` no longer returns `integration_bypass: []` for a project (closes O8-1); `test_fleet` shows a project's release branch is `""` (`release.BRANCHING`), so the core renders no bypass. CR4 and CR5 had no fallback left (O4-5, O5-4); CR2 had none (O4-1). CR6: `odoo-release.yml` keeps `ref: <integration>` and the caller's non-cancelling `release` group: they are no longer the fallback but what the flow needs, since `standards-release-ff` refuses a checkout that is not the `sha` it starts from, and a `workflow_run`'s `github.sha` is not the integration head | — |
| O9-7 | §6.4 the reusable workflows use `standards-*` composite actions; O7-2, O8-7 "O9 decides" | swapped in. `standards-install`'s `uv tool install --force --python 3.12 "odoo-nix-tools @ git+file://<clone of this tree>#subdirectory=py/odoo_nix_tools"` in a scratch `UV_TOOL_DIR` resolved `standards-core==1.3.0` from `git+https://github.com/Avunu/python-devops-nix@2a96bf1…#subdirectory=standards` in under 2 s; the installed `odoo-nix` printed 2.2.0, listed the profiles, synced and checked the addons fixture (`sync --write --offline`, `sync --check` clean) and answered `config shape` from an addon directory. `odoo-pr-policy.yml`: `standards-install`, committed from the locked odoo-nix (`nix build …#committed`), `standards-pr-policy`. `odoo-release.yml`: `standards-install`, the series check, a step for the App bot's identity and the checked-out head, `standards-release-ff` (`bump`, `base: origin/<series>`, `wait-checks: 900`, `git-user`); no Nix. `odoo-deps.yml`: `relock-plan` installs from the integration branch's `flake.lock` (fetched into `$RUNNER_TEMP/base`, `working-directory`), `relock-push` and `project-update` install before `ci enable-automerge`, `automerge` is `standards-install` + `standards-deps-automerge` (which runs fetch-metadata itself; the relock state is computed in a step: `rollout-input-moved`, `empty` or `patch`), `update-branches` is `standards-update-branches` (`dispatch-ci` without an App token). `fleet-audit.yml`: `standards-install`, gh from that odoo-nix's nixpkgs only when the runner has none, `standards-fleet-audit`. `odoo-lint.yml`/`odoo-test.yml` stay on Nix (§6.4). actionlint (with shellcheck) and zizmor clean | closes O7-2, O8-7, O8-8. Trade-offs: those jobs now install a `uv` Python 3.12 instead of building odoo-nix-tools with Nix (whose check phase runs the suites, minutes per uncached run), and an odoo-nix lock node of type `git` is refused there (`standards-install` reads github nodes only), where the inline steps accepted one |
| O9-8 | §9 O9 docs; plan B5 "note in `conventions.md` that the exit codes and sync flags are shared" | `docs/standards/{README,profiles,modules,managed-files,ci,versioning,fleet}.md` (section order 7, after Reference), from the code (`--help` texts, `modules.schema.json`, `manifest.d`, `series.DEVIATIONS`, the workflows' interfaces, `verdict.DECISION_TABLE`). `docs/development/editors.md`: the seed section corrected (it seeds the excludes and `extensions.json` too) and a new "The `ide` module" section; the `Odoo.serverConfigPath` guidance kept, linked to the module that removes it. odoo-nix has no `docs/conventions.md` of its own (it follows python-devops-nix's, whose Standards section, core stage 9, already says the exit codes and sync flags are shared and names odoo-nix), so the note is in `docs/standards/README.md`, linking there. Also: `docs/README.md` links the section, `docs/reference/{README,layout}.md` list the new apps, checks and the release job, the package README's development section names the dev lock and `bump-base` | — |
| O9-9 | §9 O9 "release-PR job re-rendering the fixtures" | release.yml's `fixtures` job (after `release-please`, before `dispatch-ci`, which now needs it so its dispatch lands on the new head): on the open `release-please--branches--main` PR branch it moves the standards fixtures' `github:Avunu/odoo-nix/release-<N>` URLs (flake.nix and flake.lock's `original.ref`) to `version.txt`'s major, reruns `gen_fixture_data.py` and `uv lock --project py/odoo_nix_tools` (uv and Python from this flake's nixpkgs), and pushes `test: render the standards fixtures for v<version>` with `GITHUB_TOKEN` when anything changed | unlike frappe-nix's fixtures, odoo-nix's are unsynced source trees (the tests sync them), so the release's version reaches only the dev lock (its editable root's `version`) and, on a major, the release-branch URLs; tests that name `release-2` literally (`test_flake_block`'s `RENDERED`) still need a hand edit for 3.0 |
| O9-10 | §4.2 "Frozen once v2.3.0 is tagged"; §9 "freeze `recommended@2.3`" | data only: both built-ins' headers say they are frozen, and `test_profiles.Frozen` records each file's sha256 (and that no other built-in exists without a digest), so an edit fails the suite and a changed `recommended` must be a new `recommended@2.<minor>.toml`. The body is §4.2's with O4-6's `src-icon` | the tag itself is the user's (release 2.3) |
| O9-11 | core follow-up 6 "regenerate the `--help` snapshot" | regenerated on Python 3.14: the words were already equal (the test compares words), only argparse's column layout changed | — |
| O9-12 | — | `tests/test_workspace.py` (not a standards file): `subprocess.run(…, check=False)` | ruff-pre-commit v0.17.2's PLW1510 failed `prek run --all-files` (the `lint` job) on HEAD already |
| O9-13 | O6-22 "`github:Avunu/odoo-nix/release-2` must exist on GitHub before this odoo-init is released" | it exists (`release-2` = `v2.2.0` = `39f9215`); the 2.3 release fast-forwards it | closes O6-22 |
| O9-14 | §9 O9 "release 2.3"; "the plan's pre-release end-to-end on a fresh clone of an addon repo" | the release is not done: it needs the user's approval. The pre-release end-to-end ran on a fresh clone of Avunu/web-addons (`feat/dev-env`) with an earlier state of this tree committed in a scratch clone (before O9-15's final form to O9-20: its tools.nix carried a `// { pythonModule }` workaround instead of the `passthru`, and relock.py, `context.py`'s ide seed and the docs were older) and the profile from a local copy (hand-locked, O9-21): opt-in, sync (22 files, `mirror.yml` retired), a second sync and `sync --check` clean after the adoption steps (whool `pyproject.toml`, then the consumer's `nix run .#relock`), `prek run -a`, the dev shell, `gate lint`, `gate test` (26 tests); every failure left was adoption work in the repository (whool `pyproject.toml`, prettier/eslint/ruff findings, `icon.png`, `development_status`, a deliberate ERROR in a test log). What it found in odoo-nix is O9-15 to O9-18. The final tree's coverage hook on such a checkout is covered by `checks.standards-shell-eval-coverage`; the rerun on the final tree is partial (O9-23) | the release stays open; see the release checklist below |
| O9-15 | §5.3 tools.nix's `coverage` "the lock's coverage built for `odooPython`"; lib/raw-odoo.nix "a coverage.py package built for `python`" | the hook reads `coverage.pythonModule.sitePackages`, which nixpkgs' packages carry and pyproject-nix's do not: every opted-in checkout whose tools lock has coverage (`tests` on, as in `recommended@2.3`) failed to evaluate the default shell and `packages.odooCli` (`attribute 'pythonModule' missing`). tools.nix now adds `passthru.pythonModule = odooPython` (passthru only: the derivation is unchanged). New `checks.standards-shell-eval-coverage` over a new fixture `tests/fixtures/standards-coverage` (symlinks: the opted-in addons tree of `standards-shell-addons`, `addons-repo`'s `nix/uv.lock`, `standards-locks/standards-addons/recommended/tools`): `odooCli.drvPath` and the default shell's packages evaluate, and the CLI differs from the one without the standards' additions (it takes the lock's coverage). Failed before the fix with the same error | blocker of the end-to-end; standards-shell-eval-opted-in had no lock, so nothing evaluated this |
| O9-16 | §3.1 ide "the seed `modules/devenv.nix` writes" into a missing file; editors.md "the seed already recommends `Odoo.odoo`" | `odoo-init --standards` syncs before the shell is ever entered, so in a repository without `.vscode/` (all 10 addon repositories) sync created the files and the seed never ran. `context.ide_specs(root)` (the templates' `ide_specs`) folds `seed` into the `set` spec when `.vscode/settings.json` does not exist, and `seed_extensions` into the `recommendations` union when `.vscode/extensions.json` does not; for an existing file the spec is the managed one alone, so the next plan neither checks nor retracts the seed's leaves (they are the checkout's, as the shell's seed would be). Not a merge into an existing file on shell entry: that would change every project's shell, opted in or not, and needs a JSONC writer in bash. Tests: `test_ide_real.Data.test_a_missing_file_gets_the_seed`, and the fixture matrix asserts the addons fixture's created files carry `python.defaultInterpreterPath` and `Odoo.odoo`, and keep the first after `ide` is retracted. editors.md corrected | the core's `jsonc-merge` has no seed of its own; this is the product's spec |
| O9-17 | — (review: no test of `bump_base.py`) | `checks.bump-base` (offline): over a copy of `.github/**`, `py/odoo_nix_tools/pyproject.toml` and `flake.lock`, with a commented-out `uses:` line added, `bump_base.py` with a made-up commit moves every live `.github` pin (counted independently with grep; 18 today, at least 18 required) and the one `standards-core` URL, leaves the commented line, then the core's pins module refuses the tree, and accepts it once `flake.lock`'s node names the same commit | — |
| O9-18 | lib/odoo_nix_cli/workspace/relock.py "the project root ($REPO_ROOT, else the working directory)" | `nix run .#relock` took `$REPO_ROOT` even from another project's dev-shell environment inherited by the terminal, and relocked that project (seen in the end-to-end: web-addons' relock wrote `nix/` and `.odoo-nix/` into a project checkout; removed). `project_root()`: `$REPO_ROOT` only when the working directory is it or below it (real paths), else the working directory. Tests: `test_workspace.RelockAppTest.test_main_ignores_another_projects_repo_root`, and `tests/relock.sh` (another project's root is left untouched) | predates the standards; a hazard for §8.2's relock across 10 repositories from one terminal |
| O9-19 | §3.0 "`docs/standards/managed-files.md` is generated from" `DEVIATIONS` | it is hand-written (O9-8). `test_series.Docs` holds its table to `DEVIATIONS`: the ids in order and each `Applies` cell (code spans unwrapped) equal to `Deviation.applies`, and "proposed" in the cell exactly for a proposed one. Two `applies` strings now read as the page does (`"projects"`, `"always (proposed, pending sign-off)"`). The package's check phase gets the page (`lib/standards/package.nix` `repoFiles`), so `standards-unit` runs the test | — |
| O9-20 | O9-8's pages | corrected from the docs review: `ci.yml` only with the `lint` or `test` gate and `pr-policy.yml` only with `commits` or `releases` (managed-files.md, ci.md's callers), and the required checks are the gates that are on; `schema` is in both files, the profile-only keys are refused in the table; the built-ins' `[org]` values (`dev-docs-url`, `repo-url`); `tools/pyproject.toml`'s keys (`[project].dependencies`, `[tool.uv]`, `[tool.coverage.*]`); `odoo-nix data-path schema/gate-report.schema.json`; the test cluster's data directory and socket; `releases.tag-prefix` and `releases.tool`; the CI workflows that install through `standards-install` need a `github:` odoo-nix lock (ci.md, `dev-shell.odoo-nix-url`); `console` fences are `bash` as on every other page; layout.md's `check` has three jobs; scaffolder.md links the standards page, not this file | — |
| O9-21 | §8.2 trying the profile with `--profile-path` before it is published | `--profile-path` changes only where the profile is read: the core's phase A still locks `standards-profile` from `profile`'s URL, a 404 before Avunu/odoo-standards-profile exists (exit 3). Documented, in docs/standards/profiles.md and the profile's README: lock the input from the clone with `--override-input`, put the node's `original` back to the GitHub URL, sync again. Core follow-up (proposed, not done here): phase A passes `--override-input standards-profile <dir>` when `--profile-path` is given and the input cannot be fetched | — |
| O9-22 | O9-8, O9-20's pages | corrected from the second docs review: README says only `sync` (so `odoo-init --sync`/`--check` and `gate lint`'s sync check) refuses both files opening the table, while `config` and `profile show` read the root `pyproject.toml` (O9-4); managed-files.md quotes both whole-file headers (`` `odoo-init --sync` `` in backticks; `edit only inside the odoo-nix:local region.` or `do not edit.`, the latter taking no additions), lists the `ci` retire rule's three matches (`oca_run_tests`, `ghcr.io/oca/oca-ci`, `pre-commit/action`) and `retire-keep`, the `/result` and `/result-*` lines, the integration branch as a series source, the `python-envs.*` notice as `ide`-only, and two more refusals (an `untested` entry naming no addon, a series without data); modules.md: `untested.reason` has at least 10 characters, and `tests.goal` is recorded for reference, shown nowhere yet (`modules.schema.json`'s description says the same); versioning.md: in CI `odoo-lint.yml`'s own step exports `ODOO_NIX_EXPECT_REV` (`standards-install` in the uv jobs); ci.md: `deps.yml` has `workflow_dispatch`; fleet.md's `updated`. README's two python-devops-nix links point at the pinned commit `2a96bf1` (public, so they resolve now) instead of `main`, which has neither until #58 merges | showing `tests.goal` in the gate's test report is left for later (a code change) |
| O9-23 | O9-14 on the final tree | rerun on a fresh clone of Avunu/web-addons (`b777cf0`) with the final staged tree committed in a scratch engine (`ODOO_NIX_URL_OVERRIDE=git+file://…`, `ODOO_NIX_ALLOW_SKEW=1`): opt-in (exit 2 with the inputs-block diff, then `--force` exit 3 on the unpublished profile, O9-21), hand-locked profile, `odoo-init --sync` (22 files, `mirror.yml` retired), `sync --write` idempotent, `config shape`, `profile show`, both files opening the table refused by `sync --check` (exit 2), `prek run -a` in `lib.standards.lintShell` (every hook starts; failures are adoption findings), the `committed` commit-msg stage, `gate lint`, `.vscode/` with the O9-16 seed. **Not run**: the consumer's `nix run --no-pure-eval .#relock` (so `sync --check` stopped at exit 1 on `nix/uv.lock predates web_theme_carbon/pyproject.toml`), `nix develop --no-pure-eval -c odoo-nix gate test`, and the `odools.toml` the shell writes: each evaluates the clone's own flake, which this session's permission policy refused ("Code from External") | **open, the user's**: in the scratch clone `o9/e2e-verify/web-addons`, with the two variables above, `nix run --no-pure-eval .#relock`, `odoo-nix sync --check` (expect 0), `nix develop --no-pure-eval -c odoo-nix gate test`, then look at `odools.toml` (one `[[config]]`, `odoo_path = "./.odoo-nix/odoo"`, `./.` in the addons paths). Core follow-up (proposed, not odoo-nix's): when the only findings are `check` items sync cannot fix, `report.py`'s summary still says "N file(s) drifted — run `odoo-init --sync`"; it should name the item's remedy or count check items apart from drifted files |

**Release checklist (2.3, the user's; nothing here is done).** In this order: python-devops-nix#58 merges and v1.3.0 is tagged; `nix run .#bump-base -- v1.3.0` (then `standards-core-pins`, offline and in CI with `--reachable`, is green); repoint docs/standards/README.md's two python-devops-nix links from the pinned `2a96bf1` to the tag (or `main`) and check them; publish Avunu/odoo-standards-profile (its README's "Before the first release"); finish O9-23's end-to-end steps (relock, `sync --check` exit 0, `gate test`, `odools.toml`); then release-please's 2.3.0 PR.
