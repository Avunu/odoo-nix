# Evaluation-level assertions over the flake-parts module's container image
# (modules/containers.nix): the name the image is built under, with and
# without containers.registry, and the parts of its config python-devops-nix's
# docs/conventions.md (Containers) asks for: the OCI labels, a healthcheck, and the
# User with and without containers.nonRoot, and the directories the image
# makes writable. A consumer's flake is evaluated through lib.mkFlake and only
# the image's imageName, passthru.imageConfig and its customisation layer's
# fakeRootCommands are read, so nothing is built.
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
  rootConfig = (image { nonRoot = false; }).imageConfig;
  hasHome = config: builtins.elem "HOME=/var/lib/odoo" config.Env;

  # The customisation layer's fakeRootCommands, one command a line. The layer
  # is reached through the image's layers JSON, which dockerTools builds
  # from it.
  setup =
    containers:
    let
      inherit (pkgs) lib;
      layer =
        lib.findFirst (d: d ? fakeRootCommands) (throw "no customisation layer")
          (image containers).stream.conf.layersJsonFile.exportReferencesGraph.graph;
    in
    builtins.filter (line: line != "") (map lib.trim (lib.splitString "\n" layer.fakeRootCommands));
in
{
  # <registry>/<name>/odoo since 2.0.0 (python-devops-nix's
  # <registry>/<name>/<role>).
  container-name = {
    expected = "acme/odoo";
    actual = imageName { };
  };
  container-name-registry = {
    expected = "ghcr.io/avunu/acme/odoo";
    actual = imageName { registry = "ghcr.io/avunu"; };
  };
  # A trailing slash is the separator already: not doubled.
  container-name-registry-slash = {
    expected = "ghcr.io/avunu/acme/odoo";
    actual = imageName { registry = "ghcr.io/avunu/"; };
  };
  # Non-root since 2.0.0: uid/gid 1000, home /var/lib/odoo.
  container-user = {
    expected = {
      user = "1000:1000";
      home = true;
    };
    actual = {
      user = imageConfig.User;
      home = hasHome imageConfig;
    };
  };
  # nonRoot = false: root, as through 1.x.
  container-user-root = {
    expected = {
      user = "0:0";
      home = false;
    };
    actual = {
      user = rootConfig.User;
      home = hasHome rootConfig;
    };
  };
  # What odoo writes: /etc/odoo (the entrypoint's odoo.conf), the filestore
  # under /var/lib/odoo, and /tmp. Owned by uid/gid 1000 with nonRoot.
  container-writable = {
    expected = [
      "mkdir -p /tmp /var/lib/odoo/data"
      "chmod 1777 /tmp"
      "mkdir -p /etc/odoo /var/lib/odoo"
      "chown -Rh 1000:1000 /etc/odoo /var/lib/odoo"
    ];
    actual = setup { };
  };
  container-writable-root = {
    expected = [
      "mkdir -p /tmp /var/lib/odoo/data"
      "chmod 1777 /tmp"
      "mkdir -p /etc/odoo /var/lib/odoo"
    ];
    actual = setup { nonRoot = false; };
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
    expected = "acme/odoo";
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
