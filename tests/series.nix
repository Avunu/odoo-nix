# Everything odoo-nix asserts about ONE Odoo series, built for real from the
# pinned OCB input with the library code consumers use -- the same calls
# modules/devenv.nix makes, without the flake-parts module in between.
#
# The workspace is tests/fixtures/<series>: a committed, consumer-shaped uv
# project (pyproject.toml + uv.lock; no `odoo/`, that is `coreSource`) plus one
# custom addon whose Odoo tests are what odoo-test-<major> runs.
#
# Returns:
#   eval  -- { name = { expected; actual; }; } for flake.nix's mkEvalCheck
#   all   -- derivations that run on every system (no Odoo process)
#   linux -- derivations that run Odoo or a VM
{
  pkgs,
  lib,
  inputs,
  series,
  ocb,
  python,
  odooNixAddons,
  mkCheck,
}:
let
  major = lib.versions.major series;
  is19 = lib.versionAtLeast series "19.0";
  workspaceRoot = ./fixtures + "/${series}";
  projectName = "odoo-nix-fixture-${major}";
  fixtureAddon = "odoo_nix_fixture";
  # Deliberately not dev_mailcatch's DEFAULT_PORT (1025): the fixture test
  # asserts the value came from the [dev_mailcatch] section of odoo.conf.
  mailcatchPort = 2525;
  presets = builtins.fromJSON (builtins.readFile ../lib/odoo-presets.json);

  layout = {
    coreSrc = "odoo";
    externalDir = "modules";
    customDir = "custom";
    extraAddons = [ ];
  };

  overrides = import ../lib/overrides.nix;

  pythonEnvs = import ../lib/python.nix {
    inherit
      pkgs
      lib
      python
      workspaceRoot
      projectName
      ;
    coreSource = ocb;
    pyproject-nix = inputs.pyproject-nix;
    pyproject-build-systems = inputs.pyproject-build-systems;
    uv2nix = inputs.uv2nix;
    # What modules/devenv.nix wires by default (builtinPythonLibraries,
    # builtinOverrides), so the fixture env is built the way a consumer's is.
    pythonLibraries = {
      pycups = [ pkgs.cups ];
    };
    extraOverrides = lib.composeManyExtensions [
      (overrides.psycopg2 { inherit pkgs; })
      (overrides.python-ldap { inherit pkgs; })
    ];
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
    odooPythonEnv = pythonEnvs.odooPythonEnv;
  };

  # addons_path for the sandboxed runs: the assembled package's roots, plus
  # odoo-nix's own addons so dev_mailcatch is loadable server-wide -- the dev
  # shell's shape (devenv.nix, extraAddonsAbs), re-rooted on the store copy.
  addons = import ../lib/addons.nix {
    inherit lib workspaceRoot layout;
    coreSource = ocb;
    extraAddonsAbs = [ odooNixAddons ];
  };

  confSynth = import ../lib/odoo-conf.nix {
    inherit pkgs lib;
    addonsPath = addons.addonsPathFor "${builtOdoo}";
    odooConf = {
      # Empty host/password = keys left out = unix socket, no password (the
      # run passes --db_host=$PGHOST anyway).
      dbHost = "";
      dbPort = 5432;
      dbUser = "odoo";
      dbPassword = "";
      dbName = null;
      # Relative to CWD, which mkCheck sets to the build directory.
      dataDir = "./odoo-data";
      adminPasswd = "admin";
      httpInterface = "127.0.0.1";
      httpPort = 18069;
      geventPort = 18072;
      workers = 0;
      logging = {
        level = "test";
        handlers = [ ];
        db = false;
        dbLevel = "warning";
        file = null;
      };
      withoutDemo = true;
      extra = { };
    };
    # Mirrors devenv.nix: setting the key replaces Odoo's default set, and
    # 19.0's default includes `rpc`.
    serverWideModules = [
      "base"
    ]
    ++ lib.optional is19 "rpc"
    ++ [
      "web"
      "dev_mailcatch"
    ];
    extraSections.dev_mailcatch = {
      enabled = true;
      host = "127.0.0.1";
      port = mailcatchPort;
    };
  };
  conf = confSynth.odooConfFile;

  # In-sandbox PostgreSQL: postgresqlTestHook runs initdb + pg_ctl as the build
  # user on a unix socket under $NIX_BUILD_TOP/run/postgresql with TCP off, and
  # exports PGHOST/PGUSER/PGDATABASE. Odoo hands db_host to psycopg2 verbatim
  # and libpq treats a `/`-prefixed host as a socket directory.
  pg = {
    nativeCheckInputs = [
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
    builtodoo-addons-path = {
      expected = "${ocb}/odoo/addons,${ocb}/addons,/ROOT/custom";
      actual = builtOdoo.passthru.addonsPath "/ROOT";
    };
    builtodoo-version = {
      expected = series;
      actual = builtOdoo.passthru.odooVersion;
    };
  };

  all = {
    # uv.lock was locked against *this* pin: same series, same install_requires.
    lock-fresh =
      mkCheck "lock-fresh-${major}"
        {
          nativeCheckInputs = [ (pkgs.python3.withPackages (ps: [ ps.setuptools ])) ];
        }
        ''
          python3 ${./lock_fresh.py} ${workspaceRoot + "/uv.lock"} ${ocb} ${series}
        '';
  };

  linux = {
    # The deployable artifact assembles, its wrapper runs the real interpreter,
    # and it is the production env (no editable installs, no dev group).
    builtOdoo = mkCheck "builtOdoo-${major}" { } ''
      test -x ${builtOdoo}/odoo/odoo-bin
      test -f ${builtOdoo}/custom/${fixtureAddon}/__manifest__.py
      grep -q '${pythonEnvs.odooPythonEnv}/bin/python' ${builtOdoo}/bin/odoo
      ${builtOdoo}/bin/odoo --version | tee version.txt
      grep -qx 'Odoo Server ${series}' version.txt
    '';

    # `-i base` through the production wrapper. `web` is auto_install with
    # base and lives under <ocb>/addons, so its presence proves the second
    # core root; the dev_mailcatch banner proves extraAddonsAbs + [dev_mailcatch].
    odoo-init = mkCheck "odoo-init-${major}" pg ''
      ${builtOdoo}/bin/odoo ${odooArgs} -i base 2>&1 | tee odoo.log
      ${noErrors}
      ${installed "base"}
      ${installed "web"}
      grep -q 'dev_mailcatch ACTIVE' odoo.log
    '';

    # The fixture addon's Odoo tests, with the test env (prod wheels + dev
    # group). Odoo reports a skipped test exactly like a passed one (see the
    # odoo-test script in lib/scripts.nix), so the stats line must show the
    # module's tests actually ran.
    odoo-test = mkCheck "odoo-test-${major}" pg ''
      ${pythonEnvs.testPythonEnv}/bin/python ${builtOdoo}/odoo/odoo-bin ${odooArgs} \
        -i ${fixtureAddon} --test-enable --test-tags /${fixtureAddon} 2>&1 | tee odoo.log
      ${noErrors}
      grep -E '${fixtureAddon}: [1-9][0-9]* tests' odoo.log
      grep -E ' 0 failed, 0 error\(s\) of [1-9][0-9]* tests' odoo.log
      grep -q 'dev_mailcatch ACTIVE .* 127.0.0.1:${toString mailcatchPort}' odoo.log
      ${installed fixtureAddon}
    '';

    module-odoo = import ./module-odoo.nix {
      inherit pkgs series builtOdoo;
      odooModule = ../modules/nixos.nix;
    };
  };
}
