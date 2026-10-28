"""odoo-init's pieces that tests/odoo-init.sh reaches only indirectly, without
git remotes, uv or a terminal: the command line, the configuration and presets
schemas, template rendering and installing, the OCA catalogue (odoo_nix_cli.oca),
mode and series detection with their exit codes, and the prompts, with rich
stood in by a fake.

Run: python3 -I tests/test_odoo_init.py <dir holding odoo_nix_cli> <data dir> <template dir>
     (checks.odoo-init-unit)
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import unittest.mock
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, os.path.abspath(sys.argv.pop(1)))
DATA = Path(sys.argv.pop(1)).resolve()
TEMPLATE = Path(sys.argv.pop(1)).resolve()

from odoo_nix_cli import oca
from odoo_nix_cli.init import args as args_mod
from odoo_nix_cli.init import (
    command,
    config,
    detect,
    presets,
    select,
    template,
    ui,
)
from odoo_nix_cli.init.state import Run, normalize_db, normalize_name

PRESETS = {
    "18.0": {
        "label": "18.0",
        "branch": "18.0",
        "python": "python311",
        "requiresPython": ">=3.11",
    },
    "19.0": {
        "label": "19.0",
        "branch": "19.0",
        "python": "python312",
        "requiresPython": ">=3.12",
    },
}
CATALOG = [
    {
        "module": "a",
        "repo": "r-a",
        "version": "18.0.1.0.0",
        "depends": ["b", "sale"],
        "installable": True,
    },
    {
        "module": "b",
        "repo": "r-b",
        "version": "18.0.1.0.0",
        "depends": ["c", "a"],
        "installable": True,
    },
    {
        "module": "c",
        "repo": "r-c",
        "version": "18.0.1.0.0",
        "depends": [],
        "installable": True,
        "application": True,
    },
    {
        "module": "a",
        "repo": "r-a",
        "version": "19.0.1.0.0",
        "depends": [],
        "installable": True,
    },
    {
        "module": "d",
        "repo": "r-d",
        "version": "18.0.1.0.0",
        "depends": [],
        "installable": False,
    },
]
BUNDLES = {
    "one": {"label": "One", "modules": ["a", "z"]},
    "two": {"label": "Two", "modules": ["c"]},
}


class InDir(unittest.TestCase):
    """Each test in a fresh, empty working directory."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, cwd)


def run_state(argv=(), **kw):
    cfg = config.InitConfig(
        presets="",
        template=str(TEMPLATE),
        oca_dataset="",
        oca_bundles="",
        oca_sources="",
        build_deps=None,
    )
    st = Run(
        args=args_mod.parse_args(list(argv)),
        config=cfg,
        presets=presets.parse(PRESETS),
        **kw,
    )
    if st.version in st.presets:
        st.resolve_preset()
    return st


class ArgsTest(unittest.TestCase):
    def test_defaults(self):
        a = args_mod.parse_args([])
        self.assertEqual(
            (a.mode, a.target, a.version, a.commit, a.commit_msg),
            ("auto", "", "", False, None),
        )

    def test_values_both_ways(self):
        a = args_mod.parse_args(
            ["--version", "18.0", "--name=x", "--db", "d", "--bundles=a,,b", "t"]
        )
        self.assertEqual((a.version, a.name, a.db, a.target), ("18.0", "x", "d", "t"))
        self.assertEqual(a.bundles, ["a", "b"])

    def test_apps_is_modules(self):
        self.assertEqual(args_mod.parse_args(["--apps", "x,y"]).modules, ["x", "y"])

    def test_series_is_gone(self):
        for argv in (["--series", "19.0"], ["--series=18.0"]):
            with self.assertRaises(args_mod.UsageError) as cm:
                args_mod.parse_args(argv)
            self.assertIn(
                "--series is --version since odoo-nix 2.0.0", str(cm.exception)
            )
        self.assertNotIn("--series", args_mod.USAGE)

    def test_switches_and_modes(self):
        a = args_mod.parse_args(
            ["--migrate", "--force", "--dry-run", "-y", "--skip-lock"]
        )
        self.assertEqual(
            (a.mode, a.force, a.dry_run, a.assume_yes, a.skip_lock),
            ("migrate", True, True, True, True),
        )
        self.assertTrue(args_mod.parse_args(["--yes"]).assume_yes)
        self.assertEqual(args_mod.parse_args(["--init"]).mode, "init")

    def test_commit_takes_its_message_only_with_equals(self):
        a = args_mod.parse_args(["--commit", "dir"])
        self.assertEqual((a.commit, a.commit_msg, a.target), (True, None, "dir"))
        a = args_mod.parse_args(["--commit=feat: x"])
        self.assertEqual((a.commit, a.commit_msg), (True, "feat: x"))

    def test_help_stops_parsing(self):
        self.assertTrue(args_mod.parse_args(["--help", "--bogus"]).help)
        self.assertTrue(args_mod.parse_args(["-h"]).help)

    def test_usage_errors_are_1(self):
        for argv, message in (
            (["--bogus"], "unknown flag: --bogus"),
            (["--version"], "--version needs a value"),
        ):
            with self.assertRaises(args_mod.UsageError) as ctx:
                args_mod.parse_args(argv)
            self.assertEqual(ctx.exception.code, 1)
            self.assertEqual(str(ctx.exception), message)


class ConfigTest(unittest.TestCase):
    GOOD: ClassVar[dict] = {
        "presets": "/p",
        "template": "/t",
        "ocaDataset": "/d",
        "ocaBundles": "/b",
        "ocaSources": "/s",
        "buildDeps": None,
    }

    def test_good(self):
        c = config.parse(self.GOOD)
        self.assertEqual((c.oca_dataset, c.build_deps), ("/d", None))

    def test_refuses_unknown_missing_and_wrong(self):
        for data, message in (
            ({**self.GOOD, "extra": "x"}, "unknown key(s): extra"),
            (
                {k: v for k, v in self.GOOD.items() if k != "template"},
                "missing key(s): template",
            ),
            ({**self.GOOD, "presets": None}, "config.presets"),
            ([], "expected an object"),
        ):
            with self.assertRaises(config.ConfigError) as ctx:
                config.parse(data)
            self.assertIn(message, str(ctx.exception))

    def test_load_needs_the_variable(self):
        with (
            unittest.mock.patch.dict(os.environ, {}, clear=True),
            self.assertRaises(config.ConfigError) as ctx,
        ):
            config.load()
        self.assertIn(config.ENV, str(ctx.exception))


class PresetsTest(unittest.TestCase):
    def test_parse(self):
        p = presets.parse(PRESETS)
        self.assertEqual(list(p), ["18.0", "19.0"])
        self.assertEqual(
            (p["18.0"].branch, p["18.0"].pyver, p["19.0"].pyver),
            ("18.0", "3.11", "3.12"),
        )

    def test_series_is_gone(self):
        old = {
            k: {("series" if f == "branch" else f): v for f, v in e.items()}
            for k, e in PRESETS.items()
        }
        with self.assertRaises(presets.PresetError) as cm:
            presets.parse(old)
        self.assertIn("series is branch since odoo-nix 2.0.0", str(cm.exception))

    def test_optional_keys(self):
        p = presets.parse(
            {
                "x": {
                    **PRESETS["18.0"],
                    "nodejs": "nodejs_22",
                    "overrideDependencies": ["a<2"],
                }
            }
        )
        self.assertEqual(
            (p["x"].nodejs, p["x"].override_dependencies), ("nodejs_22", ("a<2",))
        )

    def test_refuses(self):
        for data in (
            {},
            [],
            {"x": []},
            {"x": {**PRESETS["18.0"], "extra": 1}},
            {"x": {k: v for k, v in PRESETS["18.0"].items() if k != "python"}},
            {"x": {**PRESETS["18.0"], "python": "pypy3"}},
            {"x": {**PRESETS["18.0"], "label": ""}},
            {"x": {**PRESETS["18.0"], "overrideDependencies": "a"}},
        ):
            with self.assertRaises(presets.PresetError, msg=repr(data)):
                presets.parse(data)


class PresetsFileTest(unittest.TestCase):
    """lib/odoo-presets.json, as shipped: the shared schema, branch not series."""

    def test_shipped(self):
        path = os.environ.get("ODOO_PRESETS")
        if not path:
            self.skipTest("ODOO_PRESETS not set")
        raw = json.loads(Path(path).read_text())
        self.assertTrue(all("branch" in e and "series" not in e for e in raw.values()))
        self.assertEqual(sorted(presets.load(path)), sorted(raw))


class NamesTest(unittest.TestCase):
    def test_name(self):
        self.assertEqual(normalize_name("Acme Shop"), "acme-shop")
        self.assertEqual(normalize_name("--a__b--"), "a-b")
        self.assertEqual(normalize_name("!!!"), "odoo-project")

    def test_db(self):
        self.assertEqual(normalize_db("acme-db"), "acme_db")
        self.assertEqual(normalize_db("__Shop DB"), "shop_db")
        self.assertEqual(normalize_db("___"), "odoo")


class TemplateTest(InDir):
    def test_substitute_is_literal_and_one_pass(self):
        values = {"@A@": "x|&\\1 @B@", "@B@": "no"}
        self.assertEqual(
            template.substitute("@A@/@B@/@C@", values), "x|&\\1 @B@/no/@C@"
        )

    def test_render(self):
        st = run_state(["--name", "x"], version="19.0", name="shop", db="shop_db")
        staging = template.render(st)
        self.addCleanup(__import__("shutil").rmtree, staging)
        flake = (staging / "flake.nix").read_text()
        self.assertIn('name = "shop";', flake)
        self.assertIn('odooSeries = "19.0";', flake)
        self.assertIn("python = pkgs.python312;", flake)
        self.assertRegex(flake, r'(?m)^\s*dbName = "shop_db";$')
        self.assertIn(
            'requires-python = ">=3.12"', (staging / "pyproject.toml").read_text()
        )
        for f in template.files(staging):
            self.assertNotRegex((staging / f).read_text(), r"@[A-Z_]+@", f)
        self.assertIn("custom/.gitkeep", template.files(staging))

    def test_install_never_overwrites(self):
        staging = self.dir / "staging"
        (staging / "sub").mkdir(parents=True)
        (staging / "new.txt").write_text("new\n")
        (staging / "kept.txt").write_text("theirs\n")
        (staging / "sub" / "f").write_text("f\n")
        (staging / ".gitignore").write_text("# head\n/.devenv/\n*.pyc\n")
        (staging / "aside").write_text("x\n")
        work = self.dir / "work"
        work.mkdir()
        os.chdir(work)
        Path("kept.txt").write_text("mine\n")
        Path(".gitignore").write_text("*.pyc")
        written = template.install(staging, skip=("aside",))
        self.assertEqual(written, [".gitignore", "new.txt", "sub/f"])
        self.assertEqual(Path("kept.txt").read_text(), "mine\n")
        self.assertFalse(Path("aside").exists())
        self.assertEqual(
            Path(".gitignore").read_text(), "*.pyc\n\n# odoo-nix\n/.devenv/\n"
        )
        # Run again: nothing left to write.
        self.assertEqual(template.install(staging), ["aside"])


class OcaTest(unittest.TestCase):
    def test_resolve_repos_follows_depends_across_repos_and_cycles(self):
        self.assertEqual(
            oca.resolve_repos(CATALOG, "18.0", ["a"]), ["r-a", "r-b", "r-c"]
        )
        self.assertEqual(oca.resolve_repos(CATALOG, "19.0", ["a"]), ["r-a"])
        self.assertEqual(oca.resolve_repos(CATALOG, "18.0", ["nope", ""]), [])

    def test_expand_bundles(self):
        warnings = []
        got = oca.expand_bundles(
            BUNDLES, CATALOG, "18.0", ["one", "two", "three"], warnings.append
        )
        self.assertEqual(got, ["a", "c"])
        self.assertEqual(
            warnings,
            [
                "unknown bundle: three   (available: one two)",
                "not available for 18.0, skipped: z",
            ],
        )
        self.assertEqual(
            oca.expand_bundles(BUNDLES, CATALOG, "19.0", [], warnings.append), []
        )

    def test_installable_order_and_search(self):
        rows = oca.installable(CATALOG, "18.0")
        self.assertEqual([m["module"] for m in rows], ["c", "a", "b"])
        self.assertEqual([m["module"] for m in oca.search(rows, "r")], ["c", "a", "b"])
        self.assertEqual([m["module"] for m in oca.search(rows, "C")], ["c"])
        self.assertEqual(oca.search(rows, "  "), [])
        self.assertTrue(oca.label(rows[0]).startswith("★ c  ·  r-c"))

    def test_urls(self):
        self.assertEqual(
            oca.repo_url("server-ux"), "https://github.com/OCA/server-ux.git"
        )
        for arg in ("https://x/y.git", "git@h:o/r.git", "o/r", "r.git"):
            self.assertTrue(oca.url_shaped(arg), arg)
        self.assertFalse(oca.url_shaped("sale_order_type"))
        self.assertEqual(oca.resolve_git_url("o/r.git"), "https://github.com/o/r.git")
        self.assertEqual(oca.resolve_git_url("git@h:o/r"), "git@h:o/r")
        for bad in ("h/o/r", "o/", "r.git"):
            with self.assertRaises(ValueError):
                oca.resolve_git_url(bad)
        self.assertEqual(oca.repo_slug("https://h/o/r/"), "r")
        self.assertEqual(oca.repo_slug("git@h:o/r.git"), "r")

    def test_scan_modules(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d, "repo")
            (root / "m1").mkdir(parents=True)
            (root / "m1" / "__manifest__.py").write_text("{}")
            (root / "x").mkdir()
            self.assertEqual(oca.scan_modules(root), ["m1"])
            (root / "__manifest__.py").write_text("{}")
            self.assertEqual(oca.scan_modules(root), ["m1", "repo"])

    def test_shipped_data(self):
        catalog = oca.load_catalog(DATA / "oca-modules.json")
        bundles = oca.load_bundles(DATA / "oca-bundles.json")
        self.assertEqual(
            oca.resolve_repos(catalog, "18.0", ["account_tax_balance"]),
            ["account-financial-reporting", "server-ux"],
        )
        warnings = []
        self.assertIn(
            "project_parent",
            oca.expand_bundles(bundles, catalog, "19.0", ["project"], warnings.append),
        )
        self.assertEqual(
            warnings,
            [
                "not available for 19.0, skipped: project_task_add_very_high project_timesheet_time_control"
            ],
        )


def git(*argv):
    subprocess.run(["git", *argv], check=True, capture_output=True)


class DetectTest(InDir):
    def manifest(self, path, version):
        Path(path).mkdir(parents=True)
        Path(path, "__manifest__.py").write_text(
            repr({"name": "x", "version": version})
        )

    def test_empty(self):
        self.assertTrue(detect.dir_is_empty("."))
        self.assertTrue(detect.dir_is_empty("missing"))
        self.assertFalse(detect.looks_like_odoo_tree())
        self.assertIsNone(detect.detect_series())

    def test_layouts(self):
        Path("custom").mkdir()
        self.assertTrue(detect.looks_like_empty_tree())
        self.manifest("modules/repo/m", "18.0.1.0.0")
        self.assertTrue(detect.looks_like_odoo_tree())
        self.assertFalse(detect.looks_like_empty_tree())

    def test_ocb_with_and_without_odoo_bin(self):
        Path("odoo").mkdir()
        self.assertFalse(detect.has_ocb())
        Path("odoo/odoo-bin").touch()
        self.assertTrue(detect.has_ocb())
        # An Enterprise tree can come without odoo-bin: the odoo package says it.
        Path("odoo/odoo-bin").unlink()
        Path("odoo/odoo").mkdir()
        Path("odoo/odoo/release.py").write_text(
            "version_info = (19, 0, 0, FINAL, 0, '')\n"
        )
        self.assertTrue(detect.has_ocb())
        self.assertTrue(detect.looks_like_odoo_tree())

    def test_series_from_manifests_most_common(self):
        self.manifest("custom/a", "18.0.1.0.0")
        self.manifest("custom/b", "18.0.2.0.0")
        self.manifest("modules/r/c", "19.0.1.0.0")
        self.manifest("modules/r/d", "1.0")
        self.assertEqual(detect.detect_series(), ("18.0", "the module manifests"))

    def test_series_from_release_then_gitmodules_then_flake(self):
        Path("odoo/odoo").mkdir(parents=True)
        Path("odoo/odoo-bin").touch()
        Path("odoo/odoo/release.py").write_text(
            "version_info = (19, 0, 0, FINAL, 0, '')\n"
        )
        self.assertEqual(detect.detect_series(), ("19.0", "odoo/odoo/release.py"))
        git("config", "-f", ".gitmodules", "submodule.core.path", "odoo")
        git("config", "-f", ".gitmodules", "submodule.core.branch", "18.0")
        self.assertEqual(detect.detect_series(), ("18.0", ".gitmodules"))
        Path("flake.nix").write_text(
            '{\n  # odooSeries = "17.0";\n  odooSeries = "19.0";\n}\n'
        )
        self.assertEqual(detect.detect_series(), ("19.0", "flake.nix"))

    def test_flake_kinds_and_values(self):
        Path("flake.nix").write_text("{ outputs = _: { }; }")
        self.assertTrue(detect.has_foreign_flake())
        Path("flake.nix").write_text(
            "  # odoo-nix.flakeModules\n"
            "  imports = [ odoo-nix.flakeModules.default ];\n"
            '    # name = "nope";\n'
            '    name = "shop";\n'
            '    dbName = "shop_db";\n'
        )
        self.assertTrue(detect.is_odoo_nix_project())
        self.assertFalse(detect.has_foreign_flake())
        self.assertEqual(
            (detect.existing_name(), detect.existing_db()), ("shop", "shop_db")
        )
        Path("flake.nix").write_text(
            'odoo-nix.lib.mkFlake\nprojectName = "old";\nodooConf.dbName = "d";\n'
        )
        self.assertEqual((detect.existing_name(), detect.existing_db()), ("old", "d"))
        for line in ('settings.dbName = "e";', 'settings.options.db_name = "e";'):
            Path("flake.nix").write_text(f"odoo-nix.lib.mkFlake\n{line}\n")
            self.assertEqual(detect.existing_db(), "e", line)

    def test_foreign_pyproject(self):
        self.assertFalse(detect.has_foreign_pyproject())
        Path("pyproject.toml").write_text("[project]\n")
        self.assertTrue(detect.has_foreign_pyproject())
        Path("pyproject.toml").write_text((TEMPLATE / "pyproject.toml").read_text())
        self.assertFalse(detect.has_foreign_pyproject())

    def test_repo_state(self):
        self.assertEqual(detect.repo_state(), "none")
        git("init", "-q", ".")
        self.assertEqual(detect.repo_state(), "own")
        Path("sub").mkdir()
        os.chdir("sub")
        self.assertEqual(detect.repo_state(), "nested")

    def test_preset_for(self):
        p = presets.parse(PRESETS)
        self.assertEqual(
            (detect.preset_for("18.0", p), detect.preset_for("16.0", p)), ("18.0", None)
        )


class DecideModeTest(InDir):
    def code(self, argv):
        st = run_state(argv)
        with unittest.mock.patch("sys.stdout", io.StringIO()):
            try:
                return command.decide_mode(st), st
            except ui.Die as e:
                return e.code, st

    def test_codes(self):
        Path("notes.txt").touch()
        self.assertEqual(self.code(["--init"])[0], 2)
        self.assertEqual(self.code(["--init", "--force"])[0], "init")
        self.assertEqual(self.code(["--migrate"])[0], 6)
        self.assertEqual(self.code(["--migrate", "--force"])[0], "migrate")
        self.assertEqual(self.code([])[0], 6)
        Path("modules").mkdir()
        self.assertEqual(self.code([])[0], 7)
        Path("modules/m").mkdir()
        Path("modules/m/__manifest__.py").write_text("{}")
        self.assertEqual(self.code([])[0], "migrate")
        Path("flake.nix").write_text("{ }")
        self.assertEqual(self.code([])[0], 4)
        Path("flake.nix").write_text("odoo-nix.flakeModules.default")
        mode, st = self.code([])
        self.assertEqual((mode, st.repair), ("migrate", True))


class FakeRich:
    """rich.prompt and rich.console, answering from a list."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []
        fake = self

        class Prompt:
            @staticmethod
            def ask(question, **kw):
                fake.asked.append(question)
                return fake.answers.pop(0)

        class Confirm(Prompt):
            pass

        class Console:
            def __init__(self, **kw):
                pass

            def print(self, *a, **kw):
                pass

        self.modules = {
            "rich": types.ModuleType("rich"),
            "rich.prompt": types.SimpleNamespace(Prompt=Prompt, Confirm=Confirm),
            "rich.console": types.SimpleNamespace(Console=Console),
        }

    def __enter__(self):
        self.patch = unittest.mock.patch.dict(sys.modules, self.modules)
        self.patch.__enter__()
        return self

    def __exit__(self, *exc):
        self.patch.__exit__(*exc)


class PromptsTest(unittest.TestCase):
    OPTIONS: ClassVar[list] = [("18.0", "eighteen"), ("19.0", "nineteen")]

    def test_choose_by_number_or_name_and_retries(self):
        with FakeRich(["9", "2"]):
            self.assertEqual(ui.choose("h", self.OPTIONS), "19.0")
        with FakeRich(["18.0"]):
            self.assertEqual(ui.choose("h", self.OPTIONS), "18.0")

    def test_choose_many(self):
        with FakeRich(["1 nope", "2,18.0"]):
            self.assertEqual(ui.choose_many("h", self.OPTIONS), ["19.0", "18.0"])
        with FakeRich([""]):
            self.assertEqual(ui.choose_many("h", self.OPTIONS), [])

    def test_confirm_is_no_without_a_terminal(self):
        with unittest.mock.patch.object(ui, "has_tty", return_value=False):
            self.assertFalse(ui.confirm("q"))
        with (
            unittest.mock.patch.object(ui, "has_tty", return_value=True),
            FakeRich([True]),
        ):
            self.assertTrue(ui.confirm("q", default=False))

    def test_pick_modules_searches_until_empty(self):
        with (
            FakeRich(["r-", "1,3", "zzz", "c", "1", ""]) as fake,
            unittest.mock.patch("sys.stdout", io.StringIO()),
        ):
            self.assertEqual(select.pick_modules(CATALOG, "18.0"), ["c", "b"])
        self.assertEqual(sum("Search" in q for q in fake.asked), 4)

    def test_select_prompts_only_with_a_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "m.json").write_text(json.dumps(CATALOG))
            Path(d, "b.json").write_text(json.dumps(BUNDLES))
            st = run_state([], version="18.0")
            st.config = config.InitConfig(
                presets="",
                template="",
                oca_dataset=f"{d}/m.json",
                oca_bundles=f"{d}/b.json",
                oca_sources="",
                build_deps=None,
            )
            with unittest.mock.patch.object(ui, "has_tty", return_value=False):
                select.select(st, prompt=True)
            self.assertEqual((st.bundles, st.modules, st.repos), ([], [], []))
            # bundles? yes → "two"; modules? yes → search "a", pick 1, done.
            answers = [True, "2", True, "a", "1", ""]
            with (
                unittest.mock.patch.object(ui, "has_tty", return_value=True),
                FakeRich(answers),
                unittest.mock.patch("sys.stdout", io.StringIO()),
            ):
                select.select(st, prompt=True)
            self.assertEqual(
                (st.bundles, st.modules, st.repos),
                (["two"], ["a", "c"], ["r-a", "r-b", "r-c"]),
            )

    def test_require_version(self):
        st = run_state([])
        with (
            unittest.mock.patch.object(ui, "has_tty", return_value=False),
            self.assertRaises(ui.Die) as ctx,
        ):
            select.require_version(st)
        self.assertEqual(ctx.exception.code, 5)
        st = run_state([], version="17.0")
        with self.assertRaises(ui.Die) as ctx:
            select.require_version(st)
        self.assertEqual(ctx.exception.code, 5)
        st = run_state([])
        with (
            unittest.mock.patch.object(ui, "has_tty", return_value=True),
            FakeRich(["2"]),
        ):
            select.require_version(st)
        self.assertEqual(st.p.python, "python312")


class MainTest(InDir):
    def main(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with (
            unittest.mock.patch("sys.stdout", out),
            unittest.mock.patch("sys.stderr", err),
            unittest.mock.patch.dict(os.environ, env or {}),
        ):
            rc = command.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_help_and_usage_errors_need_no_config(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            rc, out, _ = self.main(["--help"])
            self.assertEqual(rc, 0)
            self.assertTrue(out.startswith("Usage: odoo-init"))
            rc, _, err = self.main(["--bogus"])
            self.assertEqual(rc, 1)
            self.assertIn("ERROR: unknown flag: --bogus", err)

    def test_no_config(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            rc, _, err = self.main([])
        self.assertEqual(rc, 1)
        self.assertIn(config.ENV, err)

    def test_migrate_on_nothing_is_1(self):
        cfg = self.dir / "c.json"
        p = self.dir / "p.json"
        p.write_text(json.dumps(PRESETS))
        cfg.write_text(json.dumps({**ConfigTest.GOOD, "presets": str(p)}))
        rc, _, err = self.main(
            ["--migrate", "--version", "18.0", "nowhere"], {config.ENV: str(cfg)}
        )
        self.assertEqual(rc, 1)
        self.assertIn("nothing to migrate", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
