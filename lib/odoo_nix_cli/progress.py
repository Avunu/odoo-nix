"""Live progress feedback for `odoo db migrate` / `upgrade` / `provision`.

Odoo's module loader has no progress *callback* -- only log records, but they
are already structured (record.args), not strings to regex. This module
attaches a logging.Handler to `odoo.modules.loading` and `odoo.modules.migration`
that reads those args directly (matched by exact record.msg, copied verbatim
from the Odoo source odoo-nix's own presets target -- odoo/modules/loading.py
and odoo/modules/migration.py, 18.0/19.0) and drives either a live rich
progress display (interactive terminal) or plain narrated lines (everything
else -- journald, `nix flake check`, redirected output), the same
degrade-gracefully split bench's own `migrate` command makes.

Odoo's loader commits progressively per module, so there is no true
all-or-nothing rollback to report if one fails partway through -- the summary
is explicit about what already committed versus what did not, rather than
implying atomicity Odoo does not have.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Self

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

_LOADING_LOGGER = "odoo.modules.loading"
_MIGRATION_LOGGER = "odoo.modules.migration"

# Copied verbatim from odoo/modules/loading.py / odoo/modules/migration.py --
# matched by exact record.msg, so nothing here parses formatted text.
_MSG_LOADING = "Loading module %s (%d/%d)"
_MSG_LOADED = "Module %s loaded in %.2fs%s, %s queries%s"
_MSG_MIGRATION_SCRIPT = "module %(addon)s: Running upgrade %(fmt_version)s %(name)s"


@dataclass
class ModuleResult:
    name: str
    duration: float | None = None
    queries: int | None = None
    scripts: list[str] = field(default_factory=list)


@dataclass
class MigrationRecorder:
    total: int = 0
    order: list[str] = field(default_factory=list)
    results: dict[str, ModuleResult] = field(default_factory=dict)
    on_module_start: Callable[[str, int, int], None] | None = None
    on_module_done: Callable[[str, ModuleResult], None] | None = None
    on_script: Callable[[str, str, str], None] | None = None

    def _result(self, name: str) -> ModuleResult:
        if name not in self.results:
            self.results[name] = ModuleResult(name=name)
            self.order.append(name)
        return self.results[name]

    def handle(self, record: logging.LogRecord) -> None:
        if record.name == _LOADING_LOGGER:
            if record.msg == _MSG_LOADING:
                name, index, total = record.args
                self.total = total
                self._result(name)
                if self.on_module_start:
                    self.on_module_start(name, index, total)
            elif record.msg == _MSG_LOADED:
                name, duration, _extra1, queries, _extra2 = record.args
                result = self._result(name)
                result.duration = duration
                result.queries = queries
                if self.on_module_done:
                    self.on_module_done(name, result)
        elif record.name == _MIGRATION_LOGGER and record.msg == _MSG_MIGRATION_SCRIPT:
            args = record.args
            addon, name, fmt_version = args["addon"], args["name"], args["fmt_version"]
            self._result(addon).scripts.append(f"{name} {fmt_version}")
            if self.on_script:
                self.on_script(addon, name, fmt_version)


class _RecorderHandler(logging.Handler):
    def __init__(self, recorder: MigrationRecorder):
        super().__init__()
        self._recorder = recorder

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._recorder.handle(record)
        except Exception:  # noqa: BLE001, S110 -- rendering must never break a real migration
            pass


class MigrationProgress:
    """One database's worth of progress: a live display while it runs, a
    summary table when it's done. `console.is_terminal` picks the renderer --
    a live bar + spinner on a real TTY, narrated lines everywhere else (rich's
    Live/Progress redraw logic assumes it owns the terminal; forced onto a
    redirected/journald stream it just spams refresh frames, so that path
    uses plain prints instead)."""

    def __init__(self, db_name: str, console: Console | None = None):
        self.db_name = db_name
        self.console = console or Console()
        self.recorder = MigrationRecorder()
        self._handler = _RecorderHandler(self.recorder)
        self._progress: Progress | None = None
        self._task = None
        self._start = 0.0
        self._prev_levels: dict[str, int] = {}

    def __enter__(self) -> Self:
        self._start = time.monotonic()
        # odoo.tools.config.parse_config(setup_logging=False) means
        # odoo.netsvc.init_logger() never ran, so these loggers' *effective*
        # level is inherited straight from the root logger's Python default
        # (WARNING) -- the "Loading module %s (%d/%d)" / per-migration-script
        # records are INFO and would be dropped before ever reaching this
        # handler. Set each logger's own level directly (independent of
        # root, and of whatever `log_level` odoo.conf carries) and restore
        # it on exit.
        for name in (_LOADING_LOGGER, _MIGRATION_LOGGER):
            logger = logging.getLogger(name)
            self._prev_levels[name] = logger.level
            logger.setLevel(logging.DEBUG)
            logger.addHandler(self._handler)
        if self.console.is_terminal:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.fields[db]}[/] {task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=self.console,
                transient=False,
            )
            self._progress.start()
            self._task = self._progress.add_task("starting…", db=self.db_name, total=None)
            self.recorder.on_module_start = self._on_start
            self.recorder.on_script = self._on_script
        else:
            self.console.print(f"==> {self.db_name}: migrating…")
            self.recorder.on_module_start = self._on_start_plain
            self.recorder.on_script = self._on_script_plain
        return self

    def _on_start(self, name, index, total) -> None:
        self._progress.update(self._task, completed=index - 1, total=total, description=name)

    def _on_script(self, addon, name, fmt_version) -> None:
        self._progress.update(self._task, description=f"{addon} → {name} {fmt_version}")

    def _on_start_plain(self, name, index, total) -> None:
        self.console.print(f"    [{index}/{total}] {name}")

    def _on_script_plain(self, addon, name, fmt_version) -> None:
        self.console.print(f"        └─ {name} {fmt_version}")

    def __exit__(self, exc_type, exc, tb) -> None:
        for name in (_LOADING_LOGGER, _MIGRATION_LOGGER):
            logger = logging.getLogger(name)
            logger.removeHandler(self._handler)
            logger.setLevel(self._prev_levels.get(name, logging.NOTSET))
        if self._progress is not None:
            if exc is None and self.recorder.total:
                self._progress.update(self._task, completed=self.recorder.total)
            self._progress.stop()
        elapsed = time.monotonic() - self._start
        self._print_summary(elapsed, failed=exc is not None, error=exc)

    def _print_summary(self, elapsed: float, failed: bool, error: BaseException | None) -> None:
        table = Table(title=f"{self.db_name} — migration summary")
        table.add_column("Module")
        table.add_column("Time", justify="right")
        table.add_column("Queries", justify="right")
        table.add_column("Migration scripts")
        for name in self.recorder.order:
            r = self.recorder.results[name]
            table.add_row(
                name,
                f"{r.duration:.2f}s" if r.duration is not None else "[yellow](interrupted)[/]",
                str(r.queries) if r.queries is not None else "-",
                ", ".join(r.scripts) if r.scripts else "",
            )
        if self.recorder.order:
            self.console.print(table)
        done = sum(1 for r in self.recorder.results.values() if r.duration is not None)
        if failed:
            self.console.print(
                f"[bold red]✗ {self.db_name}: failed after {done} module(s) committed ({elapsed:.1f}s) — {error}[/]"
            )
            if done:
                self.console.print(
                    "[yellow]Odoo commits each module's upgrade as it completes, so the modules "
                    "above already committed; only the failing module (and anything after it) did not.[/]"
                )
        else:
            self.console.print(f"[bold green]✓ {self.db_name}: {done} module(s) migrated in {elapsed:.1f}s[/]")
