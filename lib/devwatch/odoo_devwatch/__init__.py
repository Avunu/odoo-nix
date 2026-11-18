"""Leave build trees and other roots out of Odoo's autoreload watcher.

Odoo's ``--dev=reload`` watcher schedules one watchdog observer per entry of
``odoo.addons.__path__``, and watchdog starts two threads for each one. An
addon installed in editable mode leaves a ``build/__editable__`` tree on that
path. Its links point into a module the addons path already covers, so the
watcher pays two threads per addon for nothing. Those threads reserve address
space, which Odoo's virtual-memory soft limit counts, and a dev server with
enough of them restarts itself on every boot.

Two variables, each a list of shell-style patterns (``fnmatch``: ``*`` also
matches ``/``) separated by ``:``:

``ODOO_NIX_WATCH_EXCLUDE``
    Roots the watcher does not schedule, whatever they hold. When such a root
    holds code that no other watched root covers, a warning says that edits
    under it will not reload.

``ODOO_NIX_WATCH_EXCLUDE_IF_COVERED``
    Roots left out only where the code their links reach is watched through
    another root. Every existing link must lead into a watched root. If one
    does not, the root stays watched and a warning says why. A dangling link
    has no code, so it does not count against the exclusion.

Only the watcher's view is filtered, for the length of its constructor: every
entry stays on ``odoo.addons.__path__``, so imports resolve exactly as before.
Constructions are serialised by a lock. Odoo builds its watcher once, in
start-up, before its server threads run; an import from another thread during
that window would not see the filtered roots, which is why the window is kept
to the constructor.

Unset or empty, nothing is patched.

Loaded by a ``.pth`` graft (``zzz-odoo-devwatch.pth``, lib/python.nix) in the
development and test environments, never in production. Standard library
only, written to Python 3.11.
"""

import fnmatch
import functools
import logging
import os
import threading

from ._hook import on_import

EXCLUDE_ENV = "ODOO_NIX_WATCH_EXCLUDE"
COVERED_ENV = "ODOO_NIX_WATCH_EXCLUDE_IF_COVERED"

#: The logger odoo.service.server writes its own autoreload lines with.
_log = logging.getLogger("odoo.service.server")

#: The watcher classes odoo.service.server defines: watchdog's, then the
#: inotify package's (Odoo prefers it when it can import it).
WATCHERS = ("FSWatcherWatchdog", "FSWatcherInotify")

#: Serialises the filtered constructions. Re-entrant, so a watcher built inside
#: another's constructor cannot deadlock.
_LOCK = threading.RLock()

_INSTALLED = False


def patterns(name, environ=None):
    """The patterns in one variable: entries stripped, empty ones dropped."""
    raw = (os.environ if environ is None else environ).get(name, "")
    return tuple(p.strip() for p in raw.split(":") if p.strip())


def excluded(path, pats):
    """True when ``path`` matches one of ``pats`` (case-sensitive ``fnmatch``)."""
    return any(fnmatch.fnmatchcase(path, pat) for pat in pats)


def _under(path, root):
    return path == root or path.startswith(root + os.sep)


def _links_covered(root, watched):
    """True when every existing module ``root`` links to lies under a watched root.

    An editable install's build tree holds links into the module source. A link
    that resolves to nothing has no code to lose, so it does not keep the root
    watched. One that resolves to code outside every watched root does: the
    root is then the only thing watching that code, and it stays.

    A root that does not exist has nothing to lose. A root that exists but
    cannot be listed might hold anything, so it is not treated as covered.
    """
    if not os.path.isdir(root):
        return True
    try:
        names = os.listdir(root)
    except OSError:
        return False
    for name in names:
        target = os.path.realpath(os.path.join(root, name))
        if os.path.exists(target) and not any(_under(target, w) for w in watched):
            return False
    return True


def _wrap_init(cls, explicit, covered):
    original = cls.__init__

    @functools.wraps(original)
    def __init__(self, *args, **kwargs):
        import odoo.addons

        with _LOCK:
            namespace = odoo.addons.__path__
            full = list(namespace)

            def guarded(path):
                return excluded(path, explicit) or excluded(path, covered)

            # The roots that stay watched whatever the patterns say: the cover
            # an excluded root's links must fall under to be dropped.
            watched = [os.path.realpath(p) for p in full if not guarded(p)]
            kept = []
            for path in full:
                if excluded(path, explicit):
                    if _links_covered(path, watched):
                        _log.info("autoreload: not watching %s (%s)", path, EXCLUDE_ENV)
                    else:
                        _log.warning(
                            "autoreload: %s is excluded by %s, and its code is not "
                            "watched through any other root: edits under it will not reload",
                            path,
                            EXCLUDE_ENV,
                        )
                elif excluded(path, covered):
                    if _links_covered(path, watched):
                        _log.info("autoreload: not watching %s (%s)", path, COVERED_ENV)
                    else:
                        _log.warning(
                            "autoreload: %s matches %s, but its code is not watched "
                            "through any other root; watching it",
                            path,
                            COVERED_ENV,
                        )
                        kept.append(path)
                else:
                    kept.append(path)
            # The watcher reads odoo.addons.__path__ in its constructor and
            # nowhere else. Restore the full list even if the constructor
            # raises, so the import path never sees the filtered view.
            namespace[:] = kept
            try:
                original(self, *args, **kwargs)
            finally:
                namespace[:] = full

    __init__._odoo_devwatch = True
    cls.__init__ = __init__


def patch_server(server, explicit=(), covered=()):
    """Filter the watchers of ``odoo.service.server`` once it is imported."""
    patched = 0
    for name in WATCHERS:
        cls = getattr(server, name, None)
        if cls is None:
            continue
        if not getattr(cls.__init__, "_odoo_devwatch", False):
            _wrap_init(cls, tuple(explicit), tuple(covered))
        patched += 1
    if not patched:
        _log.warning(
            "autoreload: odoo.service.server defines none of %s, so %s and %s have no effect",
            ", ".join(WATCHERS),
            EXCLUDE_ENV,
            COVERED_ENV,
        )


def install():
    """Register the patch for ``odoo.service.server``, when any pattern is set."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    explicit = patterns(EXCLUDE_ENV)
    covered = patterns(COVERED_ENV)
    if not (explicit or covered):
        return
    on_import(
        "odoo.service.server",
        lambda server: patch_server(server, explicit, covered),
    )
