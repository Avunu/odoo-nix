---
title: Memory and disk
description: What the dev shell does to keep PostgreSQL off btrfs copy-on-write, the submodule clones small, and the numeric libraries to one thread each.
order: 9
tags: [performance, btrfs, postgresql, git]
updated: 2026-10-21
---

## PostgreSQL off copy-on-write

PostgreSQL rewrites pages in place. On btrfs, copy-on-write turns every such write into a new extent, compressed first on the compressed mounts btrfs desktops usually have, and every fsync into a filesystem transaction that other programs' saves wait behind.

`postgres.noCow` (on by default, Linux only) keeps the dev data directory off copy-on-write with `chattr +C`. The attribute only reaches files created after it is set, so shell entry arranges it for a data directory that `initdb` has not created yet. A cluster that already exists is reported, not touched. To move one across, stop `devenv up` and run, once:

```bash
odoo-nix-db-nocow migrate "$PGDATA"
```

It copies the stopped cluster into a NOCOW directory and keeps its mode 0700. On any other filesystem the option does nothing. It is python-devops-nix's `lib.dbNocow`.

## Small submodule clones

OCB's history is large, and a project carries dozens of module repositories. Shell entry, the scaffolder and `odoo module add` clone them all as partial clones of their paired branch: every commit and folder, but only the checked-out files. OCB gets its commits alone, since its folder history is enormous. History still works offline, and a file's old contents are fetched when first asked for.

On every entry the shell also stops those clones from growing behind your back: it fetches a newly pinned commit the ordinary way before `git submodule update` could lazily download its whole history, merges the small packs that lazy fetches leave, and keeps fetches from recursing into nested submodules. A submodule that was cloned shallow gets its branch's history in place, once. See [What shell entry does](README.md#what-shell-entry-does).

## One thread per numeric library

The dev shell, the production units and the container image all set `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `NUMEXPR_NUM_THREADS` to 1 (python-devops-nix's `lib.python.threadCaps`). NumPy, SciPy and pandas, any of which a module may pull in, size their pools to the host's CPU count on import. A request-serving process gains nothing from that: the pools cost threads in every worker, can fail outright on a many-core host (`OpenBLAS blas_thread_init: pthread_create failed`), and do not survive a forking server's fork cleanly.

## The restore cache

`odoo db restore` keeps downloaded backups in `.devenv/state/odoo-nix/restore/`: the one just fetched and one other, so a large backup is not downloaded twice and the cache does not grow without bound. See [Restore a production backup](restore-from-production.md).
