"""``odoo-init``'s command line.

Parsed by hand, as frappe-nix's frappe-init parses its own, because the rules
are the documented ones (docs/reference/scaffolder.md) and neither click nor
argparse says them: ``--commit`` takes its message only as ``--commit=<msg>``,
so ``--commit <dir>`` is the flag and a target; ``--version`` takes a value; a
usage error is exit 1.

``--series``, the name ``--version`` had before python-devops-nix's
docs/conventions.md (Scaffolder: version flag), is refused since odoo-nix 2.0.0
with a usage error naming ``--version``. ``--apps`` is ``--modules``, as it
always was.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
  --addons            Bring a repository of addons into odoo-nix (addons mode):
                      flake.nix, .odoo-series, nix/pyproject.toml, .envrc,
                      .gitignore, then the first relock
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

Standards (odoo-nix's managed files, `odoo-nix sync`; exit codes 0 clean,
1 drift, 2 configuration, 3 environment):
  --sync              Write the managed files of the checkout here
  --check             Report drift and write nothing
  --standards <p>     Opt in with this profile (minimal, recommended,
                      github:<owner>/<repo>[/<ref>], ./<dir>); implies --sync
  --profile-path <d>  Read the org profile from this directory; implies --sync
  --offline           Run no nix, uv or npm command
  --only <paths>      Limit to these managed paths (repeatable)
  --format <f>        --check report: text | json | github
  --expect-rev <rev>  --check: the odoo-nix revision these tools came from
With --addons or --migrate, the scaffold runs first and the standards sync
follows in the same run.

With a terminal and no flags you are prompted for what is missing. Bundles and
modules are both optional and independent: skip both for a plain Odoo core
project, or combine them -- the two selections are unioned.
"""

#: A flag's name before odoo-nix 2.0.0 → its name now (python-devops-nix docs/conventions.md,
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
    # The standards run's (odoo-nix sync's), passed on one to one.
    "--standards": "standards",
    "--profile-path": "profile_path",
    "--format": "format",
    "--expect-rev": "expect_rev",
    # Hidden: a handed-over sync's phase (odoo-nix sync --phase).
    "--phase": "phase",
}

#: Valued flags that may be given more than once, and the list each extends.
REPEATED = {"--only": "only"}

#: Switches and the field each sets to True.
SWITCHES = {
    "--force": "force",
    "--dry-run": "dry_run",
    "-y": "assume_yes",
    "--yes": "assume_yes",
    "--skip-lock": "skip_lock",
    "--sync": "sync",
    "--check": "check",
    "--offline": "offline",
    "--addons": "addons",
    # Hidden: a fixture checkout's sync (odoo-nix sync --throwaway).
    "--throwaway": "throwaway",
}

#: The standards flags odoo-nix sync takes as they are (DESIGN.md §5.5): switches,
#: then valued flags.
SYNC_SWITCHES = ("force", "dry_run", "skip_lock", "offline", "throwaway")
SYNC_VALUED = ("standards", "profile_path", "format", "expect_rev", "phase")


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
    # Addons mode (a repository of addons).
    addons: bool = False
    # The standards run (odoo-nix sync).
    sync: bool = False
    check: bool = False
    offline: bool = False
    throwaway: bool = False
    standards: str = ""
    profile_path: str = ""
    format: str = ""
    expect_rev: str = ""
    phase: str = ""
    only: list[str] = field(default_factory=list)

    @property
    def standards_mode(self) -> bool:
        """Any of --sync, --check, --standards, --profile-path: a standards run."""
        return bool(self.sync or self.check or self.standards or self.profile_path)

    def sync_argv(self) -> list[str]:
        """``odoo-nix sync``'s command line for this run: ``--check`` or ``--write``,
        then the standards flags one to one."""
        out = ["sync", "--check" if self.check else "--write"]
        for name in SYNC_SWITCHES:
            if getattr(self, name):
                out.append("--" + name.replace("_", "-"))
        for name in SYNC_VALUED:
            value = getattr(self, name)
            if value:
                out += ["--" + name.replace("_", "-"), value]
        for chunk in self.only:
            out += ["--only", chunk]
        return out

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
        elif flag in REPEATED:
            if eq:
                value = inline
            elif words:
                value = words.pop(0)
            else:
                raise UsageError(f"{word} needs a value", show_usage=False)
            getattr(args, REPEATED[flag]).append(value)
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
    if args.sync and args.check:
        raise UsageError("--sync and --check cannot be combined", show_usage=False)
    if args.addons and args.mode == "init":
        raise UsageError(
            "--addons brings an existing directory into addons mode: it cannot be"
            " combined with --init",
            show_usage=False,
        )
    return args
