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
}
#: Keys whose value may be null.
NULLABLE = {"core_source"}
LAYOUT_KEYS = {
    "coreSrc": "core_src",
    "externalDir": "external_dir",
    "customDir": "custom_dir",
}


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
    for k, v in values.items():
        if k == "layout" or (k in NULLABLE and v is None):
            continue
        if not (isinstance(v, str) and v):
            raise ConfigError(f"config.{k}: expected a non-empty string, got {v!r}")
    for k, v in vars(values["layout"]).items():
        if not (isinstance(v, str) and v):
            raise ConfigError(
                f"config.layout.{k}: expected a non-empty string, got {v!r}"
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
