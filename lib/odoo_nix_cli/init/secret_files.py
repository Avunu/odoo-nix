"""Secrets, as far as the scaffolder goes: secrets/README.md in a new project,
so the layout is discoverable before anyone has a key. Nothing here creates or
encrypts anything: odoo-init cannot know the recipients.
"""

from __future__ import annotations

from pathlib import Path

SECRETS_README = """\
# secrets/

age-encrypted credentials for this project. **These files are committed** —
they are ciphertext, and a flake's source tree is exactly its git-tracked files,
so an untracked one is invisible to the build.

Declare who may read them in `flake.nix`:

    odoo-nix.secrets = {
      dir = ./secrets;
      recipients.you = "ssh-ed25519 AAAA… you@host";
    };

Then, in the dev shell:

    setup-backup-access          # object-store credentials for `odoo db restore`
    edit-secret <name>           # any other secret
    check-secrets                # are the .age files encrypted to who we think?
    rekey-secrets                # after changing `recipients`

There is deliberately no `secrets.nix`: the recipient list in `flake.nix` is the
only place it is written down, and the rules file agenix reads is generated from
it. A hand-maintained rules file can be edited without re-encrypting anything,
and nothing notices.
"""

PATH = Path("secrets/README.md")


def scaffold_secrets_dir() -> bool:
    """secrets/README.md, unless secrets/ exists; whether it was written."""
    if PATH.parent.exists():
        return False
    PATH.parent.mkdir(parents=True)
    PATH.write_text(SECRETS_README, encoding="utf-8")
    return True


def secrets_declared(flake: str) -> bool:
    """flake.nix declares odoo-nix.secrets: a line that names it outside a comment."""
    return any(
        "odoo-nix.secrets" in line and not line.lstrip().startswith("#")
        for line in flake.splitlines()
    )
