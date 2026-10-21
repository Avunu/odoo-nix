"""What lib/init.nix bakes into ``odoo-init``: store paths, as the JSON file
``ODOO_NIX_INIT_CONFIG`` names. A missing or unknown key is refused.

``odoo-init`` runs before any project exists, so this is all it reads.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

ENV = "ODOO_NIX_INIT_CONFIG"


class ConfigError(Exception):
    """The configuration is missing or not of the documented shape."""


@dataclass(frozen=True)
class InitConfig:
    # lib/odoo-presets.json.
    presets: str
    # templates/project: the files a project is given.
    template: str
    # data/oca-modules.json and data/oca-bundles.json.
    oca_dataset: str
    oca_bundles: str
    # lib/oca_sources.py: writes the uv path sources and the install set.
    oca_sources: str
    # odoo-nix-build-deps (lib/build-deps.nix), or null to leave the block alone.
    build_deps: str | None


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w.title() for w in rest)


def parse(data: Any) -> InitConfig:
    if not isinstance(data, dict):
        raise ConfigError("config: expected an object")
    known = {_camel(f.name): f for f in fields(InitConfig)}
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise ConfigError(f"config: unknown key(s): {', '.join(unknown)}")
    missing = [k for k in known if k not in data]
    if missing:
        raise ConfigError(f"config: missing key(s): {', '.join(missing)}")
    values: dict[str, Any] = {}
    for key, f in known.items():
        value = data[key]
        nullable = f.name == "build_deps"
        if not (isinstance(value, str) and value) and not (nullable and value is None):
            raise ConfigError(
                f"config.{key}: expected a non-empty string, got {value!r}"
            )
        values[f.name] = value
    return InitConfig(**values)


def load(path: str | os.PathLike[str] | None = None) -> InitConfig:
    """Read the file ``ODOO_NIX_INIT_CONFIG`` names (or PATH)."""
    path = path or os.environ.get(ENV)
    if not path:
        raise ConfigError(
            f"${ENV} is not set; run odoo-init as `nix run github:Avunu/odoo-nix`"
        )
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    return parse(data)
