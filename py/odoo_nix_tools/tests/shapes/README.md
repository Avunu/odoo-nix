Shapes for the suites that edit consumers' files. Two kinds:

- copies of Avunu's public addon repositories' own files, kept byte for byte (real names
  kept): refresh one with `git show <rev>:<path>` and say so here;
- synthetic files representative of a project-shape checkout (`project-a`, `project-b`),
  written for these tests: each keeps the properties its suite reads (named below and in
  the suite's docstring), so change one only with its suite.

| Directory | Files | From | Read by |
| --- | --- | --- | --- |
| `manifests/` | addon manifests | see `manifests/README.md` | `test_discover`, `test_release` |
| `vscode/` | `project-b-settings.json` (4-space, `git.detectSubmodules`, `python-envs.defaultEnvManager`, `Odoo.selectedProfile`), `project-b-extensions.json` (no final newline) | synthetic | `test_ide_real` |
| `vscode/` | `project-a-settings.json` (2-space, an inline array), `project-a-extensions.json` (`bierner.lit-html`) | synthetic | `test_ide_real` |
| `flakes/` | `project-b.nix` (`self.submodules`, an indented string), `project-a.nix` | synthetic | `test_flake_block` |
| `flakes/` | `edi-addons.nix`, `vertical-auto-repair-addons.nix` | `Avunu/edi-addons` `df99108`, `Avunu/vertical-auto-repair-addons` `ec8a565` (`feat/odoo-standards`) `flake.nix` | `test_flake_block` |
| `pyproject/` | `project-b.toml` (odoo-nix's three generated blocks) | synthetic | `test_foreign_blocks` |
| `pyproject/` | `edi-addons-nix.toml` | edi-addons `nix/pyproject.toml` (same commit) | `test_foreign_blocks` |
| `gitignore/` | `project-b.gitignore`, `project-a.gitignore` | synthetic | `test_blocks` |
| `gitignore/` | `edi-addons.gitignore` | edi-addons `.gitignore` (same commit) | `test_blocks` |

The flakes are not linted (`flake.nix` `nixLintIgnore`): the project flakes carry the
unused `self` deadnix reports (DESIGN.md §8.3), which is part of what they test.

The three icon shapes (`ok-128`, `wide-200x100`, `heavy-150k`) are not files: `support.ICONS`
makes them (`support.png`), so no binary is kept for them.
