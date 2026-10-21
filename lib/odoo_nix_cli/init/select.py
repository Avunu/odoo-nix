"""The series, the bundles and the modules: from the flags, or asked for.

Nothing is added unless asked for: each OCA question defaults to no, and a run
without a terminal and with neither flag gives a plain Odoo core project.
"""

from __future__ import annotations

from odoo_nix_cli import oca
from odoo_nix_cli.init import ui
from odoo_nix_cli.init.state import Run

#: How many matches the module search lists at once.
SEARCH_LIMIT = 30


def choose_series(st: Run) -> str:
    return ui.choose("Odoo series:", [(key, p.label) for key, p in st.presets.items()])


def require_version(st: Run) -> None:
    """st.version, asked for when there is a terminal; then its preset."""
    if not st.version:
        if ui.has_tty():
            st.version = choose_series(st)
        else:
            ui.die(f"--version is required (one of: {st.preset_keys})", 5)
    if st.version not in st.presets:
        ui.die(f"unknown Odoo series '{st.version}' (expected: {st.preset_keys})", 5)
    st.resolve_preset()


def pick_bundles(bundles: oca.Bundles) -> list[str]:
    options = [
        (
            name,
            f"{name}  —  {b.get('label', '')}  ({len(b.get('modules', []))} modules)",
        )
        for name, b in sorted(bundles.items())
    ]
    return ui.choose_many("OCA bundles:", options)


def pick_modules(catalog: oca.Catalog, series: str) -> list[str]:
    """A search over every installable module of SERIES (★ = application),
    repeated until an empty search; the modules picked along the way."""
    rows = oca.installable(catalog, series)
    if not rows:
        ui.out(f"No installable modules for series {series}.")
        return []
    picked: list[str] = []
    while True:
        query = ui.ask(
            "Search OCA modules: a module or repo name (empty to finish)", ""
        )
        if not query.strip():
            return picked
        hits = oca.search(rows, query)
        if not hits:
            ui.out(f"  nothing matches '{query}'")
            continue
        more = f", the first {SEARCH_LIMIT}" if len(hits) > SEARCH_LIMIT else ""
        options = [(m["module"], oca.label(m)) for m in hits[:SEARCH_LIMIT]]
        for name in ui.choose_many(f"{len(hits)} match(es){more}:", options):
            if name not in picked:
                picked.append(name)
        if picked:
            ui.out(f"  selected: {' '.join(picked)}")


def select(st: Run, *, prompt: bool) -> None:
    """st.bundles, st.modules and st.repos, from the flags or, with PROMPT and a
    terminal, asked for."""
    a = st.args
    catalog = oca.load_catalog(st.config.oca_dataset)
    bundles = oca.load_bundles(st.config.oca_bundles)
    ask = prompt and ui.has_tty()

    # Curated bundles first: they expand to module names, scoped to the series.
    if a.bundles:
        st.bundles = a.bundles
    elif ask and ui.confirm(
        "Add curated OCA bundles? (base, sales, accounting, …)", default=False
    ):
        st.bundles = pick_bundles(bundles)
    selected = (
        oca.expand_bundles(bundles, catalog, st.version, st.bundles, st.warn)
        if st.bundles
        else []
    )

    # Then individual modules, unioned with whatever the bundles contributed.
    if a.modules:
        picked = a.modules
    elif ask and ui.confirm(
        "Add individual OCA modules? (search the full catalog)", default=False
    ):
        picked = pick_modules(catalog, st.version)
    else:
        picked = []
    st.modules = sorted({m for m in [*selected, *picked] if m})
    st.repos = oca.resolve_repos(catalog, st.version, st.modules) if st.modules else []
