"""The locked-tools ``.pre-commit-config.yaml`` (DESIGN.md §3.3, §7.2 test_precommit)."""

from __future__ import annotations

import re
import unittest

import yaml
from odoo_nix_tools import precommit, series
from odoo_nix_tools.product import PRODUCT
from support import SyncCase

DROPPED = {
    "oca-gen-addon-readme",
    "oca-update-pre-commit-excluded-addons",
    "oca-gen-external-dependencies",
}
EVERY = {name: True for name in PRODUCT.modules.names}
ORG = {
    "repo": "example-org/fixture-addons",
    "addon-manifest": {"author": "Example Org", "website": "https://github.com/{repo}"},
    "pylint-odoo": {"optional-run": True},
    "js-xml": {"exclude": []},
}
ADDONS = {
    "shape": "addons",
    "addons_root": ".",
    "has_sh": True,
    "has_nix": True,
    "addons": [],
    "not_installable": [],
}


def oca_ids(series_name: str) -> list[str]:
    """The hook ids of OCA's rendered ``.pre-commit-config.yaml``, in order."""
    doc = yaml.safe_load(
        series.load(series_name)["reference_files"][".pre-commit-config.yaml"]
    )
    return [hook["id"] for repo in doc["repos"] for hook in repo["hooks"]]


def build(
    series_name: str,
    modules: dict | None = None,
    cfg: dict | None = None,
    facts: dict | None = None,
) -> list[precommit.Hook]:
    cfg = cfg if cfg is not None else ORG
    facts = facts if facts is not None else ADDONS
    data = series.effective(series_name, cfg, facts)
    return precommit.hooks(data, modules if modules is not None else EVERY, cfg, facts)


class HookList(unittest.TestCase):
    def test_oca_hooks_minus_the_dropped_three(self) -> None:
        for name in series.known():
            with self.subTest(series=name):
                ours = [h.id for h in build(name) if h.id not in OWN]
                wanted = [i for i in oca_ids(name) if i not in DROPPED]
                self.assertEqual(ours, wanted)

    def test_github_excluded_per_hook(self) -> None:
        for name in series.known():
            for hook in build(name):
                if hook.id not in OWN:
                    with self.subTest(series=name, hook=hook.id):
                        self.assertTrue((hook.exclude or "").startswith(r"^\.github/"))
            data = series.effective(name, ORG, ADDONS)
            self.assertNotIn(
                "^.github/", [alt["pattern"] for alt in data.exclude], name
            )

    def test_stage_names_on_18(self) -> None:
        stages = {s for h in build("18.0") for s in h.stages}
        self.assertTrue(stages)
        self.assertFalse(stages & {"commit", "push", "merge-commit"})
        self.assertIn("pre-commit", stages)

    def test_readme_fix_gone_on_20(self) -> None:
        module = next(h for h in build("20.0") if h.id == "oca-checks-odoo-module")
        self.assertNotIn("--fix", module.args)
        raw = next(
            h
            for h in series.load("20.0")["hooks"]
            if h["id"] == "oca-checks-odoo-module"
        )
        self.assertIn("--fix", raw["args"])

    def test_entries_are_locked_executables(self) -> None:
        for hook in build("18.0"):
            with self.subTest(hook=hook.id):
                if hook.language == "fail":
                    self.assertFalse(hook.entry.startswith(("tools/", "node_modules/")))
                    continue
                self.assertEqual(hook.language, "system")
                prefix = {
                    "js-xml": "node_modules/.bin/",
                    "workflow-lint": "tools/.bin/",
                    "shell-lint": "tools/.bin/",
                    "nix-lint": "tools/.bin/",
                    "commits": "tools/.bin/",
                }.get(hook.module, "tools/.venv/bin/")
                self.assertTrue(hook.entry.startswith(prefix), hook.entry)

    def test_website_hook(self) -> None:
        hook = next(h for h in build("18.0") if h.id == "oca-fix-manifest-website")
        self.assertEqual(hook.args, ("https://github.com/example-org/fixture-addons",))
        self.assertIs(hook.pass_filenames, False)
        project = {**ADDONS, "shape": "project", "addons_root": "custom"}
        hook = next(
            h
            for h in build("18.0", facts=project)
            if h.id == "oca-fix-manifest-website"
        )
        self.assertEqual(
            hook.args,
            ("--addons-dir=custom", "https://github.com/example-org/fixture-addons"),
        )
        no_site = {**ORG, "addon-manifest": {"author": "", "website": ""}}
        self.assertNotIn(
            "oca-fix-manifest-website", [h.id for h in build("18.0", cfg=no_site)]
        )


# odoo-nix's own hooks (rule 5); every other one is OCA's.
OWN = {
    "check-json",
    "check-yaml",
    "actionlint",
    "zizmor",
    "shellcheck",
    "nixfmt",
    "statix",
    "deadnix",
    "committed",
}


class Gating(unittest.TestCase):
    def ids(self, **off: bool) -> list[str]:
        modules = {**EVERY, **{k.replace("_", "-"): v for k, v in off.items()}}
        return [h.id for h in build("18.0", modules=modules)]

    def test_js_xml_off(self) -> None:
        ids = self.ids(js_xml=False)
        self.assertNotIn("prettier", ids)
        self.assertNotIn("eslint", ids)

    def test_pylint_optional_run(self) -> None:
        cfg = {**ORG, "pylint-odoo": {"optional-run": False}}
        hooks = [h for h in build("18.0", cfg=cfg) if h.id == "pylint_odoo"]
        self.assertEqual([h.args[0] for h in hooks], ["--rcfile=.pylintrc-mandatory"])

    def test_packaging_only_in_addon_repositories(self) -> None:
        project = {**ADDONS, "shape": "project", "addons_root": "custom"}
        self.assertNotIn("whool-init", [h.id for h in build("18.0", facts=project)])
        self.assertIn("whool-init", [h.id for h in build("18.0")])

    def test_shell_and_nix_need_their_files(self) -> None:
        facts = {**ADDONS, "has_sh": False, "has_nix": False}
        ids = [h.id for h in build("18.0", facts=facts)]
        for hook in ("shellcheck", "nixfmt", "statix", "deadnix"):
            self.assertNotIn(hook, ids)
        self.assertIn("shellcheck", self.ids())

    def test_own_hooks_by_module(self) -> None:
        self.assertNotIn("committed", self.ids(commits=False))
        ids = self.ids(workflow_lint=False, hygiene=False)
        for hook in (
            "actionlint",
            "zizmor",
            "check-json",
            "check-yaml",
            "forbidden-files",
        ):
            self.assertNotIn(hook, ids)
        zizmor = next(h for h in build("18.0") if h.id == "zizmor")
        self.assertIn("--offline", zizmor.entry)

    def test_js_xml_exclude(self) -> None:
        cfg = {**ORG, "js-xml": {"exclude": ["carbon_ui/frontend/", "static/dist/"]}}
        prettier = next(h for h in build("18.0", cfg=cfg) if h.id == "prettier")
        self.assertTrue(
            (prettier.exclude or "").endswith(
                r"|^(?:carbon_ui/frontend/|static/dist/)"
            ),
            prettier.exclude,
        )
        self.assertIn(r"^\.vscode/", prettier.exclude or "")


class Yaml(unittest.TestCase):
    def test_scalars_read_back(self) -> None:
        for value in (
            r"\.rej$",
            r"[a-zA-Z0-9_]*/i18n/en\.po$",
            "found forbidden files; remove them",
            "true",
            "18.0",
            "a: b",
            "x #y",
            "-x",
            "*x",
            "",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    yaml.safe_load(f"k: {precommit.scalar(value)}")["k"], value
                )

    def test_hooks_round_trip(self) -> None:
        hooks = build("18.0")
        text = "hooks:\n" + precommit.hooks_yaml(hooks)
        doc = yaml.safe_load(text)["hooks"]
        self.assertEqual([h["id"] for h in doc], [h.id for h in hooks])
        for raw, hook in zip(doc, hooks, strict=True):
            self.assertEqual(raw["entry"], hook.entry)
            self.assertEqual(raw.get("exclude"), hook.exclude)
            self.assertEqual(raw.get("files"), hook.files)
            self.assertEqual(tuple(raw.get("args", ())), hook.args)


class Rendered(SyncCase):
    def test_project_file(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        text = (root / ".pre-commit-config.yaml").read_text()
        doc = yaml.safe_load(text)
        self.assertNotIn("default_language_version", doc)
        pattern = doc["exclude"]
        # The not-installable region names the project's path, and the regex compiles
        # with the region markers as (?x) comments.
        block = text.split("# NOT INSTALLABLE ADDONS\n", 1)[1].split("# END", 1)[0]
        self.assertEqual(block.strip(), "^custom/fixture_legacy/|")
        regex = re.compile(pattern)
        self.assertTrue(regex.search("custom/fixture_legacy/__manifest__.py"))
        self.assertTrue(regex.search("tools/uv.lock"))
        self.assertTrue(regex.search("package-lock.json"))
        self.assertFalse(regex.search(".github/workflows/ci.yml"))
        self.assertFalse(regex.search("custom/fixture_sale/models/sale_order.py"))
        # The locks alternative is last and the local region sits before it.
        lines = [line.strip() for line in pattern.splitlines() if line.strip()]
        self.assertEqual(lines[-1], series.LOCKS)
        self.assertEqual(
            lines[-4:-2],
            [
                "# odoo-nix:local-begin exclude",
                "# odoo-nix:local-end exclude",
            ],
        )
        self.assertEqual(
            text.splitlines()[-2:],
            [
                "  # odoo-nix:local-begin hooks",
                "  # odoo-nix:local-end hooks",
            ],
        )

    def test_local_regions_kept_and_checked(self) -> None:
        root = self.profile_fixture("standards-project", "recommended")
        self.write(root)
        path = root / ".pre-commit-config.yaml"
        text = (
            path.read_text()
            .replace(
                "  # odoo-nix:local-begin exclude\n",
                "  # odoo-nix:local-begin exclude\n  ^artifacts/|\n",
            )
            .replace(
                "  # odoo-nix:local-begin hooks\n",
                "  # odoo-nix:local-begin hooks\n  - repo: local\n    hooks:\n"
                "      - id: my-check\n        name: my-check\n        entry: true\n"
                "        language: system\n",
            )
        )
        path.write_text(text)
        self.write(root)
        kept = path.read_text()
        self.assertIn("  ^artifacts/|\n", kept)
        self.assertIn("id: my-check", kept)
        self.assertTrue(
            re.compile(yaml.safe_load(kept)["exclude"]).search("artifacts/a.eml")
        )
        self.check(root)
        # A region hook redefining a managed id is exit 2.
        path.write_text(kept.replace("id: my-check", "id: ruff"))
        code, text = self.check(root, ok=False)
        self.assertEqual(code, 2, text)
        self.assertIn("hook id ruff", text)


if __name__ == "__main__":
    unittest.main()
