# NixOS VM test for services.odoo-nix with a REAL Odoo: the fixture's
# production-shaped CLI package for one series. nginx.nix keeps a stub
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
#   - redeploying v2 recovers;
#   - root's `odoo` (adminCli) runs as the service user, with its PATH;
#   - nginx serves filestore attachments Odoo authorized (nginx.xSendfile);
#   - backups and pre-migrate snapshots are owner-only, though nginx is in
#     the service group, while what a migration writes to the filestore stays
#     readable to nginx through that group;
#   - logs: Odoo's records reach the journal as `<N>logger [db] message`,
#     with their syslog priority on every line (tracebacks too), no
#     asctime/pid, and the journal fields;
#   - the units run under python-devops-nix's hardening baseline, and
#     odoo-init as the service user.
#
# Run: nix build .#checks.<system>.service-18   (needs KVM)
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
  # 20.0 removed ir.attachment's `datas` (it logs "Use raw, datas has been
  # removed" and creates an empty attachment); `raw` takes the same base64
  # over RPC.
  attachmentField = if lib.versionAtLeast series "20.0" then "raw" else "datas";
in
# A test module: tests/series.nix registers it with lib.checks.mk's
# nixosTest, which names it.
{
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
          xSendfile = true;
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
    import re
    from datetime import timedelta

    def psql(sql):
        return machine.succeed(f"sudo -u postgres psql -d acme -tAc \"{sql}\"").strip()

    def icp(key):
        return psql(f"select value from ir_config_parameter where key = '{key}'")

    def migrate_log():
        return machine.succeed("journalctl -u odoo-migrate.service --no-pager")

    def mode(path):
        return int(machine.succeed(f"stat -c %a {path}").strip(), 8)

    def assert_private(directory, pattern):
        # Whole databases: nginx is in the odoo group (nginx.xSendfile), so
        # neither the file nor its directory may grant the group anything.
        assert mode(directory) == 0o700, f"{directory} is {mode(directory):o}"
        files = machine.succeed(f"find {directory} -name '{pattern}'").split()
        assert files, f"nothing matching {pattern} in {directory}"
        for f in files:
            assert mode(f) == 0o600, f"{f} is {mode(f):o}"
            machine.fail(f"sudo -u nginx cat {f} > /dev/null")

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

    with subtest("Odoo logs to the journal natively"):
        def journal(*matches):
            out = machine.succeed("journalctl -o json --no-pager " + " ".join(matches))
            return [json.loads(line) for line in out.splitlines() if line.strip()]

        def text(e):
            # journald exports a MESSAGE it considers binary as a byte array
            m = e.get("MESSAGE", "")
            return bytes(m).decode("utf-8", "replace") if isinstance(m, list) else m

        def odoo_entries(unit):
            # PID 1's own lines about the unit are not Odoo's
            return [e for e in journal(f"_SYSTEMD_UNIT={unit}") if e.get("_PID") != "1"]

        web = odoo_entries("odoo.service")
        version = next(e for e in web if "Odoo version" in text(e))
        # <6> consumed by journald as the priority; the logger stays, with no
        # [db] (no request, no database), and asctime and pid (fields journald
        # has) go
        assert text(version).startswith("odoo Odoo version ${series}"), version
        assert version["PRIORITY"] == "6", version
        assert version["SYSLOG_IDENTIFIER"] == "odoo-web", version
        assert version["APP_SERVICE"] == "web" and version["APP_SITE"] == "acme", version
        # Not one line in Odoo's terminal format -- the prefork workers and
        # the separately exec'd gevent process included.
        stamped = [text(e) for e in web if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} \d+ ", text(e))]
        assert not stamped, stamped[:5]
        # the request log of the curls above, with Odoo's perf_info, and the
        # database it served in brackets (werkzeug's logger through 19.0;
        # 20.0 logs requests itself, as odoo.http.server)
        assert any(
            re.search(r"^(?:werkzeug|odoo\.http\.server) (\[acme\] )?.*\"GET /web/login HTTP/1\.[01]\" 200 ", text(e))
            for e in web
        ), [text(e) for e in web if "werkzeug" in text(e) or "odoo.http.server" in text(e)][-5:]
        # what Odoo logs about a database names it: `<logger> [acme] ...`
        assert any(re.match(r"^odoo\.\S+ \[acme\] ", text(e)) for e in web), [text(e) for e in web][-10:]

        migrate = odoo_entries("odoo-migrate.service")
        assert any("provisioned 'acme'" in text(e) for e in migrate), migrate[-5:]
        assert all(
            e["SYSLOG_IDENTIFIER"] == "odoo-migrate" and e["APP_SERVICE"] == "migrate" and e["APP_SITE"] == "acme"
            for e in migrate
        ), migrate[-5:]

        # An ERROR with a traceback, from the same package and environment
        # the service runs with (a server-wide module that does not exist;
        # the database exists, so nothing is created): every line of it at
        # PRIORITY 3, the traceback's as much as the message's.
        machine.execute(
            "systemd-run --wait --collect --unit odoo-journald-probe"
            " -p User=odoo -p Group=odoo -p WorkingDirectory=/var/lib/odoo"
            " ${odooCli}/bin/odoo -c /var/lib/odoo/odoo.conf --load=base,web,no_such_module"
            " --workers=0 --max-cron-threads=0 --stop-after-init"
        )
        probe = odoo_entries("odoo-journald-probe.service")
        failed = next(i for i, e in enumerate(probe) if "Failed to load server-wide module `no_such_module`" in text(e))
        assert text(probe[failed]).startswith("odoo.service.server Failed to load"), probe[failed]
        assert text(probe[failed + 1]) == "Traceback (most recent call last):", probe[failed:failed + 3]
        # ...down to the exception itself, the record's last line
        last = next(i for i in range(failed, len(probe)) if "No module named" in text(probe[i]))
        record = probe[failed:last + 1]
        assert len(record) > 3 and all(e["PRIORITY"] == "3" for e in record), record

        # nginx's access log, as JSON, with the site's fields
        entry = journal("SYSLOG_IDENTIFIER=nginx_access")[-1]
        access = json.loads(text(entry))
        assert access["site"] == "odoo.example.com" and access["uri"] == "/web/login", access
        assert access["status"] == 200, access
        assert entry["APP_SERVICE"] == "nginx" and entry["APP_SITE"] == "acme", entry

    with subtest("the units run sandboxed, init as the service user"):
        def prop(unit, name):
            return machine.succeed(f"systemctl show {unit} -P {name}").strip()

        for unit in ("odoo.service", "odoo-migrate.service", "odoo-init.service"):
            assert prop(unit, "ProtectSystem") == "strict", unit
            assert prop(unit, "NoNewPrivileges") == "yes", unit
            assert prop(unit, "CapabilityBoundingSet") == "", (unit, prop(unit, "CapabilityBoundingSet"))
            # No unit-wide umask: the filestore subtest below needs group read.
            assert prop(unit, "UMask") == "0022", (unit, prop(unit, "UMask"))
        assert prop("odoo-init.service", "User") == "odoo"
        # The runtime conf odoo-init wrote, as the service user, private.
        machine.succeed("stat -c '%a %U:%G' /var/lib/odoo/odoo.conf | grep -x '600 odoo:odoo'")
        # Odoo itself cannot write outside its state directory.
        pid = prop("odoo.service", "MainPID")
        machine.succeed(f"awk '$5 == \"/\" {{ print $6 }}' /proc/{pid}/mountinfo | grep -q '^ro'")

    with subtest("root's odoo runs as the service, with its tools and config"):
        # pg_dump is on no root PATH here: the wrapper brings the service's.
        machine.succeed("odoo db backup acme --format dump --path /var/lib/odoo/admin-backups")
        owners = machine.succeed("find /var/lib/odoo/admin-backups -name '*.dump' -printf '%u\\n'").split()
        assert owners and set(owners) == {"odoo"}, owners
        assert_private("/var/lib/odoo/admin-backups", "*.dump")
        # and in the default place, <data_dir>/backups/<db>/
        machine.succeed("odoo db backup acme --format dump")
        assert mode("/var/lib/odoo/data/backups") == 0o700
        assert_private("/var/lib/odoo/data/backups/acme", "*.dump")
        # A shell beside the running multi-worker service: no second server
        # binding its port. Piped, so the wrapper runs it with --pipe.
        out = machine.succeed("echo 'print(\"DBNAME\", env.cr.dbname)' | odoo shell acme")
        assert "DBNAME acme" in out, out

    with subtest("nginx sends filestore attachments (x_sendfile)"):
        def rpc(service, method, *args):
            payload = json.dumps({"jsonrpc": "2.0", "method": "call",
                                  "params": {"service": service, "method": method, "args": list(args)}})
            res = json.loads(machine.succeed(
                f"curl -sSf -H 'Content-Type: application/json' -d '{payload}' http://127.0.0.1:8069/jsonrpc"
            ))
            assert "result" in res, res
            return res["result"]

        uid = rpc("common", "login", "acme", "admin", "admin")
        att_id = rpc("object", "execute_kw", "acme", uid, "admin", "ir.attachment", "create",
                     [{"name": "hello.txt", "${attachmentField}": "aGVsbG8gZnJvbSB0aGUgZmlsZXN0b3Jl", "public": True}])
        [att] = rpc("object", "execute_kw", "acme", uid, "admin", "ir.attachment", "read",
                    [[att_id], ["store_fname"]])
        store_fname = att["store_fname"]
        url = f"/web/content/{att_id}"
        # Through nginx: the file itself.
        body = machine.succeed(f"curl -sSf -H 'Host: odoo.example.com' http://localhost{url}")
        assert body == "hello from the filestore", body
        # Odoo itself only authorized it: an empty body and the redirect nginx followed.
        headers = machine.succeed(f"curl -sSf -D - -o /tmp/direct http://127.0.0.1:8069{url}")
        assert f"x-accel-redirect: /web/filestore/acme/{store_fname}" in headers.lower(), headers
        assert machine.succeed("stat -c %s /tmp/direct").strip() == "0"
        # The internal location is not reachable from outside.
        machine.succeed(
            "curl -sS -o /dev/null -w '%{http_code}' -H 'Host: odoo.example.com'"
            f" http://localhost/web/filestore/acme/{store_fname} | grep -x 404"
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

    with subtest("the pre-migrate snapshot is private; what the migration wrote is not"):
        assert_private("/var/lib/odoo/data/backups/acme/premigrate", "*.dump")
        # v2's post-migrate wrote a public attachment. nginx sends it from the
        # filestore (xSendfile) as a member of the odoo group, so every
        # directory down to it needs group r-x and the file group r.
        att_id, store_fname = psql(
            "select id, store_fname from ir_attachment where name = 'odoo_nix_fixture_migrated.txt'"
        ).split("|")
        paths = ["/var/lib/odoo/data/filestore/acme"]
        for part in store_fname.split("/"):
            paths.append(f"{paths[-1]}/{part}")
        for path in paths:
            need = 0o040 if path == paths[-1] else 0o050
            assert mode(path) & need == need, f"{path} is {mode(path):o}, which nginx cannot read through the group"
        machine.succeed(f"sudo -u nginx cat {paths[-1]} > /dev/null")
        body = machine.succeed(f"curl -sSf -H 'Host: odoo.example.com' http://localhost/web/content/{att_id}")
        assert body == "written during migrate", body

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
