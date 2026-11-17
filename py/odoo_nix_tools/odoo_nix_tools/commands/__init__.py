"""odoo-nix's own commands, beside the core's (DESIGN.md §6): ``agent``, ``check``,
``gate``, ``ratchet``, ``release`` and ``verify-patch``."""

from __future__ import annotations

from standards_core.commands import Command

from odoo_nix_tools.commands.agent import AGENT
from odoo_nix_tools.commands.check import CHECK
from odoo_nix_tools.commands.gate import GATE
from odoo_nix_tools.commands.ratchet import RATCHET
from odoo_nix_tools.commands.release import RELEASE
from odoo_nix_tools.commands.verify_patch import VERIFY_PATCH

EXTRA: tuple[Command, ...] = (AGENT, CHECK, GATE, RATCHET, RELEASE, VERIFY_PATCH)
