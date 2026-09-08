# NixOS VM test for services.odoo-nix.
#
# Run: nix build .#checks.<system>.module   (needs KVM)
#
# odoo-nix is a library flake: the real Odoo package is assembled by the
# consuming project, so there is nothing here to build a genuine Odoo from.
# Instead a stub package stands in for it — it satisfies the three things the
# module actually consumes from `package` (a `name`, `passthru.addonsPath`, and
# `bin/odoo`) and echoes the request headers it receives back as JSON.
#
# That makes this a test of the module's generated runtime rather than of Odoo:
# the systemd units, the synthesized odoo.conf, and — the reason it exists — the
# nginx front end, including that socket mode forwards the correct client IP and
# public scheme. Those are exactly the things a stub cannot fake away, because
# they are produced by this module and asserted end-to-end through nginx.
{
  pkgs,
  odooModule,
}:
let
  # Stands in for the assembled Odoo. Reads http_interface/http_port out of the
  # generated conf so it binds wherever the module told Odoo to bind, then
  # reflects the request headers so the test can assert what nginx sent.
  stubOdoo =
    pkgs.runCommand "stub-odoo"
      {
        passthru.addonsPath = p: "${p}/addons";
      }
      ''
        mkdir -p $out/bin $out/addons
        cat > $out/bin/odoo <<'EOF'
        #!${pkgs.python3}/bin/python3
        import configparser, json, sys
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        conf_path = sys.argv[sys.argv.index("-c") + 1]
        cp = configparser.ConfigParser()
        cp.read(conf_path)
        opts = cp["options"]
        host = opts.get("http_interface") or "127.0.0.1"
        port = int(opts.get("http_port"))

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                body = json.dumps(
                    {k.lower(): v for k, v in self.headers.items()}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        ThreadingHTTPServer((host, port), H).serve_forever()
        EOF
        chmod +x $out/bin/odoo
      '';

  common = {
    imports = [ odooModule ];
    virtualisation.memorySize = 1024;
    services.odoo-nix = {
      enable = true;
      package = stubOdoo;
      dbName = "odoo";
      database.createLocally = true;
    };
  };
in
pkgs.testers.runNixOSTest {
  name = "odoo-nix";

  nodes = {
    # ---- socket: nginx fronts Odoo over a unix socket, no TCP listener ----
    socket =
      { ... }:
      {
        imports = [ common ];
        services.odoo-nix.nginx = {
          enable = true;
          socketPath = "/run/odoo/nginx.sock";
        };
      };

    # ---- tcp: the pre-existing named-vhost behaviour, plus logging ----
    tcp =
      { ... }:
      {
        imports = [ common ];
        services.odoo-nix.nginx = {
          enable = true;
          domain = "odoo.example.com";
        };
        services.odoo-nix.logging = {
          level = "debug";
          handlers = [ "werkzeug:WARNING" ];
          file = "/var/log/odoo/odoo.log";
          rotate = true;
        };
      };
  };

  testScript = ''
    import json

    start_all()

    for m in (socket, tcp):
        m.wait_for_unit("postgresql.service")
        m.wait_for_unit("odoo-init.service")
        m.wait_for_unit("odoo.service")
        m.wait_for_unit("nginx.service")
        # the synthesized runtime conf is secret-bearing, so it stays 0600
        m.succeed("stat -c '%a' /var/lib/odoo/odoo.conf | grep -x 600")
        # proxy_mode is on whenever nginx fronts Odoo, so werkzeug's ProxyFix
        # honours the X-Forwarded-* headers asserted below
        m.succeed("grep -qE '^proxy_mode\\s*=\\s*True' /var/lib/odoo/odoo.conf")
        # Odoo stays on loopback TCP in both modes
        m.succeed("grep -qE '^http_interface\\s*=\\s*127\\.0\\.0\\.1' /var/lib/odoo/odoo.conf")

    # ---- socket mode ----
    socket.wait_for_file("/run/odoo/nginx.sock")
    # The directory is the access gate: nginx chmods the socket itself to 0666.
    # 0770 rather than 0750 because nginx *creates* its listen socket in here and
    # is only a member of the odoo group, so it needs group write.
    socket.succeed("stat -c '%a %U:%G' /run/odoo | grep -x '770 odoo:odoo'")
    # nginx is in the odoo group so it can traverse that directory
    socket.succeed("id -nG nginx | tr ' ' '\\n' | grep -qx odoo")

    hdrs = json.loads(
        socket.succeed(
            "curl -sS --unix-socket /run/odoo/nginx.sock"
            " -H 'CF-Connecting-IP: 203.0.113.9' http://odoo/"
        )
    )
    # TLS terminated at the edge, so Odoo must be told the public scheme is
    # https even though $scheme over a unix socket is http
    assert hdrs["x-forwarded-proto"] == "https", hdrs
    # the real client IP survives, despite a unix socket having no peer address
    assert hdrs["x-real-ip"] == "203.0.113.9", hdrs
    assert hdrs["x-forwarded-for"] == "203.0.113.9", hdrs

    # nothing listens on the network in socket mode
    socket.fail("curl -sS --max-time 5 http://localhost/")
    socket.fail("ss -HltnO | grep -qE ':80\\s'")

    # ---- tcp mode: untouched ----
    tcp.wait_for_open_port(80)
    hdrs = json.loads(
        tcp.succeed("curl -sS -H 'Host: odoo.example.com' http://localhost/")
    )
    assert hdrs["x-forwarded-proto"] == "http", hdrs
    tcp.succeed("test ! -e /run/odoo/nginx.sock")

    # ---- tcp mode: logging options threaded into the runtime conf ----
    tcp.succeed("grep -qE '^log_level\\s*=\\s*debug' /var/lib/odoo/odoo.conf")
    tcp.succeed("grep -qE '^log_handler\\s*=\\s*werkzeug:WARNING' /var/lib/odoo/odoo.conf")
    tcp.succeed("grep -qE '^logfile\\s*=\\s*/var/log/odoo/odoo\\.log' /var/lib/odoo/odoo.conf")
    # the logfile's parent dir is pre-created and owned by the service user
    tcp.succeed("stat -c '%a %U:%G' /var/log/odoo | grep -x '750 odoo:odoo'")
    # the generated logrotate config (including our stanza) passes its own
    # --debug validation
    tcp.wait_for_unit("logrotate-checkconf.service")
  '';
}
