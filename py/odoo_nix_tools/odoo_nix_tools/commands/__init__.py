"""odoo-nix's own commands, beside the core's (DESIGN.md §6): ``check``, ``gate`` and
``ratchet``."""

from __future__ import annotations

from standards_core.commands import Command

from odoo_nix_tools.commands.check import CHECK
from odoo_nix_tools.commands.gate import GATE
from odoo_nix_tools.commands.ratchet import RATCHET

EXTRA: tuple[Command, ...] = (CHECK, GATE, RATCHET)
