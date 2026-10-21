---
title: The development shell
description: What devenv up runs, how ports are chosen per project, what shell entry does with submodules, odoo.conf and addons_path, how a fresh clone loads, and the CI mode.
nav_title: Development
order: 4
tags: [devenv, development, ports]
updated: 2026-10-21
---

`direnv allow` (or `nix develop --no-pure-eval`) loads the shell. `devenv up` then starts:

- **PostgreSQL** 16, its data under `.devenv/state`, listening on `127.0.0.1` on the project's database port. The role `settings.dbUser` is created as a superuser, and the database `settings.dbName` is created empty.
- **Mailpit**, the mail catcher (`mailpit.enable`, on by default), before the server and whether or not the mail guard is on.
- **odoo**: `odoo-bin -c odoo.conf --dev=all` from the live checkout, threaded, serving HTTP and websockets in one process.

The banner printed on entry names the project, the series, the server's and Mailpit's addresses, and the commands you will use most.

## Ports

Every TCP port the shell binds is a base plus one offset from 0 to 899, hashed from the project's `name`:

| Port                         | Base  | Option          |
| ---------------------------- | ----- | --------------- |
| Odoo HTTP (`http_port`)      | 10000 | `ports.http`    |
| Odoo websockets (`gevent_port`) | 11000 | `ports.gevent` |
| PostgreSQL                   | 12000 | `ports.db`      |
| Mailpit SMTP                 | 13000 | `ports.smtp`    |
| Mailpit web UI               | 14000 | `ports.mailUi`  |

So several projects run at once, and every clone of one project lands on the same ports. A linked worktree (`git worktree add`) hashes `name@<path>` instead and gets its own (`ports.worktreeSalt`). Nothing moves a port that is already taken: set `ports.offset`, or `ODOO_NIX_PORT_OFFSET=<0..899>` for one shell, to pick another offset. `ports.base` pins the HTTP port alone.

The ports used to be fixed (8069, 8072, 5432, 1025, 8025). To keep those:

```nix
odoo-nix.ports = lib.mapAttrs (_: lib.mkForce) {
  http = 8069;
  gevent = 8072;
  db = 5432;
  smtp = 1025;
  mailUi = 8025;
};
```

Only the port moves: devenv rewrites `postgresql.conf` on every start and the data directory stays where it was, so the databases are all there on the new port. The shell exports `ODOO_NIX_HTTP_PORT` and `ODOO_NIX_GEVENT_PORT`.

## What shell entry does

On every entry the shell:

- checks out the git submodules this clone has never had, as partial clones of the branch `.gitmodules` pairs them with: every commit and folder but only the checked-out files, and OCB with its commits only. History works offline, and another branch is one fetch away (`git remote set-branches --add origin 17.0 && git fetch origin`). A submodule you later remove or deinitialize stays out until `odoo project update`, and one that is already checked out is never moved. A shallow submodule gets its branch's history in place, once;
- keeps those clones from growing: it fetches a newly pinned commit the ordinary way before `git submodule update` could lazily download its whole history, merges the packs lazy fetches leave behind, and stops fetches recursing into nested submodules;
- symlinks the synthesized `odoo.conf` into place, and creates the filestore and `custom/` directories;
- on btrfs, keeps a PostgreSQL data directory that does not exist yet off copy-on-write (see [Memory and disk](memory-and-disk.md));
- refreshes the [editor integration](editors.md).

The submodule checkout is `odoo-nix-sources enter`, from python-devops-nix's `lib.sources`. Its messages are `odoo-nix: …` lines on stderr.

## A fresh clone

The project's flake sets `self.submodules = true`, so Nix reads every submodule while it evaluates the flake, which is before the shell exists to check them out. The scaffolded `.envrc` checks them out first:

```bash
if git submodule status --recursive 2> /dev/null | grep '^-' > /dev/null; then
  nix run github:Avunu/odoo-nix#bootstrap -- "$PWD" || true
fi
use flake . --no-pure-eval
```

After the first entry that costs one `git submodule status`. On a fresh clone, `odoo-nix-bootstrap` reads the odoo-nix revision `flake.lock` pins (from the lock alone, since the flake cannot be evaluated yet) and runs that revision's `odoo-nix-sources enter --treeless odoo`, the shell's own checkout. A lock from before `sources` existed, or no lock, gets the bootstrap's own copy. Without direnv, run the `nix run` line by hand before `nix develop --no-pure-eval`.

A project scaffolded before the bootstrap existed has a one-line `.envrc`. See [the troubleshooting entry](../reference/troubleshooting.md#a-fresh-clone-fails-to-evaluate-does-not-appear-to-be-a-git-repository) to unstick it.

## odoo.conf and addons_path

`odoo.conf` is a read-only file in the Nix store, rendered from the `settings.*` options and the derived `addons_path` (`lib/odoo-conf.nix`), and symlinked to `./odoo.conf`. `--dev` stays a command-line flag, so the same file would work in production. Edit the options, not the file; `settings.extra` takes any other `[options]` key.

`addons_path` is derived on every evaluation (`lib/addons.nix`): the two OCB roots (`odoo/odoo/addons` and `odoo/addons`), then each directory under `modules/` that holds at least one module (a child with a `__manifest__.py`), sorted, then `custom/`, then `layout.extraAddons`. With the guard rails on, odoo-nix's own addons directory in the Nix store comes last; it holds only the deprecated `dev_mailcatch` stub. The workspace's entries are relative to it, so the file is the same on every machine. Adding or removing a submodule changes the path by itself, after a `direnv reload`.

## CI mode

`ODOO_NIX_CI` set to anything but empty, `0` or `false` turns the shell into one a script can drive:

```bash
ODOO_NIX_CI=1 nix develop --no-pure-eval -c <COMMAND>
```

It exports `PC_TUI_ENABLED=0` and `DEVENV_IN_DIRENV_SHELL=true` first, so `devenv up` runs from a script, skips the submodule checkout (the job checks out what it needs), and prints the banner as one line: `odoo-nix: CI mode (<name>, Odoo <series>, http <port>)`. It is read when the shell starts, so one shell serves both.

## In this section

- [The odoo command](commands.md) and [Migrations](migrations.md)
- [Manage modules](modules.md)
- [Development guard rails](guard-rails.md)
- [Secrets](secrets.md) and [Restore a production backup](restore-from-production.md)
- [Python dependencies and locks](locks.md)
- [Editors and live reload](editors.md)
- [Memory and disk](memory-and-disk.md)
- [Upgrading odoo-nix](upgrading.md)
