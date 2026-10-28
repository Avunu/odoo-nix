"""The `odoo ui` store: python-devops-nix's devtui plugin (devtui.plugin).

The catalog is the series' OCA modules (data/oca-modules.json) and the curated
bundles, shown as stacks (data/oca-bundles.json), plus every module already in
the workspace that the catalog does not list: a third-party repository's under
modules/, and the project's own under custom/. "Installed" is modules.txt, the
modules the project asks for.

Nothing here touches the workspace: an add is `odoo module add` (and
`odoo module add-bundle`), a removal `odoo module remove`, run by the TUI from
the workspace root, which is also where the paths below are read from. So the
TUI and the command line can never disagree about what an add does.

Runs on the TUI's interpreter, not the CLI's: standard library only, and of
odoo_nix_cli only the catalog's pure functions (odoo_nix_cli.oca).
"""

from __future__ import annotations

import ast
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from devtui.catalog import Bundle, Catalog, Item
from devtui.plugin import Closure, Field, Form, Step
from devtui.spec import Action, Spec

from odoo_nix_cli import oca

#: How long the README fetch waits for GitHub.
TIMEOUT = 6.0
README_FRAGMENTS = ("DESCRIPTION", "USAGE", "CONFIGURE")


def _manifest(path: Path) -> dict[str, Any]:
    """A module's __manifest__.py, read as a literal: never executed."""
    try:
        data = ast.literal_eval(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, SyntaxError):
        return {}
    return data if isinstance(data, dict) else {}


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


class OdooProduct:
    def __init__(self, config: Mapping[str, Any], spec: Spec) -> None:
        self.cli = spec.cli
        self.root = Path(spec.root or ".")
        self.series = str(config["series"])
        self.external = self.root / str(config["externalDir"])
        self.custom = self.root / str(config["customDir"])
        self.raw_catalog = oca.load_catalog(config["ocaDataset"])
        self.raw_bundles = oca.load_bundles(config["ocaBundles"])
        self.series_rows = oca.in_series(self.raw_catalog, self.series)
        self.by_module = {m["module"]: m for m in self.series_rows}
        self._readmes: dict[str, str] = {}
        self._catalog: Catalog | None = None
        #: Where each module of _local_items is on disk.
        self._local_paths: dict[str, Path] = {}

    # -- the catalog -----------------------------------------------------------

    def _oca_item(self, m: Mapping[str, Any]) -> Item:
        installable = m.get("installable") is True
        url = f"https://github.com/OCA/{m['repo']}/tree/{self.series}/{m['module']}"
        return Item(
            id=m["module"],
            title=_one_line(m.get("name")) or m["module"],
            summary=_one_line(m.get("summary")),
            group=m["repo"],
            tags=("application",) if m.get("application") else (),
            version=str(m.get("version", "")),
            license=str(m.get("license") or ""),
            url=url,
            depends=tuple(m.get("depends") or ()),
            available=installable,
            note="" if installable else f"not installable on {self.series}",
            rank=1 if m.get("application") else 0,
            facts=(("Auto-install", "yes"),) if m.get("auto_install") else (),
        )

    def _local_items(self, known: set[str]) -> list[Item]:
        """Modules on disk the catalog does not list: a third-party
        repository's (group: its directory), and the project's own."""
        out = []
        for base, origin in ((self.external, "modules/"), (self.custom, "custom")):
            if not base.is_dir():
                continue
            dirs = (
                [base]
                if base == self.custom
                else sorted(p for p in base.iterdir() if p.is_dir())
            )
            for repo in dirs:
                for name in oca.scan_modules(repo):
                    if name in known:
                        continue
                    known.add(name)
                    path = (
                        repo / name
                        if (repo / name / "__manifest__.py").is_file()
                        else repo
                    )
                    self._local_paths[name] = path
                    manifest = _manifest(path / "__manifest__.py")
                    group = "custom" if base == self.custom else repo.name
                    out.append(
                        Item(
                            id=name,
                            title=_one_line(manifest.get("name")) or name,
                            summary=_one_line(manifest.get("summary")),
                            group=group,
                            tags=("local",)
                            + (("application",) if manifest.get("application") else ()),
                            version=str(manifest.get("version", "")),
                            license=str(manifest.get("license") or ""),
                            depends=tuple(manifest.get("depends") or ()),
                            facts=(("Source", f"{origin} (in this workspace)"),),
                        )
                    )
        return out

    def catalog(self) -> Catalog:
        if self._catalog is None:
            items = [self._oca_item(m) for m in self.series_rows]
            items += self._local_items({i.id for i in items})
            bundles = []
            for name, b in sorted(self.raw_bundles.items()):
                label = str(b.get("label", ""))
                title, _, summary = label.partition(" — ")
                bundles.append(
                    Bundle(
                        id=name,
                        title=title or name,
                        summary=summary,
                        members=tuple(b.get("modules", ())),
                    )
                )
            self._catalog = Catalog(
                noun="module",
                group_label="Repository",
                items=tuple(items),
                bundles=tuple(bundles),
                bundle_noun="stack",
            )
        return self._catalog

    def installed(self) -> set[str]:
        path = self.root / "modules.txt"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return set()
        return {line.strip() for line in text.splitlines() if line.strip()}

    # -- what an add brings ------------------------------------------------------

    def _seeds(
        self, ids: Sequence[str], bundles: Sequence[str]
    ) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        seeds = set(ids)
        seeds.update(
            oca.expand_bundles(
                self.raw_bundles,
                self.raw_catalog,
                self.series,
                bundles,
                warnings.append,
            )
        )
        return sorted(seeds), warnings

    def closure(self, ids: Sequence[str], bundles: Sequence[str]) -> Closure:
        seeds, warnings = self._seeds(ids, bundles)
        installed = self.installed()
        # Every OCA module the seeds depend on, transitively: what Odoo will
        # install with them. A dependency outside the catalog is core.
        brings: list[str] = []
        queue = [
            d for s in seeds for d in self.by_module.get(s, {}).get("depends") or ()
        ]
        seen = set(seeds)
        while queue:
            dep = queue.pop(0)
            if dep in seen or dep not in self.by_module:
                continue
            seen.add(dep)
            if dep not in installed:
                brings.append(dep)
            queue.extend(self.by_module[dep].get("depends") or ())
        repos = oca.resolve_repos(self.raw_catalog, self.series, seeds)
        present = (
            {p.name for p in self.external.iterdir()}
            if self.external.is_dir()
            else set()
        )
        new = [r for r in repos if r not in present]
        notes = []
        if bundles:
            notes.append(
                f"Stacks {', '.join(bundles)}: {len(seeds) - len(ids)} module(s) from them."
            )
        if new:
            notes.append(
                f"{len(new)} new OCA repositor{'y' if len(new) == 1 else 'ies'}: {', '.join(new)}"
            )
        else:
            notes.append("Every repository needed is already in the workspace.")
        if brings:
            notes.append(
                f"Odoo installs {len(brings)} more with them: {', '.join(sorted(brings))}"
            )
        notes.append(
            "Then: rebuild the shell (the addons path changes) and install into the database."
        )
        unavailable = tuple(
            s for s in ids if s not in self.by_module and s not in self.catalog().by_id
        )
        return Closure(
            brings=tuple(sorted(brings)),
            notes=tuple(notes + warnings),
            unavailable=unavailable,
        )

    # -- command lines -----------------------------------------------------------

    def add(self, ids: Sequence[str], bundles: Sequence[str]) -> list[Step]:
        steps = []
        if bundles:
            steps.append(
                Step((self.cli, "module", "add-bundle", *bundles), "add the stacks")
            )
        if ids:
            steps.append(Step((self.cli, "module", "add", *ids), "add the modules"))
        return steps

    def remove(self, ids: Sequence[str]) -> list[Step]:
        return [
            Step((self.cli, "module", "remove", *ids), "take them out of modules.txt")
        ]

    def after_add(self) -> list[Action]:
        return [
            Action(
                label="Rebuild, restart and install",
                argv=("devtui:rebuild", self.cli, "db", "provision"),
                help="re-evaluate the shell, restart the stack, then install modules.txt into the database",
            ),
            Action(label="Rebuild & restart only", argv=("devtui:rebuild",)),
        ]

    def forms(self) -> list[Form]:
        return [
            Form(
                label="Add a Git repository",
                fields=(
                    Field(
                        "url",
                        "Git URL or owner/repo",
                        "https://example.com/owner/repo.git",
                        required=True,
                    ),
                    Field(
                        "branch",
                        "Branch",
                        f"default: {self.series}, else the remote's own",
                    ),
                ),
                argv=(self.cli, "module", "add", "{url}", "{branch}"),
                help="Any git host. Every module in the repository is recorded in modules.txt.",
            )
        ]

    # -- the detail pane ---------------------------------------------------------

    def detail(self, item: Item) -> str:
        if item.id in self._readmes:
            return self._readmes[item.id]
        text = (
            self._local_readme(item) if "local" in item.tags else self._oca_readme(item)
        )
        self._readmes[item.id] = text
        return text

    def _local_readme(self, item: Item) -> str:
        module = self._local_paths.get(item.id)
        if module is None:
            return ""
        for name in (
            "README.md",
            "readme/DESCRIPTION.md",
            "README.rst",
            "readme/DESCRIPTION.rst",
        ):
            path = module / name
            if path.is_file():
                body = path.read_text(encoding="utf-8", errors="replace")[:20000]
                return body if name.endswith(".md") else _rst(body)
        return ""

    def _oca_readme(self, item: Item) -> str:
        """The module's readme fragments (OCA's readme/*.md, else .rst), from
        GitHub."""
        base = f"https://raw.githubusercontent.com/OCA/{item.group}/{self.series}/{item.id}/readme"
        parts = []
        for fragment in README_FRAGMENTS:
            for ext in ("md", "rst"):
                body = _fetch(f"{base}/{fragment}.{ext}")
                if body:
                    heading = fragment.capitalize()
                    parts.append(
                        f"### {heading}\n\n{body.strip() if ext == 'md' else _rst(body)}"
                    )
                    break
        return "\n\n".join(parts)


def _fetch(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            return response.read(200_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return ""


def _rst(text: str) -> str:
    """Enough reStructuredText for the pane: a literal block, as it is."""
    return "```text\n" + text.strip() + "\n```"


def load(config: Mapping[str, Any], spec: Spec) -> OdooProduct:
    return OdooProduct(config, spec)
