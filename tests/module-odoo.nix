# NixOS VM test for services.odoo-nix with a REAL Odoo: the fixture's builtOdoo
# for one series. module-nginx.nix keeps a stub so the nginx/socket contract is
# asserted independently of Odoo; this one asserts the module can actually
# bring Odoo up: autoInit's `-i base` in ExecStartPre, the login page through
# nginx (proxy_mode) and directly, and the JSON-RPC version endpoint.
#
# Run: nix build .#checks.<system>.module-odoo-18   (needs KVM)
{
  pkgs,
  odooModule,
  builtOdoo,
  series,
}:
let
  inherit (pkgs) lib;
  major = lib.versions.major series;
in
pkgs.testers.runNixOSTest {
  name = "odoo-nix-module-odoo-${major}";

  nodes.machine =
    { ... }:
    {
      imports = [ odooModule ];
      # `-i base` plus two prefork workers; the stub test's 1024 is not enough.
      virtualisation.memorySize = 2048;
      virtualisation.cores = 2;
      services.odoo-nix = {
        enable = true;
        package = builtOdoo;
        dbName = "odoo";
        database.createLocally = true;
        autoInit = true;
        withoutDemo = true;
        nginx = {
          enable = true;
          domain = "odoo.example.com";
        };
      };
      environment.systemPackages = [ pkgs.curl ];
    };

  testScript = ''
    import json
    from datetime import timedelta

    machine.start()
    machine.wait_for_unit("postgresql-setup.service")
    # ExecStartPre runs `-i base`; the unit only turns active once it finished.
    machine.wait_for_unit("odoo.service", timeout=timedelta(minutes=15))
    machine.succeed("test -e /var/lib/odoo/.odoo-nix-initialized")
    machine.wait_for_open_port(8069)

    # directly on Odoo, and through nginx (named vhost, proxy_mode on)
    machine.wait_until_succeeds(
        "curl -sSf -o /dev/null http://127.0.0.1:8069/web/login",
        timeout=timedelta(minutes=5),
    )
    machine.succeed(
        "curl -sS -o /dev/null -w '%{http_code}' -H 'Host: odoo.example.com'"
        " http://localhost/web/login | grep -x 200"
    )

    info = json.loads(machine.succeed(
        "curl -sSf -H 'Content-Type: application/json'"
        " -d '{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{}}'"
        " http://127.0.0.1:8069/web/webclient/version_info"
    ))
    assert info["result"]["server_serie"] == "${series}", info

    machine.succeed(
        "sudo -u postgres psql -d odoo -tAc"
        " \"select state from ir_module_module where name = 'base'\" | grep -x installed"
    )
  '';
}
