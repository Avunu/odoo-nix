#!/usr/bin/env python3
"""Sync the OCA Python dependencies into a project's pyproject.toml.

Aggregates `external_dependencies.python` from the Odoo modules that will
actually be INSTALLED — the modules listed in modules.txt plus their transitive
module dependency closure — NOT every module sitting in the cloned repos. A
single OCA repo (e.g. server-tools) holds ~100 modules whose unrelated Python
deps (sentry-sdk, paramiko, …) would otherwise bloat the env and collide with
Odoo's pinned requirements. Custom modules (under custom/) are always included.

Manifests are Python dict literals, so they are parsed with ast (never JSON).

The aggregated deps live in pyproject.toml inside the [project].dependencies
array, between sentinel comments, so updates are plain-text and need no tomlkit:

    # >>> odoo-nix: oca python deps (managed) >>>
    "phonenumbers",
    # <<< odoo-nix: oca python deps <<<

Usage:
    oca_pydeps.py update <pyproject.toml> <modules.txt> <modules-dir> <custom-dir>
    oca_pydeps.py scan   <modules.txt> <modules-dir> <custom-dir>   # print, no write
"""

import ast
import glob
import os
import re
import sys

# import-name -> PyPI distribution name for the common mismatches.
MAP = {
    "dateutil": "python-dateutil",
    "ldap": "python-ldap",
    "pil": "pillow",
    "crypto": "pycryptodome",
    "cryptodome": "pycryptodome",
    "stdnum": "python-stdnum",
    "magic": "python-magic",
    "yaml": "pyyaml",
    "serial": "pyserial",
    "usb": "pyusb",
    "slugify": "python-slugify",
    "jwt": "pyjwt",
    "bs4": "beautifulsoup4",
    "fpdf": "fpdf2",
}

# stdlib / stdlib-backports / non-distributions — never emit these.
SKIP = {
    "dataclasses", "typing", "enum34", "futures", "functools32",
    "argparse", "asyncio", "io", "json", "os", "sys", "subprocess",
    "odoo", "openerp",
}

BEGIN = "# >>> odoo-nix: oca python deps (managed) >>>"
END = "# <<< odoo-nix: oca python deps <<<"


def _base_name(spec):
    m = re.match(r"\s*([A-Za-z0-9._-]+)", spec)
    return m.group(1) if m else ""


def _parse_manifest(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    try:
        d = ast.literal_eval(src)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    try:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                try:
                    d = ast.literal_eval(node)
                    if isinstance(d, dict):
                        return d
                except Exception:
                    continue
    except Exception:
        pass
    return {}


def _module_index(modules_dir, custom_dir):
    """{module_name: {'depends': [...], 'python': [...], 'custom': bool}}."""
    index = {}
    for base, is_custom in ((modules_dir, False), (custom_dir, True)):
        if not base or not os.path.isdir(base):
            continue
        # modules/<repo>/<module>/__manifest__.py and custom/<module>/__manifest__.py
        for mani in glob.glob(os.path.join(base, "*", "__manifest__.py")) + \
                    glob.glob(os.path.join(base, "*", "*", "__manifest__.py")):
            name = os.path.basename(os.path.dirname(mani))
            d = _parse_manifest(mani)
            depends = [x for x in (d.get("depends") or []) if isinstance(x, str)]
            ext = d.get("external_dependencies")
            python = []
            if isinstance(ext, dict) and isinstance(ext.get("python"), (list, tuple)):
                python = [str(x) for x in ext["python"]]
            index[name] = {"depends": depends, "python": python, "custom": is_custom}
    return index


def _closure(seeds, index):
    """All modules reachable from seeds via `depends`, restricted to known
    (OCA/custom) modules. Odoo core modules aren't in the index, so traversal
    naturally stops at them (their Python deps live in Odoo's requirements)."""
    seen = set()
    stack = [s for s in seeds if s]
    while stack:
        m = stack.pop()
        if m in seen or m not in index:
            continue
        seen.add(m)
        stack.extend(index[m]["depends"])
    return seen


def _aggregate(modules_txt, modules_dir, custom_dir):
    index = _module_index(modules_dir, custom_dir)
    seeds = []
    if modules_txt and os.path.isfile(modules_txt):
        seeds = [ln.strip() for ln in open(modules_txt, encoding="utf-8") if ln.strip()]
    install = _closure(seeds, index)
    # Always install every custom module the project ships.
    install |= {n for n, info in index.items() if info["custom"]}

    missing = [s for s in seeds if s not in index]
    if missing:
        sys.stderr.write(
            "odoo-nix: note — modules not found on disk (skipped): "
            + ", ".join(sorted(missing)) + "\n"
        )

    seen = {}
    for name in install:
        for dep in index.get(name, {}).get("python", []):
            spec = dep.strip()
            base = _base_name(spec).lower()
            if not base or base in SKIP:
                continue
            mapped = MAP.get(base)
            seen[mapped if mapped else spec] = True
    return sorted(seen), len(install)


def update(pyproject, modules_txt, modules_dir, custom_dir):
    deps, n_install = _aggregate(modules_txt, modules_dir, custom_dir)
    text = open(pyproject, encoding="utf-8").read()
    if BEGIN not in text or END not in text:
        sys.stderr.write(
            f"warning: sentinel block not found in {pyproject}; skipping OCA dep sync\n"
        )
        return 1
    indent = re.search(r"^([ \t]*)" + re.escape(BEGIN), text, re.MULTILINE)
    pad = indent.group(1) if indent else "    "
    block = pad + BEGIN + "\n"
    for d in deps:
        block += f'{pad}"{d}",\n'
    block += pad + END
    new = re.sub(
        re.escape(pad + BEGIN) + r".*?" + re.escape(pad + END),
        lambda _m: block,
        text,
        count=1,
        flags=re.DOTALL,
    )
    open(pyproject, "w", encoding="utf-8").write(new)
    sys.stderr.write(
        f"odoo-nix: synced {len(deps)} OCA python dep(s) "
        f"for {n_install} installed module(s) into {pyproject}\n"
    )
    return 0


def main(argv):
    if len(argv) >= 5 and argv[1] == "update":
        return update(argv[2], argv[3], argv[4], argv[5] if len(argv) > 5 else "")
    if len(argv) >= 4 and argv[1] == "scan":
        deps, n = _aggregate(argv[2], argv[3], argv[4] if len(argv) > 4 else "")
        for d in deps:
            print(d)
        sys.stderr.write(f"({len(deps)} deps for {n} installed modules)\n")
        return 0
    sys.stderr.write(
        "usage: oca_pydeps.py update <pyproject.toml> <modules.txt> <modules-dir> <custom-dir>\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
