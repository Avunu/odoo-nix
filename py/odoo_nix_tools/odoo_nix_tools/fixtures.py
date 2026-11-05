"""The fixture checkouts every template must render for (core DESIGN.md §3.4, DESIGN.md §7.1).

``profile validate`` syncs a throwaway copy of each under an org profile, and the
conformance check under each built-in profile (core ``scaffold.fixtures.throwaway``).
They ship as ``data/fixtures/<name>.json`` (path → text), written by
``scripts/gen_fixture_data.py`` from ``tests/fixtures/standards-<name>`` and the locks
of its ``example-org`` profile, the superset every other profile's tools are a subset of
(the lock check accepts a superset in a throwaway, core CR2). Binary files (the icons)
are left out: a ``Fixture`` holds text.

Each document names its config file: the project fixture's table is in the root
``pyproject.toml``, the addons fixture's in ``nix/pyproject.toml`` (DESIGN.md §2.3), where
``write`` appends it.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Any

from standards_core.product import Fixture

DATA = Path(str(files("odoo_nix_tools") / "data")) / "fixtures"
NAMES = ("project", "addons")


def _load(name: str) -> tuple[Fixture, str]:
    doc: dict[str, Any] = json.loads((DATA / f"{name}.json").read_text())
    return (
        Fixture(table=doc["table"], files=MappingProxyType(dict(doc["files"]))),
        doc["config_file"],
    )


_LOADED = {name: _load(name) for name in NAMES}
FIXTURES = MappingProxyType({name: fixture for name, (fixture, _) in _LOADED.items()})
CONFIG_FILES = MappingProxyType({name: config for name, (_, config) in _LOADED.items()})


def table(profile: str, extra: str = "") -> str:
    """The ``[tool.odoo-nix]`` table a fixture's config file ends with."""
    return f'\n[tool.odoo-nix]\nschema = 1\nprofile = "{profile}"\n{extra}'


def write(root: Path, name: str, fixture: Fixture, profile: str) -> None:
    """``hooks.write_fixture``: the fixture's files, its config file ending with the
    table that names ``profile``."""
    config = CONFIG_FILES[name]
    for rel, text in fixture.files.items():
        if rel == config:
            text = text + table(profile, fixture.table)
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
