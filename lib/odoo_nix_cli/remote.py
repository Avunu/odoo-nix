"""Remote backup store: list, fetch and mirror, over S3 (via minio-client) or a
plain directory.

Standard library only, and no `odoo` import: `setup-backup-access` runs this
file directly (`python remote.py list`) to test credentials before encrypting
them, and the CLI imports it for `odoo db restore`.

Connection comes from the BACKUPS_* variables in the backup-access secret
(see modules/secrets.nix):

    BACKUPS_URL  BACKUPS_ACCESS_KEY  BACKUPS_SECRET_KEY  BACKUPS_BUCKET
    BACKUPS_PREFIX (optional)

Layout: <bucket>/<prefix>/<database>/<YYYY_MM_DD_HH_MM_SS>.dump[.zip] -- the
naming OCA auto_backup and `odoo db backup` already write.

Overrides, mostly for tests:

    ODOO_NIX_BACKUP_SOURCE  a directory (or any `mc` target) laid out as above,
                            used instead of BACKUPS_*
    ODOO_NIX_MC             the minio-client binary (default: `mc` on PATH)
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

#: Same shape auto_backup's `filename()` writes. Anything else in the folder
#: (notes, partial uploads) is not a backup.
BACKUP_RE = re.compile(r"^\d{4}(_\d\d){5}\.dump(\.zip)?$")

ALIAS = "odoonix"


class RemoteError(Exception):
    """A user-facing failure (missing credentials, nothing found, ...)."""


def _mc() -> str:
    return os.environ.get("ODOO_NIX_MC") or "mc"


def _run_mc(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run([_mc(), *args], capture_output=True, text=True, check=False)  # noqa: S603
    except FileNotFoundError as exc:
        raise RemoteError(f"minio-client ('{_mc()}') not found -- run inside the odoo-nix dev shell.") from exc
    if check and proc.returncode != 0:
        raise RemoteError(f"mc {' '.join(args[:2])} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc


def _missing_credentials() -> list[str]:
    needed = ("BACKUPS_URL", "BACKUPS_ACCESS_KEY", "BACKUPS_SECRET_KEY", "BACKUPS_BUCKET")
    return [name for name in needed if not os.environ.get(name)]


def has_credentials() -> bool:
    return bool(os.environ.get("ODOO_NIX_BACKUP_SOURCE")) or not _missing_credentials()


@contextlib.contextmanager
def store() -> Iterator[str]:
    """Yield the base location backups live under (`<alias>/<bucket>/<prefix>`
    or a directory), with a throwaway mc config for the duration."""
    source = os.environ.get("ODOO_NIX_BACKUP_SOURCE")
    if source:
        yield source.rstrip("/")
        return
    missing = _missing_credentials()
    if missing:
        raise RemoteError(
            f"missing {', '.join(missing)} -- run `setup-backup-access` (and decrypt via the dev shell)."
        )
    with tempfile.TemporaryDirectory(prefix="odoo-nix-mc-") as tmp:
        # Written directly rather than `mc alias set` (secret in argv) or
        # MC_HOST_<alias> (breaks on secrets containing / or +).
        config = {
            "version": "10",
            "aliases": {
                ALIAS: {
                    "url": os.environ["BACKUPS_URL"],
                    "accessKey": os.environ["BACKUPS_ACCESS_KEY"],
                    "secretKey": os.environ["BACKUPS_SECRET_KEY"],
                    "api": "S3v4",
                    "path": "auto",
                }
            },
        }
        Path(tmp, "config.json").write_text(json.dumps(config))
        Path(tmp, "config.json").chmod(0o600)
        os.environ["MC_CONFIG_DIR"] = tmp
        prefix = os.environ.get("BACKUPS_PREFIX", "").strip("/")
        try:
            yield "/".join(p for p in (ALIAS, os.environ["BACKUPS_BUCKET"], prefix) if p)
        finally:
            os.environ.pop("MC_CONFIG_DIR", None)


def _is_dir(location: str) -> bool:
    """Whether the store is a plain directory (ODOO_NIX_BACKUP_SOURCE) rather
    than an mc target. Decided by the store's root, so a database folder that
    does not exist yet is an empty listing, not an attempt to ask mc."""
    return os.path.isdir(os.environ.get("ODOO_NIX_BACKUP_SOURCE", ""))


def is_local() -> bool:
    """True when the store is a directory, so there is nothing to mirror from."""
    return _is_dir("")


def _ls(location: str) -> list[tuple[str, bool, int]]:
    """(name, is_folder, size) for each entry directly under LOCATION."""
    if _is_dir(location):
        if not os.path.isdir(location):
            return []
        return [(p.name, p.is_dir(), p.stat().st_size if p.is_file() else 0) for p in Path(location).iterdir()]
    proc = _run_mc("ls", "--json", location + "/")
    entries = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("status") == "error":
            raise RemoteError(str(item.get("error", {}).get("message", item)))
        entries.append((item["key"].rstrip("/"), item.get("type") == "folder", int(item.get("size", 0))))
    return entries


def list_databases(base: str) -> list[str]:
    return sorted(name for name, is_folder, _ in _ls(base) if is_folder)


def list_backups(base: str, db: str) -> list[tuple[str, int]]:
    """Backups for DB as (filename, size), oldest first. Filenames sort
    chronologically, which is the whole retention/selection algorithm."""
    found = [(n, s) for n, is_folder, s in _ls(f"{base}/{db}") if not is_folder and BACKUP_RE.match(n)]
    return sorted(found)


def pick(backups: list[tuple[str, int]], at: str | None) -> tuple[str, int]:
    """Newest backup, or the newest one whose name starts with AT (any prefix of
    YYYY_MM_DD_HH_MM_SS; dashes/colons/T are accepted as separators)."""
    if not backups:
        raise RemoteError("no backups found")
    if not at:
        return backups[-1]
    wanted = re.sub(r"[-:T ]", "_", at)
    matching = [b for b in backups if b[0].startswith(wanted)]
    if not matching:
        raise RemoteError(f"no backup matching '{at}' (newest is {backups[-1][0]})")
    return matching[-1]


def fetch(base: str, db: str, cache_dir: Path, at: str | None = None, use_cache: bool = True, keep: int = 2) -> Path:
    """Download the chosen backup into CACHE_DIR/<db>/ and return its path.

    Written to a .partial file and size-checked before the rename, so an
    interrupted download is never mistaken for a backup. The newest KEEP
    backups stay cached.
    """
    backups = list_backups(base, db)
    if not backups:
        raise RemoteError(f"no backups found for database '{db}' (see `list` for the databases in the store)")
    name, size = pick(backups, at)
    dest_dir = cache_dir / db
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if use_cache and dest.is_file() and dest.stat().st_size == size:
        return dest
    partial = dest.with_name(name + ".partial")
    partial.unlink(missing_ok=True)
    src = f"{base}/{db}/{name}"
    if _is_dir(src):
        shutil.copyfile(src, partial)
    else:
        _run_mc("cp", "--quiet", src, str(partial))
    if partial.stat().st_size != size:
        partial.unlink(missing_ok=True)
        raise RemoteError(f"incomplete download of {name}")
    partial.replace(dest)
    for stale in sorted(p for p in dest_dir.iterdir() if BACKUP_RE.match(p.name))[:-keep]:
        stale.unlink()
    return dest


def mirror(source: str, dest: Path) -> None:
    """Mirror a bucket path (e.g. `bucket/prefix`, the attachment storage's
    directory path) into DEST; repeat runs only copy what changed."""
    dest.mkdir(parents=True, exist_ok=True)
    _run_mc("mirror", "--overwrite", "--quiet", f"{ALIAS}/{source.strip('/')}", str(dest))


def main(argv: list[str]) -> int:
    usage = "usage: remote.py list [DB] | fetch DB [--at TS] [--cache DIR]"
    if not argv:
        print(usage, file=sys.stderr)
        return 2
    try:
        with store() as base:
            if argv[0] == "list":
                if len(argv) > 1:
                    print("\n".join(n for n, _ in list_backups(base, argv[1])))
                else:
                    print("\n".join(list_databases(base)))
            elif argv[0] == "fetch" and len(argv) > 1:
                at = argv[argv.index("--at") + 1] if "--at" in argv else None
                cache = Path(argv[argv.index("--cache") + 1]) if "--cache" in argv else Path(tempfile.gettempdir())
                print(fetch(base, argv[1], cache, at))
            else:
                print(usage, file=sys.stderr)
                return 2
    except RemoteError as exc:
        print(f"odoo-nix: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
