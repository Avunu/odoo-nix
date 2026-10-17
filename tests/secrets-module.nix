# odoo-nix's secrets module (modules/secrets.nix): python-devops-nix's
# lib.secrets.mkModule with odoo-nix's names, evaluated through lib.mkFlake as
# a consumer's flake would be. The base tests the module itself
# (lib-secrets-module, lib-secrets-schema); these pin odoo-nix's choices: the
# `odoo_` prefix, the backup-access secret encrypted to the host keys by
# default, and the flake.lib.secrets output with its odooSecrets alias.
# Same `pairs` shape as eval.nix; flake.nix turns each into a named
# mkEvalCheck.
{
  pkgs,
  lib,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;

  evalWith =
    secrets:
    let
      flake =
        mkFlake
          {
            inputs.self = {
              outPath = ../.;
              inherit inputs;
            };
          }
          {
            debug = true;
            systems = [ system ];
            imports = [ ../modules/flake-module.nix ];
            odoo-nix.secrets = secrets;
          };
    in
    {
      inherit (flake.debug) config;
      lib = flake.lib or { };
    };

  # The fixture directory holds backup-access.age only, so s3-writer is
  # declared but has no ciphertext yet.
  declared = evalWith {
    dir = ./fixtures/secrets;
    recipients.tim = "ssh-ed25519 AAAA";
    hostRecipients.prod = "ssh-ed25519 BBBB";
    extra.s3-writer = { };
  };
  cfg = declared.config.odoo-nix.secrets;
  rules = lib.listToAttrs (map (x: lib.nameValuePair x.relPath x.publicKeys) cfg.declared);

  off = evalWith { dir = ./fixtures/secrets; };
in
{
  # A secret whose .age file does not exist yet is declared (check-secrets
  # reports it) but left out of agenix-shell, so declaring one and then
  # running `edit-secret` to create it works on a fresh clone.
  secrets-declared-vs-shell = {
    expected = {
      declared = [
        "secrets/backup-access.age"
        "secrets/s3-writer.age"
      ];
      shell = [ "odoo_backup_access" ];
    };
    actual = {
      declared = map (x: x.relPath) cfg.declared;
      shell = lib.attrNames declared.config.agenix-shell.secrets;
    };
  };

  # Developers on every secret; the host keys on backup-access by default,
  # because the server reads the same file.
  secrets-recipients = {
    expected = {
      "secrets/backup-access.age" = [
        "ssh-ed25519 AAAA tim"
        "ssh-ed25519 BBBB prod"
      ];
      "secrets/s3-writer.age" = [ "ssh-ed25519 AAAA tim" ];
    };
    actual = rules;
  };

  secrets-vars = {
    expected = [
      "odoo_backup_access"
      "odoo_s3_writer"
    ];
    actual = map (x: x.var) cfg.declared;
  };

  # flake.lib.secrets, and flake.lib.odooSecrets for one release.
  secrets-flake-lib = {
    expected = {
      names = [
        "odooSecrets"
        "secrets"
      ];
      files = [
        "odoo_backup_access"
        "odoo_s3_writer"
      ];
      alias = true;
    };
    actual = {
      names = lib.attrNames declared.lib;
      files = lib.attrNames declared.lib.secrets.files;
      alias = declared.lib.odooSecrets == declared.lib.secrets;
    };
  };

  # No recipients, no secrets: nothing declared and no output.
  secrets-off = {
    expected = {
      enable = false;
      declared = [ ];
      lib = [ ];
    };
    actual = {
      inherit (off.config.odoo-nix.secrets) enable declared;
      lib = lib.attrNames off.lib;
    };
  };
}
