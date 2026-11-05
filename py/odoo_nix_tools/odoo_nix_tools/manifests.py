"""Reading an Odoo ``__manifest__.py`` without importing it.

A manifest is one Python dict literal, with comments. ``literal`` reads it with
``ast.literal_eval``, so nothing in it runs. ``replace_version`` writes a new version back
with every other byte kept (the release tool, DESIGN.md §2.2), and ``version_problem``
says why a version is not the series' ``<series>.x.y.z``.
"""

from __future__ import annotations

import ast
import re
from typing import Any

# <series>.x.y.z: OCA's five-part manifest version (DESIGN.md §2.2).
SERIES_VERSION = re.compile(r"^(?P<series>\d+\.0)\.(?P<x>\d+)\.(?P<y>\d+)\.(?P<z>\d+)$")
_LINES = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")


def literal(text: str, path: str = "__manifest__.py") -> dict[str, Any]:
    """The manifest dict in ``text``; ``ValueError`` naming ``path`` when it is not one
    dict literal (a syntax error, a call, a name)."""
    try:
        tree = ast.parse(text, filename=path, mode="exec")
    except SyntaxError as e:
        raise ValueError(f"{path}: not Python: {e.msg} (line {e.lineno})") from e
    body = [node for node in tree.body if isinstance(node, ast.Expr)]
    if len(tree.body) != 1 or len(body) != 1 or not isinstance(body[0].value, ast.Dict):
        raise ValueError(f"{path}: a manifest is one dict literal")
    try:
        value = ast.literal_eval(body[0].value)
    except ValueError as e:
        raise ValueError(f"{path}: not a literal: {e}") from e
    return value


def _dict_node(text: str, path: str) -> ast.Dict:
    try:
        tree = ast.parse(text, filename=path, mode="exec")
    except SyntaxError as e:
        raise ValueError(f"{path}: not Python: {e.msg} (line {e.lineno})") from e
    if (
        len(tree.body) != 1
        or not isinstance(tree.body[0], ast.Expr)
        or not isinstance(tree.body[0].value, ast.Dict)
    ):
        raise ValueError(f"{path}: a manifest is one dict literal")
    return tree.body[0].value


def _offset(lines: list[str], lineno: int, col: int) -> int:
    """The character offset of ``(lineno, col)``; ``col`` counts UTF-8 bytes (ast)."""
    before = sum(len(line) for line in lines[: lineno - 1])
    return before + len(lines[lineno - 1].encode()[:col].decode())


def replace_version(text: str, version: str, path: str = "__manifest__.py") -> str:
    """``text`` with the string literal of its top-level ``"version"`` key replaced by
    ``version``, in the same quote character; every other byte is kept. ``ValueError``
    naming ``path`` when there is no such key, or its value is not one plain string
    literal (an f-string, a concatenation, a name)."""
    node = _dict_node(text, path)
    value = None
    for key, item in zip(node.keys, node.values, strict=True):
        if isinstance(key, ast.Constant) and key.value == "version":
            value = item
    if value is None:
        raise ValueError(f'{path}: the manifest has no "version" key')
    if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
        raise ValueError(f'{path}: "version" is not a string literal')  # noqa: TRY004
    # ast counts lines at \n, \r\n and \r only (str.splitlines splits at more).
    lines = _LINES.findall(text)
    start = _offset(lines, value.lineno, value.col_offset)
    end = _offset(lines, value.end_lineno or value.lineno, value.end_col_offset or 0)
    source = text[start:end]
    # One literal, no prefix and no implicit concatenation: "18.0.1.0.0" or '…'.
    quote = source[:1]
    if (
        quote not in ("'", '"')
        or source.startswith(quote * 3)
        or not source.endswith(quote)
        or ast.literal_eval(source) != value.value
        or source.count(quote) != 2
    ):
        raise ValueError(f'{path}: "version" is not one plain string literal')
    if quote in version or "\\" in version or "\n" in version:
        raise ValueError(f"{path}: cannot write the version {version!r}")
    return text[:start] + quote + version + quote + text[end:]


def version_problem(version: Any, series: str) -> str | None:
    """Why ``version`` is not ``<series>.x.y.z``, or ``None``."""
    if not isinstance(version, str) or not version:
        return f"no version: it must be {series}.x.y.z"
    m = SERIES_VERSION.match(version)
    if m is None:
        return f"version {version} is not {series}.x.y.z"
    if m["series"] != series:
        return f"version {version} is not {series}.x.y.z"
    return None
