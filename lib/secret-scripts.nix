# Dev-shell commands for the secrets subsystem: edit-secret, rekey-secrets,
# check-secrets and setup-backup-access. Ported from frappe-nix's
# lib/scripts.nix; merged into the shell's `scripts` by modules/devenv.nix
# (ahead of `extraScripts`, so a consumer can still override any of them).
{
  lib,
  secrets,
  # The standalone remote tool `setup-backup-access` uses to test credentials.
  fetch,
  # Whether to offer setup-backup-access (secrets on + restore on).
  withSetup,
}:

let
  atRepo = ''
    cd "''${REPO_ROOT:?run this from the dev shell}"
  '';

  secretNames = lib.concatMapStringsSep "\n" (s: "  ${s.name}") (secrets.names or [ ]);
in
lib.optionalAttrs (secrets.enabled or false) {
  edit-secret.exec = ''
    set -euo pipefail
    ${atRepo}

    if [ -z "''${1:-}" ] || [ "''${1:-}" = "--help" ] || [ "''${1:-}" = "-h" ]; then
      cat <<'EOF'
    Usage: edit-secret <name> [identity-file]

    Decrypts a secret into $EDITOR and re-encrypts it to the recipients
    declared in flake.nix. Creates it if it does not exist.

    Declared secrets:
    ${secretNames}

    The recipient list is generated from `odoo-nix.secrets.recipients`, so
    there is no secrets.nix to keep in step. After changing that list, run
    `rekey-secrets`.
    EOF
      exit 0
    fi

    REL="${secrets.relDir}/$1.age"
    shift

    # Rules are rendered here (absolute paths) rather than committed; see
    # lib/secrets-tools.nix for why a store-path rules file does nothing.
    ${secrets.writeRules}

    # ragenix, unlike ryantm/agenix, refuses to run with a non-terminal
    # stdout; restore the documented `edit-secret foo <<EOF ... EOF` form.
    if [ ! -t 0 ]; then
      EDITOR="cp /dev/stdin"
      export EDITOR
    fi

    if [ -n "''${1:-}" ]; then
      ${lib.getExe' secrets.cli "agenix"} -e "$REPO_ROOT/$REL" -i "$1"
    else
      ${lib.getExe' secrets.cli "agenix"} -e "$REPO_ROOT/$REL"
    fi

    # A flake's source tree is only its tracked files: stage the new .age.
    if ! git ls-files --error-unmatch -- "$REL" >/dev/null 2>&1; then
      git add -- "$REL"
      echo "staged new secret $REL (age ciphertext is meant to be committed)"
    fi

    ${lib.getExe' secrets.agecheck "odoo-nix-agecheck"} check ${secrets.rulesJSON} --root .
  '';

  rekey-secrets.exec = ''
    set -euo pipefail
    ${atRepo}

    echo "Re-encrypting every declared secret to the current recipient list..."
    echo "(you need to be able to decrypt them, so this cannot run in CI)"
    echo

    ${secrets.writeRules}
    ${lib.getExe' secrets.cli "agenix"} -r "$@"

    echo
    ${lib.getExe' secrets.agecheck "odoo-nix-agecheck"} check ${secrets.rulesJSON} --root .
    echo
    echo "Commit the changed .age files -- until you do, the recipient list in"
    echo "flake.nix and the ciphertext on the branch disagree."
  '';

  check-secrets.exec = ''
    set -euo pipefail
    ${atRepo}
    if [ -n "''${1:-}" ]; then
      exec ${lib.getExe' secrets.agecheck "odoo-nix-agecheck"} explain \
        ${secrets.rulesJSON} "$1" --root .
    fi
    exec ${lib.getExe' secrets.agecheck "odoo-nix-agecheck"} check \
      ${secrets.rulesJSON} --root .
  '';
}
// lib.optionalAttrs ((secrets.enabled or false) && withSetup) {
  setup-backup-access.exec = ''
    exec ${secrets.setupBackupAccess fetch}/bin/odoo-nix-setup-backup-access "$@"
  '';
}
