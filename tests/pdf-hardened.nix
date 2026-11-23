# A NixOS VM test for the sandbox of the units that render PDF reports: odoo.service
# and odoo-migrate (modules/nixos.nix, odooHardening and webHardening). A unit with
# their profile selection (python-devops-nix's chromium and jit profiles) and their
# SystemCallFilter (lib/pdf-hardening.nix) runs pdfkiln's wkhtmltopdf, and the file it
# writes starts with %PDF. Odoo's own VM tests start Odoo but render no report, so this
# is what shows the widened filter works on Odoo's PDF path. It runs no Odoo: the
# hardened unit is all the check needs.
#
# Run: nix build --no-link -L .#checks.<system>.pdf-hardened   (needs KVM)
{
  pkgs,
  base,
  pdfkiln,
}:
let
  # Odoo's home is its state directory, and Chromium writes its profile under
  # HOME, so the probe's home is writable the same way.
  state = "/var/lib/pdf-probe";
  html = pkgs.writeText "probe.html" "<html><body><h1>pdf-hardened</h1></body></html>";
  # The overrides Odoo's PDF units get, from the same file (modules/nixos.nix).
  pdfHardening = import ../lib/pdf-hardening.nix { inherit (pkgs) lib; };
in
# A test module: flake.nix registers it with lib.checks.mk's nixosTest, which names it.
{
  nodes.machine = {
    virtualisation.memorySize = 2048;
    fonts.packages = [ pkgs.liberation_ttf ];
    users.users.odoo = {
      isSystemUser = true;
      group = "odoo";
      home = state;
    };
    users.groups.odoo = { };
    systemd.tmpfiles.rules = [ "d ${state} 0750 odoo odoo -" ];

    systemd.services.pdf-probe = {
      description = "Render a PDF under the sandbox of Odoo's PDF units";
      path = [ pdfkiln ];
      serviceConfig = {
        Type = "oneshot";
        User = "odoo";
        Group = "odoo";
        ExecStart = pkgs.writeShellScript "pdf-probe" ''
          wkhtmltopdf --quiet ${html} ${state}/probe.pdf
        '';
      }
      // base.nixos.hardening {
        readWritePaths = [ state ];
        profiles = [
          "chromium"
          "jit"
        ];
        overrides = pdfHardening;
      };
    };
  };

  testScript = ''
    machine.wait_for_unit("multi-user.target")
    machine.succeed("systemctl start pdf-probe.service")
    machine.succeed("head -c 4 ${state}/probe.pdf | grep -x %PDF")
    # systemd prints the filter's expanded syscall names: chroot(2) is in @mount.
    machine.succeed("systemctl show pdf-probe.service -P SystemCallFilter | grep -qw chroot")
  '';
}
