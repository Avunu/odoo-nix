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

What this does not see: libpq. psycopg2 opens PostgreSQL connections in C, which
is why the database is neither blocked nor in the allowlist -- and why a
``db_host`` pointing at a remote server is not this guard's business.

Not a firewall for the machine, only for this process tree's Python.
"""

import ipaddress
import socket

from .._hook import on_import
from .._patch import STATUS, announce, block, require
from .._settings import settings

NAME = "egress"

_INSTALLED = False

#: Warn once per destination: a retry loop would otherwise bury the log.
_WARNED = set()

#: host -> frozenset of resolved addresses, for allowlisted hostnames.
_RESOLVED = {}


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
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return ()
    return tuple({ip for ip in (_ip(i[4][0]) for i in infos) if ip is not None})


def _allowed(host):
    """Whether a connection to HOST (name or literal) may proceed."""
    st = settings()
    names, networks = _parse_allow(st.items(NAME, "allow_hosts"))
    if st.guard_enabled("mail"):
        names.append(st.mail_host.lower())  # the catcher, wherever it listens
    addr = _ip(host)
    if addr is not None:
        return _is_local(addr) or any(addr in net for net in networks)

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
    message = f"blocked connection to {host}:{port}"
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
