# Everything odoo-nix asserts about ONE Odoo series, built for real from the
# pinned OCB input with the library code consumers use -- the same calls
# modules/devenv.nix makes, without the flake-parts module in between.
#
# The workspace is tests/fixtures/<series>: a committed, consumer-shaped uv
# project (pyproject.toml + uv.lock; no `odoo/`, that is `coreSource`) plus one
# custom addon whose Odoo tests are what odoo-test-<major> runs.
#
# Returns:
#   eval  -- { name = { expected; actual; }; } for lib.checks.mk's `eval`
#   all   -- derivations that run on every system (no Odoo process)
#   linux -- derivations that run Odoo or a VM
{
  pkgs,
  lib,
  inputs,
  series,
  ocb,
  python,
  scriptCheck,
  nixosTest,
}:
let
  major = lib.versions.major series;
  is19 = lib.versionAtLeast series "19.0";
  workspaceRoot = ./fixtures + "/${series}";
  projectName = "odoo-nix-fixture-${major}";
  fixtureAddon = "odoo_nix_fixture";
  # Deliberately not the devguard's default mail port (1025): the fixture test
  # asserts the value came from the Nix-baked settings, not the package defaults.
  mailcatchPort = 2525;
  presets = builtins.fromJSON (builtins.readFile ../lib/odoo-presets.json);

  layout = {
    coreSrc = "odoo";
    externalDir = "modules";
    customDir = "custom";
    extraAddons = [ ];
  };

  buildDeps = import ../lib/build-deps.nix {
    inherit pkgs;
    base = inputs.python-devops-nix.lib;
  };

  # The dev guard rails, as a project would bake them: only the test env gets
  # them (lib/python.nix); odooPythonEnv -- what builtOdoo runs -- must not.
  devguard = import ../lib/devguard.nix {
    inherit pkgs;
    base = inputs.python-devops-nix.lib;
    settings.guards.mail.port = mailcatchPort;
  };

  # journald-native log lines: every env gets them, odooPythonEnv included.
  journald = import ../lib/journald.nix {
    inherit pkgs;
    base = inputs.python-devops-nix.lib;
  };

  pythonEnvs = import ../lib/python.nix {
    inherit
      pkgs
      lib
      python
      workspaceRoot
      projectName
      devguard
      journald
      ;
    pythonLib = inputs.python-devops-nix.lib.python;
    coreSource = ocb;
    # The package fixes (python-devops-nix's lib.python.overrides) are
    # lib/python.nix's own, so the fixture env is built the way a consumer's is.
    inherit (inputs) pyproject-nix pyproject-build-systems uv2nix;
  };

  builtOdoo = import ../lib/odoo.nix {
    inherit
      pkgs
      lib
      workspaceRoot
      layout
      projectName
      ;
    odooSeries = series;
    coreSource = ocb;
    inherit (pythonEnvs) odooPythonEnv;
  };

  # The `odoo` CLI, production-shaped (no workspace scripts -- this fixture
  # is not a git checkout): exercises the same wrapper NixOS/containers get.
  mkCli =
    name: tree:
    import ../lib/cli.nix {
      inherit pkgs lib name;
      inherit python;
      rawOdooBin = "${tree}/bin/odoo";
      mirrorTree = tree;
      targetPythonEnv = pythonEnvs.odooPythonEnv;
      cliScripts = null;
      base = inputs.python-devops-nix.lib;
    };
  odooCli = mkCli "${projectName}-cli" builtOdoo;

  # addons_path for the sandboxed runs: the assembled package's roots, the
  # dev shell's shape re-rooted on the store copy.
  addons = import ../lib/addons.nix {
    inherit lib workspaceRoot layout;
    coreSource = ocb;
  };

  # One odoo.conf per assembled tree: addons_path points into it, so a
  # migration check needs a conf for each build it runs.
  mkConf =
    tree:
    (import ../lib/odoo-ini.nix { inherit pkgs lib; }).generate "odoo.conf" {
      # No db_host/db_password: unix socket, no password (the run passes
      # --db_host=$PGHOST anyway).
      options = {
        addons_path = addons.addonsPathFor "${tree}";
        db_port = 5432;
        db_user = "odoo";
        # Relative to CWD, which is the build directory a check runs in.
        data_dir = "./odoo-data";
        admin_passwd = "admin";
        http_interface = "127.0.0.1";
        http_port = 18069;
        gevent_port = 18072;
        workers = 0;
        log_level = "test";
        log_db_level = "warning";
        without_demo = true;
        # Mirrors devenv.nix: setting the key replaces Odoo's default set,
        # and 19.0's default includes `rpc`.
        server_wide_modules = [
          "base"
        ]
        ++ lib.optional is19 "rpc"
        ++ [ "web" ];
      };
    };
  conf = mkConf builtOdoo;

  # Later builds of the same project for the migration checks: the fixture
  # addon at 1.0.1 (a new field + a post-migrate script) and 1.0.2 (a
  # migration that commits a change and then fails). Only custom/ differs --
  # same OCB, same Python env -- so each is a cheap assembly plus its own
  # production-shaped CLI, whose store path is the build identity the
  # migration records.
  mkBuild =
    version:
    let
      tree = import ../lib/odoo.nix {
        inherit pkgs lib layout;
        workspaceRoot = ./fixtures/migrate + "/${version}";
        projectName = "${projectName}-${version}";
        odooSeries = series;
        coreSource = ocb;
        inherit (pythonEnvs) odooPythonEnv;
      };
    in
    {
      inherit tree;
      conf = mkConf tree;
      cli = mkCli "${projectName}-${version}-cli" tree;
    };
  v2 = mkBuild "v2";
  v3 = mkBuild "v3";

  # In-sandbox PostgreSQL: postgresqlTestHook runs initdb + pg_ctl as the build
  # user on a unix socket under $NIX_BUILD_TOP/run/postgresql with TCP off, and
  # exports PGHOST/PGUSER/PGDATABASE. Odoo hands db_host to psycopg2 verbatim
  # and libpq treats a `/`-prefixed host as a socket directory.
  pg = {
    tools = [
      pkgs.postgresql_16
      pkgs.postgresqlTestHook
    ];
    env = {
      PGUSER = "odoo";
      PGDATABASE = "odoo_${major}";
      # CREATEDB as in the dev shell; SUPERUSER so a module pre_init_hook could
      # CREATE EXTENSION (base_geoengine-style) if a future fixture needs it.
      postgresqlTestUserOptions = "LOGIN SUPERUSER CREATEDB";
    };
  };
  # The hook attaches to the check phase, which a script check does not have,
  # so the script runs the phase's hooks itself.
  pgCheck =
    name: text:
    scriptCheck name pg ''
      runHook preCheck
      ${text}
      runHook postCheck
    '';

  odooArgs = ''-c ${conf} -d "$PGDATABASE" --db_host="$PGHOST" --db_user="$PGUSER" --stop-after-init'';

  # Belt and braces over the exit code: Odoo logs test failures at ERROR, and
  # docutils' manifest-description noise looks like `(ERROR/3)`, not ` ERROR `.
  noErrors = ''
    if grep -E ' (ERROR|CRITICAL) |FAIL(ED)?:' odoo.log; then
      echo "odoo-nix: errors in the Odoo log above" >&2
      exit 1
    fi
  '';

  installed = mod: ''
    psql -d "$PGDATABASE" -tAc "select state from ir_module_module where name = '${mod}'" | grep -qx installed \
      || { echo "odoo-nix: module ${mod} is not installed in $PGDATABASE" >&2; exit 1; }
  '';
in
{
  inherit builtOdoo pythonEnvs conf;

  eval = {
    # The fixture's requires-python is the presets' for this series.
    fixture-requires-python = {
      expected = presets.${series}.requiresPython;
      actual = pythonEnvs.rootPyproject.project."requires-python";
    };
    # passthru.addonsPath contract: absolute core roots from coreSource, then
    # the workspace-relative components against the given root. `/ROOT` rather
    # than "${builtOdoo}" so this stays a pure eval check (no string context
    # that would pull the package -- and its odoo wheel -- into the build).
    built-odoo-addons-path = {
      expected = "${ocb}/odoo/addons,${ocb}/addons,/ROOT/custom";
      actual = builtOdoo.passthru.addonsPath "/ROOT";
    };
    built-odoo-version = {
      expected = series;
      actual = builtOdoo.passthru.odooVersion;
    };
    # uv.lock covers every dependency pyproject.toml declares (the audit
    # every virtualenv goes through; tests/lock-audit.nix has a stale one).
    lock-audit = {
      expected = [ ];
      actual = pythonEnvs.lockAudit.missing;
    };
  };

  all = {
    # uv.lock was locked against *this* pin: same series, same install_requires.
    lock-fresh =
      scriptCheck "lock-fresh-${major}"
        {
          tools = [ (pkgs.python3.withPackages (ps: [ ps.setuptools ])) ];
        }
        ''
          python3 ${./lock_fresh.py} ${workspaceRoot + "/uv.lock"} ${ocb} ${series}
        '';

    # The managed [tool.uv.extra-build-dependencies] block is what
    # odoo-nix-build-deps derives from this uv.lock (`nix run .#relock` keeps
    # it so).
    build-deps = scriptCheck "build-deps-${major}" { } ''
      ${lib.getExe buildDeps} check ${workspaceRoot + "/pyproject.toml"} ${workspaceRoot + "/uv.lock"}
    '';
  };

  linux = {
    # The deployable artifact assembles, its wrapper runs the real interpreter,
    # and it is the production env (no editable installs, no dev group).
    built-odoo = scriptCheck "built-odoo-${major}" { } ''
      test -x ${builtOdoo}/odoo/odoo-bin
      test -f ${builtOdoo}/custom/${fixtureAddon}/__manifest__.py
      grep -q '${pythonEnvs.odooPythonEnv}/bin/python' ${builtOdoo}/bin/odoo
      ${builtOdoo}/bin/odoo --version | tee version.txt
      grep -qx 'Odoo Server ${series}' version.txt
      # The websocket worker is a separate `odoo-bin gevent` process that only
      # a multi-worker server spawns. Every other check here runs workers = 0,
      # as does the dev shell, so this is the one place its import path --
      # odoo/__init__.py's argv[1] == 'gevent' branch, gevent.monkey.patch_all()
      # before anything else is imported -- is exercised. A consumer's lock
      # once carried gevent 22.10.2 (Odoo's own 3.11 pin), which imports
      # pkg_resources, and setuptools 82, which no longer ships it: the dev
      # shell was fine and production crash-looped.
      ${builtOdoo}/bin/odoo gevent --version | tee gevent-version.txt
      grep -qx 'Odoo Server ${series}' gevent-version.txt
      # python-magic finds libmagic with no LD_LIBRARY_PATH -- this sandbox
      # has none, and neither has services.odoo-nix. Only the dev shell sets
      # one, which is how it once worked there and nowhere else.
      ${pythonEnvs.odooPythonEnv}/bin/python -c \
        'import magic; t = magic.from_buffer(b"%PDF-1.4\n", mime=True); assert t == "application/pdf", t'
    '';

    # `-i base` through the production wrapper. `web` is auto_install with
    # base and lives under <ocb>/addons, so its presence proves the second
    # core root. This is the production wrapper and the production env, so the
    # dev guard rails must be absent from it: no odoo_devguard on disk, no
    # banner in the log. The journald graft is there (inert: stderr is not
    # the journal here, so Odoo's own format and the checks above stand).
    odoo-init = pgCheck "odoo-init-${major}" ''
      ${builtOdoo}/bin/odoo ${odooArgs} -i base 2>&1 | tee odoo.log
      ${noErrors}
      ${installed "base"}
      ${installed "web"}
      if grep -q 'odoo_devguard' odoo.log; then
        echo "the production environment ran the dev guard rails" >&2
        exit 1
      fi
      test ! -e ${pythonEnvs.odooPythonEnv}/${python.sitePackages}/odoo_devguard
      test ! -e ${pythonEnvs.odooPythonEnv}/${python.sitePackages}/zzz-odoo-devguard.pth
      test -e ${pythonEnvs.odooPythonEnv}/${python.sitePackages}/odoo_journald/_journald.py
      grep -qxF 'import odoo_journald; odoo_journald.install()' \
        ${pythonEnvs.odooPythonEnv}/${python.sitePackages}/zzz-odoo-journald.pth
    '';

    # The fixture addon's Odoo tests, with the test env (prod wheels + dev
    # group). Odoo reports a skipped test exactly like a passed one, so the
    # stats line must show the module's tests actually ran.
    odoo-test = pgCheck "odoo-test-${major}" ''
      ${pythonEnvs.testPythonEnv}/bin/python ${builtOdoo}/odoo/odoo-bin ${odooArgs} \
        -i ${fixtureAddon} --test-enable --test-tags /${fixtureAddon} 2>&1 | tee odoo.log
      ${noErrors}
      grep -E '${fixtureAddon}: [1-9][0-9]* tests' odoo.log
      grep -E ' 0 failed, 0 error\(s\) of [1-9][0-9]* tests' odoo.log
      grep -q 'odoo_devguard\[mail\] ACTIVE -- ALL outgoing email is redirected to 127.0.0.1:${toString mailcatchPort}' odoo.log
      ${installed fixtureAddon}
    '';

    # The `odoo` CLI end to end: passthrough (--help/--version), then a full
    # db lifecycle (provision a fresh database -- the create-if-missing path
    # `Registry.new()` itself does not cover -- migrate, backup, drop,
    # restore) against a *different* database than the one `pg`/PGDATABASE
    # pre-creates, exercising --db-host/--db-user the same way odooArgs does
    # for the raw odoo-bin checks above.
    cli-lifecycle = pgCheck "cli-lifecycle-${major}" ''
      DBFLAGS="--db-host $PGHOST --db-user $PGUSER"
      CLIDB="odoo_nix_cli_${major}"

      ${odooCli}/bin/odoo --help | grep -q "Commands:"
      ${odooCli}/bin/odoo db --help | grep -q migrate
      ${odooCli}/bin/odoo --version | tee version.txt
      grep -qx 'Odoo Server ${series}' version.txt

      # New database: provision creates it (base only -- no modules.txt at
      # this cwd) since Registry.new() itself assumes the database exists.
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db provision "$CLIDB" 2>&1 | tee provision.log
      refute grep -qE ' (ERROR|CRITICAL) ' provision.log
      grep -q "provisioned '$CLIDB'" provision.log
      psql -d "$CLIDB" -tAc "select state from ir_module_module where name = 'base'" | grep -qx installed

      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db list | grep -q "$CLIDB"

      # Idempotent re-run: provision on an existing database migrates
      # instead of reinstalling -- and since provisioning recorded the
      # checksum baseline and nothing changed since, that migration has
      # nothing to update. (cli-migrate covers the runs that do.)
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db provision "$CLIDB" --no-backup 2>&1 | tee reprovision.log
      refute grep -qE ' (ERROR|CRITICAL) ' reprovision.log
      grep -q 'already exists' reprovision.log
      grep -q 'up to date' reprovision.log

      # Backup, drop, restore.
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db backup "$CLIDB" --path ./backups 2>&1 | tee backup.log
      grep -q "$CLIDB →" backup.log
      BACKUP_FILE=$(ls ./backups/*.zip | head -n1)
      test -n "$BACKUP_FILE"

      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db drop "$CLIDB" --yes
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db list > after-drop.log
      refute grep -q "$CLIDB" after-drop.log

      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db restore "$CLIDB" "$BACKUP_FILE" 2>&1 | tee restore.log
      grep -q "restored '$CLIDB'" restore.log
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db list | grep -q "$CLIDB"
      psql -d "$CLIDB" -tAc "select state from ir_module_module where name = 'base'" | grep -qx installed
    '';

    # `odoo db restore` with no backup file: the newest (or --at) backup from
    # the remote store -- here a directory laid out like the bucket
    # (<root>/<db>/<ts>.dump), the same code path the S3 store takes after
    # listing. The restore conventions shared with frappe-nix
    # (python-devops-nix CONVENTIONS.md, Restore): neutralized and migrated by
    # default, overwriting unless --no-force, --force a warned no-op,
    # --files/--attachments, refused without the devguard unless
    # restore.requireDevguard is off, and --at in ISO 8601 or odoo-nix's
    # naming.
    cli-remote-restore = pgCheck "cli-remote-restore-${major}" ''
      DBFLAGS="--db-host $PGHOST --db-user $PGUSER"
      SRCDB="odoo_nix_rsrc_${major}"
      DSTDB="odoo_nix_rdst_${major}"
      export ODOO_NIX_BACKUP_SOURCE="$PWD/bucket"
      odoo() { ${odooCli}/bin/odoo -c ${conf} $DBFLAGS "$@"; }
      fails() { # <log> <command...>: the command must fail
        local log="$1"; shift
        if "$@" >"$log" 2>&1; then echo "expected to fail: $*" >&2; cat "$log" >&2; exit 1; fi
      }
      # `! grep` is exempt from errexit, so it could never fail the check.
      lacks() { # <text> <log>
        if grep -q -- "$1" "$2"; then echo "$2 should not say: $1" >&2; exit 1; fi
      }
      neutralized() { psql -d "$DSTDB" -tAc "select count(*) from ir_mail_server where name = 'neutralization - disable emails'"; }

      odoo db provision "$SRCDB" 2>&1 | tee provision.log
      if grep -qE ' (ERROR|CRITICAL) ' provision.log; then exit 1; fi
      odoo db backup "$SRCDB" --format dump --path "$ODOO_NIX_BACKUP_SOURCE/$SRCDB" 2>&1 | tee backup.log

      odoo db restore "$DSTDB" --from "$SRCDB" --list | tee list.log
      grep -qE '^[0-9]{4}(_[0-9]{2}){5}\.dump ' list.log
      NAME="$(head -n1 list.log | cut -d' ' -f1)"

      # neutralized and migrated by default
      odoo db restore "$DSTDB" --from "$SRCDB" 2>&1 | tee restore.log
      grep -q "restored '$DSTDB'" restore.log
      grep -q "migrating '$DSTDB'" restore.log
      grep -q "$DSTDB: up to date" restore.log
      psql -d "$DSTDB" -tAc "select state from ir_module_module where name = 'base'" | grep -qx installed
      neutralized | grep -qx 1

      # --no-force refuses an existing database; without it, it is overwritten
      fails refuse.log odoo db restore "$DSTDB" --from "$SRCDB" --no-force
      grep -q -- '--no-force' refuse.log
      odoo db restore "$DSTDB" --from "$SRCDB" --no-neutralize --no-migrate 2>&1 | tee overwrite.log
      grep -q "dropping existing '$DSTDB'" overwrite.log
      grep -q "restored '$DSTDB'" overwrite.log
      lacks "migrating" overwrite.log
      neutralized | grep -qx 0

      # --force: a no-op through 1.x, a usage error that says so since 2.0.0
      fails force.log odoo db restore "$DSTDB" --from "$SRCDB" --force
      grep -q -- '--force was removed in odoo-nix 2.0.0' force.log
      lacks "dropping existing" force.log

      # restore.migrate = false reaches the CLI as ODOO_NIX_RESTORE_MIGRATE=0
      ODOO_NIX_RESTORE_MIGRATE=0 odoo db restore "$DSTDB" --from "$SRCDB" 2>&1 | tee nomigrate.log
      lacks "migrating" nomigrate.log

      # --files; --attachments, its name through 1.x, is a usage error that
      # names it. A directory store has nothing to mirror from, so --files
      # only reaches the storages step.
      odoo db restore "$DSTDB" --from "$SRCDB" --files 2>&1 | tee files.log
      grep -q "restored '$DSTDB'" files.log
      fails attachments.log odoo db restore "$DSTDB" --from "$SRCDB" --attachments
      grep -q -- '--attachments/--no-attachments is --files/--no-files since odoo-nix 2.0.0' attachments.log
      lacks "dropping existing" attachments.log

      # devguard.enable = false in a dev shell (ODOO_NIX_DEVGUARD=0) refuses to
      # restore a production database, unless explicitly overridden, or
      # restore.requireDevguard is off
      fails unguarded.log env ODOO_NIX_DEVGUARD=0 ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db restore "$DSTDB" --from "$SRCDB"
      grep -q 'devguard' unguarded.log
      grep -q 'requireDevguard' unguarded.log
      ODOO_NIX_DEVGUARD=0 ODOO_NIX_RESTORE_ALLOW_UNGUARDED=1 odoo db restore "$DSTDB" --from "$SRCDB" 2>&1 | tee override.log
      grep -q "restored '$DSTDB'" override.log
      ODOO_NIX_DEVGUARD=0 ODOO_NIX_RESTORE_REQUIRE_DEVGUARD=0 odoo db restore "$DSTDB" --from "$SRCDB" 2>&1 | tee notrequired.log
      grep -q "restored '$DSTDB'" notrequired.log

      # --at: ISO 8601 and odoo-nix's own naming, whole or a leading part
      ISO="$(sed -E 's/^([0-9]{4})_([0-9]{2})_([0-9]{2})_([0-9]{2})_([0-9]{2})_([0-9]{2}).*/\1-\2-\3T\4:\5:\6/' <<<"$NAME")"
      for at in "$ISO" "''${ISO%%T*}" "$NAME" "''${NAME:0:10}"; do
        odoo db restore "$DSTDB" --from "$SRCDB" --at "$at" --no-migrate 2>&1 | tee at-ok.log
        grep -q "backup: $NAME" at-ok.log
        grep -q "restored '$DSTDB'" at-ok.log
      done

      # a time nothing matches fails with a message, not a restore; so does
      # something that is not a time
      fails at.log odoo db restore "$DSTDB" --from "$SRCDB" --at 2001
      grep -q 'no backup matches --at 2001' at.log
      fails at-bad.log odoo db restore "$DSTDB" --from "$SRCDB" --at yesterday
      grep -q 'is not a point in time' at-bad.log

      # project restore takes the same flags: --no-force refuses there too
      fails project-refuse.log odoo project restore --restore "$DSTDB" "$ODOO_NIX_BACKUP_SOURCE/$SRCDB/$NAME" --no-force
      grep -q -- '--no-force' project-refuse.log
      odoo project restore --restore "$DSTDB" "$ODOO_NIX_BACKUP_SOURCE/$SRCDB/$NAME" --no-migrate 2>&1 | tee project.log
      grep -q "restored '$DSTDB'" project.log
    '';

    # `odoo db backup --format dump` (no filestore), `--keep-days` pruning,
    # and the project-scoped `odoo project backup`/`odoo project restore`
    # (every database matching dbfilter by default; explicit --restore DB
    # PATH pairs, no "latest" auto-discovery) -- a separate check from
    # cli-lifecycle so a failure here names this surface specifically.
    cli-project-backup = pgCheck "cli-project-backup-${major}" ''
      DBFLAGS="--db-host $PGHOST --db-user $PGUSER"
      CLIDB1="odoo_nix_proj1_${major}"
      CLIDB2="odoo_nix_proj2_${major}"

      # `project backup`'s default scope is *every* database this role owns
      # -- including postgresqlTestHook's own pre-created $PGDATABASE, which
      # is otherwise never -i base'd. dump_db_manifest() queries
      # ir_module_module directly (odoo/service/db.py), so backing up an
      # uninitialized database raises -- correctly caught and reported by
      # _run_multi as one failed item rather than a crash, but this check
      # wants a clean run, so make $PGDATABASE a real Odoo database too.
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db provision "$PGDATABASE" 2>&1 | tee provision0.log
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db provision "$CLIDB1" 2>&1 | tee provision1.log
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db provision "$CLIDB2" 2>&1 | tee provision2.log
      refute grep -qE ' (ERROR|CRITICAL) ' provision0.log provision1.log provision2.log

      # project backup: no arguments, every database, one subfolder each
      # under the given parent (not one flat folder -- auto_backup-style
      # filenames carry no db name, so a flat folder risks two databases'
      # same-second backups colliding).
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS project backup --path ./project-backups 2>&1 | tee project-backup.log
      refute grep -qE ' (ERROR|CRITICAL) ' project-backup.log
      grep -q "$PGDATABASE →" project-backup.log
      grep -q "$CLIDB1 →" project-backup.log
      grep -q "$CLIDB2 →" project-backup.log
      ls ./project-backups/$CLIDB1/*.dump.zip
      ls ./project-backups/$CLIDB2/*.dump.zip

      # --format dump: plain pg_dump custom format, no filestore -- still a
      # full round trip through db restore.
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db backup "$CLIDB1" --format dump --path ./dump-format 2>&1 | tee dump-format.log
      DUMP_FILE=$(ls ./dump-format/*.dump)
      test -n "$DUMP_FILE"
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db drop "$CLIDB1" --yes
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db restore "$CLIDB1" "$DUMP_FILE" 2>&1 | tee dump-restore.log
      grep -q "restored '$CLIDB1'" dump-restore.log
      psql -d "$CLIDB1" -tAc "select state from ir_module_module where name = 'base'" | grep -qx installed

      # --keep-days: a manufactured old-timestamped backup gets pruned, the
      # one just written does not.
      mkdir -p ./keepdays-test
      touch ./keepdays-test/2000_01_01_00_00_00.dump.zip
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db backup "$CLIDB2" --path ./keepdays-test --keep-days 1 2>&1 | tee keepdays.log
      refute test -e ./keepdays-test/2000_01_01_00_00_00.dump.zip
      test "$(ls ./keepdays-test/*.dump.zip | wc -l)" = "1"

      # project restore: drop both, restore both in one explicit-pairs batch
      # call (the zip backups project backup produced above).
      RESTORE1=$(ls ./project-backups/$CLIDB1/*.dump.zip)
      RESTORE2=$(ls ./project-backups/$CLIDB2/*.dump.zip)
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db drop "$CLIDB1" --yes
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db drop "$CLIDB2" --yes
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS project restore --restore "$CLIDB1" "$RESTORE1" --restore "$CLIDB2" "$RESTORE2" 2>&1 | tee project-restore.log
      refute grep -qE ' (ERROR|CRITICAL) ' project-restore.log
      grep -q "restored '$CLIDB1'" project-restore.log
      grep -q "restored '$CLIDB2'" project-restore.log
      psql -d "$CLIDB1" -tAc "select state from ir_module_module where name = 'base'" | grep -qx installed
      psql -d "$CLIDB2" -tAc "select state from ir_module_module where name = 'base'" | grep -qx installed
    '';

    # `odoo db migrate` from one build to the next, as the deploy-time
    # migration runs it (odoo-migrate.service): change detection, the
    # --if-needed fast path, version drift, a verified snapshot (python-devops-nix's
    # flow: lib.nixos.migrate.modules), rollback of a migration that fails
    # after committing, snapshot retention, and an uninitialised database left
    # alone.
    cli-migrate = pgCheck "cli-migrate-${major}" ''
      DBFLAGS="--db-host $PGHOST --db-user $PGUSER"
      DB="odoo_nix_migrate_${major}"
      SERVICE_ARGS="--if-needed --snapshot dump --keep 2 --rollback"
      icp() { psql -d "$DB" -tAc "select value from ir_config_parameter where key = '$1'"; }
      fixture_version() { psql -d "$DB" -tAc "select latest_version from ir_module_module where name = 'odoo_nix_fixture'"; }
      snapshots() { find ./odoo-data/backups/"$DB"/premigrate -type f 2>/dev/null | wc -l; }
      # `! grep` would not trip errexit (a negated pipeline never does).
      no_errors() {
        if grep -E ' (ERROR|CRITICAL) ' "$1"; then
          echo "odoo-nix: errors in $1 (above)" >&2
          exit 1
        fi
      }

      # v1: provision installs base + the fixture and records the baseline
      # (checksums + this build), so the first migrate is not a full -u all.
      echo odoo_nix_fixture > modules.txt
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db provision "$DB" --modules-file modules.txt 2>&1 | tee v1.log
      no_errors v1.log
      grep -q "provisioned '$DB'" v1.log
      test "$(icp odoo_nix.migrated_build)" = "${odooCli}"
      icp module_auto_update.installed_checksums | grep -q '"odoo_nix_fixture"'

      # Same build again: one query, no registry load.
      ${odooCli}/bin/odoo -c ${conf} $DBFLAGS db migrate "$DB" $SERVICE_ARGS 2>&1 | tee v1-again.log
      grep -q "already migrated by this build" v1-again.log
      test "$(snapshots)" = 0

      # v2: only the fixture changed, so only the fixture is updated -- its
      # new column exists, its post-migrate ran, and v2 is recorded.
      ${v2.cli}/bin/odoo -c ${v2.conf} $DBFLAGS db migrate "$DB" $SERVICE_ARGS 2>&1 | tee v2.log
      no_errors v2.log
      grep -q "1 module(s) to update: odoo_nix_fixture" v2.log
      test "$(icp odoo_nix_fixture.migrated_to)" = "1.0.1"
      test "$(fixture_version)" = "${series}.1.0.1"
      psql -d "$DB" -tAc "select 1 from information_schema.columns where table_name = 'res_partner' and column_name = 'odoo_nix_fixture_flag'" | grep -qx 1
      test "$(icp odoo_nix.migrated_build)" = "${v2.cli}"
      test "$(snapshots)" = 1
      # The flow's snapshot: named for the database, 0600 in a 0700
      # directory, verified before the migration relied on it.
      grep -q "odoo-migrate($DB): snapshot verified" v2.log
      snap=$(find ./odoo-data/backups/"$DB"/premigrate -name "premigrate-$DB-*.dump")
      test "$(stat -c %a "$snap")" = 600
      test "$(stat -c %a ./odoo-data/backups/"$DB"/premigrate)" = 700

      # Version drift with unchanged checksums -- a database restored from
      # somewhere its modules were never updated -- is still migrated. The
      # build marker is cleared too, as a restored dump's would differ.
      psql -d "$DB" -c "update ir_module_module set latest_version = '${series}.1.0.0' where name = 'odoo_nix_fixture'"
      psql -d "$DB" -c "delete from ir_config_parameter where key = 'odoo_nix.migrated_build'"
      ${v2.cli}/bin/odoo -c ${v2.conf} $DBFLAGS db migrate "$DB" $SERVICE_ARGS 2>&1 | tee drift.log
      no_errors drift.log
      grep -q "odoo_nix_fixture (${series}.1.0.0 → ${series}.1.0.1)" drift.log
      test "$(fixture_version)" = "${series}.1.0.1"

      # v3 fails after committing 'partial': non-zero exit, and the database
      # is back exactly as v2 left it.
      if ${v3.cli}/bin/odoo -c ${v3.conf} $DBFLAGS db migrate "$DB" $SERVICE_ARGS > v3.log 2>&1; then
        cat v3.log; echo "odoo-nix: the failing v3 migration exited 0" >&2; exit 1
      fi
      cat v3.log
      grep -q "database restored from" v3.log
      test "$(icp odoo_nix_fixture.migrated_to)" = "1.0.1"
      test "$(fixture_version)" = "${series}.1.0.1"
      test "$(icp odoo_nix.migrated_build)" = "${v2.cli}"
      # ...and v2 still runs on it: nothing left half-updated.
      ${v2.cli}/bin/odoo -c ${v2.conf} $DBFLAGS db migrate "$DB" $SERVICE_ARGS 2>&1 | tee after-rollback.log
      grep -q "already migrated by this build" after-rollback.log

      # A failure never prunes: all three snapshots are still there, the
      # one the rollback used included. The next successful migration
      # applies --keep 2 (clearing the marker forces one; --also gives it
      # something to update, so it snapshots).
      test "$(snapshots)" = 3
      grep -q "odoo-migrate($DB): rolling back from" v3.log
      # A snapshot named before odoo-nix took the flow from python-devops-nix
      # goes once as many new ones as --keep keeps exist.
      touch ./odoo-data/backups/"$DB"/premigrate/2026_01_01_00_00_00.dump
      psql -d "$DB" -c "delete from ir_config_parameter where key = 'odoo_nix.migrated_build'"
      ${v2.cli}/bin/odoo -c ${v2.conf} $DBFLAGS db migrate "$DB" $SERVICE_ARGS --also odoo_nix_fixture 2>&1 | tee keep.log
      no_errors keep.log
      grep -q "odoo_nix_fixture (requested)" keep.log
      test "$(snapshots)" = 2

      # An uninitialised database is skipped, successfully.
      createdb odoo_nix_empty_${major}
      ${v2.cli}/bin/odoo -c ${v2.conf} $DBFLAGS db migrate odoo_nix_empty_${major} $SERVICE_ARGS 2>&1 | tee empty.log
      grep -q "has no Odoo schema" empty.log
    '';

    service = nixosTest "service-${major}" (
      import ./service.nix {
        inherit pkgs series odooCli;
        odooCliV2 = v2.cli;
        odooCliV3 = v3.cli;
        odooModule = inputs.self.nixosModules.default;
      }
    );
  };
}
