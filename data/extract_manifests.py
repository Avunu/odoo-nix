#!/usr/bin/env python3
"""
Extract Odoo module manifests from all OCA repositories and produce a JSON feed.

Output JSON schema per module:
{
    "module": "account_financial_report",
    "repo": "account-financial-reporting",
    "name": "Account Financial Reports",
    "version": "18.0.1.4.20",
    "application": true,
    "installable": true,
    "auto_install": false,
    "depends": ["account", "date_range", "report_xlsx"],
    "license": "AGPL-3",
    "summary": "OCA Financial Reports"
}
"""

import ast
import json
import os
import re
import sys
from pathlib import Path

# Directories that are NOT OCA repos
SKIP_DIRS = {
    ".github", "OCB", "OpenUpgrade", ".git",
    "setup",  # setup dirs contain symlinks/submodules, not real modules
}

def extract_dict_from_file(filepath: str) -> dict | None:
    """Safely parse the manifest dictionary from a __manifest__.py file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    if not content.strip():
        return None

    # Find the opening brace of the manifest dict
    brace_idx = content.find("{")
    if brace_idx == -1:
        return None

    # Find the matching closing brace
    # We track brace depth to handle nested dicts/lists
    depth = 0
    end_idx = -1
    for i in range(brace_idx, len(content)):
        ch = content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i
                break

    if end_idx == -1:
        return None

    dict_str = content[brace_idx : end_idx + 1]

    # Remove trailing comma before closing brace — common in Odoo manifests
    # (e.g., ... "license": "AGPL-3",}) — ast.literal_eval doesn't like it
    dict_str = re.sub(r",\s*}", "}", dict_str)

    try:
        manifest = ast.literal_eval(dict_str)
        return manifest if isinstance(manifest, dict) else None
    except (ValueError, SyntaxError):
        # Fall back to eval() for cases ast.literal_eval can't handle
        # (like implicit string concatenation in some edge cases)
        try:
            manifest = eval(dict_str, {"__builtins__": {}}, {})
            return manifest if isinstance(manifest, dict) else None
        except Exception:
            return None


def is_odoo_module(dir_path: Path) -> bool:
    """Check if a directory is an Odoo module (has __manifest__.py)."""
    manifest = dir_path / "__manifest__.py"
    return manifest.is_file()


def process_repo(repo_path: Path) -> list[dict]:
    """Process a single OCA repo and return list of module data dicts."""
    results = []
    repo_name = repo_path.name

    try:
        entries = sorted(repo_path.iterdir())
    except PermissionError:
        return results

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue

        if not is_odoo_module(entry):
            continue

        manifest_path = entry / "__manifest__.py"
        manifest = extract_dict_from_file(str(manifest_path))

        if manifest is None:
            print(f"  [WARN] Could not parse manifest: {manifest_path}", file=sys.stderr)
            continue

        module_name = entry.name

        # Build the output record
        record = {
            "module": module_name,
            "repo": repo_name,
            "name": manifest.get("name", module_name),
            "version": manifest.get("version", ""),
            "application": manifest.get("application", False) is True,
            "installable": manifest.get("installable", True) is True,
            "auto_install": manifest.get("auto_install", False) is True,
            "depends": manifest.get("depends", []),
            "license": manifest.get("license", ""),
            "summary": manifest.get("summary", ""),
        }

        # Normalize depends — always a list of strings
        if isinstance(record["depends"], str):
            record["depends"] = [record["depends"]]
        elif not isinstance(record["depends"], list):
            record["depends"] = []
        record["depends"] = [str(d) for d in record["depends"]]

        results.append(record)

    return results


def main():
    base_dir = Path(__file__).resolve().parent
    output_path = base_dir / "oca-modules.json"

    all_modules = []
    total_repos = 0
    total_modules = 0

    entries = sorted(base_dir.iterdir())

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in SKIP_DIRS:
            continue

        # Quick sanity: does this directory contain any Odoo module subdirs?
        # Some dirs like 'doc/' or 'oca-addons-repo-template/' may not be repos.
        has_manifest = False
        try:
            for child in entry.iterdir():
                if child.is_dir() and (child / "__manifest__.py").is_file():
                    has_manifest = True
                    break
        except PermissionError:
            continue

        if not has_manifest:
            continue

        total_repos += 1
        repo_name = entry.name
        print(f"Processing repo: {repo_name} ...", file=sys.stderr)

        modules = process_repo(entry)
        all_modules.extend(modules)
        total_modules += len(modules)
        print(f"  -> {len(modules)} modules", file=sys.stderr)

    # Sort by module name for stable output
    all_modules.sort(key=lambda m: (m["repo"], m["module"]))

    # Write JSON output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_modules, f, indent=2, ensure_ascii=False)

    print(f"\nDone! {total_repos} repos, {total_modules} modules", file=sys.stderr)
    print(f"Output: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
