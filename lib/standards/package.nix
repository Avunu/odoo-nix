# odoo-nix-tools (py/odoo_nix_tools), with standards-core from python-devops-nix
# (its DESIGN.md §10.3). Called with <python>Packages.callPackage: flake.nix builds
# it on python3, and on python311 (the core's floor) for checks.standards-unit.
#
# `base` is python-devops-nix's lib; `coreRev` is the python-devops-nix input's
# rev, written into standards-core's _source.json for the version-skew row (null
# when the input has none, as a `path:` override in development).
#
# pythonRuntimeDepsCheck stays on: it fails the build when the standards-core
# built here does not satisfy py/odoo_nix_tools/pyproject.toml. The unittest
# suites in py/odoo_nix_tools/tests run as the check phase, with the odoo-nix
# files they read from outside the package (the standards fixtures,
# version.txt, lib/odoo-presets.json) under $ODOO_NIX_TOOLS_REPO.
{
  lib,
  base,
  pkgs,
  python,
  buildPythonPackage,
  flit-core,
  unittestCheckHook,
  git,
  coreRev ? null,
}:
let
  src = ../../py/odoo_nix_tools;
  # The repository files the suites compare against, at their repository paths.
  repoFiles = lib.fileset.toSource {
    root = ../..;
    fileset = lib.fileset.unions [
      ../../version.txt
      ../odoo-presets.json
      ../../tests/fixtures/standards-project
      ../../tests/fixtures/standards-addons
      ../../tests/fixtures/standards-profiles
    ];
  };
  standardsCore = base.standards.package {
    inherit pkgs python;
    rev = coreRev;
  };
in
buildPythonPackage {
  pname = "odoo-nix-tools";
  inherit ((lib.importTOML (src + "/pyproject.toml")).project) version;
  pyproject = true;

  # The distribution and its tests: not DESIGN.md, scripts/ or byte-compiled files.
  src = lib.fileset.toSource {
    root = src;
    fileset = lib.fileset.difference (lib.fileset.unions [
      (src + "/pyproject.toml")
      (src + "/README.md")
      (src + "/odoo_nix_tools")
      (src + "/tests")
    ]) (lib.fileset.fileFilter (f: f.hasExt "pyc") src);
  };

  build-system = [ flit-core ];
  dependencies = [ standardsCore ];

  nativeCheckInputs = [
    unittestCheckHook
    git
  ];
  unittestFlags = [
    "-s"
    "tests"
    "-v"
  ];
  # The suites create throwaway repositories; git wants a home and no user config.
  preCheck = ''
    export HOME="$TMPDIR" GIT_CONFIG_GLOBAL=/dev/null
    export ODOO_NIX_TOOLS_REPO=${repoFiles}
  '';

  pythonImportsCheck = [
    "odoo_nix_tools"
    "odoo_nix_tools.cli"
    "odoo_nix_tools.product"
  ];

  meta = {
    description = "odoo-nix's standards tools";
    license = lib.licenses.mit;
    mainProgram = "odoo-nix";
  };
}
