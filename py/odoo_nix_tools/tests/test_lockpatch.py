"""``odoo-nix verify-patch`` (odoo_nix_tools.lockpatch): what relock-push and
project-update accept from a plan job's patch before they mint the CI App's token. Each
case stages a change in a real git index and checks it against HEAD."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from odoo_nix_tools import lockpatch
from support import run_cli

PYPROJECT = """\
[project]
name = "acme-addons"
dependencies = [
    # >>> odoo-nix: install set (managed from modules.txt) >>>
    "odoo",
    # <<< odoo-nix: install set <<<
]

[tool.uv.sources]
# >>> odoo-nix: module sources (managed) >>>
    odoo = { path = "../.odoo-nix/odoo" }
# <<< odoo-nix: module sources <<<

[tool.uv.extra-build-dependencies]
# >>> odoo-nix: sdist build deps (managed) >>>
"odoo" = ["setuptools"]
# <<< odoo-nix: sdist build deps (managed) <<<
"""

FILES = "https://files.pythonhosted.org/packages/aa/bb"


def pkg(name: str, version: str, source: str, *dists: str) -> str:
    text = f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {source}\n'
    for kind, url, digest in (d.split("|") for d in dists):
        if kind == "sdist":
            text += f'sdist = {{ url = "{url}", hash = "sha256:{digest}" }}\n'
        else:
            text += f'wheels = [{{ url = "{url}", hash = "sha256:{digest}" }}]\n'
    return text + "\n"


PYPI = '{ registry = "https://pypi.org/simple" }'
UV_LOCK = (
    'version = 1\nrevision = 3\nrequires-python = ">=3.12"\n\n'
    + pkg("odoo", "18.0", '{ directory = "../.odoo-nix/odoo" }')
    + pkg("acme-addons", "0", '{ virtual = "." }')
    + pkg(
        "babel",
        "2.17.0",
        PYPI,
        f"sdist|{FILES}/babel-2.17.0.tar.gz|11",
        f"wheel|{FILES}/babel-2.17.0-py3-none-any.whl|12",
    )
    + pkg(
        "legacy",
        "1.0",
        '{ git = "https://github.com/acme/legacy?rev=abc#abc" }',
    )
)


def sh(root: Path, *args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
        input=stdin,
    ).stdout


class Case(unittest.TestCase):
    kind = "relock"
    base: ClassVar[dict[str, str]] = {
        "nix/pyproject.toml": PYPROJECT,
        "nix/uv.lock": UV_LOCK,
        "flake.lock": "{}\n",
        ".github/workflows/ci.yml": "name: ci\n",
    }

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        sh(self.root, "init", "-q")
        for path, text in self.base.items():
            self.write(path, text)
        sh(self.root, "add", "-A")
        self.extra_base()
        sh(self.root, "commit", "-qm", "base")

    def extra_base(self) -> None:
        pass

    def write(self, path: str, text: str, mode: int = 0o644) -> None:
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text)
        os.chmod(full, mode)

    def edit(self, path: str, old: str, new: str) -> None:
        full = self.root / path
        text = full.read_text()
        self.assertIn(old, text)
        full.write_text(text.replace(old, new, 1))

    def problems(self) -> list[str]:
        sh(self.root, "add", "-A")
        return lockpatch.verify(self.root, "HEAD", lockpatch.KINDS[self.kind])

    def assertPasses(self) -> None:
        self.assertEqual(self.problems(), [])

    def assertRefused(self, *needles: str) -> None:
        found = self.problems()
        self.assertTrue(found, "accepted")
        text = "\n".join(found)
        for needle in needles:
            self.assertIn(needle, text)


class Relock(Case):
    def test_an_honest_relock(self) -> None:
        self.edit(
            "nix/pyproject.toml", '    "odoo",\n', '    "odoo",\n    "jsonpath_ng",\n'
        )
        self.edit(
            "nix/pyproject.toml",
            '"odoo" = ["setuptools"]\n',
            '"docopt" = ["setuptools"]\n"odoo" = ["setuptools"]\n',
        )
        self.edit(
            "nix/pyproject.toml",
            '    odoo = { path = "../.odoo-nix/odoo" }\n',
            '    odoo = { path = "../.odoo-nix/odoo" }\n'
            '    "odoo-addon-x" = { path = "../.odoo-nix/external/oca/x", editable = true }\n',
        )
        lock = (self.root / "nix/uv.lock").read_text()
        lock = lock.replace("babel-2.17.0", "babel-2.18.0").replace(
            '"2.17.0"', '"2.18.0"'
        )
        lock += pkg(
            "jsonpath-ng",
            "1.7.0",
            PYPI,
            f"sdist|{FILES}/jsonpath-ng-1.7.0.tar.gz|21",
            f"wheel|{FILES}/jsonpath_ng-1.7.0-py3-none-any.whl|22",
        )
        lock += pkg(
            "odoo-addon-x", "18.0.1.0.0", '{ editable = "../.odoo-nix/external/oca/x" }'
        )
        self.write("nix/uv.lock", lock)
        self.assertPasses()

    def test_cli(self) -> None:
        self.edit("nix/uv.lock", "revision = 3", "revision = 4")
        sh(self.root, "add", "-A")
        code, out, _ = run_cli("verify-patch", "relock", "--root", str(self.root))
        self.assertEqual(code, 0, out)
        self.edit("nix/uv.lock", "revision = 4", 'revision = 4\n[x]\ny = "z"')
        self.write("flake.lock", '{"x": 1}\n')
        sh(self.root, "add", "-A")
        code, out, _ = run_cli("verify-patch", "relock", "--root", str(self.root))
        self.assertEqual(code, 1, out)
        self.assertIn("::error title=verify-patch::flake.lock: not a path", out)

    # Entries.
    def test_nothing(self) -> None:
        self.assertRefused("changes nothing")

    def test_other_paths(self) -> None:
        for path in (
            "flake.lock",
            ".github/workflows/ci.yml",
            "nix/x.sh",
            "pyproject.toml",
        ):
            with self.subTest(path=path):
                sh(self.root, "reset", "-q", "--hard")
                self.write(path, "x\n")
                self.assertRefused(path)

    def test_deleted_lock(self) -> None:
        (self.root / "nix/uv.lock").unlink()
        self.assertRefused("nix/uv.lock: D")

    def test_executable(self) -> None:
        os.chmod(self.root / "nix/uv.lock", 0o755)
        self.assertRefused("100755")

    def test_symlink(self) -> None:
        (self.root / "nix/uv.lock").unlink()
        os.symlink("/etc/passwd", self.root / "nix/uv.lock")
        self.assertRefused("120000")

    def test_paths(self) -> None:
        for path, why in (
            ("a/../b", "`..`"),
            ("a/.git/config", ".git"),
            ("/etc/x", "absolute"),
            ("a\tb", "control"),
            (".github/x", ".github"),
        ):
            with self.subTest(path=path):
                self.assertIn(why, lockpatch.path_problem(path) or "")
        self.assertIsNone(lockpatch.path_problem("nix/uv.lock"))

    # pyproject.toml.
    def test_outside_the_blocks(self) -> None:
        self.edit("nix/pyproject.toml", 'name = "acme-addons"', 'name = "acme"')
        self.assertRefused("outside odoo-nix's managed blocks")

    def test_moved_sentinel(self) -> None:
        self.edit(
            "nix/pyproject.toml",
            "    # <<< odoo-nix: install set <<<\n]\n",
            "]\n    # <<< odoo-nix: install set <<<\n",
        )
        self.assertRefused("outside")

    def test_second_block(self) -> None:
        with (self.root / "nix/pyproject.toml").open("a") as f:
            f.write(
                "# >>> odoo-nix: module sources (managed) >>>\n"
                "# <<< odoo-nix: module sources <<<\n"
            )
        self.assertRefused("twice")

    def test_module_source_outside_the_repository(self) -> None:
        for path in ("/nix/store/x", "../../x", "https://e.example/x", "../.git/x"):
            with self.subTest(path=path):
                sh(self.root, "reset", "-q", "--hard")
                self.edit(
                    "nix/pyproject.toml",
                    '../.odoo-nix/odoo" }',
                    f'../.odoo-nix/odoo" }}\n    y = {{ path = "{path}" }}',
                )
                self.assertRefused("outside the repository")

    def test_module_source_not_a_path(self) -> None:
        self.edit(
            "nix/pyproject.toml",
            '../.odoo-nix/odoo" }',
            '../.odoo-nix/odoo" }\n    y = { git = "https://e.example/y" }',
        )
        self.assertRefused("not a path source")

    def test_install_set_url(self) -> None:
        self.edit(
            "nix/pyproject.toml",
            '    "odoo",\n',
            '    "odoo",\n    "x @ https://e.example/x.whl",\n',
        )
        self.assertRefused("direct URL")

    def test_install_set_breaks_out(self) -> None:
        # Closes the array and opens tables of its own: every line between the
        # sentinels, text outside them unchanged.
        self.edit(
            "nix/pyproject.toml",
            '    "odoo",\n',
            '    "odoo",\n'
            '    "evil @ https://evil.example/evil-1.0-py3-none-any.whl",\n'
            "]\n"
            "[tool.odoo-nix.ci.submodule-app]\n"
            'app-id = "AVUNU_CI_APP_ID"\n'
            'private-key = "AVUNU_CI_PRIVATE_KEY"\n'
            "[tool.odoo-nix.dependabot]\n"
            'auto-merge-policy = "all"\n'
            "[tool.zz]\n"
            "x = [\n",
        )
        self.assertRefused(
            "direct URL", "not one quoted requirement", "parsed, differs"
        )

    def test_install_set_escapes(self) -> None:
        for line in (
            r'    "evil \u0040 https://evil.example/evil.whl",',
            r'    "evil\u0022, \u0022x",',
            "    'evil @ https://evil.example/evil.whl',",
            '    "odoo", "evil",',
        ):
            with self.subTest(line=line):
                sh(self.root, "reset", "-q", "--hard")
                self.edit(
                    "nix/pyproject.toml", '    "odoo",\n', f'    "odoo",\n{line}\n'
                )
                self.assertRefused("install set")

    def test_install_set_markers(self) -> None:
        self.edit(
            "nix/pyproject.toml",
            '    "odoo",\n',
            '    "odoo",\n    "paramiko<4",\n'
            '    "pywin32; sys_platform == \'win32\'",\n    "requests[socks]>=2",\n',
        )
        self.assertPasses()

    def test_parsed_sources(self) -> None:
        self.assertEqual(
            lockpatch._parsed_problems(
                "p",
                '[tool.uv.sources]\nodoo = { path = "odoo" }\n',
                '[tool.uv.sources]\nodoo = { path = "odoo" }\n'
                'x = { git = "https://e.example/x" }\n'
                'y = { path = "/nix/store/y" }\n',
                "",
            ),
            [
                "p: tool.uv.sources.x: not a path source",
                "p: tool.uv.sources.y: '/nix/store/y' is outside the repository",
            ],
        )

    def test_parsed_index(self) -> None:
        found = lockpatch._parsed_problems(
            "p",
            "[project]\ndependencies = []\n",
            "[project]\ndependencies = []\n"
            '[[tool.uv.index]]\nurl = "https://e.example/simple"\n',
            "",
        )
        self.assertEqual(len(found), 1)
        self.assertIn("parsed, differs", found[0])

    def test_parsed_build_deps(self) -> None:
        self.assertEqual(
            lockpatch._parsed_problems(
                "p",
                '[tool.uv.extra-build-dependencies]\nx = ["setuptools"]\n',
                '[tool.uv.extra-build-dependencies]\nx = ["setuptools"]\n'
                'y = ["setuptools", "evil"]\nz = { a = 1 }\n',
                "",
            ),
            [
                "p: tool.uv.extra-build-dependencies.y: grants evil",
                "p: tool.uv.extra-build-dependencies.z: not a list of names",
            ],
        )

    def test_build_dependency(self) -> None:
        self.edit(
            "nix/pyproject.toml",
            '"odoo" = ["setuptools"]',
            '"odoo" = ["setuptools", "evil"]',
        )
        self.assertRefused("grants evil")

    # uv.lock.
    def test_sources(self) -> None:
        for source in (
            '{ git = "https://e.example/x?rev=1#1" }',
            '{ registry = "https://e.example/simple" }',
            '{ url = "https://e.example/x-1.0.tar.gz" }',
            '{ directory = "/nix/store/x" }',
            '{ editable = "../../x" }',
        ):
            with self.subTest(source=source):
                sh(self.root, "reset", "-q", "--hard")
                with (self.root / "nix/uv.lock").open("a") as f:
                    f.write(pkg("x", "1.0", source))
                self.assertRefused("x comes from")

    def test_base_source(self) -> None:
        self.edit("nix/uv.lock", 'version = "1.0"', 'version = "1.1"')
        self.assertPasses()

    def test_files(self) -> None:
        for url, why in (
            (
                "https://e.example/packages/babel-2.17.0.tar.gz",
                "not on files.pythonhosted.org",
            ),
            (
                "http://files.pythonhosted.org/p/babel-2.17.0.tar.gz",
                "not on files.pythonhosted.org",
            ),
            (f"{FILES}/evil-2.17.0.tar.gz", "not a file of that package"),
            (f"{FILES}/babel-2.16.0.tar.gz", "not a file of that package"),
            (f"{FILES}/evil-2.17.0-py3-none-any.whl", "not a file of that package"),
        ):
            with self.subTest(url=url):
                sh(self.root, "reset", "-q", "--hard")
                self.edit("nix/uv.lock", f"{FILES}/babel-2.17.0.tar.gz", url)
                self.assertRefused(why)

    def test_wheel_names_normalised(self) -> None:
        with (self.root / "nix/uv.lock").open("a") as f:
            f.write(
                pkg(
                    "Zope.Interface",
                    "7.0",
                    PYPI,
                    f"sdist|{FILES}/zope_interface-7.0.tar.gz|1",
                    f"wheel|{FILES}/zope.interface-7.0-cp312-cp312-manylinux_x86_64.whl|2",
                )
            )
        self.assertPasses()

    def test_hash_of_a_base_file(self) -> None:
        self.edit("nix/uv.lock", "sha256:11", "sha256:99")
        self.assertRefused("another hash")

    def test_another_package_file(self) -> None:
        # babel's sdist, claimed by another package.
        with (self.root / "nix/uv.lock").open("a") as f:
            f.write(pkg("x", "2.17.0", PYPI, f"sdist|{FILES}/babel-2.17.0.tar.gz|11"))
        self.assertRefused("not a file of that package")

    def test_not_toml(self) -> None:
        self.edit("nix/uv.lock", "version = 1", "version = = 1")
        self.assertRefused("not TOML")


class ProjectUpdate(Case):
    kind = "project-update"
    base: ClassVar[dict[str, str]] = {
        "pyproject.toml": PYPROJECT.replace("../.odoo-nix/odoo", "odoo"),
        "uv.lock": UV_LOCK.replace("../.odoo-nix/odoo", "odoo"),
        ".gitmodules": (
            '[submodule "modules/oca/web"]\n\tpath = modules/oca/web\n'
            "\turl = https://github.com/OCA/web\n\tbranch = 18.0\n"
        ),
    }

    def extra_base(self) -> None:
        self.gitlink("modules/oca/web", "1" * 40)

    def gitlink(self, path: str, sha: str) -> None:
        sh(self.root, "update-index", "--add", "--cacheinfo", f"160000,{sha},{path}")

    def problems(self) -> list[str]:
        # No `add -A`: the submodule has no work tree here; the index is the patch.
        sh(self.root, "add", "--", "pyproject.toml", "uv.lock", ".gitmodules")
        return lockpatch.verify(self.root, "HEAD", lockpatch.KINDS[self.kind])

    def test_submodule_moved_and_relocked(self) -> None:
        self.gitlink("modules/oca/web", "2" * 40)
        self.edit(
            "pyproject.toml", '    "odoo",\n', '    "odoo",\n    "odoo-addon-web_x",\n'
        )
        self.edit(
            "pyproject.toml",
            '    odoo = { path = "odoo" }\n',
            '    odoo = { path = "odoo" }\n'
            '    "odoo-addon-web_x" = { path = "modules/oca/web/web_x", editable = true }\n',
        )
        with (self.root / "uv.lock").open("a") as f:
            f.write(
                pkg(
                    "odoo-addon-web-x",
                    "18.0.1.0.0",
                    '{ editable = "modules/oca/web/web_x" }',
                )
            )
        self.assertPasses()

    def test_unregistered_gitlink(self) -> None:
        self.gitlink("modules/oca/evil", "3" * 40)
        self.assertRefused("modules/oca/evil: not a path")

    def test_gitmodules(self) -> None:
        self.gitlink("modules/oca/web", "2" * 40)
        self.edit(".gitmodules", "https://github.com/OCA/web", "https://e.example/web")
        self.assertRefused(".gitmodules: not a path")

    def test_gitlink_to_a_file(self) -> None:
        sh(self.root, "rm", "-q", "--cached", "modules/oca/web")
        self.write("modules/oca/web", "x\n")
        sh(self.root, "add", "modules/oca/web")
        self.assertRefused("a submodule may only move")

    # The branch tips (`--tips`).
    def tips(self, tips: dict[str, str]) -> list[str]:
        sh(self.root, "add", "--", "pyproject.toml", "uv.lock", ".gitmodules")
        asked: list[tuple[str, str]] = []

        def read_tip(url: str, ref: str) -> str | None:
            asked.append((url, ref))
            return tips.get(f"{url} {ref}")

        out = lockpatch.verify(
            self.root,
            "HEAD",
            lockpatch.KINDS[self.kind],
            tips=True,
            superproject="https://github.com/acme/project",
            read_tip=read_tip,
        )
        self.asked = asked
        return out

    def test_tip(self) -> None:
        self.gitlink("modules/oca/web", "2" * 40)
        tip = {"https://github.com/OCA/web refs/heads/18.0": "2" * 40}
        self.assertEqual(self.tips(tip), [])
        self.assertEqual(
            self.asked, [("https://github.com/OCA/web", "refs/heads/18.0")]
        )

    def test_not_the_tip(self) -> None:
        # A fork's pull-request commit, or an older one: GitHub serves both by SHA.
        self.gitlink("modules/oca/web", "2" * 40)
        tip = {"https://github.com/OCA/web refs/heads/18.0": "4" * 40}
        found = self.tips(tip)
        self.assertEqual(len(found), 1)
        self.assertIn(
            "and the tip of 18.0 at https://github.com/OCA/web is 4444", found[0]
        )

    def test_unreadable_tip(self) -> None:
        self.gitlink("modules/oca/web", "2" * 40)
        self.assertIn("could not read refs/heads/18.0", "\n".join(self.tips({})))

    def test_no_branch(self) -> None:
        self.edit(".gitmodules", "\tbranch = 18.0\n", "")
        sh(self.root, "add", ".gitmodules")
        sh(self.root, "commit", "-qm", "no branch")
        self.gitlink("modules/oca/web", "2" * 40)
        self.assertIn("no branch", "\n".join(self.tips({})))
        self.assertEqual(self.asked, [])

    def test_remote_urls(self) -> None:
        sup = "https://github.com/acme/project"
        for url, want in (
            ("https://github.com/OCA/web", "https://github.com/OCA/web"),
            ("git@github.com:acme/studio.git", "https://github.com/acme/studio.git"),
            ("ssh://git@github.com/acme/studio", "https://github.com/acme/studio"),
            ("../studio.git", "https://github.com/acme/studio.git"),
            ("./sub", "https://github.com/acme/project/sub"),
            ("file:///etc", None),
            ("ext::sh -c x", None),
            ("http://github.com/OCA/web", None),
            ("https://u:p@github.com/OCA/web", None),
            ("/srv/web", None),
        ):
            with self.subTest(url=url):
                self.assertEqual(lockpatch.remote_url(url, sup), want)
        self.assertIsNone(lockpatch.remote_url("../x", ""))

    def test_ls_remote(self) -> None:
        remote = self.root / "remote"
        sh(self.root, "init", "-q", "--bare", str(remote))
        work = self.root / "work"
        sh(self.root, "clone", "-q", str(remote), str(work))
        sh(work, "commit", "-q", "--allow-empty", "-m", "x")
        sh(work, "push", "-q", "origin", "HEAD:refs/heads/18.0")
        head = sh(work, "rev-parse", "HEAD").strip()
        self.assertEqual(
            lockpatch.ls_remote(f"file://{remote}", "refs/heads/18.0"), head
        )
        self.assertIsNone(lockpatch.ls_remote(f"file://{remote}", "refs/heads/17.0"))
        self.assertIsNone(
            lockpatch.ls_remote(f"file://{self.root}/none", "refs/heads/x")
        )

    def test_nix_lock_is_not_this_kind(self) -> None:
        self.write("nix/uv.lock", "version = 1\n")
        sh(self.root, "add", "nix/uv.lock")
        self.assertRefused("nix/uv.lock: not a path")


if __name__ == "__main__":
    unittest.main()
