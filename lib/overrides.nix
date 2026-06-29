# Composable Python package overrides for packages that need system libraries.
#
# With uv2nix `sourcePreference = "wheel"`, most of Odoo's native deps resolve to
# prebuilt manylinux wheels and need no override. These overlays are the safety
# net for when a source build is forced (e.g. no wheel for the locked version or
# the target platform). They mirror frappe-nix/lib/overrides.nix.
#
# Each override takes `pkgs` (and any system packages) and returns a Python
# package-set overlay (final: prev: { ... }).
#
# Usage in a consuming flake:
#   pythonOverrides = lib.composeManyExtensions [
#     (odoo-nix.lib.overrides.psycopg2 { inherit pkgs; })
#     (odoo-nix.lib.overrides.python-ldap { inherit pkgs; })
#   ];

{
  # psycopg2 (non-binary; Odoo requires the source package) builds from sdist and
  # needs pg_config at build time + libpq to link. In current nixpkgs pg_config is
  # split out as `postgresql.pg_config` and the client lib is `libpq`.
  psycopg2 =
    { pkgs }:
    final: prev: {
      psycopg2 = prev.psycopg2.overrideAttrs (old: {
        nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
          final.setuptools
          pkgs.postgresql.pg_config
        ];
        buildInputs = (old.buildInputs or [ ]) ++ [
          pkgs.libpq
          pkgs.openssl
          pkgs.zlib
        ];
      });
    };

  # python-ldap needs OpenLDAP + Cyrus SASL headers. It also hardcodes the legacy
  # reentrant lib name `ldap_r` in setup.cfg, but modern OpenLDAP (2.5+) merged
  # libldap_r into libldap, so patch the link target to plain `ldap`/`lber`.
  python-ldap =
    { pkgs }:
    final: prev: {
      python-ldap = prev.python-ldap.overrideAttrs (old: {
        nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
          final.setuptools
          pkgs.pkg-config
        ];
        buildInputs = (old.buildInputs or [ ]) ++ [
          pkgs.openldap
          pkgs.cyrus_sasl
          pkgs.openssl
        ];
        postPatch = (old.postPatch or "") + ''
          if [ -f setup.cfg ]; then
            substituteInPlace setup.cfg --replace-quiet "ldap_r" "ldap"
          fi
        '';
      });
    };

  # lxml needs libxml2 + libxslt headers.
  lxml =
    { pkgs }:
    final: prev: {
      lxml = prev.lxml.overrideAttrs (old: {
        nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
          final.setuptools
          pkgs.pkg-config
          pkgs.libxml2.dev
          pkgs.libxslt.dev
        ];
        buildInputs = (old.buildInputs or [ ]) ++ [
          pkgs.libxml2
          pkgs.libxslt
          pkgs.zlib
        ];
      });
    };

  # libsass bundles its own sources; it only needs a C++ toolchain, supplied by
  # stdenv. Provided for completeness / forced source builds.
  libsass =
    _:
    final: prev: {
      libsass = prev.libsass.overrideAttrs (old: {
        nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
          final.setuptools
        ];
      });
    };
}
