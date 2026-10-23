"""`odoo module remove`: the inverse of `odoo module add` (python-devops-nix
docs/conventions.md, Source management; frappe-nix's `bench remove-app`).

add records modules in modules.txt and clones the repositories they need; this
takes modules out of modules.txt and the repositories nothing left needs out
of the workspace. Like add, it never touches a database: uninstalling a
module is Odoo's (Apps), and this refuses to take away the code of a module a
database still has installed.
"""

from __future__ import annotations

import ast
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from odoo_nix_cli import oca
from odoo_nix_cli.init import ui
from odoo_nix_cli.init.proc import git, probe, probe_ok, run
from odoo_nix_cli.workspace.add import Stop
from odoo_nix_cli.workspace.common import (
    read_modules,
    submodules,
    write_modules,
)
from odoo_nix_cli.workspace.config import WorkspaceConfig
from odoo_nix_cli.workspace.update import regenerate

USAGE = """\
Usage: odoo module remove [--force] [--keep-repos] <module | repo> …

Takes each <module> out of modules.txt, and then every repository under
modules/ that held one of them, or that their dependencies reached, and that
no module left in modules.txt needs any more: its submodule is deinitialised
and dropped from .gitmodules (staging only that; any other uncommitted
.gitmodules edit stays as it was) and its clone deleted. Then pyproject.toml's
path sources are regenerated and the workspace re-locked (uv lock).

A <repo> is a submodule under modules/, by its folder name or its path
(server-ux, modules/server-ux): it is removed, with every module of it that
modules.txt lists.

Refuses while a database still has a module installed whose code would go,
and while a repository to remove has uncommitted changes. Uninstall the
module in Odoo first (Apps), or commit or discard the changes.

  --force       skip both checks
  --keep-repos  only edit modules.txt; leave every repository where it is"""


class UsageError(Exception):
    pass


@dataclass
class Plan:
    # modules.txt entries to take out
    modules: list[str] = field(default_factory=list)
    # submodule paths to remove
    repos: list[str] = field(default_factory=list)
    # modules whose code goes with those repositories
    code: list[str] = field(default_factory=list)


def parse_args(argv: Iterable[str]) -> tuple[list[str], bool, bool] | None:
    """(names, force, keep_repos), or None for --help."""
    names: list[str] = []
    force = keep = False
    for arg in argv:
        if arg == "--force":
            force = True
        elif arg == "--keep-repos":
            keep = True
        elif arg in ("-h", "--help"):
            return None
        elif arg.startswith("-"):
            raise UsageError(f"unknown flag: {arg}")
        else:
            names.append(arg)
    if not names:
        raise UsageError("name a module or a repository")
    return names, force, keep


def _manifest(path: Path) -> dict:
    try:
        data = ast.literal_eval((path / "__manifest__.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def modules_on_disk(cfg: WorkspaceConfig) -> dict[str, tuple[str, list[str]]]:
    """{module: (the submodule path holding it, or "" for custom/, its depends)}."""
    found: dict[str, tuple[str, list[str]]] = {}
    for d in sorted(Path(cfg.layout.custom_dir).glob("*/__manifest__.py")):
        found[d.parent.name] = ("", list(_manifest(d.parent).get("depends") or []))
    for path in sorted(submodules()):
        if not path.startswith(f"{cfg.layout.external_dir}/"):
            continue
        for name in oca.scan_modules(path):
            mdir = (
                Path(path)
                if name == Path(path).name and (Path(path) / "__manifest__.py").exists()
                else Path(path, name)
            )
            found.setdefault(name, (path, list(_manifest(mdir).get("depends") or [])))
    return found


def reached(
    seeds: Iterable[str],
    disk: dict[str, tuple[str, list[str]]],
    catalog_repos: Callable[[list[str]], list[str]],
) -> set[str]:
    """The submodule paths SEEDS and their dependencies live in: on disk by the
    manifests' depends, and for a module not on disk by the OCA catalogue."""
    repos: set[str] = set()
    seen: set[str] = set()
    queue = list(seeds)
    missing: list[str] = []
    while queue:
        m = queue.pop()
        if m in seen:
            continue
        seen.add(m)
        if m in disk:
            repo, depends = disk[m]
            if repo:
                repos.add(repo)
            queue.extend(depends)
        else:
            missing.append(m)
    repos.update(catalog_repos(missing))
    return repos


def plan(cfg: WorkspaceConfig, names: list[str], keep_repos: bool) -> Plan:
    listed = read_modules()
    subs = [p for p in submodules() if p.startswith(f"{cfg.layout.external_dir}/")]
    disk = modules_on_disk(cfg)
    catalog = oca.load_catalog(cfg.oca_dataset)
    present = set(subs)

    def catalog_repos(mods: list[str]) -> list[str]:
        paths = (
            f"{cfg.layout.external_dir}/{r}"
            for r in oca.resolve_repos(catalog, cfg.series, mods)
        )
        return [p for p in paths if p in present]

    # Where a listed module lives: on disk, else where the catalogue says.
    home = {
        m["module"]: f"{cfg.layout.external_dir}/{m['repo']}"
        for m in oca.in_series(catalog, cfg.series)
    }
    home.update({m: repo for m, (repo, _) in disk.items()})

    out = Plan()
    explicit: list[str] = []
    for name in names:
        path = name.rstrip("/")
        if "/" not in path:
            path = f"{cfg.layout.external_dir}/{path}"
        if name in listed:
            out.modules.append(name)
        elif path in present:
            explicit.append(path)
            out.modules += [m for m in listed if home.get(m) == path]
        else:
            raise Stop(
                1,
                f"odoo module remove: no module '{name}' in modules.txt, and no repository {path} in .gitmodules.",
            )
    out.modules = sorted(set(out.modules))
    if not keep_repos:
        left = [m for m in listed if m not in out.modules]
        needed = reached(left, disk, catalog_repos)
        candidates = reached(out.modules, disk, catalog_repos) | set(explicit)
        for path in explicit:
            if path in needed:
                users = sorted(
                    m for m in left if path in reached([m], disk, catalog_repos)
                )
                raise Stop(
                    1,
                    f"odoo module remove: {path} is still needed by {' '.join(users)} in modules.txt — remove those too, or keep it.",
                )
        out.repos = sorted(candidates - needed)
        out.code = sorted(m for m, (repo, _) in disk.items() if repo in out.repos)
    return out


def installed(modules: list[str], ctx_obj: dict) -> tuple[dict[str, list[str]], str]:
    """({database: the MODULES it has installed}, why the databases could not be
    read, or "")."""
    try:
        import odoo.sql_db

        from odoo_nix_cli import odooenv

        conf = odooenv.resolve_config_path(ctx_obj.get("config"))
        odoo_config = odooenv.load_config(conf, odooenv.db_connection_args(ctx_obj))
        databases = odooenv.list_target_databases(None, True, odoo_config)
    except Exception as e:  # noqa: BLE001 -- any of them means: cannot tell
        return {}, f"{type(e).__name__}: {e}"
    found: dict[str, list[str]] = {}
    for db in databases:
        try:
            with odoo.sql_db.db_connect(db).cursor() as cr:
                cr.execute(
                    "SELECT name FROM ir_module_module WHERE state <> 'uninstalled' AND state <> 'uninstallable' AND name = ANY(%s) ORDER BY name",
                    (modules,),
                )
                names = [row[0] for row in cr.fetchall()]
        except Exception as e:  # noqa: BLE001
            return {}, f"{db}: {type(e).__name__}: {e}"
        if names:
            found[db] = names
    return found, ""


def refuse_if_in_use(p: Plan, ctx_obj: dict) -> None:
    if p.code:
        found, error = installed(p.code, ctx_obj)
        if error:
            raise Stop(
                1,
                "odoo module remove: could not read the installed modules of the databases\n"
                f"  ({error})\n"
                f"(is the database up? devenv up) — not removing {' '.join(p.repos)} ({len(p.code)} module(s))\n"
                "without knowing no database still has one of them installed. Pass --force to remove it anyway.",
            )
        if found:
            lines = [f"    {db}: {' '.join(mods)}" for db, mods in found.items()]
            raise Stop(
                1,
                "odoo module remove: modules whose code would go are still installed:\n"
                + "\n".join(lines)
                + "\nUninstall them in Odoo first (Apps), or pass --force to remove them anyway.",
            )
    for path in p.repos:
        dirty = (
            probe(git("-C", path, "status", "--porcelain"))
            if Path(path, ".git").exists()
            else ""
        )
        if dirty:
            raise Stop(
                1,
                f"odoo module remove: {path} has uncommitted changes that removing it would discard:\n"
                + "\n".join(dirty.splitlines()[:20])
                + "\nCommit or discard them, or pass --force to remove it anyway.",
            )


def remove_submodule(path: str) -> None:
    """PATH out of git: deinitialised, its gitlink and .gitmodules section
    removed and staged, its clone deleted.

    Plumbing, not `git rm`: git rm refuses outright while .gitmodules has any
    unstaged edit, the usual state of a workspace mid-work. .gitmodules'
    working copy and index copy each lose the section on their own, so exactly
    this removal is staged and every other edit stays where it was.
    """
    name = submodules().get(path, path)
    ui.out(f"Removing the {path} submodule…")
    if Path(path, ".git").exists():
        run(git("submodule", "deinit", "-q", "-f", "--", path))
    # Best effort, silently: deinit has usually removed it already.
    probe_ok(git("config", "--local", "--remove-section", f"submodule.{name}"))
    run(git("update-index", "--force-remove", "--", path))
    try:
        os.rmdir(path)
    except OSError:
        pass
    probe_ok(
        git("config", "-f", ".gitmodules", "--remove-section", f"submodule.{name}")
    )
    staged = probe(git("show", ":.gitmodules"))
    if staged is not None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(staged + "\n")
        try:
            if probe_ok(
                git("config", "-f", f.name, "--remove-section", f"submodule.{name}")
            ):
                blob = (probe(git("hash-object", "-w", f.name)) or "").strip()
                run(git("update-index", "--cacheinfo", f"100644,{blob},.gitmodules"))
        finally:
            os.unlink(f.name)
    # Its clone. Left behind, it also makes a later `odoo module add` of the
    # same repository refuse ("A git directory for … is found locally").
    gitdir = probe(git("rev-parse", "--git-path", f"modules/{name}"))
    if gitdir:
        shutil.rmtree(gitdir, ignore_errors=True)
    if os.path.lexists(path):
        ui.warn_line(f"{path} still holds files git never tracked; left in place")


def remove(cfg: WorkspaceConfig, argv: list[str], ctx_obj: dict | None = None) -> int:
    try:
        parsed = parse_args(argv)
    except UsageError as e:
        print(USAGE, file=sys.stderr)
        print(f"\nerror: {e}", file=sys.stderr)
        return 1
    if parsed is None:
        print(USAGE)
        return 0
    names, force, keep_repos = parsed

    p = plan(cfg, names, keep_repos)
    if not force:
        refuse_if_in_use(p, ctx_obj or {})

    for path in p.repos:
        remove_submodule(path)
    if p.modules:
        write_modules([m for m in read_modules() if m not in p.modules])
        ui.out(f"  - modules.txt: {' '.join(p.modules)}")
    rc = regenerate(cfg)
    if rc != 0:
        return rc

    what = " ".join([*p.modules, *(r for r in p.repos)])
    ui.out(
        f"\n✅ Removed {what}.\n"
        "   Commit the staged removal with modules.txt, pyproject.toml and uv.lock,\n"
        "   then: direnv reload"
    )
    if p.modules and not p.code:
        ui.out(
            "   A database that has one of them installed still has it: uninstall it in Odoo (Apps) when it should go."
        )
    return 0
