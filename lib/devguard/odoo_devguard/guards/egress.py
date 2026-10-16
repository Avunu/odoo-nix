"""Egress guard: the catch-all.

Refuses every ``connect()`` this process makes to a non-loopback address unless
the destination is allowlisted (``devguard.egress.allowHosts`` /
``ODOO_DEVGUARD_EGRESS_ALLOW_HOSTS``). Odoo's outbound paths are too many to
enumerate -- requests, httpx (openai, ollama), aiohttp (s3fs), urllib3 (plaid),
urllib (currency rates), paramiko (SFTP backups), smtplib, and whatever the
next addon imports -- but they all end in ``socket.socket.connect``.

What passes untouched:

* ``AF_UNIX`` (the dev PostgreSQL socket, the mail catcher if it were a socket)
* loopback and the unspecified address: Mailpit, the longpolling worker,
  queue_job's runner calling back into its own ``/queue_job/runjob``
* anything in ``allow_hosts``: a hostname (``*.example.com`` allowed), an IP
  literal, or a CIDR

Hostname entries are matched against the name a connection was *resolved
from*. Clients resolve first and connect by address -- ``create_connection``,
urllib3, asyncio -- so ``connect()`` only ever sees an IP. ``getaddrinfo`` is
wrapped to remember which names produced which addresses, and an address passes
if a name that resolved to it is allowlisted. One resolved some other way
(aiodns, gevent's resolver, a hard-coded IP) is not remembered, and is refused
unless its address is allowlisted: the gap fails closed. An address that an
allowlisted name shares with another host (a CDN) passes for both.

What this does not see: libpq. psycopg2 opens PostgreSQL connections in C, which
is why the database is neither blocked nor in the allowlist -- and why a
``db_host`` pointing at a remote server is not this guard's business.

Not a firewall for the machine, only for this process tree's Python.
"""

import ipaddress
import socket
import threading

from .._hook import on_import
from .._patch import STATUS, announce, block, require
from .._settings import settings

NAME = "egress"

_INSTALLED = False

#: Warn once per destination: a retry loop would otherwise bury the log.
_WARNED = set()

#: address -> the names getaddrinfo resolved to it, in this process.
_ORIGINS = {}
_ORIGINS_LOCK = threading.Lock()

#: A bound, not a cache policy: past it the map starts over. Clients resolve
#: right before they connect, so starting over loses nothing in use.
_ORIGINS_MAX = 4096

#: The real resolver. A module global looked up at call time, so the unit test
#: can stand DNS in without a network.
_getaddrinfo = socket.getaddrinfo


def enabled():
    return settings().guard_enabled(NAME)


def _parse_allow(entries):
    """Split the allowlist into (names, networks)."""
    names, networks = [], []
    for entry in entries:
        entry = entry.strip().lower()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            names.append(entry)
    return names, networks


def _name_allowed(host, names):
    host = host.lower().rstrip(".")
    for pattern in names:
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) or host == pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


def _is_local(addr):
    return addr.is_loopback or addr.is_unspecified


def _ip(host):
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def _resolve(host):
    """Addresses a hostname maps to, via the original getaddrinfo."""
    try:
        infos = _getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return ()
    return tuple({ip for ip in (_ip(i[4][0]) for i in infos) if ip is not None})


def _origins(addr):
    with _ORIGINS_LOCK:
        return set(_ORIGINS.get(addr, ()))


def _remember(host, infos):
    """Record the addresses a name resolved to. Never fails a resolution."""
    if isinstance(host, bytes):
        try:
            host = host.decode("idna")
        except UnicodeError:
            return
    if not isinstance(host, str) or _ip(host) is not None:
        return
    name = host.lower().rstrip(".")
    if not name:
        return
    addrs = set()
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else None
        if isinstance(sockaddr, tuple) and sockaddr and isinstance(sockaddr[0], str):
            addr = _ip(sockaddr[0])
            if addr is not None:
                addrs.add(addr)
    with _ORIGINS_LOCK:
        if len(_ORIGINS) >= _ORIGINS_MAX:
            _ORIGINS.clear()
        for addr in addrs:
            _ORIGINS.setdefault(addr, set()).add(name)


def getaddrinfo(host, port, *args, **kwargs):
    """``socket.getaddrinfo``, remembering what each name resolved to."""
    infos = _getaddrinfo(host, port, *args, **kwargs)
    _remember(host, infos)
    return infos


def _allowed(host):
    """Whether a connection to HOST (name or literal) may proceed."""
    st = settings()
    names, networks = _parse_allow(st.items(NAME, "allow_hosts"))
    if st.guard_enabled("mail"):
        names.append(st.mail_host.lower())  # the catcher, wherever it listens
    addr = _ip(host)
    if addr is not None:
        # Resolved first, as nearly every client does: allowed if a name that
        # produced this address is.
        return (
            _is_local(addr)
            or any(addr in net for net in networks)
            or any(_name_allowed(name, names) for name in _origins(addr))
        )

    if host.lower().rstrip(".") == "localhost" or _name_allowed(host, names):
        return True
    # A bare name that is not allowlisted may still *resolve* somewhere allowed
    # (an /etc/hosts alias for 127.0.0.1, a CIDR-allowlisted internal name).
    resolved = _resolve(host)
    return bool(resolved) and all(
        _is_local(a) or any(a in net for net in networks) for a in resolved
    )


def _check(sock, address):
    """Raise DevGuardBlocked unless connecting SOCK to ADDRESS is allowed."""
    if not enabled():
        return
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return  # AF_UNIX and friends
    if not isinstance(address, tuple) or not address:
        return
    host = address[0]
    if isinstance(host, bytes):
        host = host.decode("idna")
    if host == "":
        return  # "" is INADDR_ANY for connect: the local host
    if _allowed(host):
        return

    port = address[1] if len(address) > 1 else "?"
    announce(
        NAME,
        "outbound connections from this process are blocked (loopback only). "
        "Allow a host with ODOO_DEVGUARD_EGRESS_ALLOW_HOSTS=host[,host...] or "
        "devguard.egress.allowHosts; ODOO_DEVGUARD_DISABLE=egress turns it off for one command",
    )
    key = (host, port)
    addr = _ip(host)
    resolved_from = sorted(_origins(addr)) if addr is not None else []
    message = f"blocked connection to {host}:{port}"
    if resolved_from:
        message += f" ({', '.join(resolved_from)})"
    if key in _WARNED:
        raise_blocked(message)
    _WARNED.add(key)
    block(NAME, message)


def raise_blocked(message):
    from .._settings import DevGuardBlocked

    raise DevGuardBlocked(f"odoo_devguard[{NAME}]: {message}")


def _wrap(cls, original_connect, original_connect_ex):
    def connect(self, address):
        _check(self, address)
        return original_connect(self, address)

    def connect_ex(self, address):
        _check(self, address)
        return original_connect_ex(self, address)

    cls.connect = connect
    cls.connect_ex = connect_ex


def _patch_stdlib():
    cls = socket.socket
    _wrap(cls, cls.connect, cls.connect_ex)
    STATUS["socket.socket.connect"] = "patched"
    # socket.create_connection, urllib3 and asyncio look this up on the module
    # at call time, so rebinding it reaches them all.
    socket.getaddrinfo = getaddrinfo
    STATUS["socket.getaddrinfo"] = "patched"


def _patch_gevent(module):
    # gevent.monkey.patch_all() swaps socket.socket for gevent's own class, which
    # carries its own connect: the longpolling/websocket worker (`odoo gevent`)
    # would otherwise be unguarded.
    cls = require(module, "socket")
    _wrap(cls, require(cls, "connect"), require(cls, "connect_ex"))


def install():
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    _patch_stdlib()
    on_import("gevent._socket3", _patch_gevent)
