#!/usr/bin/env python3
"""Assert tests/fixtures/<series>/uv.lock was locked against the pinned OCB.

uv.lock records nothing about the OCB revision itself -- only what uv derived
from the tree: the `odoo` package's version (the series, "18.0") and its
requires-dist (setup.py install_requires). Those two are what can be checked
without network, so they are checked. A dependabot bump of an ocb-* input that
changes either fails here with the one command that fixes it.

install_requires is read by executing setup.py with `setuptools.setup`
captured, not by regex: exact, and it also runs release.py.

Usage: lock_fresh.py <uv.lock> <ocb source dir> <series>
"""

import os
import re
import runpy
import sys
import tomllib

import setuptools


def normalize(requirement):
    name = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement).group(1)
    return re.sub(r"[-_.]+", "-", name).lower()


def setup_kwargs(ocb):
    captured = {}
    setuptools.setup = lambda **kw: captured.update(kw)
    cwd = os.getcwd()
    os.chdir(ocb)  # find_packages() walks the CWD
    try:
        runpy.run_path(os.path.join(ocb, "setup.py"), run_name="__main__")
    finally:
        os.chdir(cwd)
    return captured


def main(lock_path, ocb, series):
    kw = setup_kwargs(ocb)
    with open(lock_path, "rb") as f:
        lock = tomllib.load(f)
    odoo = next((p for p in lock["package"] if p["name"] == "odoo"), None)

    problems = []
    if odoo is None:
        problems.append("uv.lock has no `odoo` package")
    else:
        if odoo.get("source") != {"directory": "odoo"}:
            problems.append(
                f"uv.lock records odoo as {odoo.get('source')!r}, "
                "expected the path source `odoo/`"
            )
        if odoo["version"] != kw["version"]:
            problems.append(
                f"uv.lock has odoo {odoo['version']}, the pinned OCB is {kw['version']}"
            )
        locked = {
            normalize(d["name"])
            for d in odoo.get("metadata", {}).get("requires-dist", [])
            if "extra ==" not in d.get("marker", "")
        }
        pinned = {normalize(r) for r in kw["install_requires"]}
        if locked != pinned:
            problems.append(
                "install_requires drift -- missing from uv.lock: "
                f"{sorted(pinned - locked)}; stale in uv.lock: {sorted(locked - pinned)}"
            )
    if kw["version"] != series:
        problems.append(
            f"the pinned OCB is {kw['version']}, but this fixture is for {series} "
            "(input pointed at the wrong branch?)"
        )

    if problems:
        print(
            f"tests/fixtures/{series}/uv.lock does not match the pinned OCB:",
            file=sys.stderr,
        )
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nThe pin moved (dependabot, or `nix flake update ocb-*`) and the lock "
            "did not follow. Fix:\n",
            file=sys.stderr,
        )
        print("    nix run .#relock", file=sys.stderr)
        print(
            f"    git add tests/fixtures/{series}/uv.lock "
            f"tests/fixtures/{series}/pyproject.toml\n",
            file=sys.stderr,
        )
        return 1
    print(
        f"uv.lock for {series} matches the pinned OCB {kw['version']} "
        f"({len(kw['install_requires'])} install_requires)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
