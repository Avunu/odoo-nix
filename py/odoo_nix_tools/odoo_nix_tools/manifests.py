"""Reading an Odoo ``__manifest__.py`` without importing it.

A manifest is one Python dict literal, with comments. ``literal`` reads it with
``ast.literal_eval``, so nothing in it runs. Writing the version back (``replace_version``)
and the version rules (``version_problem``) arrive with the release tool (DESIGN.md §2.2,
stage O7).
"""

from __future__ import annotations

import ast
from typing import Any


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
