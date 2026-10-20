"""One run's state: the arguments, what was resolved from them, and what the
steps found and did. The bash kept this in globals; here it is one object the
steps are handed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.args import InitArgs
from odoo_nix_cli.init.config import InitConfig
from odoo_nix_cli.init.presets import Preset

#: Where OCB, the OCA repositories and the project's own modules live: the
#: template's layout (odoo-nix.layout's defaults).
CORE = "odoo"
MODULES = "modules"
CUSTOM = "custom"
OCB_URL = "https://github.com/OCA/OCB.git"


@dataclass
class Run:
    args: InitArgs
    config: InitConfig
    presets: dict[str, Preset]
    # init | migrate
    mode: str = "init"
    # migrate mode on a project odoo-init made: nothing to convert, only to repair.
    repair: bool = False
    # Resolved from the arguments, the directory and the prompts.
    version: str = ""
    # Where migrate mode read the series, when it was not given.
    detected_from: str = ""
    preset: Preset | None = None
    name: str = ""
    db: str = ""
    target: str = ""
    # The directory as the user named it, for the next steps' `cd`; "" for the
    # current one.
    cd: str = ""
    # Bundle names asked for, the modules they and --modules select, and the
    # OCA repositories those need.
    bundles: list[str] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    # Submodule paths this run added.
    added: list[str] = field(default_factory=list)
    # The managed blocks of pyproject.toml are this run's to write: false when
    # an existing pyproject.toml has none and was kept.
    manage_pyproject: bool = True
    warnings: list[str] = field(default_factory=list)

    def warn(self, text: str) -> None:
        self.warnings.append(text)
        ui.warn_line(text)

    @property
    def p(self) -> Preset:
        if self.preset is None:
            raise RuntimeError(
                "internal: no preset resolved"
            )  # a bug here, not in the input
        return self.preset

    def resolve_preset(self) -> None:
        self.preset = self.presets[self.version]

    @property
    def preset_keys(self) -> str:
        """The presets, as the messages list them."""
        return " ".join(self.presets)

    @property
    def branch(self) -> str:
        """The git branch of OCB and every OCA repository."""
        return self.p.branch


def normalize_name(name: str) -> str:
    """A project name: a Nix string, a port seed and a container image prefix."""
    n = re.sub(r"[^a-z0-9-]", "-", name.lower())
    n = re.sub(r"-+", "-", n).strip("-")
    return n or "odoo-project"


def normalize_db(db: str) -> str:
    """A database name: lower case, [a-z0-9_], no leading underscore."""
    n = re.sub(r"[^a-z0-9_]", "_", db.lower()).lstrip("_")
    return n or "odoo"
