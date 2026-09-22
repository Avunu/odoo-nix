# NixOS VM test for services.odoo-nix with a REAL Odoo: the fixture's
# production-shaped CLI package for one series. module-nginx.nix keeps a stub
# so the nginx/socket contract is asserted independently of Odoo; this one
# asserts the module can actually bring Odoo up -- and keep the schema in
# step with the code across deploys:
#
#   - first boot: odoo-migrate provisions the empty database (autoInit) before
#     odoo.service starts; the login page through nginx (proxy_mode) and
#     directly, and the JSON-RPC version endpoint;
#   - a restart of the same build: the migration is a no-op;
#   - a deploy of v2 (specialisation): the fixture is updated, its migration
#     runs, its new column exists;
#   - a deploy of v3, whose migration fails after committing: rolled back,
#     and odoo.service stays DOWN rather than serving v3 on v2's schema;
#   - redeploying v2 recovers.
#
# Run: nix build .#checks.<system>.module-odoo-18   (needs KVM)
{
  pkgs,
  odooModule,
  odooCli,
  odooCliV2,
  odooCliV3,
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
        package = odooCli;
        # Deliberately not the role's name: a database named after the
        # project, owned by the "odoo" role, is the production shape (and
        # nixpkgs' ensureDBOwnership cannot express it).
        dbName = "acme";
        database.createLocally = true;
        autoInit = true;
        withoutDemo = true;
        nginx = {
          enable = true;
          domain = "odoo.example.com";
        };
      };
      # Provisioning installs base plus modules.txt (relative to the unit's
      # WorkingDirectory, the state dir): the fixture has to be installed for
      # the v2/v3 deploys to have anything to migrate.
      systemd.tmpfiles.rules = [ "f /var/lib/odoo/modules.txt 0644 odoo odoo - odoo_nix_fixture" ];
      environment.systemPackages = [ pkgs.curl ];

      specialisation = {
        v2.configuration.services.odoo-nix.package = lib.mkForce odooCliV2;
        v3.configuration.services.odoo-nix.package = lib.mkForce odooCliV3;
      };
    };

  testScript = ''
    import json
    from datetime import timedelta

    def psql(sql):
        return machine.succeed(f"sudo -u postgres psql -d acme -tAc \"{sql}\"").strip()

    def icp(key):
        return psql(f"select value from ir_config_parameter where key = '{key}'")

    def migrate_log():
        return machine.succeed("journalctl -u odoo-migrate.service --no-pager")

    def switch(to):
        # /run/booted-system: after the first `test` switch, /run/current-system
        # is the specialisation's toplevel, which has no specialisation/ of its own.
        return f"/run/booted-system/specialisation/{to}/bin/switch-to-configuration test"

    machine.start()
    machine.wait_for_unit("postgresql-setup.service")
    # odoo.service Requires odoo-migrate, which provisions the empty database
    # first; the unit only turns active once that finished.
    machine.wait_for_unit("odoo.service", timeout=timedelta(minutes=15))
    assert "provisioned 'acme'" in migrate_log()
    assert icp("odoo_nix.migrated_build") == "${odooCli}"
    migrated = int(machine.succeed("systemctl show odoo-migrate.service -P ExecMainExitTimestampMonotonic"))
    started = int(machine.succeed("systemctl show odoo.service -P ExecMainStartTimestampMonotonic"))
    assert 0 < migrated <= started, (migrated, started)
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

    assert psql("select state from ir_module_module where name = 'base'") == "installed"
    assert psql("select state from ir_module_module where name = 'odoo_nix_fixture'") == "installed"
    # The database is owned by the Odoo role although it is not named after it.
    machine.succeed(
        "sudo -u postgres psql -tAc"
        " \"select pg_get_userbyid(datdba) from pg_database where datname = 'acme'\" | grep -x odoo"
    )

    with subtest("a restart of the same build migrates nothing"):
        machine.succeed("systemctl restart odoo.service")
        machine.wait_for_unit("odoo.service")
        assert "already migrated by this build" in migrate_log()

    with subtest("deploying v2 migrates exactly the changed module"):
        machine.succeed(switch("v2"))
        machine.wait_for_unit("odoo.service")
        assert "1 module(s) to update: odoo_nix_fixture" in migrate_log()
        assert icp("odoo_nix_fixture.migrated_to") == "1.0.1"
        assert icp("odoo_nix.migrated_build") == "${odooCliV2}"
        assert psql(
            "select 1 from information_schema.columns"
            " where table_name = 'res_partner' and column_name = 'odoo_nix_fixture_flag'"
        ) == "1"
        machine.wait_until_succeeds("curl -sSf -o /dev/null http://127.0.0.1:8069/web/login")

    with subtest("a failed v3 migration rolls back and keeps Odoo down"):
        machine.fail(switch("v3"))
        machine.succeed("systemctl is-failed odoo-migrate.service")
        machine.fail("systemctl is-active odoo.service")
        assert "database restored from" in migrate_log()
        assert icp("odoo_nix_fixture.migrated_to") == "1.0.1"
        assert icp("odoo_nix.migrated_build") == "${odooCliV2}"
        machine.succeed("find /var/lib/odoo/data/backups/acme/premigrate -name '*.dump' | grep -q .")

    with subtest("redeploying v2 recovers"):
        machine.succeed(switch("v2"))
        machine.wait_for_unit("odoo.service")
        machine.wait_until_succeeds("curl -sSf -o /dev/null http://127.0.0.1:8069/web/login")
  '';
}
