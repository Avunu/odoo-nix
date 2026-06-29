#!/usr/bin/env python3
"""Keep pyproject.toml's [tool.uv.extra-build-dependencies] in sync with the
sdist-only packages in uv.lock.

Legacy sdist-only packages (no wheel for the locked version) frequently predate
PEP 517 and don't declare setuptools as a build dependency, so uv2nix fails to
build them in the Nix sandbox. Rather than hand-maintain the list, scan uv.lock
for every wheel-less package and grant each a setuptools build dep. Harmless for
packages that already declare a backend (extra-build-dependencies is additive).

The entries live in a sentinel-delimited managed block, so updates are
plain-text and need no tomlkit:

    [tool.uv.extra-build-dependencies]
    # >>> odoo-nix: sdist build deps (managed) >>>
    "py3o-formats" = ["setuptools"]
    # <<< odoo-nix: sdist build deps (managed) <<<

Usage:
    uv_build_deps.py update <pyproject.toml> <uv.lock>
"""

import re
import sys
import tomllib

BEGIN = "# >>> odoo-nix: sdist build deps (managed) >>>"
END = "# <<< odoo-nix: sdist build deps (managed) <<<"

# Always grant setuptools to these, even if a wheel exists for the locked
# version on this run — they are reliably sdist-only across platforms/versions.
ALWAYS = ["docopt", "ofxparse", "python-ldap", "rjsmin", "vobject"]


def sdist_only(lockfile, exclude):
    lock = tomllib.load(open(lockfile, "rb"))
    out = []
    for pkg in lock.get("package", []):
        name = pkg.get("name")
        if not name or name == exclude or pkg.get("wheels"):
            continue
        # Skip the virtual/editable workspace root (no real build).
        src = pkg.get("source", {})
        if isinstance(src, dict) and (src.get("virtual") or src.get("editable")):
            continue
        out.append(name)
    return out


def update(pyproject, lockfile):
    text = open(pyproject, encoding="utf-8").read()
    root = re.search(r'(?m)^\s*name\s*=\s*"([^"]+)"', text)
    names = sorted(set(sdist_only(lockfile, root.group(1) if root else None)) | set(ALWAYS))
    if BEGIN not in text or END not in text:
        sys.stderr.write(
            f"warning: sdist sentinel block not found in {pyproject}; "
            "skipping build-dep sync\n"
        )
        return 1
    indent = re.search(r"^([ \t]*)" + re.escape(BEGIN), text, re.MULTILINE)
    pad = indent.group(1) if indent else ""
    block = pad + BEGIN + "\n"
    for n in names:
        block += f'{pad}"{n}" = ["setuptools"]\n'
    block += pad + END
    new = re.sub(
        re.escape(pad + BEGIN) + r".*?" + re.escape(pad + END),
        lambda _m: block,
        text,
        count=1,
        flags=re.DOTALL,
    )
    open(pyproject, "w", encoding="utf-8").write(new)
    sys.stderr.write(f"odoo-nix: synced {len(names)} sdist build-dep entr(ies)\n")
    return 0


def main(argv):
    if len(argv) >= 4 and argv[1] == "update":
        return update(argv[2], argv[3])
    sys.stderr.write("usage: uv_build_deps.py update <pyproject.toml> <uv.lock>\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
