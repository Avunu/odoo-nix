"""``odoo-init``'s command line.

Parsed by hand, as frappe-nix's frappe-init parses its own, because the rules
are the documented ones (docs/reference/scaffolder.md) and neither click nor
argparse says them: ``--commit`` takes its message only as ``--commit=<msg>``,
so ``--commit <dir>`` is the flag and a target; ``--version`` takes a value; a
usage error is exit 1.

``--series``, the name ``--version`` had before python-devops-nix's
CONVENTIONS.md (Scaffolder: version flag), is refused since odoo-nix 2.0.0
with a usage error naming ``--version``. ``--apps`` is ``--modules``, as it
always was.
"""

from __future__ import annotations

from dataclasses import dataclass

USAGE = """\
Usage: odoo-init [options] [target-dir]

Scaffold a new odoo-nix project (Odoo OCB + OCA), or bring an existing Odoo
tree in odoo-nix's layout (OCB at odoo/, OCA repos under modules/, your own
modules under custom/) into odoo-nix. The mode is detected from the target
directory (default: the current directory when it is such a tree or an
odoo-nix project, otherwise a new project).

Mode:
  --init              Force scaffold mode
  --migrate           Force migration mode (also repairs an odoo-nix project)
  --force             Relax the mode guard; never overwrites an existing file
  --dry-run           Print the plan and exit without changing anything
  -y, --yes           Assume yes (required to migrate without a terminal)

Common:
  --version <v>       Odoo series: 18.0 | 19.0 | 20.0  (overrides detection)
  --bundles <a,b>     Comma-separated curated OCA bundles to install
  --modules <a,b,c>   Comma-separated OCA module names to install (alias: --apps)
  --name <name>       Project name (default: existing / target dir basename)
  --db <name>         Default database name (default: existing / odoo)
  --skip-lock         Do not run `uv lock`
  --commit[=<msg>]    Commit the result instead of only staging it
  -h, --help          Show this help

With a terminal and no flags you are prompted for what is missing. Bundles and
modules are both optional and independent: skip both for a plain Odoo core
project, or combine them -- the two selections are unioned.
"""

#: A flag's name before odoo-nix 2.0.0 → its name now (CONVENTIONS.md,
#: Scaffolder), for the usage error.
REMOVED = {"--series": "--version"}

#: Flags that take a value, as `--flag <v>` or `--flag=<v>`, and the field each sets.
VALUED = {
    "--version": "version",
    "--bundles": "bundles_csv",
    "--modules": "modules_csv",
    "--apps": "modules_csv",
    "--name": "name",
    "--db": "db",
}

#: Switches and the field each sets to True.
SWITCHES = {
    "--force": "force",
    "--dry-run": "dry_run",
    "-y": "assume_yes",
    "--yes": "assume_yes",
    "--skip-lock": "skip_lock",
}


class UsageError(Exception):
    """A command line odoo-init refuses: the usage, then MESSAGE, exit 1."""

    def __init__(self, message: str, *, show_usage: bool = True) -> None:
        super().__init__(message)
        self.code = 1
        self.show_usage = show_usage


@dataclass
class InitArgs:
    # auto | init | migrate
    mode: str = "auto"
    force: bool = False
    dry_run: bool = False
    assume_yes: bool = False
    skip_lock: bool = False
    commit: bool = False
    # None: the mode's default message (pipeline.commit_message).
    commit_msg: str | None = None
    version: str = ""
    bundles_csv: str | None = None
    modules_csv: str | None = None
    name: str = ""
    db: str = ""
    target: str = ""
    help: bool = False

    @property
    def bundles(self) -> list[str]:
        return csv(self.bundles_csv)

    @property
    def modules(self) -> list[str]:
        return csv(self.modules_csv)


def csv(value: str | None) -> list[str]:
    """A comma-separated flag's words, empty ones dropped."""
    return [w.strip() for w in (value or "").split(",") if w.strip()]


def parse_args(argv: list[str]) -> InitArgs:
    args = InitArgs()
    words = list(argv)
    while words:
        word = words.pop(0)
        flag, eq, inline = word.partition("=")
        if not word.startswith("-") or word == "-":
            args.target = word
            continue
        if flag in REMOVED:
            raise UsageError(
                f"{flag} is {REMOVED[flag]} since odoo-nix 2.0.0", show_usage=False
            )
        if flag in VALUED:
            if eq:
                value = inline
            elif words:
                value = words.pop(0)
            else:
                raise UsageError(f"{word} needs a value", show_usage=False)
            setattr(args, VALUED[flag], value)
        elif word == "--commit":
            args.commit = True
        elif flag == "--commit" and eq:
            args.commit = True
            args.commit_msg = inline
        elif word in ("--init", "--migrate"):
            args.mode = word[2:]
        elif word in SWITCHES:
            setattr(args, SWITCHES[word], True)
        elif word in ("-h", "--help"):
            args.help = True
            return args
        else:
            raise UsageError(f"unknown flag: {word}")
    return args
