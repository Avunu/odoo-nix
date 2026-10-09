# The one derivation of a project's secret set.
#
# Called by modules/secrets.nix (to configure agenix-shell), by modules/devenv.nix
# (to build the rules file and the dev-shell scripts) and by the checks — so the
# .age paths, the rules file and the shell variable names cannot drift apart.
#
# Pure: no pkgs, no IO, and deliberately no `self`. flake-parts' `self` is the
# flake's own output set, so reading it from something that *writes* a flake
# output (flake.lib.odooSecrets) is an infinite recursion. Repo-relative paths
# therefore come from `relDir`, a plain string, rather than from stripping a
# prefix off the flake root.
{ lib }:

let
  inherit (lib) concatMapStringsSep filter optionals;
in
rec {
  # A shell-variable-safe rendering of a secret name.
  # ("s3-writer" -> "s3_writer")
  slug = lib.replaceStrings [ "." "-" " " ] [ "_" "_" "_" ];

  # `recipients` is an attrset so every key has a name. Carry that name into the
  # key line as an SSH comment: age parses authorized_keys format and ignores
  # the comment, and the recipient tag is derived from the key blob alone — so
  # in exchange the generated rules file and every agecheck message can say
  # "gideon" instead of "AAAAC3NzaC1l…". Cosmetic, and it cannot change what a
  # file is encrypted to.
  labelled = lib.mapAttrsToList (
    name: key: if lib.length (lib.splitString " " key) >= 3 then key else "${key} ${name}"
  );

  # The standard roles. Each is a *shape*, not just a name: `format` is what the
  # dev shell does with the plaintext. The backup-access env-file is also what
  # services.odoo-nix.environmentFiles consumes in production, so the server and
  # the developer's `odoo db restore` read one ciphertext.
  projectRoles = [
    {
      attr = "backupAccess";
      file = "backup-access";
      format = "env";
      var = "odoo_backup_access";
    }
  ];

  # Every declared secret, normalised:
  #
  #   relPath    repo-relative .age path — this is the agenix rules key, because
  #              agenix looks a rule up by the literal string you pass it and
  #              writes its output relative to $PWD (agenix.sh: `keys()`,
  #              `edit()`). That is what lets RULES point at a generated store
  #              file while the .age files stay in the worktree.
  #   file       store path agenix-shell reads
  #   var        agenix-shell secret name; $<var> and $<var>_PATH follow
  #   format     env | raw | json
  #   role       which standard role, or the `extra` attribute name
  #   publicKeys recipients for this particular secret
  secretList =
    cfg:
    let
      mk =
        {
          subpath,
          var,
          format,
          role,
          developers,
          hosts,
        }:
        {
          inherit var format role;
          relPath = "${cfg.relDir}/${subpath}";
          file = cfg.dir + "/${subpath}";
          publicKeys =
            optionals developers (labelled cfg.recipients) ++ optionals hosts (labelled cfg.hostRecipients);
        };

      project = map (
        r:
        mk {
          subpath = "${r.file}.age";
          inherit (r) format var;
          inherit (cfg.${r.attr}) hosts;
          role = r.attr;
          developers = true;
        }
      ) (filter (r: cfg.${r.attr}.enable) projectRoles);

      extra = lib.mapAttrsToList (
        name: e:
        mk {
          subpath = "${name}.age";
          inherit (e) format var hosts;
          role = name;
          developers = true;
        }
      ) cfg.extra;
    in
    project ++ extra;

  # { <var> = { name; file; mode; }; } — agenix-shell.secrets.
  #
  # `name` is set explicitly rather than left to agenix-shell's toShellVar,
  # which maps every hyphen to "__" — the variable a script reads would
  # otherwise depend on the attribute key's punctuation.
  #
  # Secrets whose .age file does not exist yet are left out, deliberately.
  # agenix-shell types `file` as a path, so Nix copies it into the store during
  # evaluation and a missing one is an *evaluation* error — which would make a
  # freshly declared secret break the whole flake, and with it `edit-secret`,
  # the command that creates the file. Declaring a secret and then creating it
  # is the documented first run, so it has to work.
  #
  # They stay in `declared`, so `check-secrets` still reports them as missing
  # and says which command writes them. This is the one place the two lists
  # differ.
  agenixShellSecrets =
    cfg:
    lib.listToAttrs (
      map (
        s:
        lib.nameValuePair s.var {
          name = s.var;
          inherit (s) file;
          mode = "0400";
        }
      ) (filter (s: builtins.pathExists s.file) (secretList cfg))
    );

  # The agenix rules file, rendered. Generated rather than committed: a
  # hand-maintained secrets.nix can be edited without re-encrypting, which is
  # exactly how a rotated key silently stops working. Here the recipient list in
  # flake.nix is the only place it is written down.
  rulesText =
    cfg:
    let
      entry =
        s:
        "  ${builtins.toJSON s.relPath}.publicKeys = [\n"
        + concatMapStringsSep "\n" (k: "    ${builtins.toJSON k}") s.publicKeys
        + "\n  ];";
    in
    ''
      # Generated by odoo-nix from `odoo-nix.secrets` — do not edit, do not commit.
      #
      # Reached by `edit-secret` and `rekey-secrets`, which export RULES to this
      # store path. To change who can read a secret, edit `recipients` /
      # `hostRecipients` in flake.nix and run `rekey-secrets`.
      {
      ${concatMapStringsSep "\n" entry (secretList cfg)}
      }
    '';

  # What agecheck compares against: { "<relPath>" = [ <pubkey> … ]; }
  rulesJSON =
    cfg:
    builtins.toJSON (
      lib.listToAttrs (map (s: lib.nameValuePair s.relPath s.publicKeys) (secretList cfg))
    );
}
