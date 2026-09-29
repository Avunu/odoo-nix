"""journald-native log output for Odoo under systemd.

Odoo's stderr handler formats records for a terminal:
`2026-01-01 12:00:00,000 1234 INFO db odoo.foo: message`. Under systemd
every line of that lands in the journal at PRIORITY=6 whatever its level --
the asctime and pid duplicate fields journald already records, and an ERROR
is indistinguishable from an INFO to anything filtering on priority (Loki's
`level` label, `journalctl -p warning`). journald's stream transport reads an
sd-daemon `<N>` prefix off each line as that line's syslog priority
(SyslogLevelPrefix=, on by default), so the fix is only a formatter: `<N>`
from the record's level, then `dbname logger: message`.

Enabled by `services.odoo-nix` through $ODOO_NIX_JOURNALD, and only when
stderr really is the journal stream ($JOURNAL_STREAM names its device and
inode), so the same package run from a shell -- `machinectl shell`, a
debugging session -- keeps Odoo's own format.

Two ways in, because `odoo` either runs Odoo in-process or execs odoo-bin
(see __main__.py):
  - odoo-bin (the server, its gevent child, `shell`, `-i ... --stop-after-init`):
    a separate interpreter, reached through the sitecustomize in
    _journald_site/, which wraps odoo.netsvc.init_logger as it is imported;
  - the CLI's own commands (`db migrate`, ...) parse odoo.conf with
    setup_logging=False, so init_logger never runs there:
    install_root_handler() gives them a journald handler directly.

Nothing here imports odoo, click or rich: the sitecustomize path runs inside
the project's own Python env, which has none of the CLI's dependencies.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading

ENV_FLAG = "ODOO_NIX_JOURNALD"

# sd-daemon(3) levels. Odoo's extra levels sit between these (RUNBOT = 25,
# DEBUG_RPC = 9, ...), so thresholds rather than an exact lookup.
_PRIORITIES = (
    (logging.CRITICAL, 2),
    (logging.ERROR, 3),
    (logging.WARNING, 4),
    (logging.INFO, 6),
)

# Odoo colours levelname and perf_info only on a tty (or with ODOO_PY_COLORS),
# but a message can carry its own escapes; the journal would store them raw.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def priority(levelno: int) -> int:
    for threshold, prio in _PRIORITIES:
        if levelno >= threshold:
            return prio
    return 7


def stderr_is_journal() -> bool:
    """systemd sets $JOURNAL_STREAM to "<st_dev>:<st_ino>" of the stream it
    connected; comparing against stderr's own fstat is how sd_journal_stream_fd
    consumers are meant to check (systemd.exec(5)) -- the variable alone is
    inherited by anything the service spawns, wherever its stderr points."""
    value = os.environ.get("JOURNAL_STREAM", "")
    dev, _, ino = value.partition(":")
    try:
        st = os.fstat(sys.stderr.fileno())
        return (int(dev), int(ino)) == (st.st_dev, st.st_ino)
    except (AttributeError, OSError, ValueError):
        return False


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1" and stderr_is_journal()


class JournaldFormatter(logging.Formatter):
    """`<N>dbname logger: message [perf_info]`, every line prefixed.

    journald splits a stream on newlines, so a traceback would otherwise
    become one entry at the record's priority followed by a dozen at the
    default -- every line gets the same `<N>`.

    dbname: 19.0's LogRecord factory sets it on the record; 18.0 sets it in
    DBFormatter.format(), which this formatter replaces, so fall back to the
    same thread attribute that does. perf_info (query count/time) is set by
    Odoo's record factory ("" by default) and filled in by the PerfFilter on
    the werkzeug logger for request lines.
    """

    def __init__(self) -> None:
        super().__init__("%(dbname)s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "dbname"):
            record.dbname = getattr(threading.current_thread(), "dbname", "?")
        text = super().format(record)
        perf_info = getattr(record, "perf_info", "")
        if perf_info:
            text = f"{text} {perf_info}"
        prefix = f"<{priority(record.levelno)}>"
        return "\n".join(prefix + line for line in _ANSI.sub("", text).split("\n"))


def _is_stderr_handler(handler: logging.Handler) -> bool:
    # Exact type: FileHandler/WatchedFileHandler (logging.file) subclass
    # StreamHandler and must keep Odoo's format; SysLogHandler (`syslog`)
    # is not a StreamHandler at all.
    return type(handler) is logging.StreamHandler and handler.stream is sys.stderr


def retarget_stderr_handlers() -> None:
    for handler in logging.getLogger().handlers:
        if _is_stderr_handler(handler):
            handler.setFormatter(JournaldFormatter())


def patch_netsvc(netsvc) -> None:
    """Wrap init_logger so its stderr handler gets JournaldFormatter once
    Odoo has built it. Everything else init_logger does (the LogRecord
    factory, log_handler levels, log_db, the werkzeug PerfFilter, warnings
    capture) is left exactly as Odoo sets it up. Callers reach it as
    `odoo.netsvc.init_logger` / `netsvc.init_logger` (tools/config.py, 18.0
    and 19.0), so replacing the module attribute is enough."""
    original = netsvc.init_logger
    if getattr(original, "_odoo_nix_journald", False):
        return

    def init_logger(*args, **kwargs):
        result = original(*args, **kwargs)
        retarget_stderr_handlers()
        return result

    init_logger._odoo_nix_journald = True
    init_logger.__wrapped__ = original
    init_logger.__doc__ = original.__doc__
    netsvc.init_logger = init_logger


class _NetsvcImportHook:
    """sys.meta_path finder that patches odoo.netsvc as it is imported.

    Importing odoo from sitecustomize to patch it eagerly is not an option:
    odoo/__init__.py branches on sys.argv (gevent's monkey-patching must come
    before anything else is imported), and argv is not final that early. So
    wait for the import Odoo does itself, and patch the module right after it
    executes -- before tools/config.py, which imported it, can call it.
    """

    _target = "odoo.netsvc"

    def find_spec(self, fullname, path, target=None):
        if fullname != self._target:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None:
                break
        else:
            return None
        loader = spec.loader
        exec_module = getattr(loader, "exec_module", None)
        if exec_module is None:
            return None

        def patched_exec_module(module):
            exec_module(module)
            patch_netsvc(module)
            if self in sys.meta_path:
                sys.meta_path.remove(self)

        loader.exec_module = patched_exec_module
        return spec


def install_import_hook() -> None:
    netsvc = sys.modules.get("odoo.netsvc")
    if netsvc is not None:
        patch_netsvc(netsvc)
        return
    if not any(isinstance(f, _NetsvcImportHook) for f in sys.meta_path):
        sys.meta_path.insert(0, _NetsvcImportHook())


def install_root_handler(level: int = logging.WARNING) -> None:
    """For the CLI's in-process commands, where init_logger never runs and
    Python's last-resort handler would print bare WARNING+ messages at the
    journal's default priority. Same threshold, now with priorities; the
    CLI's own progress output stays on its rich console (plain lines,
    PRIORITY=6)."""
    root = logging.getLogger()
    if any(_is_stderr_handler(h) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(JournaldFormatter())
    root.addHandler(handler)
