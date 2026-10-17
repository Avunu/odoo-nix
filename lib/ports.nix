# The dev shell's TCP ports, as pure functions so tests/ports-eval.nix can
# call them with any checkout path. modules/devenv.nix calls them with
# `builtins.getEnv`.
#
# Ported from frappe-nix's lib/ports.nix; python-devops-nix PLAN.md, Phase 5
# moves it into the base as `lib.ports`, and both products then import it.
#
# Every port is a fixed base plus one offset, 0..899, decided at evaluation:
# devenv's port allocator is the identity under its flake integration, so
# nothing moves a port that is already taken. Two projects that hash to the
# same offset collide, and the offset is what keeps them apart.
{ lib }:

rec {
  # sha256(seed)[0:4] mod 900, the same hash frappe-nix uses.
  offsetFor =
    seed: lib.mod (lib.fromHexString (builtins.substring 0 4 (builtins.hashString "sha256" seed))) 900;

  # What the offset is hashed from: the project's `name`, so every clone of
  # a project lands on the same ports. With `salt` (`ports.worktreeSalt`), a
  # *linked worktree* (`git worktree add`: its .git is a file, not a
  # directory) adds its path, so two worktrees of one project can run at
  # once; the primary checkout keeps the name's hash.
  #
  #   salt     whether a linked worktree's path goes into the seed
  #   gitKind  what `<pwd>/.git` is: "regular", "directory", or null (absent,
  #            or pure evaluation, where PWD is "")
  seed =
    {
      name,
      salt,
      pwd,
      gitKind,
    }:
    if salt && pwd != "" && gitKind == "regular" then "${name}@${pwd}" else name;

  # ODOO_NIX_PORT_OFFSET as a number, or null when unset. A value that is not
  # 0..899 is ignored with a warning rather than failing evaluation: the shell
  # still opens, on the ports it would have had.
  parseEnvOffset =
    value:
    if value == "" then
      null
    else if builtins.match "[0-9]{1,3}" value != null && lib.toIntBase10 value <= 899 then
      lib.toIntBase10 value
    else
      lib.warn "odoo-nix: ODOO_NIX_PORT_OFFSET=${value} is not a number from 0 to 899; ignored" null;

  # Every port, from one offset. The ranges are clear of frappe-nix's (8000,
  # 3306, 9000, 19000-21000 + offset), so a bench and a project never meet.
  basesFor = offset: {
    http = 10000 + offset;
    gevent = 11000 + offset;
    db = 12000 + offset;
    smtp = 13000 + offset;
    mailUi = 14000 + offset;
  };

  # `<pwd>/.git`'s kind, for `seed`. Impure by nature (it reads the checkout),
  # so modules/devenv.nix calls it and the tests pass `gitKind` directly.
  gitKindAt =
    pwd:
    let
      dotGit = pwd + "/.git";
    in
    if pwd == "" || !(builtins.pathExists dotGit) then null else builtins.readFileType dotGit;
}
