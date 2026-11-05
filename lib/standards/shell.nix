# What the standards add to an odoo-nix dev shell (py/odoo_nix_tools/DESIGN.md
# §5.2), all gated on the [tool.odoo-nix] opt-in line of the shape's config file:
# a project's root pyproject.toml, an addon repository's nix/pyproject.toml. A
# shell that has not opted in is byte for byte one without this file
# (checks.standards-shell-eval).
#
#   optedIn       the config file has the table
#   nodeExcludes  "." in addons mode with a root package.json: the standards'
#                 node_modules is the root's, not an addon's build
#   apps          odoo-init (--sync, --check, --standards) and odoo-nix
#   devShells     odoo-nix-lint: CI's lint gate and pr-policy, without Odoo or
#                 PostgreSQL
#   devenvModule  the dev shell's packages and its entry: the tool links, git's
#                 blame.ignoreRevsFile, `prek install -c`
#   lintShell     the lint shell, opted in or not (lib.standards.lintShell)
#   links         the shell code that links tools/.venv, tools/.bin and
#                 node_modules (shared by both shells)
#   tools, nixTools, nixToolsEnv
#                 what they link: lib/standards/tools.nix's, and the engine's
#                 Nix tools (tools/.bin)
{
  pkgs,
  lib,
  workspaceRoot,
  # The file holding [tool.odoo-nix], from the root.
  configFile,
  addonsMode,
  odooNix,
  odooInit,
  # lib/standards/tools.nix over the checkout.
  tools,
}:
let
  path = workspaceRoot + "/${configFile}";
  # `[tool.odoo-nix]`, `[tool.odoo-nix.<x>]` or `[[tool.odoo-nix.<x>]]` on a line of
  # its own: the core's opt-in rule, read without parsing the file.
  optInLine = line: builtins.match "[[:space:]]*\\[{1,2}tool\\.odoo-nix[].].*" line != null;
  optedIn =
    builtins.pathExists path
    && lib.any (l: builtins.isString l && optInLine l) (builtins.split "\n" (builtins.readFile path));

  # The engine's Nix tools the hooks run from tools/.bin (DESIGN.md §3.3 rule 5).
  nixTools = [
    pkgs.committed
    pkgs.actionlint
    pkgs.zizmor
    pkgs.shellcheck
    pkgs.nixfmt-rs
    pkgs.statix
    pkgs.deadnix
  ];
  nixToolsEnv = pkgs.buildEnv {
    name = "odoo-nix-standards-tools";
    paths = nixTools;
  };

  # A store path that is a link to `path` inside another: a link to it can be a GC
  # root (`nix-store --add-root` roots whole store paths, and rewrites a link to a
  # subdirectory into one to its store path).
  storeLink =
    name: path:
    pkgs.runCommandLocal name { } ''
      ln -s ${path} $out
    '';
  binLink = storeLink "odoo-nix-standards-bin" "${nixToolsEnv}/bin";

  # Anchored on the work tree's top level, not $DEVENV_ROOT, which the plain
  # mkShell lint shell does not set. A real directory where a link goes is left
  # alone, as ideSetup leaves .venv (modules/devenv.nix). Each link is an indirect
  # GC root, so a garbage collection between shell entries does not leave the
  # hooks of a GUI commit dangling.
  links = ''
    _odoo_nix_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    _odoo_nix_link() { # <link, from the root> <store path>
      local link="$_odoo_nix_root/$1"
      if [ -e "$link" ] && [ ! -L "$link" ]; then
        echo "⚠  ./$1 exists and is not a symlink — leaving it alone." >&2
        echo "   Remove it to let odoo-nix link the standards' tools there." >&2
      elif [ "$(readlink "$link" 2>/dev/null)" != "$2" ]; then
        mkdir -p "$(dirname "$link")"
        ln -sfn "$2" "$link"
        if command -v nix-store >/dev/null; then
          nix-store --add-root "$link" --indirect --realise "$2" >/dev/null 2>&1 || true
        fi
      fi
    }
    _odoo_nix_unlink() { # <link>: a dangling link goes
      if [ -L "$_odoo_nix_root/$1" ] && [ ! -e "$_odoo_nix_root/$1" ]; then
        rm -f "$_odoo_nix_root/$1"
      fi
    }
    ${
      if tools.toolsEnv != null then
        ''_odoo_nix_link tools/.venv "${tools.toolsEnv}"''
      else
        "_odoo_nix_unlink tools/.venv"
    }
    _odoo_nix_link tools/.bin "${binLink}"
    ${lib.optionalString (tools.nodeModules != null) ''
      _odoo_nix_link node_modules "${storeLink "odoo-nix-standards-node-modules" "${tools.nodeModules}/node_modules"}"
    ''}
    unset -f _odoo_nix_link _odoo_nix_unlink
  '';

  lintShell = pkgs.mkShell {
    name = "odoo-nix-lint";
    packages = [
      odooNix
      tools.prek
      pkgs.git
    ]
    ++ nixTools;
    shellHook = links;
  };
in
{
  inherit
    optedIn
    nixTools
    nixToolsEnv
    links
    lintShell
    tools
    ;

  nodeExcludes = lib.optional (
    optedIn && addonsMode && builtins.pathExists (workspaceRoot + "/package.json")
  ) ".";

  apps = lib.optionalAttrs optedIn {
    odoo-init = {
      type = "app";
      program = lib.getExe odooInit;
      meta.description = "odoo-init --sync / --check / --standards: odoo-nix's managed files";
    };
    odoo-nix = {
      type = "app";
      program = lib.getExe odooNix;
      meta.description = "odoo-nix's standards tools: managed files, profiles and configuration";
    };
  };

  devShells = lib.optionalAttrs optedIn { odoo-nix-lint = lintShell; };

  devenvModule = {
    key = "odoo-nix:lib/standards/shell.nix";
  }
  // lib.optionalAttrs optedIn {
    packages = [
      odooNix
      odooInit
      tools.prek
    ]
    ++ nixTools;
    enterShell = links + ''
      if [ -f "$_odoo_nix_root/.git-blame-ignore-revs" ] \
        && [ "$(git -C "$_odoo_nix_root" config --get blame.ignoreRevsFile || true)" != .git-blame-ignore-revs ]; then
        git -C "$_odoo_nix_root" config blame.ignoreRevsFile .git-blame-ignore-revs || true
      fi
      # `-c`: a commit runs the root config only, never prek's workspace mode over
      # a nested one (DESIGN.md §1.2). Not in CI, which runs `odoo-nix gate lint`.
      case "''${ODOO_NIX_CI:-}" in
        "" | 0 | false)
          if [ -f "$_odoo_nix_root/.pre-commit-config.yaml" ]; then
            _odoo_nix_hook="$(cd "$_odoo_nix_root" && git rev-parse --git-path hooks/pre-commit)"
            case "$_odoo_nix_hook" in /*) ;; *) _odoo_nix_hook="$_odoo_nix_root/$_odoo_nix_hook" ;; esac
            if ! grep -qF "$(readlink -f "${lib.getExe tools.prek}")" "$_odoo_nix_hook" 2>/dev/null; then
              (cd "$_odoo_nix_root" \
                && ${lib.getExe tools.prek} install -c .pre-commit-config.yaml \
                  --hook-type pre-commit --hook-type commit-msg >/dev/null) || true
            fi
            unset _odoo_nix_hook
          fi
          ;;
      esac
    '';
  };
}
