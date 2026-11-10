# Agents

Coding agents push changes that CI sends back for things the pre-commit hooks would have caught. The hooks are installed per clone, by the dev shell's entry (`prek install`), and an agent working in a fresh clone, a worktree, or outside `direnv` never enters that shell. Nothing then runs on its commits, and nothing tells it to run the gates by hand.

`ide.agents = true` closes that gap for Claude Code, and tells every other agent what to run.

```toml
[tool.odoo-nix.ide]
enable = true
agents = true
```

## What sync writes

| File | Strategy | What it holds |
| --- | --- | --- |
| `AGENTS.md` | a sentinel block, appended at the end | the checks to run before a push: the commands, in order. The rest of the file is yours: a repository's own guidance goes above the block |
| `CLAUDE.md` | whole | `@AGENTS.md`, so Claude Code reads the same text |
| `.claude/settings.json` | whole | the three hooks below |

`AGENTS.md` is read by Claude Code (through `CLAUDE.md`), Codex, Cursor, Copilot and others. The hooks are Claude Code's. A personal setting belongs in `.claude/settings.local.json`, which this module never touches.

## The hooks

Each one runs `odoo-nix agent hook <event>`: the dev shell's `odoo-nix` when it is on `PATH`, else the lint shell's (`nix develop --no-pure-eval .#odoo-nix-lint`, the shell CI's lint gate runs in, which links the locked tools). Without Nix they do nothing.

| Event | Does |
| --- | --- |
| `SessionStart` | installs the git hooks (`pre-commit`, `commit-msg`) where they are missing, so every commit is checked from the first one |
| `PreToolUse` on `Bash` | before a `git push` or `gh pr create`/`ready`, runs `odoo-nix gate lint` and refuses the command while a step fails. A gate that cannot run (exit 3: a tool or the base branch is missing) is reported and lets the command through |
| `Stop` | runs `prek run -c .pre-commit-config.yaml --files …` on the files the working tree changed, and sends a failure back to the agent. It runs once per stop: the agent gets one chance to fix, and a finding it cannot fix never traps the session. The commit hook and CI still refuse it |

The `Stop` check looks at the working tree, so a file rewritten by a script is checked as well as one edited with a tool. There is no per-edit hook: the pre-commit hooks are formatters, and a file rewritten between an agent's edits makes its next edit fail.

`odoo-nix gate test` is not a hook: it takes minutes. `AGENTS.md` tells the agent to run it when it changed addon code.

## Turning it off

Set `agents = false` (or leave it out; the default is off). Sync then removes `CLAUDE.md` and `.claude/settings.json`, and the block from `AGENTS.md`, and leaves `AGENTS.md` in place, empty when the block was all it held: delete it yourself.
