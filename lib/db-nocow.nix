# Keeps the dev shell's PostgreSQL datadir off btrfs copy-on-write. Ported from
# frappe-nix's lib/db-nocow.nix (there for MariaDB).
#
# PostgreSQL rewrites 8 KB pages in place, all day. On a copy-on-write
# filesystem no write lands in place: each one allocates a new extent,
# rewrites the checksum and extent trees above it, and — on a filesystem
# mounted with compression, which btrfs desktops usually are — compresses the
# page first. The table files fragment within days of a restore, and every
# fsync PostgreSQL issues (each commit, each checkpoint) commits a btrfs
# transaction that other programs' fsyncs then queue behind. `odoo db
# restore`, `-i`/`-u` and the test suite are mostly fsyncs.
#
# The standard remedy is the NOCOW attribute (`chattr +C`), which turns off
# copy-on-write, data checksums and compression for the files it covers. It is
# only honoured on a file that is still empty, so it is set on a *directory*
# and every file and directory created inside inherits it.
#
# Which directory differs from frappe-nix's: devenv runs `initdb` only when
# $PGDATA does not exist, so creating it empty to mark it would leave it never
# initialized. `prepare` instead marks its *parent* while the datadir is still
# missing — initdb's mkdir then inherits the attribute — and clears the
# parent's again on the first entry that finds the datadir there, marked. Only
# what is created in the parent meanwhile (the first `devenv up`'s other state)
# is NOCOW besides, which for dev state costs nothing that matters.
#
# A datadir that already holds a cluster cannot be fixed in place — the
# attribute does not reach existing data — so `prepare` only says so, and
# `migrate` does the copy, with the server stopped.
#
# Not btrfs: both subcommands are silent no-ops.
{ pkgs }:

pkgs.writeShellApplication {
  name = "odoo-nix-db-nocow";
  runtimeInputs = with pkgs; [
    coreutils
    e2fsprogs # chattr, lsattr
    gnugrep
  ];
  text = ''
    usage() {
      echo "usage: odoo-nix-db-nocow prepare <datadir>" >&2
      echo "       odoo-nix-db-nocow migrate <datadir>" >&2
      exit 2
    }

    on_btrfs() {
      [ "$(stat -f -c %T "$1" 2>/dev/null)" = btrfs ]
    }

    # lsattr prints the flags as one word ahead of the name; C is NOCOW.
    has_nocow() {
      lsattr -d -- "$1" 2>/dev/null | cut -d' ' -f1 | grep -q C
    }

    is_empty() {
      [ -z "$(ls -A -- "$1" 2>/dev/null)" ]
    }

    # PostgreSQL's own lock: postmaster.pid names the running server's pid on
    # its first line. Stale after a crash, so the pid has to be alive too.
    server_running() {
      local pid
      [ -f "$1/postmaster.pid" ] || return 1
      pid=$(head -n 1 -- "$1/postmaster.pid")
      [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
    }

    prepare() {
      [ "$#" -eq 1 ] || usage
      local dir parent marker
      dir=''${1%/}
      parent=$(dirname -- "$dir")
      marker="$parent/.odoo-nix-nocow-parent"

      if [ ! -e "$dir" ]; then
        mkdir -p -- "$parent"
        on_btrfs "$parent" || return 0
        has_nocow "$parent" && return 0
        chattr +C -- "$parent"
        : > "$marker"
        return 0
      fi

      # The parent was marked for initdb's sake, and the datadir has it now.
      if [ -e "$marker" ]; then
        chattr -C -- "$parent" 2>/dev/null || true
        rm -f -- "$marker"
      fi

      on_btrfs "$dir" || return 0
      has_nocow "$dir" && return 0
      if is_empty "$dir"; then
        chattr +C -- "$dir"
        return 0
      fi

      echo "⚠  $dir holds a database on btrfs with copy-on-write on."
      echo "   Every database write is copied and compressed, which makes installs,"
      echo "   restores and tests slow and stalls other programs' saves. To fix it,"
      echo "   stop \`devenv up\` and run:  odoo-nix-db-nocow migrate \"$dir\""
    }

    migrate() {
      [ "$#" -eq 1 ] || usage
      local dir
      dir=$(realpath -- "$1")

      if [ ! -d "$dir" ]; then
        echo "odoo-nix-db-nocow: $dir is not a directory" >&2
        exit 1
      fi
      if ! on_btrfs "$dir"; then
        echo "$dir is not on btrfs; nothing to do."
        exit 0
      fi
      if has_nocow "$dir"; then
        echo "$dir already has copy-on-write off; nothing to do."
        exit 0
      fi
      if server_running "$dir"; then
        echo "odoo-nix-db-nocow: PostgreSQL is running on $dir — stop \`devenv up\` first." >&2
        exit 1
      fi

      local need avail
      need=$(du -sb -- "$dir" | cut -f1)
      avail=$(df -B1 --output=avail -- "$dir" | tail -n 1 | tr -d ' ')
      # The copy and the original coexist until the swap at the end, and a
      # btrfs that fills completely is far harder to recover than a refusal.
      if [ "$avail" -lt $((need + need / 10 + 1073741824)) ]; then
        echo "odoo-nix-db-nocow: need about $((need / 1048576)) MiB free beside $dir, have $((avail / 1048576)) MiB." >&2
        exit 1
      fi

      # Not local: the EXIT trap below has to see it however the script ends.
      tmp="$dir.nocow-$$"
      backup="$dir.cow-backup-$(date +%Y%m%d-%H%M%S)"

      trap 'rm -rf -- "$tmp"' EXIT
      mkdir -- "$tmp"
      chattr +C -- "$tmp"

      echo "Copying $((need / 1048576)) MiB into a copy-on-write-free directory…"
      # --reflink=never: a reflink would share the original's copy-on-write
      # extents, which is the one thing this copy exists to get rid of (btrfs
      # refuses to clone between COW and NOCOW files anyway). cp does not carry
      # inode flags across, so every copied file takes +C from $tmp. -a keeps
      # the 0700 mode PostgreSQL insists on for its datadir.
      cp -a --reflink=never -- "$dir/." "$tmp/"
      chmod --reference="$dir" -- "$tmp"
      sync -f -- "$tmp"

      mv -- "$dir" "$backup"
      mv -- "$tmp" "$dir"
      trap - EXIT

      echo "Done. The original is kept at:"
      echo "  $backup"
      echo "Start \`devenv up\`, check Odoo works, then remove it:"
      echo "  rm -rf \"$backup\""
    }

    [ "$#" -ge 1 ] || usage
    cmd=$1
    shift
    case $cmd in
      prepare) prepare "$@" ;;
      migrate) migrate "$@" ;;
      *) usage ;;
    esac
  '';
}
