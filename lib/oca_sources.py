#!/usr/bin/env python3
"""Generate the uv path-source dependency model in pyproject.toml.

Odoo modules are modern OCA `whool` packages (`odoo-addon-<module>`, installing
under `odoo/addons/<module>`) whose build-time metadata declares their full
dependency graph: `odoo-addon-<dep>` for OCA depends, `odoo` for core depends,
and the manifest's `external_dependencies.python` as real PyPI requirements.
OCB itself resolves as an editable `odoo` dependency (its setup.py carries
Odoo's own requirements). So uv — not a custom aggregator — resolves everything.

This writes two managed blocks (sentinel-delimited, plain text, no tomlkit):

  [project].dependencies  -> "odoo" + every module in modules.txt as a root
  [tool.uv.sources]       -> "odoo" + EVERY local module, as editable path deps

uv then resolves the transitive closure of the roots against the local sources
(repos are cloned by oca_resolve_repos, so every needed module is local) and
pulls only the genuine external Python deps from PyPI.

Not every Odoo module is packaged, though: a plain addons repo (no per-module
`pyproject.toml`/`setup.py`) is perfectly valid for Odoo, which loads modules
from addons_path, but uv cannot build it. Such modules are never emitted as
uv sources; instead they are walked from the roots and folded into the install
set — their `external_dependencies.python` become direct requirements and their
`depends` are followed (packaged ones become `odoo-addon-<dep>` roots, unpackaged
ones are walked in turn, anything not on disk is assumed to be core).

A repository of addons (odoo-nix's addons mode) has no modules.txt: with
`--roots=local` every installable module of the custom directory is a root
instead. A module whose directory resolves into the Nix store (a flake input
the dev shell links in, `externalSources`) is a plain path source, built once
as a wheel; one in the working tree is editable, so edits are live.

Usage:
    oca_sources.py update [--roots=local] <pyproject.toml> <modules.txt> <modules-dir> <custom-dir> <core-src>
"""

import ast
import glob
import os
import re
import sys

DEP_BEGIN = "# >>> odoo-nix: install set (managed from modules.txt) >>>"
DEP_END = "# <<< odoo-nix: install set <<<"
SRC_BEGIN = "# >>> odoo-nix: module sources (managed) >>>"
SRC_END = "# <<< odoo-nix: module sources <<<"


def _dist(module):
    return "odoo-addon-" + module


def _local_modules(modules_dir, custom_dir):
    """{module_name: relpath} for every local Odoo module (has __manifest__.py)."""
    found = {}
    patterns = []
    if modules_dir:
        patterns += [
            # modules/<repo>/<module>
            os.path.join(modules_dir, "*", "*", "__manifest__.py"),
            # modules/<module>
            os.path.join(modules_dir, "*", "__manifest__.py"),
        ]
    if custom_dir:
        patterns += [os.path.join(custom_dir, "*", "__manifest__.py")]
    for pat in patterns:
        for mani in sorted(glob.glob(pat)):
            d = os.path.dirname(mani)
            name = os.path.basename(d)
            # Last wins (custom/ over modules/), but never a copy Odoo would
            # not install over one it would: an external source may ship an
            # unported copy of a module (installable: False).
            if name in found and _installable(found[name]) and not _installable(d):
                continue
            found[name] = d
    return found


def _is_packaged(module_dir):
    """True when uv can build the module dir (whool pyproject or legacy setup.py)."""
    return any(
        os.path.isfile(os.path.join(module_dir, f))
        for f in ("pyproject.toml", "setup.py")
    )


def _in_store(module_dir):
    """True when the module's directory is a store path (an externalSources
    input, linked in): read-only and immutable, so never an editable source."""
    return os.path.realpath(module_dir).startswith("/nix/store/")


def _installable(module_dir):
    return _read_manifest(module_dir).get("installable", True) is not False


def _read_manifest(module_dir):
    try:
        with open(os.path.join(module_dir, "__manifest__.py"), encoding="utf-8") as f:
            manifest = ast.literal_eval(f.read())
    except (OSError, SyntaxError, ValueError) as e:
        sys.stderr.write(f"warning: could not read manifest in {module_dir}: {e}\n")
        return {}
    return manifest if isinstance(manifest, dict) else {}


def _expand_roots(roots, local, packaged):
    """Fold unpackaged modules into the install set.

    Returns (packaged root modules, extra PyPI requirements), walking the
    `depends` of every unpackaged module reachable from `roots`.
    """
    dist_roots, reqs, seen = [], [], set()
    stack = list(reversed(roots))
    while stack:
        m = stack.pop()
        if m in seen or m not in local:
            continue  # not on disk: core (or reported as missing by the caller)
        seen.add(m)
        if m in packaged:
            dist_roots.append(m)  # uv resolves its graph from whool metadata
            continue
        manifest = _read_manifest(local[m])
        for req in (manifest.get("external_dependencies") or {}).get("python") or []:
            if req not in reqs:
                reqs.append(req)
        stack.extend(reversed(manifest.get("depends") or []))
    return dist_roots, reqs


def _replace_block(text, begin, end, body, *, label):
    if begin not in text or end not in text:
        sys.stderr.write(f"warning: sentinel block ({label}) not found; skipped\n")
        return text, False
    indent = re.search(r"^([ \t]*)" + re.escape(begin), text, re.MULTILINE)
    pad = indent.group(1) if indent else "    "
    block = pad + begin + "\n" + body + pad + end
    return (
        re.sub(
            re.escape(pad + begin) + r".*?" + re.escape(pad + end),
            lambda _m: block,
            text,
            count=1,
            flags=re.DOTALL,
        ),
        True,
    )


def _custom_roots(custom_dir, local):
    """Every installable module of CUSTOM_DIR, sorted: an addons repository's
    install set."""
    roots = []
    for mani in glob.glob(os.path.join(custom_dir, "*", "__manifest__.py")):
        d = os.path.dirname(mani)
        name = os.path.basename(d)
        if local.get(name) == d and _installable(d):
            roots.append(name)
    return sorted(roots)


def update(pyproject, modules_txt, modules_dir, custom_dir, core_src, roots_local=False):
    local = _local_modules(modules_dir, custom_dir)
    # Only packaged modules can be uv path sources; unpackaged ones are folded
    # into the install set by _expand_roots.
    sources = {m: d for m, d in local.items() if _is_packaged(d)}

    roots = []
    if roots_local:
        roots = _custom_roots(custom_dir, local)
    elif modules_txt and os.path.isfile(modules_txt):
        with open(modules_txt, encoding="utf-8") as f:
            roots = [ln.strip() for ln in f if ln.strip()]
    # Only emit roots that exist locally; a root whose repo isn't cloned would
    # make uv fall back to PyPI (version conflicts). Warn so the user can add it
    # via `odoo module add` (which clones its repo).
    local_roots, extra_reqs = _expand_roots(roots, local, sources)
    missing = [m for m in roots if m not in local]
    if missing:
        sys.stderr.write(
            "odoo-nix: note — install modules not found on disk (skipped; "
            "add them with `odoo module add` to clone their repo): "
            + ", ".join(sorted(missing))
            + "\n"
        )

    with open(pyproject, encoding="utf-8") as f:
        text = f.read()
    indent = re.search(r"^([ \t]*)" + re.escape(DEP_BEGIN), text, re.MULTILINE)
    pad = indent.group(1) if indent else "    "

    # `packaging`: Odoo parses a versioned external_dependencies entry
    # (`paramiko<4`) with it and refuses the module without it, yet OCB does
    # not declare it, so a lock only had it when something else pulled it in.
    dep_body = pad + '"odoo",\n' + pad + '"packaging",\n'
    for m in local_roots:
        dep_body += f'{pad}"{_dist(m)}",\n'
    for req in extra_reqs:
        dep_body += f'{pad}"{req}",\n'

    # OCB `odoo` is a NON-editable path source: its vendored pep517_odoo build
    # backend works for a plain wheel build but not uv2nix's editable build. The
    # wheel just satisfies the modules' `odoo==<series>.*` requirement + provides
    # Odoo's own deps; odoo is still RUN from source via odoo-bin (source path
    # wins), so OCB edits reflect at runtime.
    src_body = pad + f'odoo = {{ path = "{core_src}" }}\n'
    for module in sorted(sources):
        rel = sources[module]
        editable = "" if _in_store(rel) else ", editable = true"
        src_body += f'{pad}"{_dist(module)}" = {{ path = "{rel}"{editable} }}\n'

    text, ok1 = _replace_block(text, DEP_BEGIN, DEP_END, dep_body, label="dependencies")
    text, ok2 = _replace_block(text, SRC_BEGIN, SRC_END, src_body, label="sources")
    with open(pyproject, "w", encoding="utf-8") as f:
        f.write(text)
    sys.stderr.write(
        f"odoo-nix: synced {len(roots)} install root(s) + {len(sources)} module source(s)"
        + (
            f" ({len(local) - len(sources)} unpackaged module(s) on addons_path only)"
            if len(local) > len(sources)
            else ""
        )
        + "\n"
    )
    return 0 if (ok1 and ok2) else 1


def main(argv):
    args = list(argv[1:])
    roots_local = "--roots=local" in args
    args = [a for a in args if a != "--roots=local"]
    if len(args) >= 6 and args[0] == "update":
        return update(*args[1:6], roots_local=roots_local)
    sys.stderr.write(
        "usage: oca_sources.py update [--roots=local] <pyproject.toml> <modules.txt> "
        "<modules-dir> <custom-dir> <core-src>\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
