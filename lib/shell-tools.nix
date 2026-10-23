# The dev shell's commands that come from python-devops-nix (docs/library.md,
# Development shell), configured for odoo-nix in one place: modules/devenv.nix, the scaffolder
# (lib/init.nix) and the flake's checks all take them from here.
#
#   odoo-nix-sources    lib.sources.command: shell entry's submodule checkout
#                       (`enter --treeless <coreSrc> ROOT`) and the first clone
#                       of a source repository (`clone`), as partial clones of
#                       the paired branch. Every submodule is a source (no
#                       scope), and a checkout recurses into its own submodules.
#                       The core path is passed at run time (`--treeless`), so
#                       one command serves every layout.
#   odoo-nix-bootstrap  lib/bootstrap.sh: odoo-nix-sources from the revision a
#                       project's flake.lock pins, run before Nix evaluates
#                       the project's flake, which reads its submodules. A
#                       project's .envrc runs it on a fresh clone
#                       (`nix run github:Avunu/odoo-nix#bootstrap`), OCB
#                       (odoo/) commits-only when the project has it there.
#   odoo-nix-db-nocow   lib.dbNocow: the dev PostgreSQL datadir off btrfs
#                       copy-on-write. devenv runs initdb only when $PGDATA is
#                       missing, so the parent is marked until it has made it;
#                       a running server is a live postmaster.pid.
#   odoo-nix-banner     lib.banner.command: the welcome banner, from a JSON spec
#                       (lib.banner.script).
#
#   import ./lib/shell-tools.nix { inherit pkgs; base = inputs.python-devops-nix.lib; python = cfg.python; }
{
  pkgs,
  base,
  # The tools' interpreter (python-devops-nix docs/library.md, Python
  # versions: out-of-process tools).
  # The dev shell passes the project's, so the shell carries no second one.
  python ? pkgs.python3,
}:
rec {
  sources = base.sources.command {
    inherit pkgs python;
    label = "odoo-nix";
    noun = "project";
    recursive = true;
    updateCommand = "odoo project update";
  };

  bootstrap = pkgs.writeShellApplication {
    name = "odoo-nix-bootstrap";
    runtimeInputs = [
      pkgs.git
      pkgs.gnugrep
      pkgs.coreutils
    ];
    text = ''
      LABEL=odoo-nix
      INPUT=odoo-nix
      SOURCES=${pkgs.lib.getExe sources}
      LOCKREF=${./bootstrap-lock.nix}
      STATUS=--recursive
      TREELESS=odoo
    ''
    + builtins.readFile ./bootstrap.sh;
    meta.description = "Check out a fresh clone's submodules before Nix evaluates the project's flake";
  };

  dbNocow = base.dbNocow {
    inherit pkgs;
    label = "odoo-nix";
    strategy = "parent";
    server = "pidfile";
  };

  banner = base.banner.command {
    inherit pkgs python;
    name = "odoo-nix-banner";
  };
}
