"""``odoo-nix ratchet coverage`` (DESIGN.md §6.3, §7.2 test_ratchet): R1 (fail_under never
falls), R2 (untested never grows), the base that has not opted in, and ``--raise``, which
never lowers."""

from __future__ import annotations

import os

from support import SyncCase, git, run_cli

TOOLS = "tools/pyproject.toml"


def tools_text(fail_under: float | None) -> str:
    text = '# odoo-nix:managed\n[project]\nname = "tools"\n\n[tool.coverage.run]\nbranch = true\n'
    if fail_under is not None:
        text += f"\n[tool.coverage.report]\nfail_under = {fail_under}  # raised by hand\nshow_missing = true\n"
    return text


class Ratchet(SyncCase):
    def setUp(self) -> None:
        super().setUp()
        self.root = self.profile_fixture(
            "standards-project", "recommended", {TOOLS: tools_text(40)}
        )
        self.base = git(self.root, "rev-parse", "HEAD").strip()
        os.environ.pop("GITHUB_ACTIONS", None)

    def ratchet(self, *argv: str) -> tuple[int, str]:
        code, out, err = run_cli("ratchet", "coverage", *argv, cwd=self.root)
        return code, out + err

    def commit(self, rel: str, text: str) -> None:
        (self.root / rel).write_text(text)
        git(self.root, "commit", "-q", "-am", "change")

    def untested(self, *names: str) -> None:
        config = self.root / "pyproject.toml"
        rows = "".join(
            f'[[tool.odoo-nix.untested]]\naddon = "{n}"\nreason = "x"\n' for n in names
        )
        text = config.read_text()
        head, _, _ = text.partition("\n[[tool.odoo-nix.untested]]")
        self.commit("pyproject.toml", head.rstrip("\n") + "\n\n" + rows)

    def test_unchanged_and_raised_pass(self) -> None:
        self.assertEqual(self.ratchet("--base", self.base)[0], 0)
        self.commit(TOOLS, tools_text(55))
        code, out = self.ratchet("--base", self.base)
        self.assertEqual(code, 0, out)
        self.assertIn("ok", out)

    def test_r1_fail_under_fell(self) -> None:
        self.commit(TOOLS, tools_text(35))
        code, out = self.ratchet("--base", self.base)
        self.assertEqual(code, 1, out)
        self.assertEqual(
            out.strip(),
            "tools/pyproject.toml: [tool.coverage.report] fail_under fell from 40 to 35:"
            " the coverage floor only rises",
        )
        self.commit(TOOLS, tools_text(None))
        code, out = self.ratchet("--base", self.base)
        self.assertEqual(code, 1, out)
        self.assertIn("from 40 to 0", out)

    def test_r2_untested_grew(self) -> None:
        self.untested("fixture_sale")
        code, out = self.ratchet("--base", self.base)
        self.assertEqual(code, 1, out)
        self.assertTrue(
            out.startswith(
                "pyproject.toml: [[tool.odoo-nix.untested]] gained fixture_sale:"
            ),
            out,
        )
        # Once the base has it, it is no longer new; removing it always passes.
        base = git(self.root, "rev-parse", "HEAD").strip()
        self.assertEqual(self.ratchet("--base", base)[0], 0)
        self.untested()
        self.assertEqual(self.ratchet("--base", base)[0], 0)

    def test_base_not_opted_in(self) -> None:
        config = self.root / "pyproject.toml"
        text = config.read_text()
        self.commit("pyproject.toml", text.partition("[tool.odoo-nix]")[0])
        base = git(self.root, "rev-parse", "HEAD").strip()
        self.commit("pyproject.toml", text)
        self.commit(TOOLS, tools_text(0))
        code, out = self.ratchet("--base", base)
        self.assertEqual(code, 0, out)
        self.assertIn("the adoption sets the start", out)

    def test_bad_base(self) -> None:
        self.assertEqual(self.ratchet("--base", "no-such-rev")[0], 3)
        self.assertEqual(self.ratchet()[0], 2)

    def test_raise(self) -> None:
        code, out = self.ratchet("--raise", "--total", "52.9")
        self.assertEqual(code, 0, out)
        self.assertIn("fail_under 40 → 52 (measured 52.9)", out)
        self.assertEqual((self.root / TOOLS).read_text(), tools_text(52))

    def test_raise_never_lowers(self) -> None:
        for total in ("39.99", "40.5"):
            with self.subTest(total=total):
                code, out = self.ratchet("--raise", "--total", total)
                self.assertEqual(code, 0, out)
                self.assertIn("fail_under stays 40", out)
                self.assertEqual((self.root / TOOLS).read_text(), tools_text(40))

    def test_raise_measures_with_the_locked_coverage(self) -> None:
        bin_dir = self.root / "tools/.venv/bin"
        bin_dir.mkdir(parents=True)
        cov = bin_dir / "coverage"
        cov.write_text(
            '#!/bin/sh\necho "$COVERAGE_FILE $*" > "$(dirname "$0")/argv"\necho 61.25\n'
        )
        cov.chmod(0o755)
        os.environ.pop("COVERAGE_FILE", None)
        code, out = self.ratchet("--raise")
        self.assertEqual(code, 0, out)
        self.assertIn("fail_under 40 → 61", out)
        self.assertEqual(
            (bin_dir / "argv").read_text().split(),
            [
                str(self.root / ".odoo-nix/coverage/.coverage"),
                "report",
                "--rcfile=tools/pyproject.toml",
                "--format=total",
                "--precision=2",
            ],
        )

    def test_raise_reads_the_total_under_fail_under(self) -> None:
        # Under fail_under, coverage prints the total, then a failure line, and exits 2.
        bin_dir = self.root / "tools/.venv/bin"
        bin_dir.mkdir(parents=True)
        cov = bin_dir / "coverage"
        cov.write_text(
            "#!/bin/sh\necho 31.50\n"
            "echo 'Coverage failure: total of 31.50 is less than fail-under=40.00'\n"
            "exit 2\n"
        )
        cov.chmod(0o755)
        code, out = self.ratchet("--raise")
        self.assertEqual(code, 0, out)
        self.assertIn("fail_under stays 40", out)
        self.assertEqual((self.root / TOOLS).read_text(), tools_text(40))

    def test_raise_without_tools(self) -> None:
        (self.root / TOOLS).unlink()
        self.assertEqual(self.ratchet("--raise", "--total", "50")[0], 2)
