# Secrets for an odoo-nix project: agenix for the ciphertext, agenix-shell for
# the dev shell, one declaration serving both -- and the deployment host too.
#
# TOP-LEVEL, not perSystem, deliberately. agenix-shell.secrets is a top-level
# option and there is no supported way to reach a perSystem value from there;
# and recipients and .age paths are facts about the project, not about
# x86_64-linux. Top level says *who* and *what*, perSystem (modules/devenv.nix)
# says *how the shell behaves*. Ported from frappe-nix's modules/secrets.nix.
{
  config,
  lib,
  ...
}:

let
  inherit (lib)
    mkOption
    mkEnableOption
    types
    literalExpression
    ;

  cfg = config.odoo-nix.secrets;
  # No `self`: flake-parts' `self` is the flake's own output set, and this
  # module writes one (flake.lib.odooSecrets). Reading one from the other is an
  # infinite recursion -- hence `relDir` below.
  schema = import ../lib/secrets-schema.nix { inherit lib; };

  sshKey =
    types.strMatching "^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9-]+) [A-Za-z0-9+/]+=*( .*)?$"
    // {
      name = "sshPublicKey";
      description = "SSH public key (authorized_keys format)";
    };

  extraModule = types.submodule (
    { name, ... }:
    {
      options = {
        format = mkOption {
          type = types.enum [
            "env"
            "raw"
            "json"
          ];
          default = "env";
          description = ''
            How the dev shell consumes the plaintext:

            `env`  -- `KEY=value` lines, sourced with `set -a` so each becomes a
                     variable. The file is executed by the shell, so it must be
                     shell syntax.
            `raw`  -- a single value; `$<var>` is it.
            `json` -- a JSON object; left on disk, `$<var>_PATH` points at it.
          '';
        };

        var = mkOption {
          type = types.str;
          default = "odoo_${schema.slug name}";
          defaultText = literalExpression "\"odoo_\${name}\"";
        };

        hosts = mkOption {
          type = types.bool;
          default = false;
          description = "Also encrypt this secret to `hostRecipients`.";
        };
      };
    }
  );
in
{
  options.odoo-nix.secrets = {
    enable = mkOption {
      type = types.bool;
      default = cfg.recipients != { };
      defaultText = literalExpression "recipients != { }";
      description = "Wire agenix + agenix-shell into this project.";
    };

    dir = mkOption {
      type = types.path;
      example = literalExpression "./secrets";
      description = ''
        Directory holding this project's `.age` files, as a path literal
        relative to your `flake.nix`, e.g. `dir = ./secrets;`.

        The `.age` files are **meant to be committed** -- they are age
        ciphertext, and a flake's source tree is exactly its git-tracked files,
        so an untracked one is invisible to the build.
      '';
    };

    relDir = mkOption {
      type = types.str;
      default = baseNameOf (toString cfg.dir);
      defaultText = literalExpression "baseNameOf dir";
      description = ''
        The same directory, relative to the project root. agenix keys its rules
        by the literal path string, so the rules file has to name
        `secrets/foo.age`, not a `/nix/store` path. Override only if `dir` is
        nested (`dir = ./nix/secrets;` needs `relDir = "nix/secrets";`).
      '';
    };

    recipients = mkOption {
      type = types.attrsOf sshKey;
      default = { };
      example = literalExpression ''{ tim = "ssh-ed25519 AAAAC3Nza..."; }'';
      description = ''
        Public keys of the people who may read this project's secrets. The
        single source of truth: the agenix rules file is generated from it
        (there is no `secrets.nix` to edit) and `check-secrets` verifies every
        `.age` file is encrypted to exactly these keys. Attribute names are
        labels, carried into the key line as an SSH comment.

        After changing this, run `rekey-secrets`.
      '';
    };

    hostRecipients = mkOption {
      type = types.attrsOf sshKey;
      default = { };
      example = literalExpression ''{ appserver = "ssh-ed25519 AAAAC3Nza..."; }'';
      description = ''
        Public keys of deployment hosts. Added to every secret with
        `hosts = true` (the backup-access secret, by default), so the server's
        `services.odoo-nix.environmentFiles` reads the same ciphertext the
        developers do.
      '';
    };

    identityPaths = mkOption {
      type = types.listOf types.str;
      default = [
        "$HOME/.ssh/id_ed25519"
        "$HOME/.ssh/id_rsa"
      ];
      description = ''
        Private keys tried when decrypting, in order. Forwarded to
        `agenix-shell.identityPaths`. Shell strings, expanded at runtime --
        which is why the dev shell needs `--no-pure-eval`.
      '';
    };

    backupAccess = {
      enable = mkOption {
        type = types.bool;
        default = cfg.enable;
        defaultText = literalExpression "secrets.enable";
        description = ''
          Declare `<dir>/backup-access.age`: object-store credentials for the
          database backups, as a shell env-file (also valid systemd
          `EnvironmentFile` syntax when values are unquoted or single-quoted).

              BACKUPS_URL=https://s3.us-east-005.backblazeb2.com
              BACKUPS_ACCESS_KEY=...
              BACKUPS_SECRET_KEY=...
              BACKUPS_BUCKET=my-backups
              BACKUPS_PREFIX=odoo        # optional

          `setup-backup-access` writes it.
        '';
      };

      hosts = mkOption {
        type = types.bool;
        default = true;
        description = ''
          Also encrypt to `hostRecipients`, so the server decrypts the same
          file. Disable to give the server its own (write-capable) key via
          `extra` and keep developers on a read-only one.
        '';
      };
    };

    extra = mkOption {
      type = types.attrsOf extraModule;
      default = { };
      description = "Additional project-specific secrets.";
    };

    # Read-only, for modules/devenv.nix and the checks.
    declared = mkOption {
      type = types.listOf (types.attrsOf types.unspecified);
      internal = true;
      readOnly = true;
      default = if cfg.enable then schema.secretList cfg else [ ];
      description = "Normalised secret list -- see lib/secrets-schema.nix.";
    };
  };

  # `mkIf` per attribute, NOT around the whole `config`: `cfg.enable` defaults
  # to `recipients != {}`, declared in this very module, so wrapping everything
  # would force the condition while the module system is still working out
  # which options this module defines (infinite recursion).
  config = {
    agenix-shell = lib.mkIf cfg.enable {
      inherit (cfg) identityPaths;
      secrets = schema.agenixShellSecrets cfg;
    };

    # Exposed so the deployment host consumes the very same ciphertext:
    #
    #   age.secrets.odoo-backup.file = inputs.myproject.lib.odooSecrets.files.odoo_backup_access;
    #   services.odoo-nix.environmentFiles = [ config.age.secrets.odoo-backup.path ];
    #
    # `optionalAttrs`, not `mkIf`: free-form flake outputs are typed `raw`, so
    # the module system would hand an `mkIf` straight through.
    flake.lib = lib.optionalAttrs cfg.enable {
      odooSecrets = {
        recipients = schema.labelled cfg.recipients ++ schema.labelled cfg.hostRecipients;
        # { "<shell var>" = <path to .age>; } -- every declared secret, flat.
        files = lib.listToAttrs (map (s: lib.nameValuePair s.var s.file) cfg.declared);
      };
    };
  };
}
