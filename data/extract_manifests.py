#!/usr/bin/env python3
"""
Extract Odoo module manifests from the OCA mirrors in .cache/ and produce a JSON
feed, one record per (repo, module, series).

Reads manifests straight out of git objects — no working trees. data/.cache/
holds one bare mirror per repo with a shallow branch per supported series (see
sync-oca-repos.sh), so a series is described by its own branch rather than by
whichever branch OCA happens to have made default.

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

Usage:  data/extract_manifests.py [series ...]     (default: the SERIES below)
"""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

# Keep in sync with lib/odoo-presets.json and sync-oca-repos.sh.
SERIES = ["19.0", "18.0"]

# Repos that are not addon collections.
SKIP_REPOS = {"OCB", "OpenUpgrade", ".github"}

# Only top-level module directories, which is what Odoo's addons_path scans.
# This also excludes each repo's setup/ tree, whose entries are symlinks back
# into the real modules.
MANIFEST_RE = re.compile(r"^[^/]+/__manifest__\.py$")


def extract_dict_from_source(content: str) -> dict | None:
    """Safely parse the manifest dictionary out of a __manifest__.py body."""
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


def git(git_dir: Path, *args: str) -> str | None:
    """Run a git command in a bare mirror; None if it fails."""
    try:
        out = subprocess.run(
            ["git", "--git-dir", str(git_dir), *args],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.decode("utf-8", "replace")


def manifest_paths(git_dir: Path, ref: str) -> list[str]:
    """Top-level `<module>/__manifest__.py` paths present at `ref`."""
    listing = git(git_dir, "ls-tree", "-r", "--name-only", ref)
    if listing is None:
        return []
    return [p for p in listing.splitlines() if MANIFEST_RE.match(p)]


def read_blobs(git_dir: Path, ref: str, paths: list[str]) -> dict[str, str]:
    """Read many blobs in one `git cat-file --batch` pass.

    One subprocess per ref rather than per module: the catalog spans ~250 repos
    × ~3 series × up to a few hundred modules, and a `git show` apiece would
    dominate the runtime.
    """
    if not paths:
        return {}
    stdin = "".join(f"{ref}:{p}\n" for p in paths).encode()
    try:
        proc = subprocess.run(
            ["git", "--git-dir", str(git_dir), "cat-file", "--batch"],
            input=stdin,
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    out = proc.stdout
    result: dict[str, str] = {}
    pos = 0
    for path in paths:
        nl = out.find(b"\n", pos)
        if nl == -1:
            break
        header = out[pos:nl].decode("utf-8", "replace")
        pos = nl + 1
        parts = header.rsplit(" ", 2)
        if len(parts) != 3 or parts[1] != "blob":
            # "<object> missing" — no trailing content to skip.
            continue
        size = int(parts[2])
        result[path] = out[pos : pos + size].decode("utf-8", "replace")
        pos += size + 1  # blob content is followed by a newline
    return result


def process_ref(git_dir: Path, repo: str, series: str) -> tuple[list[dict], int]:
    """Records for one repo at one series, plus the count of skipped modules."""
    paths = manifest_paths(git_dir, series)
    blobs = read_blobs(git_dir, series, paths)

    records = []
    skipped = 0
    for path, content in blobs.items():
        module_name = path.split("/", 1)[0]
        manifest = extract_dict_from_source(content)
        if manifest is None:
            print(f"  [WARN] Could not parse manifest: {repo}@{series}:{path}", file=sys.stderr)
            skipped += 1
            continue

        version = str(manifest.get("version", ""))
        # A manifest whose version disagrees with the branch it was read from
        # is mislabelled upstream; recording it would make it visible to the
        # wrong series, since every consumer filters on the version prefix.
        if not version.startswith(series + "."):
            skipped += 1
            continue

        record = {
            "module": module_name,
            "repo": repo,
            "name": manifest.get("name", module_name),
            "version": version,
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

        records.append(record)

    return records, skipped


def main():
    base_dir = Path(__file__).resolve().parent
    cache_dir = base_dir / ".cache"
    output_path = base_dir / "oca-modules.json"

    series_list = sys.argv[1:] or SERIES

    if not cache_dir.is_dir():
        print(f"No {cache_dir} — run sync-oca-repos.sh first.", file=sys.stderr)
        return 1

    seen: set[tuple[str, str, str]] = set()
    all_modules: list[dict] = []
    per_series = dict.fromkeys(series_list, 0)
    total_repos = 0
    total_skipped = 0

    for git_dir in sorted(cache_dir.glob("*.git")):
        repo = git_dir.name[: -len(".git")]
        if repo in SKIP_REPOS:
            continue

        found = []
        for series in series_list:
            records, skipped = process_ref(git_dir, repo, series)
            total_skipped += skipped
            for record in records:
                key = (record["repo"], record["module"], record["version"])
                if key in seen:
                    continue
                seen.add(key)
                all_modules.append(record)
                per_series[series] += 1
            if records:
                found.append(f"{series}:{len(records)}")

        if found:
            total_repos += 1
            print(f"{repo}  ->  {'  '.join(found)}", file=sys.stderr)

    # Stable output: a module now appears once per series it exists in.
    all_modules.sort(key=lambda m: (m["repo"], m["module"], m["version"]))

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_modules, f, indent=2, ensure_ascii=False)

    print(f"\nDone! {total_repos} repos, {len(all_modules)} modules", file=sys.stderr)
    for series, count in per_series.items():
        print(f"  {series}: {count}", file=sys.stderr)
    if total_skipped:
        print(f"  ({total_skipped} skipped: unparseable or version/branch mismatch)", file=sys.stderr)
    print(f"Output: {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
