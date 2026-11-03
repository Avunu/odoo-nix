Copies of the target repositories' own files, kept byte for byte (real names kept), for
the suites that edit them. Refresh a copy with `git show <rev>:<path>` and say so here.

| Directory | Files | From | Read by |
| --- | --- | --- | --- |
| `manifests/` | addon manifests | see `manifests/README.md` | `test_discover` |
| `vscode/` | `ruckus-settings.json`, `ruckus-extensions.json` | `Walnook-LLC/odoo-ruckus` `master` `35bd79c` `.vscode/` | `test_ide_real` |
| `vscode/` | `millrun-settings.json`, `millrun-extensions.json` | `Avunu/millrun` `main` `f7530da` `.vscode/` | `test_ide_real` |
| `flakes/` | `ruckus.nix`, `millrun.nix` | the same commits' `flake.nix` | `test_flake_block` |
| `flakes/` | `edi-addons.nix`, `vertical-auto-repair-addons.nix` | `Avunu/edi-addons` `df99108`, `Avunu/vertical-auto-repair-addons` `ec8a565` (`feat/odoo-standards`) `flake.nix` | `test_flake_block` |
| `pyproject/` | `ruckus.toml`, `edi-addons-nix.toml` | odoo-ruckus `pyproject.toml`, edi-addons `nix/pyproject.toml` (same commits) | `test_foreign_blocks` |
| `gitignore/` | `ruckus.gitignore`, `millrun.gitignore`, `edi-addons.gitignore` | the same commits' `.gitignore` | `test_blocks` |

The flakes are not linted (`flake.nix` `nixLintIgnore`): odoo-ruckus's and millrun's carry
the unused `self` deadnix reports (DESIGN.md §8.3), which is part of what they test.
