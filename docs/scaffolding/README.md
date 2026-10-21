---
title: Choose a mode
description: The two things the odoo-nix scaffolder does, how it picks one from the directory you run it in, and when to write the flake yourself instead.
nav_title: Scaffolding
order: 3
tags: [scaffolding, odoo-init]
updated: 2026-10-21
---

`nix run github:Avunu/odoo-nix` runs `odoo-init`. It has two modes, and it detects which one from the target directory (the current directory when that is an Odoo tree or an odoo-nix project, otherwise a new directory it asks for or you name):

| The directory                                                          | Mode                         | Read                                         |
| ---------------------------------------------------------------------- | ---------------------------- | -------------------------------------------- |
| Empty, or missing                                                      | Scaffold a new project       | [Create a new project](new-project.md)        |
| An Odoo tree in odoo-nix's layout: OCB at `odoo/`, repos under `modules/`, your modules under `custom/` | Migrate it in place          | [Migrate an existing tree](migrate.md)        |
| Already an odoo-nix project                                            | Repair it (migration mode)   | [Migrate an existing tree](migrate.md#repair) |
| Anything else that is not empty                                        | Refused, with the flag that would force a mode | [Scaffolder](../reference/scaffolder.md#exit-codes) |

`--init` and `--migrate` force a mode, and `--dry-run` prints the plan without changing anything. Neither mode overwrites a file that exists or commits anything unless you pass `--commit`: the result is staged for you to review.

A repository that is a **library of modules** mounted by other projects is a different shape: it takes OCB as a flake input instead of a submodule. The scaffolder does not write that one. See [Write the flake by hand](write-the-flake.md#a-repository-of-modules).

Every flag and exit code is in the [scaffolder reference](../reference/scaffolder.md).
