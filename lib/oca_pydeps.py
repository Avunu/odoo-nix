#!/usr/bin/env python3
"""Aggregate OCA modules' external_dependencies.python and sync them into a
project's pyproject.toml.

Canonical source of the manifest-scanning logic for odoo-nix (the scaffolder and
the in-project odoo-add-app/odoo-update scripts both call this). Manifests are
Python dict literals, so they are parsed with ast (never JSON).

The aggregated deps live in pyproject.toml inside the [project].dependencies
array, between sentinel comments, so updates are plain-text and need no tomlkit:

    # >>> odoo-nix: oca python deps (managed) >>>
    "phonenumbers",
    # <<< odoo-nix: oca python deps <<<

Usage:
    oca_pydeps.py scan   <dir>...                 # print deps, one per line
    oca_pydeps.py update <pyproject.toml> <dir>...# rewrite the sentinel block
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


def _manifest_python_deps(path):
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except Exception:
        return []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            try:
                d = ast.literal_eval(node)
            except Exception:
                continue
            ext = d.get("external_dependencies") if isinstance(d, dict) else None
            if isinstance(ext, dict) and isinstance(ext.get("python"), (list, tuple)):
                return [str(x) for x in ext["python"]]
    return []


def scan(dirs):
    seen = {}
    for root in dirs:
        if not os.path.isdir(root):
            continue
        manifests = (
            glob.glob(os.path.join(root, "*", "__manifest__.py"))
            + glob.glob(os.path.join(root, "*", "*", "__manifest__.py"))
        )
        for mani in manifests:
            for dep in _manifest_python_deps(mani):
                spec = dep.strip()
                base = _base_name(spec).lower()
                if not base or base in SKIP:
                    continue
                mapped = MAP.get(base)
                seen[mapped if mapped else spec] = True
    return sorted(seen)


def update(pyproject, dirs):
    deps = scan(dirs)
    text = open(pyproject, encoding="utf-8").read()
    if BEGIN not in text or END not in text:
        sys.stderr.write(
            f"warning: sentinel block not found in {pyproject}; skipping OCA dep sync\n"
        )
        return 1
    # Preserve the indentation of the BEGIN sentinel line.
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
    sys.stderr.write(f"odoo-nix: synced {len(deps)} OCA python dep(s) into {pyproject}\n")
    return 0


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    mode = argv[1]
    if mode == "scan":
        for d in scan(argv[2:]):
            print(d)
        return 0
    if mode == "update":
        if len(argv) < 3:
            sys.stderr.write("usage: oca_pydeps.py update <pyproject.toml> <dir>...\n")
            return 2
        return update(argv[2], argv[3:])
    sys.stderr.write(f"unknown mode: {mode}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
