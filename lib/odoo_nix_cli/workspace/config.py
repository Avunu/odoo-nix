"""What lib/cli-scripts.nix bakes for the workspace commands: the JSON file
``ODOO_NIX_WORKSPACE_CONFIG`` names. A missing or unknown key is refused.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENV = "ODOO_NIX_WORKSPACE_CONFIG"


class ConfigError(Exception):
    """The configuration is missing or not of the documented shape."""


@dataclass(frozen=True)
class Layout:
    # OCB (odoo/), the module repositories (modules/), the project's own (custom/).
    core_src: str
    external_dir: str
    custom_dir: str


@dataclass(frozen=True)
class WorkspaceConfig:
    # The Odoo series: the branch of OCB and of every OCA repository.
    series: str
    oca_dataset: str
    oca_bundles: str
    layout: Layout
    # odoo-nix-sources (python-devops-nix's lib.sources): a repository's first clone.
    sources: str
    # The re-lock (odoo_nix_cli.workspace.update): the interpreter that runs
    # lib/oca_sources.py, which rewrites pyproject.toml's managed blocks from
    # what is on disk; uv; odoo-nix-build-deps (lib/build-deps.nix).
    python: str
    oca_sources: str
    uv: str
    build_deps: str
    # OCB's store path when it is a flake input (coreSource), else None:
    # <coreSrc> is then a symlink to it, shadowed for the lock.
    core_source: str | None
    # odoo-nix-node (lib/node.nix, python-devops-nix's lib.node): the addons'
    # JavaScript builds, which `odoo module build` runs. None without one.
    node: str | None
    # Where pyproject.toml and uv.lock live, from the root: "." for a
    # project, "nix" for a repository of addons (addons mode).
    lock_dir: str
    # What the lock's install roots are: "modules.txt", or "local" (every
    # installable addon of the custom directory: addons mode).
    install_set: str
    # externalSources: {name: store path}, each linked as <externalDir>/<name>
    # before a lock, as shell entry links them.
    external_sources: dict[str, str]
    # The rendered pyproject.toml a relock writes into lock_dir when there is
    # none yet (addons mode's first lock), else None.
    pyproject_template: str | None
    # odoo-init, once the project has opted in to the standards, else None:
    # `project update` ends with `odoo-init --sync`.
    standards_init: str | None

    @property
    def addons_mode(self) -> bool:
        return self.install_set == "local"


KEYS = {
    "series": "series",
    "ocaDataset": "oca_dataset",
    "ocaBundles": "oca_bundles",
    "layout": "layout",
    "sources": "sources",
    "python": "python",
    "ocaSources": "oca_sources",
    "uv": "uv",
    "buildDeps": "build_deps",
    "coreSource": "core_source",
    "node": "node",
    "lockDir": "lock_dir",
    "installSet": "install_set",
    "externalSources": "external_sources",
    "pyprojectTemplate": "pyproject_template",
    "standardsInit": "standards_init",
}
#: Keys whose value may be null.
NULLABLE = {"core_source", "node", "pyproject_template", "standards_init"}
INSTALL_SETS = ("modules.txt", "local")
LAYOUT_KEYS = {
    "coreSrc": "core_src",
    "externalDir": "external_dir",
    "customDir": "custom_dir",
}


#: What a checkout command (`odoo module add|add-bundle|remove`, `odoo
#: project update`) says in a repository of addons, whose sources are flake
#: inputs rather than submodules.
ADDONS_MODE_REFUSAL = """\
`odoo {command}` manages a project's git submodules and modules.txt. This is a
repository of addons (odoo-nix addons mode): its dependencies are flake inputs.
  - to depend on another repository: add it to flake.nix's inputs and to
    odoo-nix.externalSources, then `nix flake lock` and `odoo project relock`;
  - to move every pin: `nix flake update`, then `odoo project relock`;
  - the install set is every installable addon in the repository."""


def _strings(data: Any, keys: dict[str, str], where: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: expected an object")
    unknown = sorted(set(data) - set(keys))
    if unknown:
        raise ConfigError(f"{where}: unknown key(s): {', '.join(unknown)}")
    missing = [k for k in keys if k not in data]
    if missing:
        raise ConfigError(f"{where}: missing key(s): {', '.join(missing)}")
    return {keys[k]: v for k, v in data.items()}


def parse(data: Any) -> WorkspaceConfig:
    values = _strings(data, KEYS, "config")
    values["layout"] = Layout(
        **_strings(values["layout"], LAYOUT_KEYS, "config.layout")
    )
    sources = values["external_sources"]
    if not isinstance(sources, dict) or not all(
        isinstance(k, str) and k and isinstance(v, str) and v
        for k, v in sources.items()
    ):
        raise ConfigError(
            f"config.externalSources: expected an object of non-empty strings, got {sources!r}"
        )
    for k, v in values.items():
        if k in ("layout", "external_sources") or (k in NULLABLE and v is None):
            continue
        if not (isinstance(v, str) and v):
            raise ConfigError(f"config.{k}: expected a non-empty string, got {v!r}")
    for k, v in vars(values["layout"]).items():
        if not (isinstance(v, str) and v):
            raise ConfigError(
                f"config.layout.{k}: expected a non-empty string, got {v!r}"
            )
    if values["install_set"] not in INSTALL_SETS:
        raise ConfigError(
            f"config.installSet: expected one of {', '.join(INSTALL_SETS)}, got {values['install_set']!r}"
        )
    return WorkspaceConfig(**values)


def load(path: str | os.PathLike[str] | None = None) -> WorkspaceConfig:
    path = path or os.environ.get(ENV)
    if not path:
        raise ConfigError(
            f"${ENV} is not set -- this command is only available from an odoo-nix workspace dev shell."
        )
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    return parse(data)
