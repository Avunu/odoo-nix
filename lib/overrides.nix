# Python package-set overlays for packages that need system libraries, as
# odoo-nix exports them (flake.lib.overrides): `<package> { pkgs }` is a
# pyproject-nix overlay (final: prev: { ... }).
#
# Every one but libsass is python-devops-nix's (lib.python.packageOverrides):
# the fixes frappe-nix and odoo-nix share, which lib/python.nix already
# applies to every project. They stay here for a flake that builds its own
# package set. libsass is odoo-nix's alone.
#
# Usage in a consuming flake:
#   pythonOverrides = lib.composeManyExtensions [
#     (odoo-nix.lib.overrides.libsass { inherit pkgs; })
#   ];
{ pythonLib }:
let
  # The names do not depend on pkgs, so the set's attribute names can be read
  # before one is passed.
  shared = builtins.attrNames (
    pythonLib.packageOverrides {
      pkgs = throw "lib.overrides: the package names need no pkgs";
    }
  );
in
builtins.listToAttrs (
  map (name: {
    inherit name;
    value = { pkgs }: (pythonLib.packageOverrides { inherit pkgs; }).${name};
  }) shared
)
// {
  # libsass bundles its own sources; it only needs a C++ toolchain, supplied by
  # stdenv. Provided for completeness / forced source builds.
  libsass = _: final: prev: {
    libsass = prev.libsass.overrideAttrs (old: {
      nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [
        final.setuptools
      ];
    });
  };
}
