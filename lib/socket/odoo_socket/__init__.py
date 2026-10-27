"""Unix sockets for Odoo's HTTP and websocket servers.

Odoo binds TCP only, on every series: 18.0 and 19.0 hand ``(interface,
port)`` to werkzeug's threaded server or bind an AF_INET socket for the
prefork workers, 20.0 calls ``socket.create_server`` with an AF_INET family,
and the gevent process binds TCP too. So nginx in front could reach Odoo
only over loopback. With this graft, services.odoo-nix puts each server on a
unix socket of its own instead, through two variables on odoo.service:

    ODOO_NIX_HTTP_SOCKET    the HTTP server: the threaded server
                            (workers = 0, websockets included), or the
                            prefork server's listen socket (workers > 0)
    ODOO_NIX_GEVENT_SOCKET  the gevent/websocket process the prefork server
                            starts (``odoo-bin gevent``)

Each process binds at most one: the gevent process (``odoo.evented``) the
second, every other the first. Unset, nothing is patched.

Where each series binds, and what is done there:

* 18.0, 19.0 threaded: ``ThreadedWSGIServerReloadable(interface, port,
  app)`` gets ``unix://<path>``, which werkzeug's BaseWSGIServer binds as
  AF_UNIX itself; only server_bind is replaced, for a log line that names
  the socket.
* 18.0-20.0 prefork: ``PreforkServer.start`` runs with ``http_enable`` off,
  so it binds nothing (and logs no TCP address), and the socket is bound
  after it. A 19.0+ reload hands the socket to the new process by its fd
  (``ODOO_HTTP_SOCKET_FD``), which Odoo opens as it is.
* 20.0 threaded and gevent: ``odoo.service.server``'s ``socket`` is a facade
  whose ``create_server`` binds the socket when it is asked for the port
  this process would have listened on.
* 18.0, 19.0 gevent: ``gevent.pywsgi.WSGIServer`` is given the socket in
  place of the ``(interface, gevent_port)`` it is constructed with.

A unix-socket peer has no address. werkzeug names it ``("<local>", 0)``;
the prefork workers and 20.0's HTTPSocket index into the address, so every
connection accepted here gets that name too. Behind nginx, proxy_mode puts
the client's own address in its place from X-Forwarded-For. The prefork
workers also set TCP_NODELAY on each connection, which a unix socket
refuses, so the connections they accept ignore TCP-level options.

A socket left behind by an earlier process is replaced, as werkzeug does
for its own unix sockets. Its mode is 0666: the directory around it, 0750
and created by the module, is what keeps it private (python-devops-nix
docs/conventions.md, Unix sockets).

Loaded by a ``.pth`` graft (``zzz-odoo-socket.pth``, lib/python.nix) in every
environment odoo-nix builds. Standard library only, written to Python 3.11:
it loads into Odoo's own interpreter, whichever a preset names.
"""

import logging
import os
import socket
import socketserver
import stat
import sys
import types

HTTP_ENV = "ODOO_NIX_HTTP_SOCKET"
GEVENT_ENV = "ODOO_NIX_GEVENT_SOCKET"

# werkzeug's name for a unix-socket client.
LOCAL = ("<local>", 0)

_logger = logging.getLogger("odoo.service.server")
_INSTALLED = False


def _evented() -> bool:
    return bool(getattr(sys.modules.get("odoo"), "evented", False))


def _path(name: str) -> str | None:
    return os.environ.get(name) or None


def _socket_activated() -> bool:
    # Odoo's own test (18.0 inline, config.http_socket_activation later):
    # systemd handed this very process a listening socket.
    return os.environ.get("LISTEN_FDS") == "1" and os.environ.get("LISTEN_PID") == str(
        os.getpid()
    )


class _UnixConnection(socket.socket):
    """A connection that ignores TCP-level options (TCP_NODELAY)."""

    __slots__ = ()

    def setsockopt(self, level, *args):
        if level == socket.IPPROTO_TCP:
            return None
        return super().setsockopt(level, *args)


class _UnixListener(socket.socket):
    """A listening unix socket whose connections are _UnixConnections,
    accepted as ``LOCAL``. socket.socket.accept, but for the class and the
    address."""

    __slots__ = ()

    def accept(self):
        fd, _ = self._accept()
        conn = _UnixConnection(self.family, self.type, self.proto, fileno=fd)
        if socket.getdefaulttimeout() is None and self.gettimeout():
            conn.setblocking(True)
        return conn, LOCAL


def listen(path: str, backlog: int, cls=None) -> socket.socket:
    """A unix socket listening at ``path``, replacing a stale one.

    ``cls`` is the socket class, ``socket.socket`` looked up now when None:
    in the gevent process that is gevent's, which its server needs."""
    try:
        if stat.S_ISSOCK(os.lstat(path).st_mode):
            os.unlink(path)
    except FileNotFoundError:
        pass
    sock = (cls or socket.socket)(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(path)
        os.chmod(path, 0o666)
        sock.listen(backlog)
    except BaseException:
        sock.close()
        raise
    _logger.info(
        "%s service listening on unix socket %s",
        "Evented" if _evented() else "HTTP",
        path,
    )
    return sock


def _http_listener(path: str, backlog: int) -> socket.socket:
    return listen(path, backlog, cls=_UnixListener)


def patch_threaded_werkzeug(server) -> None:
    """18.0, 19.0: the threaded server binds ``unix://<path>``."""
    cls = server.ThreadedWSGIServerReloadable
    original_init = cls.__init__
    original_bind = cls.server_bind

    def __init__(self, host, port, app, *args, **kwargs):
        path = _path(HTTP_ENV)
        if path and not _evented() and not _socket_activated():
            host, port = f"unix://{path}", 0
        original_init(self, host, port, app, *args, **kwargs)

    def server_bind(self):
        if self.address_family != socket.AF_UNIX:
            return original_bind(self)
        # Odoo's server_bind, less socketserver's getfqdn() of a path.
        self.reload_socket = False
        socketserver.TCPServer.server_bind(self)
        os.chmod(self.server_address, 0o666)
        self.server_name, self.server_port = self.server_address, 0
        _logger.info(
            "HTTP service (werkzeug) listening on unix socket %s", self.server_address
        )
        return None

    cls.__init__ = __init__
    cls.server_bind = server_bind


def patch_prefork(server) -> None:
    """18.0-20.0: the prefork server listens on the socket, its workers
    accept from it."""
    cls = server.PreforkServer
    original_start = cls.start
    config = server.config

    def start(self, *args, **kwargs):
        path = _path(HTTP_ENV)
        if (
            not path
            or not config["http_enable"]
            or os.environ.get("ODOO_HTTP_SOCKET_FD")
            or _socket_activated()
        ):
            result = original_start(self, *args, **kwargs)
        else:
            config["http_enable"] = False
            try:
                result = original_start(self, *args, **kwargs)
            finally:
                config["http_enable"] = True
            self.socket = _http_listener(path, 8 * self.population)
            self.socket.setblocking(False)
        # A 19.0+ reload's socket, opened from its fd as a plain socket.
        sock = self.socket
        if (
            sock is not None
            and sock.family == socket.AF_UNIX
            and not isinstance(sock, _UnixListener)
        ):
            self.socket = _UnixListener(fileno=sock.detach())
            self.socket.setblocking(False)
        return result

    cls.start = start


class _SocketFacade(types.ModuleType):
    """``socket`` as odoo.service.server sees it on 20.0: the module itself,
    but ``create_server`` binds the unix socket when asked for the port this
    process would listen on."""

    def __init__(self, real, config):
        super().__init__(real.__name__, real.__doc__)
        self._real = real
        self._config = config

    def __getattr__(self, name):
        return getattr(self._real, name)

    def create_server(self, address, *args, **kwargs):
        evented = _evented()
        path = _path(GEVENT_ENV if evented else HTTP_ENV)
        port = self._config["gevent_port" if evented else "http_port"]
        if not path or address[1] != port:
            return self._real.create_server(address, *args, **kwargs)
        backlog = kwargs.get("backlog") or 128
        # gevent's server accepts with gevent's socket class.
        return listen(path, backlog) if evented else _http_listener(path, backlog)


def patch_create_server(server) -> None:
    """20.0: the threaded, prefork and gevent servers bind through
    socket.create_server."""
    if not isinstance(server.socket, _SocketFacade):
        server.socket = _SocketFacade(server.socket, server.config)

    # gevent accepts itself, so its connections come with the unix peer's
    # empty address, which HTTPSocket and the error log index into.
    gevent_server = getattr(server, "GeventServer", None)
    original = getattr(gevent_server, "http_client_greenlet", None)
    if original is not None:

        def http_client_greenlet(self, client, address, *args, **kwargs):
            return original(self, client, address or LOCAL, *args, **kwargs)

        gevent_server.http_client_greenlet = http_client_greenlet


def patch_server(server) -> None:
    """odoo.service.server, once it is imported."""
    if hasattr(server, "ThreadedWSGIServerReloadable"):
        patch_threaded_werkzeug(server)
    else:
        patch_create_server(server)
    patch_prefork(server)


def patch_pywsgi(pywsgi) -> None:
    """18.0, 19.0: the gevent process's WSGIServer listens on the socket."""
    cls = pywsgi.WSGIServer
    original_init = cls.__init__
    original_handle = cls.handle

    def __init__(self, listener, *args, **kwargs):
        path = _path(GEVENT_ENV)
        odoo = sys.modules.get("odoo")
        if path and _evented() and isinstance(listener, tuple):
            config = odoo.tools.config
            if listener[1] == config["gevent_port"]:
                listener = listen(path, 128)
        original_init(self, listener, *args, **kwargs)

    def handle(self, sock, address):
        # gevent leaves REMOTE_ADDR out for an empty address, which Odoo's
        # request log reads.
        return original_handle(self, sock, address or LOCAL)

    cls.__init__ = __init__
    cls.handle = handle


def install() -> None:
    """Patch Odoo's servers as they are imported, when a socket is set."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    if not (_path(HTTP_ENV) or _path(GEVENT_ENV)):
        return

    from ._hook import on_import

    on_import("odoo.service.server", patch_server)
    on_import("gevent.pywsgi", patch_pywsgi)
