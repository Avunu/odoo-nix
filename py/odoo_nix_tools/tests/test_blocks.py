"""The other two sentinel blocks (DESIGN.md §3.1): ``.gitignore``'s ``dev-shell`` block,
which absorbs the same lines written by hand, on representative files
(``tests/shapes/gitignore``: two project checkouts' and edi-addons'), and the root
``README.md``'s optional ``addons-table`` block.

``absorb`` takes the hand-written lines the block holds and, with core CR4, a comment
paragraph left with nothing under it; every other line stays where it is.
"""

from __future__ import annotations

from pathlib import Path

from support import PRODUCT, SHAPES, SyncCase, need_root

BEGIN = "# >>> odoo-nix: dev-shell (managed) >>>"
END = "# <<< odoo-nix: dev-shell (managed) <<<"
BODY = [
    "/odoo.conf",
    "/odools.toml",
    "/.venv",
    "/.devenv/",
    "/.direnv/",
    "/.odoo-nix/",
    "/tools/.venv",
    "/tools/.bin",
    "/node_modules",
    "/result",
    "/result-*",
    "__pycache__/",
    "*.py[cod]",
]
# shape → (fixture, product, lines that must stay outside the block)
GITIGNORE = {
    "edi-addons": (
        "standards-addons",
        PRODUCT,
        ["*.egg-info/", "node_modules/", ".ruff_cache/"],
    ),
    "project-a": (
        "standards-project",
        PRODUCT,
        ["odoo.log", "docs/.obsidian", "/.odoo-nix-backup/"],
    ),
    "project-b": ("standards-project", PRODUCT, ["/notes/"]),
}


def split(text: str) -> tuple[list[str], list[str]]:
    """(the block's body lines, every line outside it)."""
    lines = text.splitlines()
    begin, end = lines.index(BEGIN), lines.index(END)
    return lines[begin + 1 : end], lines[:begin] + lines[end + 1 :]


class Gitignore(SyncCase):
    def test_real_shapes(self) -> None:
        need_root(self)
        for name, (fixture, product, kept) in GITIGNORE.items():
            with self.subTest(shape=name):
                before = (SHAPES / "gitignore" / f"{name}.gitignore").read_text()
                root = self.profile_fixture(fixture, "minimal", {".gitignore": before})
                self.write(root, product=product)
                after = (root / ".gitignore").read_text()
                body, outside = split(after)
                self.assertEqual(body, BODY)
                for line in kept:
                    self.assertIn(line, outside)
                # Nothing the block holds is left outside it, and no line was added.
                self.assertFalse(set(BODY) & {line.strip() for line in outside})
                self.assertLessEqual(
                    {line for line in outside if line.strip()},
                    {line for line in before.splitlines() if line.strip()},
                )
                self.commit(root)
                self.write(root, product=product)
                self.assertEqual((root / ".gitignore").read_text(), after)
                self.check(root, product=product)

    def test_emptied_comment_paragraphs_go(self) -> None:
        """edi-addons' two comment paragraphs ("# odoo-nix addons mode: links …",
        "# devenv state: …") head only lines the block absorbs (core CR4)."""
        before = (SHAPES / "gitignore" / "edi-addons.gitignore").read_text()
        self.assertIn("# odoo-nix addons mode: links the dev shell makes", before)
        root = self.profile_fixture(
            "standards-addons", "minimal", {".gitignore": before}
        )
        self.write(root)
        after = (root / ".gitignore").read_text()
        self.assertNotIn("# odoo-nix addons mode", after)
        self.assertNotIn("# devenv state", after)

    def test_missing_file_is_created(self) -> None:
        root = self.profile_fixture(
            "standards-project", "minimal", {".gitignore": None}
        )
        self.write(root)
        self.assertEqual(
            (root / ".gitignore").read_text(), "\n".join([BEGIN, *BODY, END]) + "\n"
        )


class ReadmeTable(SyncCase):
    def table(self, root: Path) -> list[str]:
        text = (root / "README.md").read_text()
        lines = text.splitlines()
        begin = lines.index("<!-- odoo-nix:begin addons-table -->")
        end = lines.index("<!-- odoo-nix:end addons-table -->")
        return lines[begin + 1 : end]

    def test_rows_from_manifests(self) -> None:
        root = self.profile_fixture("standards-addons", "example-org")
        before = (root / "README.md").read_text()
        self.write(root)
        self.assertTrue((root / "README.md").read_text().startswith(before))
        summary = "A stand-in addon for odoo-nix's standards fixtures"
        self.assertEqual(
            self.table(root),
            [
                "| Addon | Summary | License |",
                "| --- | --- | --- |",
                f"| [fixture_a](fixture_a/README.md) | {summary} | AGPL-3 |",
                f"| [fixture_b](fixture_b/README.md) | {summary} | AGPL-3 |",
            ],
        )

    def test_project_lists_installable_addons_under_custom(self) -> None:
        root = self.profile_fixture("standards-project", "example-org")
        self.write(root)
        rows = self.table(root)[2:]
        self.assertEqual(len(rows), 1)
        self.assertTrue(
            rows[0].startswith("| [fixture_sale](custom/fixture_sale/README.md) |")
        )

    def test_cells_escape_pipes_and_missing_readme(self) -> None:
        repo = need_root(self)
        manifest = (
            repo / "tests/fixtures/standards-addons/fixture_b/__manifest__.py"
        ).read_text()
        root = self.profile_fixture(
            "standards-addons",
            "example-org",
            {
                "fixture_b/__manifest__.py": manifest.replace(
                    "A stand-in addon", "A | piped\\n   stand-in addon"
                ),
                "fixture_b/README.md": None,
            },
        )
        self.write(root, ok=False)
        self.assertIn(
            "| [fixture_b](fixture_b/) | A \\| piped stand-in addon for",
            "\n".join(self.table(root)),
        )

    def test_off_by_default_and_retracted(self) -> None:
        root = self.profile_fixture("standards-addons", "example-org")
        self.write(root)
        self.commit(root)
        profile = root / ".standards-profile" / "profile.toml"
        profile.write_text(profile.read_text().replace("addons-table = true\n", ""))
        self.write(root)
        repo = need_root(self)
        self.assertEqual(
            (root / "README.md").read_text(),
            (repo / "tests/fixtures/standards-addons/README.md").read_text(),
        )
