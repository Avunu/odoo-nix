---
title: The menu
description: "odoo ui, the dev shell's interactive menu: the stack and its logs, every odoo command as a form, and a store for OCA modules, stacks and git repositories."
order: 2
tags: [cli, modules, tui]
updated: 2026-10-28
---

`odoo ui` opens the dev shell's menu. So does a bare `odoo` typed at a terminal in the dev shell; `odoo server` still runs the server in the foreground, and a bare `odoo` without a terminal (a script, a pipe) is still `odoo-bin`'s server.

The menu changes nothing itself. Everything it does is an `odoo …` command line, shown before it runs and streamed while it does, so what the menu does and what you would type are the same thing. `c` in a confirmation copies the command line.

| Key | Tab | What it shows |
| --- | --- | --- |
| `1` | Home | The shell's banner, whether the stack is up, the server's URL (`o` opens it in the browser), and the everyday actions: provision, migrate, the Odoo shell, pull and refresh. |
| `2` | Stack | `devenv up`'s processes (postgres, odoo, mailpit) and the selected one's log. `r`, `s`, `x` restart, start and stop it. `u` starts the stack in the background, `d` stops it, and `b` rebuilds: stops it, re-evaluates the shell and starts it again. The stack outlives the menu. |
| `3` | Commands | Every `odoo` subcommand, and the `odoo-bin` ones it passes through, as a tree (`/` filters). The selected command is a form for its options; the command line it makes is shown as you fill it in. |
| `4` | Store | The series' OCA modules, the curated stacks (`data/oca-bundles.json`) and every module already in `modules/` and `custom/`. |

`ctrl+p` searches every action and command at once.

## The store

A bare `odoo module add` or `odoo module add-bundle`, typed at a terminal in the dev shell, opens the store alone, without the tabs, as their picker. Everything below works the same there, and `q` leaves it.

Type to search: every word must start a word of a module's name, title, repository or summary, so a repository's name lists its modules. The left column filters by stack or repository; `★` marks an application.

- `space` picks the highlighted module. Picked again, it is unpicked; an installed one (`✓`, in `modules.txt`) is picked for removal.
- On a stack, `b` picks the whole stack.
- The line at the bottom says what the picks bring with them: the OCA modules Odoo installs alongside them.
- `a` shows what will run: `odoo module add-bundle`, `odoo module add`, `odoo module remove`, with the new repositories the closure needs. Run it, and the menu offers **Rebuild, restart and install**: the stack restarts from a re-evaluated shell (the addons path changed) and `odoo db provision` installs `modules.txt`.
- **Add a Git repository** takes any repository (`owner/repo` on GitHub, or a URL) and an optional branch: `odoo module add <url> [branch]`.

The detail pane shows the module's manifest, and its `readme/` fragments from GitHub when the network allows.
