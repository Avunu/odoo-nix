# `odoo-nix-build-deps {update,check} [pyproject.toml] [uv.lock]`: keeps
# [tool.uv.extra-build-dependencies] in step with uv.lock, between the
# `# >>> odoo-nix: sdist build deps (managed) >>>` sentinels. Every package
# the lock has no wheel for gets setuptools. python-devops-nix's
# lib.python.buildDeps (python/uv_build_deps.py there).
{ pkgs, base }:
base.python.buildDeps {
  inherit pkgs;
  label = "odoo-nix";
  # Listed whatever the lock says: reliably sdist-only across platforms and
  # versions, even when this run's lock happens to have a wheel.
  always = pkgs.lib.genAttrs [ "docopt" "ofxparse" "python-ldap" "rjsmin" "vobject" ] (_: [
    "setuptools"
  ]);
}
