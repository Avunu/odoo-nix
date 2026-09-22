"""Decide which installed modules a migration has to update, and remember the
answer in the database once it has.

Two signals, either of which puts a module in the update set:

- **Content checksums.** Odoo only creates a column, loads a view or runs a
  migration script for a module that is being installed or updated. A deploy
  that changes a module's code without `-u` leaves its schema and data behind
  the code -- silently. The checksum of each module directory is compared with
  the one stored the last time a migration succeeded. The algorithm and the
  storage are OCA `module_auto_update`'s (server-tools, addon_hash.py and
  models/module.py; click-odoo-update uses the same), so the three agree on
  what "changed" means and can share one database.
- **Version drift.** `ir_module_module.latest_version` against the manifest on
  disk. Migration scripts are keyed on versions, and a database that was
  restored from somewhere else -- a dev dump, a snapshot from an older build --
  can carry versions older than the code even when no checksum was ever
  recorded against it.

A database with no stored checksums at all gets `all`: there is nothing to
diff against, so the only safe baseline is to update everything once.

`odoo_nix.migrated_build` records the store path of the build that last
migrated this database successfully. The marker lives in the database rather
than in a stamp file on disk, so restoring a dump from elsewhere -- which
carries some other build's value, or none -- is exactly what makes the next
start migrate it.

Everything here reads and writes with plain SQL on a raw cursor, never the
ORM: the fast path must not pay for a registry load, and after a failed
update the registry cannot be trusted anyway.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from fnmatch import fnmatch

#: module_auto_update's parameter keys and default exclusions
#: (models/module.py: PARAM_INSTALLED_CHECKSUMS, PARAM_EXCLUDE_PATTERNS,
#: DEFAULT_EXCLUDE_PATTERNS). Shared on purpose -- see the module docstring.
PARAM_INSTALLED_CHECKSUMS = "module_auto_update.installed_checksums"
PARAM_EXCLUDE_PATTERNS = "module_auto_update.exclude_patterns"
DEFAULT_EXCLUDE_PATTERNS = "*.pyc,*.pyo,i18n/*.pot,i18n_extra/*.pot,static/*,tests/*"

#: The build (store path) that last migrated this database successfully.
PARAM_MIGRATED_BUILD = "odoo_nix.migrated_build"

#: `ir_module_module` states whose code has to match the schema. 'to upgrade'
#: is what an interrupted update leaves behind.
UPDATABLE_STATES = ("installed", "to upgrade")


# ── addon_hash, ported from module_auto_update/addon_hash.py ─────────────────


def _fnmatch_any(filename: str, patterns: list[str]) -> bool:
    return any(fnmatch(filename, pattern) for pattern in patterns)


def _walk(top: str, exclude_patterns: list[str], keep_langs: list[str]):
    keep = {language.split("_")[0] for language in keep_langs}
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames.sort()
        reldir = os.path.relpath(dirpath, top)
        if reldir == ".":
            reldir = ""
        for filename in sorted(filenames):
            filepath = os.path.join(reldir, filename)
            if _fnmatch_any(filepath, exclude_patterns):
                continue
            if keep and reldir in {"i18n", "i18n_extra"}:
                basename, ext = os.path.splitext(filename)
                if ext == ".po" and basename.split("_")[0] not in keep:
                    continue
            yield filepath


def addon_hash(top: str, exclude_patterns: list[str], keep_langs: list[str]) -> str:
    """sha1 over every kept file's relative path and content, in sorted walk
    order -- byte-for-byte module_auto_update's addon_hash()."""
    digest = hashlib.sha1()  # noqa: S324 -- a change detector, not a security boundary; must match module_auto_update
    for filepath in _walk(top, exclude_patterns, keep_langs):
        # The name is hashed too, so adding or removing an empty file counts.
        digest.update(filepath.encode("utf-8"))
        with open(os.path.join(top, filepath), "rb") as fh:
            digest.update(fh.read())
    return digest.hexdigest()


# ── database reads/writes (raw cursor) ───────────────────────────────────────


def get_param(cr, key: str) -> str | None:
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (key,))
    row = cr.fetchone()
    return row[0] if row else None


def set_param(cr, key: str, value: str) -> None:
    cr.execute(
        """
        INSERT INTO ir_config_parameter (key, value, create_uid, write_uid, create_date, write_date)
        VALUES (%s, %s, 1, 1, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC')
        ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, write_uid = 1, write_date = EXCLUDED.write_date
        """,
        (key, value),
    )


def _updatable_modules(cr) -> dict[str, str | None]:
    cr.execute(
        "SELECT name, latest_version FROM ir_module_module WHERE state IN %s ORDER BY name",
        (UPDATABLE_STATES,),
    )
    return dict(cr.fetchall())


def _hash_settings(cr) -> tuple[list[str], list[str]]:
    patterns = get_param(cr, PARAM_EXCLUDE_PATTERNS) or DEFAULT_EXCLUDE_PATTERNS
    exclude = [p.strip() for p in patterns.split(",") if p.strip()]
    cr.execute("SELECT code FROM res_lang WHERE active")
    keep_langs = [row[0] for row in cr.fetchall()]
    return exclude, keep_langs


def _module_path(name: str) -> str | None:
    from odoo.modules.module import get_module_path

    return get_module_path(name, display_warning=False) or None


def _disk_version(name: str, path: str) -> str | None:
    from odoo.modules.module import adapt_version, get_manifest

    manifest = get_manifest(name, path)
    version = manifest.get("version") if manifest else None
    if not version:
        return None
    try:
        return adapt_version(version)
    except ValueError:
        return None


def current_checksums(cr) -> dict[str, str]:
    """Checksums of every updatable module's code as it is on disk now."""
    exclude, keep_langs = _hash_settings(cr)
    checksums = {}
    for name in _updatable_modules(cr):
        path = _module_path(name)
        if path:
            checksums[name] = addon_hash(path, exclude, keep_langs)
    return checksums


# ── the plan ─────────────────────────────────────────────────────────────────


@dataclass
class Plan:
    """What a migration of one database will update, and why."""

    #: The module names to pass to Odoo's update loop; ["all"] for a baseline.
    update: list[str] = field(default_factory=list)
    #: name -> human-readable reason ("checksum", "18.0.3.4.1 → 18.0.4.0.0", ...)
    reasons: dict[str, str] = field(default_factory=dict)
    #: Installed in the database, but no code for them on the addons path.
    missing: list[str] = field(default_factory=list)
    #: No checksums were stored, so this is a full `-u all` baseline.
    baseline: bool = False

    @property
    def empty(self) -> bool:
        return not self.update

    def describe(self) -> str:
        if self.baseline:
            return "no module checksums recorded in this database — updating all modules once to establish a baseline"
        if self.empty:
            return "every installed module matches its code — nothing to update"
        parts = [f"{name} ({self.reasons[name]})" for name in self.update]
        return f"{len(self.update)} module(s) to update: " + ", ".join(parts)


def build_plan(cr, *, full: bool = False, also: list[str] | None = None) -> Plan:
    also = [m for m in (also or []) if m]
    plan = Plan()
    installed = _updatable_modules(cr)

    stored_raw = get_param(cr, PARAM_INSTALLED_CHECKSUMS)
    try:
        stored = json.loads(stored_raw) if stored_raw else {}
    except ValueError:
        stored = {}

    if full or not stored:
        plan.baseline = not full
        plan.update = ["all"]
        plan.reasons["all"] = "--full" if full else "baseline"
        return plan

    exclude, keep_langs = _hash_settings(cr)
    for name, db_version in installed.items():
        path = _module_path(name)
        if not path:
            plan.missing.append(name)
            continue
        disk_version = _disk_version(name, path)
        if disk_version and db_version and disk_version != db_version:
            plan.reasons[name] = f"{db_version} → {disk_version}"
        elif stored.get(name) != addon_hash(path, exclude, keep_langs):
            plan.reasons[name] = "code changed" if name in stored else "no checksum recorded"

    for name in also:
        if name in installed:
            plan.reasons.setdefault(name, "requested")

    plan.update = sorted(plan.reasons)
    return plan


def record_success(cr, build: str | None) -> None:
    """After a successful update: store every module's current checksum, and
    the build that did it. Recomputed from disk rather than carried over from
    the plan, because an update can install new auto_install modules and
    changes nothing about modules outside the plan."""
    set_param(cr, PARAM_INSTALLED_CHECKSUMS, json.dumps(current_checksums(cr), sort_keys=True))
    if build:
        set_param(cr, PARAM_MIGRATED_BUILD, build)
