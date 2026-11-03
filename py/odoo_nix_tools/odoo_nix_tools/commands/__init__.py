"""odoo-nix's own commands, beside the core's (DESIGN.md §6): ``gate``, ``check`` and
``ratchet`` arrive in stage O7."""

from __future__ import annotations

from standards_core.commands import Command

EXTRA: tuple[Command, ...] = ()
