# Secrets for an odoo-nix project: agenix for the ciphertext, agenix-shell for
# the dev shell, one declaration serving both, and the deployment host too.
#
# The module is python-devops-nix's `lib.secrets.mkModule` (docs/library.md,
# Secrets and backups), shared with frappe-nix: the option tree at `odoo-nix.secrets`, agenix-shell
# wired to it, and the secret set as `flake.lib.secrets`. modules/devenv.nix
# builds the dev-shell side from it (`lib.secrets.tools`).
#
# odoo-nix's one difference from the base's defaults: the backup-access secret
# is encrypted to `hostRecipients` too, because the server reads the same file
# (`services.odoo-nix.environmentFiles`).
{ inputs, ... }:
let
  inherit (inputs.python-devops-nix.lib) secrets;
in
{
  imports = [
    (secrets.mkModule {
      optionPath = "odoo-nix.secrets";
      label = "odoo-nix";
      varPrefix = "odoo";
      projectRoles = [
        (
          secrets.roles.backupAccess
          // {
            hosts = true;
            description = ''
              Declare `<dir>/backup-access.age`: object-store credentials for the
              database backups, as a shell env-file (also valid systemd
              `EnvironmentFile` syntax when values are unquoted or single-quoted).

                  BACKUPS_URL=https://s3.us-east-005.backblazeb2.com
                  BACKUPS_ACCESS_KEY=...
                  BACKUPS_SECRET_KEY=...
                  BACKUPS_BUCKET=my-backups
                  BACKUPS_PREFIX=odoo        # optional

              `setup-backup-access` writes it. Encrypted to `hostRecipients`
              by default (`backupAccess.hosts`), so the server's
              `services.odoo-nix.environmentFiles` reads the same ciphertext.
            '';
          }
        )
      ];
      inherit (inputs) agenix-shell;
    })
  ];
}
