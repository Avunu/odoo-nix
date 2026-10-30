"""`odoo module build [addon …]`: the build scripts of the addons that have a
package.json (python-devops-nix docs/conventions.md, JavaScript), run in the
working tree with the shell's node_modules -- what the Nix build runs into
builtOdoo, for a look at the result before it is committed. An addon is named
as Odoo names it (`acme_ui`) or by its path from the workspace root
(`custom/acme_ui`, or a repository root whose addons are its workspace).

The logic is odoo-nix-node's (lib/node.nix): `list --json` says what the
targets are, `build KEY…` runs them.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence

from odoo_nix_cli.workspace.add import Stop
from odoo_nix_cli.workspace.config import WorkspaceConfig


def targets(cfg: WorkspaceConfig) -> list[str]:
    if cfg.node is None:
        return []
    out = subprocess.run(
        [cfg.node, "list", "--json"], check=False, capture_output=True, text=True
    )
    if out.returncode != 0:
        raise Stop(out.returncode, out.stderr.rstrip())
    return list(json.loads(out.stdout or "{}"))


def resolve(keys: Sequence[str], names: Sequence[str]) -> list[str]:
    """Each name as a target key: the key itself, or the one key whose last
    path segment it is."""
    chosen: list[str] = []
    for name in names:
        name = name.rstrip("/")
        if name in keys:
            chosen.append(name)
            continue
        matches = [k for k in keys if k.rsplit("/", 1)[-1] == name]
        if len(matches) == 1:
            chosen.append(matches[0])
        elif matches:
            raise Stop(2, f"{name} is {' and '.join(matches)}; name one by its path")
        else:
            raise Stop(
                2,
                f"no addon {name} has a package.json "
                f"(those that do: {', '.join(keys) or 'none'})",
            )
    return chosen


def build(cfg: WorkspaceConfig, args: list[str]) -> int:
    keys = targets(cfg)
    if not keys:
        raise Stop(
            0,
            "odoo-nix: no addon here has a package.json, so there is nothing to build",
        )
    chosen = resolve(keys, args)
    assert cfg.node is not None
    return subprocess.run([cfg.node, "build", *chosen], check=False).returncode
