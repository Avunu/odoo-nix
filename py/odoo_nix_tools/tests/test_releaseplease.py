"""The series release flow (DESIGN.md §2.2, releaseplease.py): release-please's config
and manifest rendered from the addons, the tag form release-please parses back,
``odoo-nix release sync|unreleased|package``, the PR check that keeps versions in the
release PR, and a sync of the addons fixture under ``branching = "series"``."""

from __future__ import annotations

import json
import re
import unittest
import zipfile
from pathlib import Path
from typing import Any

from odoo_nix_tools import policy, release, releaseplease
from odoo_nix_tools.product import PRODUCT
from standards_core.commands.policy import PrContext, Rules
from standards_core.common.report import ConfigError
from support import SyncCase, TempRepos, git, need_root, run_cli

ADDONS = [
    {"name": "web_b", "path": "web_b", "installable": True, "version": "18.0.2.0.1"},
    {"name": "web_a", "path": "web_a", "installable": True, "version": "18.0.1.10.0"},
    {"name": "old", "path": "old", "installable": False, "version": "18.0.1.0.0"},
]
# release-please's own tag pattern (src/util/tag-name.ts, v17).
RP_TAG = re.compile(
    r"^((?P<component>.*)(?P<separator>[^a-zA-Z0-9]))?(?P<v>v)?"
    r"(?P<version>\d+\.\d+\.\d+.*)$"
)
MANIFEST = """{
    "name": "%s",
    "version": "%s",
    "license": "AGPL-3",
    "installable": True,
}
"""


class Config(unittest.TestCase):
    def test_one_package_per_installable_addon(self) -> None:
        cfg = releaseplease.config(ADDONS, "18.0")
        self.assertEqual(list(cfg["packages"]), ["web_a", "web_b"])
        self.assertEqual(cfg["packages"]["web_a"]["component"], "web_a-18.0")
        self.assertIn("web_a/tests", cfg["packages"]["web_a"]["exclude-paths"])
        self.assertIn(
            "web_a/static/description", cfg["packages"]["web_a"]["exclude-paths"]
        )
        self.assertEqual(
            (cfg["release-type"], cfg["tag-separator"], cfg["include-v-in-tag"]),
            ("simple", ".", False),
        )
        # The release PR's title passes the commit rules (scope `release`).
        self.assertEqual(
            cfg["group-pull-request-title-pattern"], "chore(release): release ${branch}"
        )

    def test_manifest_holds_x_y_z(self) -> None:
        self.assertEqual(
            releaseplease.manifest(ADDONS, "18.0"), {"web_a": "1.10.0", "web_b": "2.0.1"}
        )

    def test_a_version_off_the_series_is_refused(self) -> None:
        bad = [{**ADDONS[0], "version": "17.0.1.0.0"}]
        with self.assertRaises(ConfigError):
            releaseplease.manifest(bad, "18.0")

    def test_release_please_parses_the_tag_back(self) -> None:
        # The tag release-please writes from the config: component, separator, x.y.z.
        for name, xyz in (("web_a", "1.10.0"), ("l10n_x_y", "12.0.3")):
            tag = f"{release.component(name, '18.0')}{release.TAG_SEPARATOR}{xyz}"
            self.assertEqual(tag, release.tag(name, f"18.0.{xyz}"))
            m = RP_TAG.match(tag)
            assert m is not None
            self.assertEqual(
                (m["component"], m["separator"], m["v"], m["version"]),
                (f"{name}-18.0", ".", None, xyz),
            )


class Sync(TempRepos):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.make_tree(
            {
                "web_a/__manifest__.py": MANIFEST % ("A", "18.0.1.10.0"),
                "web_b/__manifest__.py": MANIFEST % ("B", "18.0.2.0.1"),
                releaseplease.MANIFEST_FILE: json.dumps(
                    {"web_a": "1.11.0", "web_b": "2.0.1"}
                ),
            }
        )

    def test_writes_the_versions_that_moved(self) -> None:
        changed = releaseplease.sync(self.root, ADDONS, "18.0")
        self.assertEqual(changed, ["web_a/__manifest__.py"])
        text = (self.root / "web_a/__manifest__.py").read_text()
        self.assertEqual(text, MANIFEST % ("A", "18.0.1.11.0"))
        self.assertEqual(releaseplease.sync(self.root, ADDONS, "18.0"), [])

    def test_a_bad_version_is_refused(self) -> None:
        (self.root / releaseplease.MANIFEST_FILE).write_text('{"web_a": "1.x"}')
        with self.assertRaises(ConfigError):
            releaseplease.sync(self.root, ADDONS, "18.0")


class Unreleased(unittest.TestCase):
    def test_addons_without_a_tag_on_this_series(self) -> None:
        tags = ["web_b-18.0.2.0.0", "web_a-17.0.1.0.0", "web_a-18.0x"]
        self.assertEqual(
            releaseplease.unreleased(ADDONS, "18.0", tags),
            [("web_a", "web_a-18.0.1.10.0")],
        )

    def test_none_when_each_has_one(self) -> None:
        tags = ["web_a-18.0.1.0.0", "web_b-18.0.2.0.1"]
        self.assertEqual(releaseplease.unreleased(ADDONS, "18.0", tags), [])


class Package(TempRepos):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.make_tree(
            {
                "web_a/__manifest__.py": MANIFEST % ("A", "18.0.1.10.0"),
                "web_a/__init__.py": "",
                "web_a/static/src/a.js": "// a\n",
                "web_a/frontend/package.json": "{}\n",
                ".gitignore": "dist/\nnode_modules/\n",
            }
        )
        built = self.root / "web_a/static/dist/app.js"
        built.parent.mkdir(parents=True)
        built.write_text("// built\n")
        stray = self.root / "web_a/frontend/node_modules/x/index.js"
        stray.parent.mkdir(parents=True)
        stray.write_text("// dependency\n")
        (self.root / "web_a/__pycache__").mkdir()
        (self.root / "web_a/__pycache__/x.pyc").write_bytes(b"\0")

    def names(self, path: Path) -> list[str]:
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()

    def test_tracked_files_only_without_a_build(self) -> None:
        out = releaseplease.package(self.root, ADDONS[1], self.tmp / "dist", wheel=False)
        self.assertEqual(out.zip.name, "web_a-18.0.1.10.0.zip")
        self.assertIsNone(out.wheel)
        self.assertEqual(
            self.names(out.zip),
            [
                "web_a/__init__.py",
                "web_a/__manifest__.py",
                "web_a/frontend/package.json",
                "web_a/static/src/a.js",
            ],
        )

    def test_build_output_goes_in_and_caches_stay_out(self) -> None:
        files = releaseplease.files(self.root, "web_a", built=True)
        self.assertIn("web_a/static/dist/app.js", files)
        self.assertFalse(any("node_modules" in f or "__pycache__" in f for f in files))

    def test_the_zip_is_reproducible(self) -> None:
        first = releaseplease.package(self.root, ADDONS[1], self.tmp / "a", wheel=False)
        second = releaseplease.package(self.root, ADDONS[1], self.tmp / "b", wheel=False)
        self.assertEqual(first.zip.read_bytes(), second.zip.read_bytes())

    def test_a_wheel_needs_pyproject_build(self) -> None:
        addon = {**ADDONS[1], "whool": True}
        with self.assertRaisesRegex(Exception, "pyproject-build"):
            releaseplease.package(self.root, addon, self.tmp / "dist")


class PrCheck(TempRepos):
    """Under series a version moves in release-please's PR only."""

    def setUp(self) -> None:
        super().setUp()
        self.root = self.make_tree({"web_a/__manifest__.py": MANIFEST % ("A", "18.0.1.0.0")})
        git(self.root, "branch", "-m", "18.0")
        git(self.root, "checkout", "-q", "-b", "topic")
        (self.root / "web_a/__manifest__.py").write_text(MANIFEST % ("A", "18.0.1.1.0"))
        git(self.root, "commit", "-qam", "feat(web_a): x")
        self.head = git(self.root, "rev-parse", "HEAD").strip()

    def check(self, head_ref: str, branching: str = "series") -> list[str]:
        cfg: dict[str, Any] = {"releases": {"branching": branching}, "series": "18.0"}
        rules = Rules(
            scheme=PRODUCT.version_schemes["odoo-series"],
            cfg=cfg,
            facts={"series": "18.0"},
            integration="18.0",
        )

        def show(rev: str, path: str) -> str | None:
            try:
                return git(self.root, "show", f"{rev}:{path}")
            except Exception:
                return None

        pr = PrContext(
            root=self.root,
            base_ref="18.0",
            head_sha=self.head,
            head_ref=head_ref,
            title="feat(web_a): x",
            author="someone",
            rules=rules,
            show=show,
            changed=lambda: ["web_a/__manifest__.py"],
        )
        return policy.pr_checks(pr)

    def test_a_hand_move_is_refused(self) -> None:
        found = self.check("topic")
        self.assertEqual(len(found), 1)
        self.assertIn("release-please's release PR moves it", found[0])

    def test_the_release_pr_moves_it(self) -> None:
        self.assertEqual(self.check(release.rp_branch("18.0")), [])

    def test_release_as_is_allowed_under_series(self) -> None:
        scheme = PRODUCT.version_schemes["odoo-series"]
        text = "fix(web_a): x\n\nRelease-As: 1.2.0\n"
        self.assertEqual(
            scheme.message_problems(text, {"releases": {"branching": "series"}}, {}), []
        )
        self.assertTrue(
            scheme.message_problems(
                text, {"releases": {"branching": "develop+series"}}, {}
            )
        )


class SeriesSync(SyncCase):
    """The addons fixture under example-org with ``branching = "series"``, on 18.0."""

    def setUp(self) -> None:
        super().setUp()
        repo = need_root(self)
        profile = repo / "tests/fixtures/standards-profiles/example-org/profile.toml"
        text = profile.read_text().replace(
            'branching = "develop+series"', 'branching = "series"'
        )
        config = (repo / "tests/fixtures/standards-addons/nix/pyproject.toml").read_text()
        config = config.replace(
            'profile = "recommended"', 'profile = "./.standards-profile"'
        ).replace('["develop", "17.0"]', '["18.0", "17.0"]')
        self.root = self.profile_fixture(
            "standards-addons",
            "example-org",
            {".standards-profile/profile.toml": text, "nix/pyproject.toml": config},
        )
        git(self.root, "branch", "-m", "18.0")
        self.sync(self.root, "--write", "--offline")

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text()

    def test_release_please_files(self) -> None:
        cfg = json.loads(self.read(releaseplease.CONFIG_FILE))
        self.assertEqual(sorted(cfg["packages"]), ["fixture_a", "fixture_b"])
        self.assertEqual(cfg["packages"]["fixture_a"]["component"], "fixture_a-18.0")
        manifest = json.loads(self.read(releaseplease.MANIFEST_FILE))
        self.assertEqual(manifest["fixture_a"], "1.0.0")

    def test_the_callers_run_on_the_series_branch(self) -> None:
        workflow = self.read(".github/workflows/release.yml")
        self.assertIn("odoo-release-please.yml", workflow)
        self.assertIn('series-branch: "18.0"', workflow)
        self.assertIn('branches: ["18.0"]', self.read(".github/workflows/ci.yml"))
        self.assertIn(r"(^|/)CHANGELOG\.md$", self.read(".pre-commit-config.yaml"))

    def test_a_version_moved_without_release_please_is_drift(self) -> None:
        self.sync(self.root, "--check")
        manifest = self.root / "fixture_a/__manifest__.py"
        manifest.write_text(manifest.read_text().replace("18.0.1.0.0", "18.0.1.1.0"))
        code, _ = self.sync(self.root, "--check", ok=False)
        self.assertEqual(code, 1)

    def test_release_commands(self) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "sync")
        code, out, err = run_cli("release", "unreleased", cwd=self.root)
        self.assertEqual(code, 0, err)
        tags = sorted(item["tag"] for item in json.loads(out))
        self.assertEqual(tags[0], "fixture_a-18.0.1.0.0")
        code, out, err = run_cli("release", "sync", "--check", cwd=self.root)
        self.assertEqual((code, out.strip()), (0, ""), err)
        code, out, err = run_cli(
            "release", "package", "fixture_a", "--no-wheel", "--out",
            str(self.tmp / "dist"), cwd=self.root,
        )
        self.assertEqual(code, 0, err)
        self.assertTrue((self.tmp / "dist/fixture_a-18.0.1.0.0.zip").is_file())


if __name__ == "__main__":
    unittest.main()
