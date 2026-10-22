# Evaluation-level assertions over the flake-parts module's container image
# (modules/containers.nix): the name the image is built under, with and
# without containers.registry and containers.roleImageNames, and the parts of
# its config python-devops-nix's CONVENTIONS.md (Containers) asks for: the
# OCI labels, a healthcheck, and the User with and without
# containers.nonRoot. A consumer's flake is evaluated through lib.mkFlake and
# only the image's imageName and passthru.imageConfig are read, so nothing is
# built (and the 1.x-name warning, which sits on drvPath, never fires).
# Same `pairs` shape as eval.nix; flake.nix turns each into a named
# check (lib.checks.mk's `eval`).
{
  pkgs,
  inputs,
  mkFlake,
}:
let
  inherit (pkgs.stdenv.hostPlatform) system;

  image =
    containers:
    (mkFlake
      {
        inputs.self = {
          outPath = ../.;
          inherit inputs;
        };
      }
      {
        systems = [ system ];
        imports = [ ../modules/flake-module.nix ];
        perSystem.odoo-nix = {
          enable = true;
          name = "acme";
          workspaceRoot = ./fixtures/19.0;
          coreSource = inputs.ocb-19;
          odooSeries = "19.0";
          python = pkgs.python312;
          containers = {
            enable = true;
          }
          // containers;
        };
      }
    ).packages.${system}.container-odoo;

  imageName = containers: (image containers).imageName;
  inherit (image { }) imageConfig;
  nonRootConfig = (image { nonRoot = true; }).imageConfig;
  hasHome = config: builtins.elem "HOME=/var/lib/odoo" config.Env;
in
{
  # 1.x: 1.0's <name>-odoo unless roleImageNames.
  container-name = {
    expected = "acme-odoo";
    actual = imageName { };
  };
  container-name-registry = {
    expected = "ghcr.io/avunu/acme-odoo";
    actual = imageName { registry = "ghcr.io/avunu"; };
  };
  container-name-role = {
    expected = "acme/odoo";
    actual = imageName { roleImageNames = true; };
  };
  container-name-role-registry = {
    expected = "ghcr.io/avunu/acme/odoo";
    actual = imageName {
      roleImageNames = true;
      registry = "ghcr.io/avunu";
    };
  };
  # A trailing slash is the separator already: not doubled.
  container-name-role-registry-slash = {
    expected = "ghcr.io/avunu/acme/odoo";
    actual = imageName {
      roleImageNames = true;
      registry = "ghcr.io/avunu/";
    };
  };
  # 1.x: root, as before, unless nonRoot.
  container-user = {
    expected = {
      user = "0:0";
      home = false;
    };
    actual = {
      user = imageConfig.User;
      home = hasHome imageConfig;
    };
  };
  container-user-non-root = {
    expected = {
      user = "1000:1000";
      home = true;
    };
    actual = {
      user = nonRootConfig.User;
      home = hasHome nonRootConfig;
    };
  };
  container-labels = {
    expected = [
      "org.opencontainers.image.licenses"
      "org.opencontainers.image.source"
      "org.opencontainers.image.title"
      "org.opencontainers.image.version"
    ];
    actual = builtins.attrNames imageConfig.Labels;
  };
  container-label-title = {
    expected = "acme-odoo";
    actual = imageConfig.Labels."org.opencontainers.image.title";
  };
  # containers.labels goes over the defaults.
  container-label-override = {
    expected = "https://example.com/acme";
    actual =
      (image { labels."org.opencontainers.image.source" = "https://example.com/acme"; })
      .imageConfig.Labels."org.opencontainers.image.source";
  };
  container-healthcheck = {
    expected = [
      "CMD"
      3
    ];
    actual = [
      (builtins.head imageConfig.Healthcheck.Test)
      imageConfig.Healthcheck.Retries
    ];
  };
}
