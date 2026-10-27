# NixOS VM test for services.odoo-nix on unix sockets end to end, with a REAL
# Odoo (the fixture's production-shaped CLI package for one series): the
# tunnel connector's side is nginx's socket, nginx reaches Odoo's HTTP server
# and its websocket server over sockets of their own, and nothing listens on
# TCP. What it asserts is the odoo_socket graft (lib/socket) inside Odoo:
#
#   - prefork (workers = 2): the workers accept from http.socketPath and the
#     gevent process listens on http.longpollingSocketPath; the login page
#     and a websocket handshake (101, then a close frame each way) through
#     nginx, and straight on each of Odoo's sockets, where the peer has no
#     address at all;
#   - the client's address from CF-Connecting-IP reaches Odoo's request log
#     (proxy_mode), though no hop in between has one;
#   - threaded (workers = 0, a specialisation): one socket answers both, and
#     nginx sends /websocket to it;
#   - no TCP listener in either: not nginx, not Odoo.
#
# Run: nix build .#checks.<system>.socket-18   (needs KVM)
{
  pkgs,
  odooModule,
  odooCli,
}:
let
  inherit (pkgs) lib;

  # A websocket handshake on a unix socket, then a masked close frame, and
  # the server's close frame back: the upgrade reached Odoo's websocket loop
  # and data flows both ways after it.
  wsProbe = pkgs.writeText "ws-probe.py" ''
    import os
    import socket
    import sys

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect(sys.argv[1])
    sock.sendall(
        b"GET /websocket HTTP/1.1\r\n"
        b"Host: odoo\r\n"
        # Odoo refuses a handshake without one (400).
        b"Origin: https://odoo\r\n"
        b"Upgrade: websocket\r\n"
        b"Connection: Upgrade\r\n"
        b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        b"Sec-WebSocket-Version: 13\r\n"
        b"CF-Connecting-IP: 203.0.113.9\r\n"
        b"\r\n"
    )
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            sys.exit(f"closed before the handshake ended: {buf!r}")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    status = head.split(b"\r\n", 1)[0]
    print(status.decode())
    if status.split()[1] != b"101":
        sys.exit(f"no upgrade: {head!r}")

    mask = os.urandom(4)
    payload = (1000).to_bytes(2, "big")
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes([0x88, 0x80 | len(payload)]) + mask + masked)
    while len(rest) < 2:
        chunk = sock.recv(4096)
        if not chunk:
            sys.exit("closed without a close frame")
        rest += chunk
    if rest[0] & 0x0F != 0x8:
        sys.exit(f"expected a close frame, got {rest[:8]!r}")
    print("close frame")
  '';
in
# A test module: tests/series.nix registers it with lib.checks.mk's
# nixosTest, which names it.
{
  nodes.machine =
    { ... }:
    {
      imports = [ odooModule ];
      # `-i base` plus two prefork workers, as service-<major>.
      virtualisation.memorySize = 2048;
      virtualisation.cores = 2;
      services.odoo-nix = {
        enable = true;
        package = odooCli;
        dbName = "acme";
        database.createLocally = true;
        autoInit = true;
        withoutDemo = true;
        workers = 2;
        http = {
          socketPath = "/run/odoo-http/http.sock";
          longpollingSocketPath = "/run/odoo-http/websocket.sock";
        };
        nginx = {
          enable = true;
          socketPath = "/run/odoo/nginx.sock";
        };
      };
      environment.systemPackages = [
        pkgs.curl
        pkgs.iproute2
      ];

      specialisation.threaded.configuration.services.odoo-nix = {
        workers = lib.mkForce 0;
        http.longpollingSocketPath = lib.mkForce "";
      };
    };

  testScript = ''
    from datetime import timedelta

    def login(sock, extra=""):
        return machine.succeed(
            f"curl -sS -o /dev/null -w '%{{http_code}}' --unix-socket {sock} {extra} http://odoo/web/login"
        ).strip()

    def websocket(sock):
        out = machine.succeed("${pkgs.python3.interpreter} ${wsProbe} " + sock)
        assert "101" in out and "close frame" in out, out

    def no_tcp():
        # Not nginx (80), not Odoo (8069, 8072).
        listening = machine.succeed("ss -Hltn").strip()
        for port in (":80 ", ":8069 ", ":8072 "):
            assert port not in listening + " ", listening

    def ready():
        machine.wait_for_unit("odoo.service", timeout=timedelta(minutes=15))
        machine.wait_for_unit("nginx.service")
        machine.wait_for_file("/run/odoo-http/http.sock")
        machine.wait_until_succeeds(
            "curl -sSf -o /dev/null --unix-socket /run/odoo/nginx.sock http://odoo/web/login",
            timeout=timedelta(minutes=5),
        )

    machine.start()
    ready()

    with subtest("prefork: the workers' socket and the gevent process's"):
        machine.wait_for_file("/run/odoo-http/websocket.sock")
        # Odoo creates them in a 0750 directory nginx traverses as a group
        # member; the sockets' own mode does not gate (0666).
        machine.succeed("stat -c '%a %U:%G' /run/odoo-http | grep -x '750 odoo:odoo'")
        for sock in ("http.sock", "websocket.sock"):
            machine.succeed(f"stat -c '%a %U %F' /run/odoo-http/{sock} | grep -x '666 odoo socket'")
        # through nginx, with the client's address from Cloudflare's header
        assert login("/run/odoo/nginx.sock", "-H 'CF-Connecting-IP: 203.0.113.9'") == "200"
        # straight on Odoo's socket: no proxy headers, a peer with no address
        assert login("/run/odoo-http/http.sock") == "200"
        no_tcp()

    with subtest("prefork: websockets through nginx and on the gevent socket"):
        websocket("/run/odoo/nginx.sock")
        websocket("/run/odoo-http/websocket.sock")

    with subtest("the client's address reaches Odoo's request log"):
        machine.wait_until_succeeds(
            "journalctl -u odoo.service -o cat --no-pager | grep -F /web/login | grep -qF 203.0.113.9"
        )

    with subtest("threaded: one socket answers /websocket too"):
        machine.succeed("/run/booted-system/specialisation/threaded/bin/switch-to-configuration test")
        ready()
        machine.succeed("systemctl show odoo -P Environment | grep -v -q ODOO_NIX_GEVENT_SOCKET")
        assert login("/run/odoo/nginx.sock", "-H 'CF-Connecting-IP: 203.0.113.9'") == "200"
        assert login("/run/odoo-http/http.sock") == "200"
        websocket("/run/odoo/nginx.sock")
        websocket("/run/odoo-http/http.sock")
        no_tcp()
  '';
}
