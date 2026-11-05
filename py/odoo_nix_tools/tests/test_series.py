"""The series data and its deviations (DESIGN.md §3.0, §7.2 test_series)."""

from __future__ import annotations

import json
import re
import unittest
from typing import Any

from odoo_nix_tools import series
from standards_core.common.report import ConfigError
from support import odoo_nix_root

ORG = {
    "repo": "Avunu/edi-addons",
    "addon-manifest": {"author": "Avunu LLC", "website": "https://github.com/{repo}"},
    "hygiene": {"forbid-contributing": True},
}
NO_ORG: dict[str, Any] = {"addon-manifest": {"author": "", "website": ""}}
ADDONS = {"shape": "addons", "addons_root": "."}
PROJECT = {"shape": "project", "addons_root": "custom"}
FIELDS = ("tools", "hooks", "exclude", "ruff", "pylint", "files", "esm_globs", "node")

# For each deviation: (series, cfg, facts) under which it applies, and series where it
# must not.
APPLIES: dict[str, tuple[tuple[str, dict, dict], tuple[str, ...]]] = {
    "odoo-nix-pins": (("19.0", ORG, ADDONS), ()),
    "drop-gen-readme": (("18.0", ORG, ADDONS), ()),
    "drop-excluded-addons": (("18.0", ORG, ADDONS), ()),
    "drop-external-deps": (("20.0", ORG, ADDONS), ()),
    "no-readme-fix": (("20.0", ORG, ADDONS), ("18.0", "19.0")),
    "stage-names": (("18.0", ORG, ADDONS), ("19.0", "20.0")),
    "forbid-contributing": (
        ("18.0", {**ORG, "hygiene": {"forbid-contributing": False}}, ADDONS),
        (),
    ),
    "addons-dir": (("18.0", ORG, PROJECT), ()),
    "github-per-hook": (("18.0", ORG, ADDONS), ()),
    "prettier-vscode": (("19.0", ORG, ADDONS), ()),
    "system-language": (("18.0", ORG, ADDONS), ()),
    "locks-excluded": (("18.0", ORG, ADDONS), ()),
    "esm-static": (("18.0", ORG, ADDONS), ()),
    "pylint-dedupe": (("18.0", ORG, ADDONS), ()),
    "required-author": (("19.0", NO_ORG, ADDONS), ()),
    "node-runtime": (("19.0", ORG, ADDONS), ("18.0",)),
}


def hook(data: series.SeriesData, hook_id: str) -> Any:
    return next((h for h in data.hooks if h["id"] == hook_id), None)


def diff(a: series.SeriesData, b: series.SeriesData) -> set[str]:
    return {f for f in FIELDS if getattr(a, f) != getattr(b, f)}


class Load(unittest.TestCase):
    def test_every_file_loads(self) -> None:
        self.assertEqual(series.known(), ("18.0", "19.0", "20.0"))
        for name in series.known():
            doc = series.load(name)
            self.assertEqual(doc["schema_version"], 1)
            self.assertEqual(doc["series"], name)

    def test_unknown_series_is_exit_2(self) -> None:
        with self.assertRaisesRegex(ConfigError, "knows series 18.0, 19.0, 20.0"):
            series.load("17.0")

    def test_presets_copy_matches_lib(self) -> None:
        root = odoo_nix_root()
        if root is None:
            self.skipTest("lib/odoo-presets.json is not available")
        lib = json.loads((root / "lib/odoo-presets.json").read_text())
        self.assertEqual(dict(series.presets()), lib)
        self.assertEqual(set(lib), set(series.known()))


class Deviations(unittest.TestCase):
    def test_the_table_is_the_pipeline(self) -> None:
        ids = [d.id for d in series.DEVIATIONS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(APPLIES))
        for d in series.DEVIATIONS:
            self.assertLessEqual(set(d.fields), set(FIELDS), d.id)
        proposed = [d.id for d in series.DEVIATIONS if d.status == "proposed"]
        self.assertEqual(proposed, ["drop-external-deps"])

    def test_each_changes_exactly_its_fields(self) -> None:
        for d in series.DEVIATIONS:
            (name, cfg, facts), elsewhere = APPLIES[d.id]
            with self.subTest(deviation=d.id):
                full = series.build(name, cfg, facts)
                without = series.build(name, cfg, facts, skip={d.id})
                self.assertIn(d.id, full.deviations)
                self.assertNotIn(d.id, without.deviations)
                self.assertEqual(diff(full, without), set(d.fields))
                for other in elsewhere:
                    data = series.build(other, cfg, facts)
                    self.assertNotIn(d.id, data.deviations, other)
                    self.assertEqual(
                        diff(data, series.build(other, cfg, facts, skip={d.id})), set()
                    )

    def test_dropped_hooks(self) -> None:
        for name in series.known():
            ids = {h["id"] for h in series.effective(name, ORG, ADDONS).hooks}
            raw = {h["id"] for h in series.load(name)["hooks"]}
            self.assertEqual(
                raw - ids,
                {
                    "oca-gen-addon-readme",
                    "oca-update-pre-commit-excluded-addons",
                    "oca-gen-external-dependencies",
                },
            )

    def test_github_per_hook_and_prettier_vscode(self) -> None:
        data = series.effective("18.0", ORG, ADDONS)
        patterns = [a["pattern"] for a in data.exclude]
        self.assertNotIn("^.github/", patterns)
        self.assertEqual(patterns[-1], series.LOCKS)
        for h in data.hooks:
            self.assertTrue(h["exclude"].startswith(r"^\.github/"), h["id"])
        self.assertEqual(hook(data, "prettier")["exclude"], r"^\.github/|^\.vscode/")
        self.assertEqual(
            hook(data, "trailing-whitespace")["exclude"],
            r"^\.github/|/README\.rst$|\.pot?$",
        )
        self.assertTrue(re.search(hook(data, "check-xml")["exclude"], ".github/x.xml"))

    def test_stage_names_on_18_only(self) -> None:
        old = hook(series.effective("18.0", ORG, ADDONS), "end-of-file-fixer")
        self.assertEqual(list(old["stages"]), ["pre-commit", "pre-push", "manual"])

    def test_no_readme_fix_on_20(self) -> None:
        self.assertEqual(
            list(
                hook(series.effective("20.0", ORG, ADDONS), "oca-checks-odoo-module")[
                    "args"
                ]
            ),
            [],
        )

    def test_forbid_contributing(self) -> None:
        cfg = {**ORG, "hygiene": {"forbid-contributing": False}}
        files = hook(series.effective("18.0", cfg, ADDONS), "obsolete dotfiles")[
            "files"
        ]
        self.assertNotIn("CONTRIBUTING", files)
        self.assertTrue(re.search(files, ".travis.yml"))
        kept = hook(series.effective("18.0", ORG, ADDONS), "obsolete dotfiles")["files"]
        self.assertTrue(re.search(kept, "CONTRIBUTING.md"))

    def test_addons_dir_and_website(self) -> None:
        project = hook(
            series.effective("18.0", ORG, PROJECT), "oca-fix-manifest-website"
        )
        self.assertEqual(
            list(project["args"]),
            ["--addons-dir=custom", "https://github.com/Avunu/edi-addons"],
        )
        addons = hook(series.effective("18.0", ORG, ADDONS), "oca-fix-manifest-website")
        self.assertEqual(list(addons["args"]), ["https://github.com/Avunu/edi-addons"])
        self.assertIsNone(
            hook(series.effective("18.0", NO_ORG, ADDONS), "oca-fix-manifest-website")
        )

    def test_system_language(self) -> None:
        for name in series.known():
            for h in series.effective(name, ORG, ADDONS).hooks:
                self.assertNotIn("additional_dependencies", h)
                self.assertNotIn("rev", h)
                if h["language"] == "fail":
                    self.assertFalse(h["entry"].startswith(("tools/", "node_modules/")))
                    continue
                self.assertEqual(h["language"], "system")
                prefix = (
                    "node_modules/.bin/"
                    if h["id"] in ("prettier", "eslint")
                    else "tools/.venv/bin/"
                )
                self.assertTrue(h["entry"].startswith(prefix), h["entry"])

    def test_pylint_dedupe_and_required_author(self) -> None:
        data = series.effective("18.0", ORG, ADDONS)
        for messages in data.pylint["messages"].values():
            self.assertEqual(len(messages["enable"]), len(set(messages["enable"])))
        self.assertEqual(
            data.pylint["odoolint"]["manifest-required-authors"], "Avunu LLC"
        )
        bare = series.effective("18.0", NO_ORG, ADDONS)
        self.assertNotIn("manifest-required-authors", bare.pylint["odoolint"])
        for name, messages in bare.pylint["messages"].items():
            self.assertNotIn("manifest-required-author", messages["enable"])
            section = bare.pylint["sections"][name]
            self.assertNotIn("manifest-required-authors", section.get("ODOOLINT", {}))
            enabled = series._split_enable(section["MESSAGES CONTROL"]["enable"])
            self.assertEqual(enabled, list(messages["enable"]))

    def test_mandatory_enable_round_trips(self) -> None:
        # .pylintrc-mandatory has no duplicate: dedupe rewrites its section text unchanged.
        raw = series.load("18.0")["pylint"]["sections"][".pylintrc-mandatory"]
        data = series.effective("18.0", ORG, ADDONS)
        self.assertEqual(
            data.pylint["sections"][".pylintrc-mandatory"]["MESSAGES CONTROL"][
                "enable"
            ],
            raw["MESSAGES CONTROL"]["enable"],
        )

    def test_esm_static_and_node(self) -> None:
        for name in series.known():
            data = series.effective(name, ORG, ADDONS)
            self.assertEqual(data.esm_globs[-2:], series.ESM_STATIC)
            nodejs = series.presets()[name]["nodejs"]
            self.assertEqual(data.node, nodejs.removeprefix("nodejs_"))
        self.assertEqual(series.effective("18.0", ORG, ADDONS).node, "22")
        self.assertEqual(series.effective("20.0", ORG, ADDONS).node, "24")


class Pins(unittest.TestCase):
    def test_every_null_version_tool_is_pinned(self) -> None:
        for name in series.known():
            raw = series.load(name)["tools"]
            data = series.effective(name, ORG, ADDONS)
            for tool_name, tool in raw.items():
                if tool["version"] is None:
                    pinned = data.tools[tool_name]
                    self.assertRegex(pinned.requirement, r"(==|>=)\d", tool_name)
            for own in series.OWN_TOOLS:
                self.assertTrue(data.tools[own].requirement.startswith(f"{own}=="))
            for tool in data.tools.values():
                if tool.ecosystem == "pypi":
                    self.assertRegex(tool.requirement, r"(==|>=)\d", tool.name)

    def test_pins_file(self) -> None:
        self.assertEqual(series.tool_pins()["checklog-odoo"], "==1.0")
        self.assertEqual(
            series.effective("20.0", ORG, ADDONS).tools["manifestoo-core"].requirement,
            "manifestoo-core>=1.16.1",
        )


class Placeholders(unittest.TestCase):
    def test_none_survives_with_or_without_an_org(self) -> None:
        for name in series.known():
            for cfg in (ORG, NO_ORG, {}):
                for facts in (ADDONS, PROJECT):
                    data = series.effective(name, cfg, facts)
                    self.assertEqual(series.placeholders_left(data), [])

    def test_a_skipped_deviation_leaves_one(self) -> None:
        data = series.build("18.0", ORG, ADDONS, skip={"drop-gen-readme"})
        self.assertTrue(
            any("@@org_slug@@" in p for p in series.placeholders_left(data))
        )

    def test_website_placeholders(self) -> None:
        cfg = {
            "repo": "Avunu/edi-addons",
            "addon-manifest": {"website": "https://x/{repo_name}/{repo}"},
        }
        self.assertEqual(series.website(cfg), "https://x/edi-addons/Avunu/edi-addons")
        self.assertEqual(series.website({}), "")


if __name__ == "__main__":
    unittest.main()


class Docs(unittest.TestCase):
    def test_managed_files_lists_every_deviation(self) -> None:
        """docs/standards/managed-files.md's table, written by hand: its ids, in order,
        and each one's Applies column are ``DEVIATIONS``' (O9-19)."""
        root = odoo_nix_root()
        page = root / "docs/standards/managed-files.md" if root else None
        if page is None or not page.is_file():
            self.skipTest("docs/standards/managed-files.md is not available")
        text = page.read_text().split("## Where odoo-nix changes OCA's rules", 1)[1]
        rows = re.findall(r"^\| `([a-z0-9-]+)` \| (.+?) \| ", text, re.MULTILINE)
        shown = [(name, applies.replace("`", "")) for name, applies in rows]
        self.assertEqual(shown, [(d.id, d.applies) for d in series.DEVIATIONS])
        for d in series.DEVIATIONS:
            self.assertEqual("proposed" in d.applies, d.status == "proposed", d.id)
