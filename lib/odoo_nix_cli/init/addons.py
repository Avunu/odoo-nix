"""Addons mode (``--addons``): bring a repository of addons into odoo-nix.

A repository of addons (OCA's shape: addon folders at the root, one branch per series)
gets templates/addons: ``flake.nix`` (OCB and its dependency repositories as inputs,
``addons.enable``), ``nix/pyproject.toml`` (the generated uv project), ``.envrc`` and
``.gitignore``; then ``.odoo-series`` and the first relock (``nix run .#relock``, which
fills ``nix/pyproject.toml``'s blocks and writes ``nix/uv.lock`` and ``flake.lock``).
See docs/scaffolding/addons-repository.md.

As in migrate mode nothing is overwritten: a file the repository has is kept, a
``.gitignore`` gains only the patterns it lacks, and a ``flake.nix`` or
``nix/pyproject.toml`` that is not odoo-nix's is refused (exit 4), or with ``--force``
kept, with odoo-nix's written beside it to merge. Only the files this run writes are
staged: an addon repository's other changes stay the user's.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import tomllib
from collections import Counter
from pathlib import Path

from odoo_nix_cli.init import ui
from odoo_nix_cli.init.detect import (
    PYPROJECT_SENTINEL,
    _code_lines,
    flake_text,
    is_odoo_nix_project,
    preset_for,
    repo_state,
)
from odoo_nix_cli.init.pipeline import next_step
from odoo_nix_cli.init.proc import attempt, git, probe, run
from odoo_nix_cli.init.select import choose_series
from odoo_nix_cli.init.state import Run, normalize_name
from odoo_nix_cli.init.template import files, install, render

SERIES_FILE = ".odoo-series"
PYPROJECT = "nix/pyproject.toml"
COMMIT_MESSAGE = "chore: develop the repository of addons with odoo-nix (addons mode)"
RELOCK = ["nix", "run", "--no-pure-eval", ".#relock"]


def is_addons_flake() -> bool:
    """flake.nix is odoo-nix's in addons mode (``addons.enable = true``)."""
    return is_odoo_nix_project() and any(
        re.search(r"\baddons\.enable\s*=\s*true\s*;", line)
        for line in _code_lines(flake_text())
    )


def has_foreign_pyproject() -> bool:
    """nix/pyproject.toml without the blocks lib/oca_sources.py manages."""
    p = Path(PYPROJECT)
    return p.is_file() and PYPROJECT_SENTINEL not in p.read_text(
        encoding="utf-8", errors="replace"
    )


def _series_of_root_manifests() -> str | None:
    """The series most root addons' manifest versions name (18.0.1.0.0 is 18.0)."""
    seen: Counter[str] = Counter()
    for path in sorted(Path(".").glob("*/__manifest__.py")):
        try:
            manifest = ast.literal_eval(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            continue
        version = manifest.get("version") if isinstance(manifest, dict) else None
        if isinstance(version, str):
            m = re.fullmatch(r"(\d+\.\d+)\.\d+\.\d+\.\d+", version.strip())
            if m:
                seen[m.group(1)] += 1
    return seen.most_common(1)[0][0] if seen else None


def detect_series() -> tuple[str, str] | None:
    """(series, where it was read): ``.odoo-series``, a series branch checked out
    (``18.0``), or the root addons' manifest versions."""
    try:
        text = Path(SERIES_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text:
        return text, SERIES_FILE
    branch = probe(git("rev-parse", "--abbrev-ref", "HEAD")) or ""
    if re.fullmatch(r"\d+\.0", branch.strip()):
        return branch.strip(), "the branch"
    found = _series_of_root_manifests()
    if found:
        return found, "the addon manifests"
    return None


def resolve_series(st: Run) -> None:
    detected = detect_series()
    if st.version:
        if st.version not in st.presets:
            ui.die(
                f"unknown Odoo series '{st.version}' (expected: {st.preset_keys})", 5
            )
        if detected and detected[0] != st.presets[st.version].branch:
            st.warn(
                f"--version {st.version}, but {detected[1]} says {detected[0]}: the"
                " series of OCB and of the inputs will not match the addons"
            )
    elif detected is None:
        if ui.has_tty():
            st.version = choose_series(st)
        else:
            ui.die(
                "could not detect the Odoo series; pass --version (one of:"
                f" {st.preset_keys})",
                5,
            )
    else:
        key = preset_for(detected[0], st.presets)
        if key is None:
            ui.die(
                f"{detected[1]} says Odoo {detected[0]}, which odoo-nix has no preset"
                f" for (expected: {st.preset_keys})",
                5,
            )
        st.version = key
        st.detected_from = detected[1]
    st.resolve_preset()


def existing_name() -> str | None:
    """nix/pyproject.toml's [project].name (the checkout's name in addons mode)."""
    try:
        data = tomllib.loads(Path(PYPROJECT).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    name = data.get("project", {}).get("name")
    return name if isinstance(name, str) and name else None


def cmd_addons(st: Run) -> None:
    a = st.args
    if is_odoo_nix_project() and not is_addons_flake():
        ui.die(
            f"'{os.getcwd()}' is an odoo-nix project, not a repository of addons:"
            " --addons is for the latter",
            6,
        )
    resolve_series(st)
    st.name = normalize_name(
        a.name or existing_name() or os.path.basename(os.path.abspath("."))
    )
    foreign = [
        path
        for path, is_foreign in (
            ("flake.nix", Path("flake.nix").is_file() and not is_odoo_nix_project()),
            (PYPROJECT, has_foreign_pyproject()),
        )
        if is_foreign
    ]
    if foreign and not a.force:
        ui.die(
            f"{' and '.join(foreign)} {'is' if len(foreign) == 1 else 'are'} not"
            " odoo-nix's. Re-run with --addons --force: odoo-nix's will be written"
            " beside each (<file>.odoo-nix) for you to merge.",
            4,
        )

    staging = render(st, st.config.addons_template)
    what = f"addons mode for '{st.name}' (Odoo {st.version}) in {os.getcwd()}"
    try:
        if a.dry_run:
            planned = [f for f in files(staging) if not os.path.lexists(f)]
            if not os.path.lexists(SERIES_FILE):
                planned.append(SERIES_FILE)
            ui.out("Plan")
            detected = (
                f" (detected from {st.detected_from})" if st.detected_from else ""
            )
            ui.info(f"{what}{detected}")
            ui.info(f"files   : {' '.join(sorted(planned)) or '<none>'}")
            for path in foreign:
                ui.info(f"aside   : {path}.odoo-nix (yours is kept)")
            ui.info(
                "lock    : skipped (--skip-lock)"
                if a.skip_lock
                else f"lock    : {' '.join(RELOCK)}"
            )
            ui.out("\n--dry-run: nothing was changed.")
            return
        ui.out(f"Setting up {what}")
        if repo_state() != "own":
            run(git("init", "-q"))
        for path in foreign:
            dest = Path(f"{path}.odoo-nix")
            shutil.copy2(staging / path, dest)
            st.warn(
                f"{path} is not odoo-nix's: odoo-nix's is {dest}; merge it into {path}"
            )
        written = install(staging, skip=tuple(foreign), verbose=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if not os.path.lexists(SERIES_FILE):
        Path(SERIES_FILE).write_text(f"{st.p.branch}\n", encoding="utf-8")
        written.append(SERIES_FILE)
        ui.info(f"+ {SERIES_FILE}")
    written += [f"{p}.odoo-nix" for p in foreign]
    # A flake sees only tracked files: stage before the relock evaluates it.
    stage(written)
    relock(st, foreign)
    stage([p for p in ("flake.lock", "nix/uv.lock", PYPROJECT) if Path(p).exists()])
    if a.commit:
        message = a.commit_msg or COMMIT_MESSAGE
        run(git("commit", "-q", "-m", message))
        ui.info(f"committed: {message}")
    report(st)


def stage(paths: list[str]) -> None:
    if paths:
        run(git("add", "--", *paths))


def relock(st: Run, foreign: list[str]) -> None:
    if st.args.skip_lock:
        ui.info("skipping the relock (--skip-lock)")
        return
    if foreign:
        st.warn(
            "nothing was locked: merge the *.odoo-nix files first, then run"
            f" `{' '.join(RELOCK)}`"
        )
        return
    ui.out(f"Locking ({' '.join(RELOCK)})…")
    if attempt(RELOCK) != 0:
        st.warn(
            f"`{' '.join(RELOCK)}` failed: list the repositories the addons depend on"
            " as flake inputs and in externalSources, then run it again"
        )


def report(st: Run) -> None:
    ui.out(f"\n✅ '{st.name}' is in addons mode in {os.getcwd()}")
    ui.out(f"   series  : {st.version} (python {st.p.pyver})")
    if st.warnings:
        ui.out(f"\n{len(st.warnings)} warning(s):")
        for w in st.warnings:
            ui.out(f"  ⚠  {w}")
    ui.out("\nNext steps:")
    if st.cd not in ("", "."):
        next_step(f"cd {st.cd}")
    next_step("git diff --cached --stat", "review what was staged")
    next_step(
        "$EDITOR flake.nix", "inputs + externalSources for the repositories needed"
    )
    next_step("direnv allow", "or: nix develop --no-pure-eval")
    next_step("odoo db provision", "(in the shell) install this repository's addons")
