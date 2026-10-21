"""lib/odoo-presets.json, read and checked (python-devops-nix CONVENTIONS.md,
Scaffolder: presets file).

One object per Odoo series, keyed by the name ``--version`` takes::

    {
        "18.0": {
            "label": "18.0 — current stable (python 3.11)",
            "branch": "18.0",
            "python": "python311",
            "requiresPython": ">=3.11",
        }
    }

``label``, ``branch``, ``python`` and ``requiresPython`` are required;
``nodejs`` and ``overrideDependencies`` are optional in the shared schema, and
odoo-nix uses neither. ``branch`` is the git branch of OCB and of every OCA
repository. It was ``series`` before the products shared one schema; a file
that still says ``series`` is read the same through 1.x, until odoo-nix 2.0.0.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED = ("label", "branch", "python", "requiresPython")
OPTIONAL = ("nodejs", "overrideDependencies")
#: The old name of a key → its name now.
RENAMED = {"series": "branch"}


class PresetError(Exception):
    """The presets file is not of the documented shape."""


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    branch: str
    # A nixpkgs attribute: python311.
    python: str
    requires_python: str
    nodejs: str | None = None
    override_dependencies: tuple[str, ...] = ()

    @property
    def pyver(self) -> str:
        """The version the attribute names: 3.11."""
        num = self.python.removeprefix("python")
        return f"{num[:1]}.{num[1:]}"


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise PresetError(f"{where}: expected a non-empty string, got {value!r}")
    return value


def parse(data: Any) -> dict[str, Preset]:
    """DATA as the presets, in the file's order."""
    if not isinstance(data, dict) or not data:
        raise PresetError("the presets file must be a non-empty object of presets")
    presets: dict[str, Preset] = {}
    for key, raw in data.items():
        where = f"presets.{key}"
        if not isinstance(raw, dict):
            raise PresetError(f"{where}: expected an object, got {type(raw).__name__}")
        entry = dict(raw)
        for old, new in RENAMED.items():
            if old in entry:
                if new in entry:
                    raise PresetError(
                        f"{where}: both {old} and {new}; {old} is {new}'s old name"
                    )
                entry[new] = entry.pop(old)
        unknown = sorted(set(entry) - set(REQUIRED) - set(OPTIONAL))
        missing = [k for k in REQUIRED if k not in entry]
        if unknown:
            raise PresetError(f"{where}: unknown key(s): {', '.join(unknown)}")
        if missing:
            raise PresetError(f"{where}: missing key(s): {', '.join(missing)}")
        python = _string(entry["python"], f"{where}.python")
        if not re.fullmatch(r"python3\d+", python):
            raise PresetError(
                f"{where}.python: expected a nixpkgs python3xx attribute, got {python!r}"
            )
        nodejs = entry.get("nodejs")
        if nodejs is not None:
            _string(nodejs, f"{where}.nodejs")
        overrides = entry.get("overrideDependencies", [])
        if not isinstance(overrides, list) or not all(
            isinstance(o, str) for o in overrides
        ):
            raise PresetError(
                f"{where}.overrideDependencies: expected a list of strings"
            )
        presets[key] = Preset(
            key=key,
            label=_string(entry["label"], f"{where}.label"),
            branch=_string(entry["branch"], f"{where}.branch"),
            python=python,
            requires_python=_string(entry["requiresPython"], f"{where}.requiresPython"),
            nodejs=nodejs,
            override_dependencies=tuple(overrides),
        )
    return presets


def load(path: str | Path) -> dict[str, Preset]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PresetError(f"cannot read {path}: {e}") from e
    return parse(data)
