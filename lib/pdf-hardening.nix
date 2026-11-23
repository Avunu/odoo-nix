# The systemd overrides for the units that render PDF reports with pdfkiln: odoo.service
# and odoo-migrate (modules/nixos.nix builds them on python-devops-nix's chromium and jit
# profiles). tests/pdf-hardened.nix applies the same set to a probe unit and renders a
# PDF with it, so the test and the units cannot drift apart.
#
# Chromium keeps its own sandbox. Its zygote enters a namespace sandbox that drops its
# file-system access with chroot(2), and chroot is in @mount, which @system-service does
# not include. Refused, the zygote fails its CHECK and Chromium does not start, so no
# PDF is made. So the filter adds @mount, and nothing else. The bounding set stays
# empty: the unit's own processes still cannot mount anything, and the mount calls
# only succeed inside the user namespaces Chromium creates for its sandbox.
{ lib }:
{
  # lib.mkDefault, as the baseline's keys are: a host can relax this one key on one
  # unit with a plain assignment to systemd.services.<unit>.serviceConfig.SystemCallFilter.
  SystemCallFilter = lib.mkDefault [
    "@system-service"
    "@mount"
  ];
}
