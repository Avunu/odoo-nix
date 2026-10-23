"""journald-native log lines for Odoo under systemd.

Odoo's stderr handler formats records for a terminal:
``2026-01-01 12:00:00,000 1234 INFO acme odoo.http: message``. Under systemd
every line of that lands in the journal at PRIORITY=6 whatever its level, and
the asctime and pid repeat fields journald records itself. Here each record
leaves as

    <N>{logger} [{db}] {message} {perf_info}

(python-devops-nix docs/conventions.md, Journald line format): ``<N>`` the record's
syslog priority on every line of it, tracebacks included, ``[{db}]`` the
database the record belongs to (left out when there is none), and Odoo's
``perf_info`` (query count and times on a request line) after the message.
The core -- priorities, the ``JOURNAL_STREAM`` check, the per-line prefix,
ANSI stripping -- is python-devops-nix's ``_journald.py``; what is Odoo's is
here: who the tenant is, the ``perf_info`` suffix, and where to patch.

Loaded by a ``.pth`` graft (``zzz-odoo-journald.pth``, lib/journald.nix) in
every environment odoo-nix builds, the production one included, so every
interpreter Odoo runs in -- odoo-bin, its prefork workers, the gevent
process it execs, ``odoo-bin shell`` -- gets it with nothing to set. It is
inert unless stderr *is* the journal (``journal_stream()``): the same
environment run from a shell or a captured subprocess keeps Odoo's format.

The ``odoo`` CLI runs on its own interpreter, with the environment on
``PYTHONPATH`` where ``.pth`` files are not processed, so it calls
``install()`` and ``install_root_handler()`` itself (odoo_nix_cli/__main__.py).

Standard library only, written to Python 3.11: it loads into Odoo's own
interpreter, whichever a preset names.
"""

import logging
import sys
import threading

from ._journald import JournaldFormatter, journal_stream

_INSTALLED = False


def tenant(record: logging.LogRecord) -> str | None:
    """The database a record belongs to. 19.0's LogRecord factory sets
    ``record.dbname``; 18.0 sets it in DBFormatter.format(), which this
    formatter replaces, so fall back to the thread attribute that does.
    Odoo's "no database" is ``?``."""
    dbname = getattr(record, "dbname", None)
    if dbname is None:
        dbname = getattr(threading.current_thread(), "dbname", None)
    if not dbname or dbname == "?":
        return None
    return str(dbname)


class OdooFormatter(JournaldFormatter):
    """``<N>{logger} [{db}] {message} {perf_info}``, ``<N>`` on every line."""

    def __init__(self) -> None:
        super().__init__(tenant=tenant)

    def message(self, record: logging.LogRecord) -> str:
        # perf_info: set by Odoo's record factory ("" by default), filled in
        # by the PerfFilter on werkzeug's logger for request lines (through
        # 19.0; 20.0's own odoo.http.server puts the numbers in the message
        # itself).
        text = super().message(record)
        perf_info = getattr(record, "perf_info", "")
        if not perf_info:
            return text
        # After the message line, not after a traceback.
        head, sep, rest = text.partition("\n")
        return f"{head} {perf_info}{sep}{rest}"


def _is_stderr_handler(handler: logging.Handler) -> bool:
    # Exact type: FileHandler and WatchedFileHandler (logging.file) subclass
    # StreamHandler and keep Odoo's format; SysLogHandler (`syslog`) is not a
    # StreamHandler at all.
    return type(handler) is logging.StreamHandler and handler.stream is sys.stderr


def retarget_stderr_handlers() -> None:
    for handler in logging.getLogger().handlers:
        if _is_stderr_handler(handler):
            handler.setFormatter(OdooFormatter())


def patch_netsvc(netsvc) -> None:
    """Wrap init_logger so its stderr handler gets OdooFormatter once Odoo
    has built it. Everything else init_logger does (the LogRecord factory,
    log_handler levels, log_db, the werkzeug PerfFilter, warnings capture) is
    left as Odoo sets it up. Callers reach it as ``odoo.netsvc.init_logger``
    (tools/config.py, 18.0 through 20.0), so replacing the attribute is enough."""
    original = netsvc.init_logger
    if getattr(original, "_odoo_journald", False):
        return

    def init_logger(*args, **kwargs):
        result = original(*args, **kwargs)
        retarget_stderr_handlers()
        return result

    init_logger._odoo_journald = True
    init_logger.__wrapped__ = original
    init_logger.__doc__ = original.__doc__
    netsvc.init_logger = init_logger


def install() -> None:
    """Patch odoo.netsvc as it is imported, when stderr is the journal.

    Importing odoo here to patch it eagerly is not an option: odoo/__init__.py
    branches on sys.argv (gevent's monkey-patching must come before anything
    else is imported), and argv is not final while ``.pth`` files run. So the
    post-import hook waits for the import Odoo does itself and patches the
    module right after it executes, before tools/config.py can call it."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    if not journal_stream():
        return

    from ._hook import on_import

    on_import("odoo.netsvc", patch_netsvc)


def install_root_handler(level: int = logging.WARNING) -> None:
    """For the CLI's in-process commands (``odoo db migrate``, ...), which
    parse odoo.conf with ``setup_logging=False``, so init_logger never runs
    and Python's last-resort handler would print bare WARNING+ messages at
    the journal's default priority. Same threshold, now with priorities.
    Does nothing unless stderr is the journal."""
    if not journal_stream():
        return
    root = logging.getLogger()
    if any(_is_stderr_handler(h) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(OdooFormatter())
    root.addHandler(handler)
