# odoo-nix

Reusable Nix infrastructure for [Odoo](https://www.odoo.com/) projects built on the [Odoo Community Backports (OCB)](https://github.com/OCA/OCB) distribution and [OCA](https://odoo-community.org/) modules.

**Documentation:** [docs.avunu.net/odoo-nix/](https://docs.avunu.net/odoo-nix/). The same pages are in [`docs/`](docs/README.md), so they also read on GitHub.

odoo-nix packages everything needed to develop and ship an Odoo and OCA project declaratively, so a project's flake stays a thin wrapper. From a small source tree (OCB and the module repositories as git submodules, a `modules.txt`, a `pyproject.toml` and its `uv.lock`) it provides:

-   a **scaffolder**, `nix run github:Avunu/odoo-nix`, that creates a project with optional OCA bundles and modules and the repositories they depend on, or brings an existing Odoo tree into odoo-nix in place
-   a **devenv** development shell (PostgreSQL, Odoo, Mailpit) with live reload, editor and odoo-ls integration, and [guard rails](docs/development/guard-rails.md) that stop a restored production database from mailing customers or reaching production storage
-   an **`addons_path` derived from the folders on disk** and an **`odoo.conf` synthesized by Nix**
-   a reproducible **Python environment** built by [uv2nix](https://github.com/pyproject-nix/uv2nix) from the committed `uv.lock`
-   one **`odoo` command** for the database lifecycle (`db provision`, `migrate`, `backup`, `restore`, …), module management (`module add`, `add-bundle`, `remove`) and workspace updates, passing everything else through to `odoo-bin`: the same command in the dev shell, on a server and in a container
-   a single-instance **NixOS module**, `services.odoo-nix`, with snapshot-protected migrations before every start, secrets kept out of the store and journald logging
-   an **OCI container image**
-   **age-encrypted secrets**, shared by the dev shell and the server

It is consumed as a [flake-parts](https://flake.parts/) module.

## Quick start

```sh
nix run github:Avunu/odoo-nix -- --version 18.0 --name acme --db acme acme
cd acme && direnv allow
devenv up               # PostgreSQL, Odoo, Mailpit
odoo db provision       # (another shell) create the database and install modules.txt
```

The banner prints the server's and Mailpit's addresses. See [Getting started](docs/getting-started.md).

## Where to read more

| I want to… | Read |
| --- | --- |
| try it | [Getting started](docs/getting-started.md) |
| scaffold a project or migrate an existing tree | [Choose a mode](docs/scaffolding/README.md) |
| write or understand the flake | [Write the flake by hand](docs/scaffolding/write-the-flake.md) |
| work in the dev shell | [The development shell](docs/development/README.md), [The odoo command](docs/development/commands.md), [Manage modules](docs/development/modules.md) |
| restore production data | [Secrets](docs/development/secrets.md), [Restore a production backup](docs/development/restore-from-production.md) |
| deploy | [From development to production](docs/production/README.md), [Run Odoo as a NixOS service](docs/production/nixos-service.md), [The container image](docs/production/container.md) |
| upgrade odoo-nix | [Upgrading odoo-nix](docs/development/upgrading.md) |
| look up an option | [Dev shell options](docs/reference/dev-shell-options.md), [`services.odoo-nix` options](docs/reference/nixos-options.md), [Secrets options](docs/reference/secrets-options.md) |
| fix an error | [FAQ and troubleshooting](docs/reference/troubleshooting.md) |
| work on odoo-nix itself | [Repository layout](docs/reference/layout.md) |

## License

MIT, see [LICENSE](LICENSE).

The test fixture addons (`tests/fixtures/`) are Odoo modules and declare `LGPL-3` in their own `__manifest__.py`.
