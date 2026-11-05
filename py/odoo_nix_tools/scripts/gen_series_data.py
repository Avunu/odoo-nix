#!/usr/bin/env python3
"""Generate odoo-nix's per-series standards data from OCA's addons repo template.

Usage::

    gen_series_data.py TEMPLATE_DIR TAG [--series 18.0 ...] [--out DIR] [--cache DIR]
                       [--offline] [--check]

TEMPLATE_DIR is a checkout of https://github.com/OCA/oca-addons-repo-template at TAG
(a git clone or an extracted tarball). For every series the script renders the
template's files the way ``copier copy --defaults`` would, with OCA's default answers,
except the organisation-specific answers (``org_slug``, ``org_name``, ``repo_slug``,
``repo_name``, ``repo_website``, ``repo_description``). Those become placeholder tokens
such as ``@@org_name@@``; nothing OCA-specific that comes from an answer reaches the
output. The script then writes ``odoo_nix_tools/data/series/<series>.json``.

The rendered ``.pre-commit-config.yaml`` names hooks from remote repositories. Their
definitions (entry, files, types, ...) come from each repository's
``.pre-commit-hooks.yaml`` at the pinned revision, fetched from
raw.githubusercontent.com (``--cache`` keeps them; ``--offline`` uses only the cache).
That lets the standards engine reproduce every hook as a ``language: system`` hook
that runs a tool from the managed tools lock.

The data records OCA's values verbatim. Deviations are applied by the standards
engine, never written here.

Only the standard library and jinja2 are used: the YAML the template and the hook
manifests use is parsed by a small subset parser (``_MiniYaml``), and the script
fails loudly on any construct outside that subset.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jinja2

SCHEMA_VERSION = 1
TEMPLATE_REPO = "OCA/oca-addons-repo-template"
DEFAULT_SERIES = ("18.0", "19.0", "20.0")
DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent / "odoo_nix_tools" / "data" / "series"
)

# Copier questions whose answers belong to the organisation and repository rather than
# to the series. Their answers are replaced by placeholder tokens.
PLACEHOLDER_QUESTIONS = (
    "org_name",
    "org_slug",
    "repo_description",
    "repo_name",
    "repo_slug",
    "repo_website",
)

# Files whose rendered bodies the engine manages (data key "files").
MANAGED_FILES = (
    ".editorconfig",
    ".pylintrc",
    ".pylintrc-mandatory",
    ".ruff.toml",
    "eslint.config.cjs",
    "prettier.config.cjs",
)
# Rendered for reference and tests only (data key "reference_files").
REFERENCE_FILES = (
    ".gitignore",
    ".pre-commit-config.yaml",
    "checklog-odoo.cfg",
)
# Read for the "ci" facts only.
CI_WORKFLOWS = (".github/workflows/pre-commit.yml", ".github/workflows/test.yml")

# Python packages behind the pre-commit repositories OCA references. The version is the
# hook repository's rev without a leading "v" (ruff-pre-commit pins ruff==<its tag>);
# maintainer-tools is not published on PyPI, so it is installed from git at the commit.
REPO_TOOLS: dict[str, tuple[str, str, str]] = {
    # repo URL (lower case): (tool key, ecosystem, package)
    "https://github.com/astral-sh/ruff-pre-commit": ("ruff", "pypi", "ruff"),
    "https://github.com/oca/maintainer-tools": (
        "maintainer-tools",
        "git",
        "oca-maintainers-tools",
    ),
    "https://github.com/oca/odoo-pre-commit-hooks": (
        "odoo-pre-commit-hooks",
        "pypi",
        "oca-odoo-pre-commit-hooks",
    ),
    "https://github.com/oca/pylint-odoo": ("pylint-odoo", "pypi", "pylint-odoo"),
    "https://github.com/pre-commit/pre-commit-hooks": (
        "pre-commit-hooks",
        "pypi",
        "pre-commit-hooks",
    ),
    "https://github.com/sbidoul/whool": ("whool", "pypi", "whool"),
}
# Pins in the template's repo_rev namespace that the rendered config does not use for
# these series but that are worth recording as tools (key: (tool key, ecosystem, package)).
UNUSED_REV_TOOLS = {"setuptools_odoo": ("setuptools-odoo", "pypi", "setuptools-odoo")}
# Tools the engine locks that the template does not pin at all (OCA CI takes them from
# the oca-ci image). Recorded with a null version so consumers see the gap.
UNPINNED_TOOLS = {
    "checklog-odoo": (
        "pypi",
        "checklog-odoo",
        "installed in OCA's oca-ci image; not pinned by the template",
    ),
    "manifestoo": (
        "pypi",
        "manifestoo",
        "installed in OCA's oca-ci image; not pinned by the template",
    ),
}

# What each OCA hook does to the tree. "kind": fail (always fails when it matches),
# checker (reads only), fixer (rewrites the files it is given or the named files),
# generator (writes files derived from the addons). "writes" lists what it may write;
# "<matched>" means the files pre-commit passes to it.
HOOK_ROLES: dict[str, dict[str, Any]] = {
    "check-case-conflict": {"kind": "checker"},
    "check-docstring-first": {"kind": "checker"},
    "check-executables-have-shebangs": {"kind": "checker"},
    "check-merge-conflict": {"kind": "checker"},
    "check-symlinks": {"kind": "checker"},
    "check-xml": {"kind": "checker"},
    "debug-statements": {"kind": "checker"},
    "end-of-file-fixer": {"kind": "fixer", "writes": ["<matched>"]},
    "eslint": {"kind": "fixer", "writes": ["<matched>"]},
    "fix-encoding-pragma": {"kind": "fixer", "writes": ["<matched>"]},
    "mixed-line-ending": {"kind": "fixer", "writes": ["<matched>"]},
    "oca-checks-odoo-module": {"kind": "checker"},
    "oca-checks-po": {"kind": "checker"},
    "oca-fix-manifest-website": {
        "kind": "fixer",
        "rewrites_manifests": True,
        "writes": ["<addon>/__manifest__.py"],
    },
    "oca-gen-addon-readme": {
        "kind": "generator",
        "writes": [
            "<addon>/README.rst",
            "<addon>/static/description/index.html",
            "<addon>/readme/*",
        ],
    },
    "oca-gen-external-dependencies": {
        "kind": "generator",
        "writes": ["requirements.txt"],
    },
    "oca-update-pre-commit-excluded-addons": {
        "kind": "fixer",
        "rewrites_pre_commit_config": True,
        "writes": [".pre-commit-config.yaml"],
    },
    "prettier": {"kind": "fixer", "writes": ["<matched>"]},
    "pylint_odoo": {"kind": "checker"},
    "ruff": {"kind": "fixer", "writes": ["<matched>"]},
    "ruff-check": {"kind": "fixer", "writes": ["<matched>"]},
    "ruff-format": {"kind": "fixer", "writes": ["<matched>"]},
    "trailing-whitespace": {"kind": "fixer", "writes": ["<matched>"]},
    "whool-init": {"kind": "generator", "writes": ["<addon>/pyproject.toml"]},
}
# Keys copied from a hook (manifest merged with the config entry, config wins).
HOOK_KEYS = (
    "additional_dependencies",
    "always_run",
    "args",
    "entry",
    "exclude",
    "exclude_types",
    "files",
    "name",
    "pass_filenames",
    "require_serial",
    "stages",
    "types",
    "types_or",
    "verbose",
)
# The pre-commit workflow OCA renders skips these hooks in CI.
CI_SKIP_RE = re.compile(r"^\s*SKIP:\s*(\S+)\s*$", re.MULTILINE)

DOC = {
    "answers": "Copier answers used to render this series: OCA's defaults, with the "
    "organisation-specific questions replaced by the placeholder tokens in 'placeholders'.",
    "ci": "What OCA's rendered CI workflows use: test images (runtime Python), the "
    "PostgreSQL image, the pre-commit job's Python and the hooks it SKIPs.",
    "deviations": "Always empty in this data. The data records OCA's values verbatim; the "
    "standards engine applies (and documents) every deviation.",
    "eslint_esm_globs": "Globs eslint.config.cjs parses as ES modules (sourceType module).",
    "exclude": "OCA's top-level pre-commit exclude: a verbose regex split into its top-level "
    "alternatives, each with the comment above it. 'moved_to_per_hook' marks the "
    "alternative the standards engine moves into per-hook excludes. "
    "'excluded_addons_markers' delimits the region oca-update-pre-commit-excluded-addons "
    "rewrites.",
    "files": "Fully rendered bodies of the files the engine manages, by file name.",
    "hooks": "OCA's hooks in config order. Each merges the hook repository's manifest with "
    "the config entry (config wins), so 'entry' plus 'args' is the command a "
    "'language: system' hook runs. 'tool' names the 'tools' entry that provides "
    "the executable (null for 'language: fail' hooks); 'upstream_language' is the language "
    "OCA runs it with; 'key' is unique when an id repeats.",
    "node": "default_language_version.node from the rendered .pre-commit-config.yaml.",
    "placeholders": "Placeholder tokens standing for organisation-specific answers, with the "
    "copier question, OCA's default and every data path that contains the token.",
    "pylint": "Parsed .pylintrc and .pylintrc-mandatory: message lists per file, the "
    "[ODOOLINT] options (with placeholders), the optional-only messages.",
    "python": "default_language_version.python, ruff's target-version, the Python of OCA's "
    "test image and of its pre-commit job.",
    "reference_files": "Other rendered files, for reference and tests; not managed whole.",
    "ruff": "The rendered .ruff.toml, parsed.",
    "series": "Odoo series this file describes.",
    "template": "The OCA template and tag the data was generated from.",
    "template_revs": "The template's raw repo_rev pins for this series, including tools the "
    "rendered config does not use.",
    "tools": "Exact pins for every tool, keyed by tool name. 'requirement' is what a uv or "
    "npm lock should resolve; 'used' is false for pins the rendered config does not use; "
    "a null version means OCA does not pin the tool.",
}


class GenError(RuntimeError):
    """A fact the generator could not determine; the message says which."""


# --------------------------------------------------------------------------------------
# A YAML subset parser: block mappings and sequences, flow sequences, empty flow
# mappings, quoted and plain scalars, literal and folded block scalars, comments.


@dataclass
class _Line:
    indent: int
    text: str


_KEY_RE = re.compile(
    r"""^(?P<key>"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[A-Za-z_$][\w.$-]*)[ \t]*:(?:[ \t]+|$)(?P<rest>.*)$"""
)
_INT_RE = re.compile(r"^[-+]?\d+$")
_FLOAT_RE = re.compile(r"^[-+]?(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_DQ_ESCAPES = {
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "t": "\t",
    "\t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
}


class _MiniYaml:
    """Parse the YAML subset used by copier.yml, pre-commit configs and hook manifests."""

    def __init__(self, text: str, source: str) -> None:
        self.lines = text.split("\n")
        self.pos = 0
        self.source = source

    def parse(self) -> Any:
        value = self._node(0)
        if self._peek() is not None:
            self._fail("unexpected content")
        return value

    def _fail(self, message: str) -> None:
        line = self.lines[self.pos] if self.pos < len(self.lines) else "<eof>"
        raise GenError(f"{self.source}:{self.pos + 1}: {message}: {line!r}")

    def _peek(self) -> _Line | None:
        while self.pos < len(self.lines):
            raw = self.lines[self.pos]
            if "\t" in raw[: len(raw) - len(raw.lstrip())]:
                self._fail("tab indentation is not supported")
            text = raw.strip()
            if text and not text.startswith("#") and text != "---":
                return _Line(len(raw) - len(raw.lstrip(" ")), text)
            self.pos += 1
        return None

    @staticmethod
    def _is_item(text: str) -> bool:
        return text == "-" or text.startswith("- ")

    def _node(self, min_indent: int) -> Any:
        line = self._peek()
        if line is None or line.indent < min_indent:
            return None
        if self._is_item(line.text):
            return self._sequence(line.indent)
        if _KEY_RE.match(line.text):
            return self._mapping(line.indent)
        return self._multiline_plain(line.indent)

    def _sequence(self, indent: int) -> list[Any]:
        items: list[Any] = []
        while (
            (line := self._peek()) is not None
            and line.indent == indent
            and self._is_item(line.text)
        ):
            after = line.text[1:]
            content = after.lstrip(" ")
            if not content or content.startswith("#"):
                self.pos += 1
                items.append(self._node(indent + 1))
                continue
            column = indent + 1 + len(after) - len(content)
            if _KEY_RE.match(content):
                self.lines[self.pos] = " " * column + content
                items.append(self._mapping(column))
            else:
                self.pos += 1
                items.append(self._value(content, indent))
        return items

    def _mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while (line := self._peek()) is not None and line.indent == indent:
            if self._is_item(line.text):
                break
            match = _KEY_RE.match(line.text)
            if not match:
                self._fail("expected a mapping key")
            key = self._inline(match["key"])
            if key in result:
                self._fail(f"duplicate key {key!r}")
            self.pos += 1
            rest = match["rest"]
            if not rest.strip() or rest.lstrip().startswith("#"):
                nxt = self._peek()
                if nxt is not None and (
                    nxt.indent > indent
                    or (nxt.indent == indent and self._is_item(nxt.text))
                ):
                    result[key] = self._node(nxt.indent)
                else:
                    result[key] = None
            else:
                result[key] = self._value(rest, indent)
        return result

    def _multiline_plain(self, indent: int) -> str:
        parts = []
        while self.pos < len(self.lines):
            raw = self.lines[self.pos]
            text = raw.strip()
            if (
                not text
                or text.startswith("#")
                or len(raw) - len(raw.lstrip(" ")) < indent
            ):
                break
            if ": " in text or " #" in text:
                self._fail("ambiguous multi-line plain scalar")
            parts.append(text)
            self.pos += 1
        return " ".join(parts)

    def _value(self, text: str, parent_indent: int) -> Any:
        stripped = text.strip()
        if stripped[:1] in ("|", ">"):
            return self._block_scalar(stripped, parent_indent)
        return self._inline(stripped)

    def _block_scalar(self, header: str, parent_indent: int) -> str:
        match = re.fullmatch(r"([|>])([-+]?)([1-9]?)([-+]?)\s*(?:#.*)?", header)
        if not match:
            self._fail("bad block scalar header")
        style, chomp = match[1], match[2] or match[4]
        block_indent = parent_indent + int(match[3]) if match[3] else None
        body: list[str] = []
        while self.pos < len(self.lines):
            raw = self.lines[self.pos]
            if not raw.strip():
                body.append("")
                self.pos += 1
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if block_indent is None:
                if indent <= parent_indent:
                    break
                block_indent = indent
            if indent < block_indent:
                break
            body.append(raw[block_indent:])
            self.pos += 1
        trailing = 0
        while body and body[-1] == "":
            body.pop()
            trailing += 1
        if style == "|":
            text = "\n".join(body)
        else:
            text = ""
            for index, line in enumerate(body):
                if index == 0:
                    text = line
                elif line == "" or body[index - 1] == "" or line.startswith(" "):
                    text += "\n" + line
                else:
                    text += " " + line
        if not body:
            return "" if chomp != "+" else "\n" * trailing
        if chomp == "-":
            return text
        if chomp == "+":
            return text + "\n" * (trailing + 1)
        return text + "\n"

    def _inline(self, text: str) -> Any:
        text = text.strip()
        if text[:1] in ("'", '"'):
            value, end = self._quoted(text)
            self._expect_end(text[end:])
            return value
        if text.startswith("["):
            items, end = self._flow_sequence(text)
            self._expect_end(text[end:])
            return items
        if text.startswith("{"):
            if re.fullmatch(r"\{\s*\}\s*(?:#.*)?", text):
                return {}
            self._fail("non-empty flow mappings are not supported")
        comment = re.search(r"\s#", text)
        if comment:
            text = text[: comment.start()].rstrip()
        return self._plain(text)

    def _expect_end(self, rest: str) -> None:
        rest = rest.strip()
        if rest and not rest.startswith("#"):
            self._fail(f"unexpected text after value: {rest!r}")

    @staticmethod
    def _plain(text: str) -> Any:
        if text in ("", "~", "null", "Null", "NULL"):
            return None
        if text in ("true", "True", "TRUE"):
            return True
        if text in ("false", "False", "FALSE"):
            return False
        if _INT_RE.match(text):
            return int(text)
        if _FLOAT_RE.match(text):
            return float(text)
        return text

    def _quoted(self, text: str) -> tuple[str, int]:
        quote = text[0]
        out: list[str] = []
        index = 1
        while index < len(text):
            char = text[index]
            if quote == "'" and char == "'":
                if text[index + 1 : index + 2] == "'":
                    out.append("'")
                    index += 2
                    continue
                return "".join(out), index + 1
            if quote == '"' and char == '"':
                return "".join(out), index + 1
            if quote == '"' and char == "\\":
                code = text[index + 1 : index + 2]
                if code in _DQ_ESCAPES:
                    out.append(_DQ_ESCAPES[code])
                    index += 2
                    continue
                width = {"x": 2, "u": 4, "U": 8}.get(code)
                if width is None:
                    self._fail(f"unsupported escape \\{code}")
                out.append(chr(int(text[index + 2 : index + 2 + width], 16)))
                index += 2 + width
                continue
            out.append(char)
            index += 1
        self._fail(
            "unterminated quoted scalar (multi-line quoted scalars are not supported)"
        )
        raise AssertionError  # unreachable

    def _flow_sequence(self, text: str) -> tuple[list[Any], int]:
        items: list[Any] = []
        index = 1
        while True:
            while index < len(text) and text[index] in " ,":
                index += 1
            if index >= len(text):
                self._fail(
                    "unterminated flow sequence (multi-line flow is not supported)"
                )
            if text[index] == "]":
                return items, index + 1
            if text[index] in "'\"":
                value, used = self._quoted(text[index:])
                items.append(value)
                index += used
            elif text[index] in "[{":
                self._fail("nested flow collections are not supported")
            else:
                end = index
                while end < len(text) and text[end] not in ",]":
                    end += 1
                items.append(self._plain(text[index:end].strip()))
                index = end


def parse_yaml(text: str, source: str) -> Any:
    return _MiniYaml(text, source).parse()


# --------------------------------------------------------------------------------------
# Rendering the template the way copier does.


def _copier_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("y", "yes", "t", "true", "on", "1"):
        return True
    if text in ("n", "no", "f", "false", "off", "0", ""):
        return False
    raise GenError(f"cannot cast {value!r} to bool")


def make_env(template_dir: Path) -> jinja2.Environment:
    # Copier's defaults: the loader is rooted at the template root (so "src/..." and
    # "version-specific/..." resolve), autoescape off, trailing newline kept.
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
        extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"],
    )
    # Filters copier provides through jinja2-ansible-filters; only the CI workflow
    # (read for "ci") uses them.
    env.filters["bool"] = _copier_bool
    env.filters["to_json"] = lambda value: json.dumps(value)
    return env


def placeholder(name: str, variant: str = "") -> str:
    return f"@@{name}{variant}@@"


def copier_answers(
    env: jinja2.Environment, questions: dict[str, Any], series: str, variant: str
) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for name, spec in questions.items():
        if name.startswith("_"):
            continue
        if not isinstance(spec, dict):
            spec = {"default": spec}
        if name == "odoo_version":
            choices = spec.get("choices") or []
            if float(series) not in choices:
                raise GenError(
                    f"series {series} is not one of the template's odoo_version choices"
                )
            answers[name] = float(series)
            continue
        if name in PLACEHOLDER_QUESTIONS:
            answers[name] = placeholder(name, variant)
            continue
        if "default" not in spec:
            raise GenError(
                f"copier question {name!r} has no default and no placeholder"
            )
        default = spec["default"]
        if isinstance(default, str):
            default = env.from_string(default).render(**answers)
        answers[name] = _cast(default, spec.get("type"), name)
    missing = [name for name in PLACEHOLDER_QUESTIONS if name not in answers]
    if missing:
        raise GenError(
            f"copier.yml no longer asks {missing}; update PLACEHOLDER_QUESTIONS"
        )
    return answers


def _cast(value: Any, qtype: str | None, name: str) -> Any:
    if qtype == "bool":
        return _copier_bool(value)
    if qtype == "float":
        return float(value)
    if qtype == "int":
        return int(value)
    if qtype in ("yaml", "json"):
        if isinstance(value, str):
            return (
                parse_yaml(value, f"default of {name}")
                if qtype == "yaml"
                else json.loads(value)
            )
        return value
    if qtype in (None, "str"):
        return value if qtype is None else ("" if value is None else str(value))
    raise GenError(f"copier question {name!r} has unsupported type {qtype!r}")


def render_tree(
    env: jinja2.Environment,
    template_dir: Path,
    answers: dict[str, Any],
    wanted: tuple[str, ...],
) -> dict[str, str]:
    """Render the wanted files of src/ like copier: templated names, .jinja suffix rendered.

    Every file name is rendered (an empty component drops the file, as in copier), but
    only the wanted contents are, so copier-only filters elsewhere (the answers file's
    ``to_nice_yaml``) need no emulation.
    """
    context = dict(answers)
    context["_copier_conf"] = {"answers_file": ".copier-answers.yml", "sep": "/"}
    rendered: dict[str, str] = {}
    src = template_dir / "src"
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        relative = path.relative_to(src)
        parts = [env.from_string(part).render(**context) for part in relative.parts]
        if any(not part for part in parts):
            continue
        name = "/".join(parts)
        is_template = name.endswith(".jinja")
        name = name.removesuffix(".jinja")
        if name not in wanted:
            continue
        if name in rendered:
            raise GenError(f"two template files render to {name}")
        if is_template:
            source = path.relative_to(template_dir).as_posix()
            rendered[name] = env.get_template(source).render(**context)
        else:
            rendered[name] = path.read_text(encoding="utf-8")
    return rendered


def repo_revs(
    env: jinja2.Environment, template_dir: Path, answers: dict[str, Any]
) -> dict[str, str]:
    source = "src/.pre-commit-config.yaml.jinja"
    names = sorted(
        set(re.findall(r"repo_rev\.(\w+)\s*=", (template_dir / source).read_text()))
    )
    probe = "{% from '" + source + "' import repo_rev with context %}{{ {"
    probe += ", ".join(
        f"'{n}': (repo_rev.{n} if repo_rev.{n} is defined else none)" for n in names
    )
    probe += "} | tojson }"
    probe += "}"
    values = json.loads(env.from_string(probe).render(**answers))
    return {key: value for key, value in sorted(values.items()) if value is not None}


# --------------------------------------------------------------------------------------
# Hook manifests.


def _manifest_url(repo: str, rev: str) -> tuple[str, str]:
    match = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?", repo)
    if not match:
        raise GenError(
            f"hook repository {repo} is not on GitHub; cannot fetch its manifest"
        )
    owner, name = match.groups()
    url = (
        f"https://raw.githubusercontent.com/{owner}/{name}/{rev}/.pre-commit-hooks.yaml"
    )
    return url, f"{owner.lower()}__{name.lower()}__{rev}.yaml"


_FETCHED: dict[str, str] = {}


def hook_manifest(
    repo: str, rev: str, cache: Path | None, offline: bool
) -> dict[str, dict[str, Any]]:
    url, filename = _manifest_url(repo, rev)
    cached = cache / filename if cache else None
    if url in _FETCHED:
        text = _FETCHED[url]
    elif cached and cached.is_file():
        text = cached.read_text(encoding="utf-8")
    elif offline:
        raise GenError(f"--offline and {filename} is not in the cache ({url})")
    else:
        request = urllib.request.Request(
            url, headers={"User-Agent": "odoo-nix gen_series_data"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode("utf-8")
        except (OSError, urllib.error.URLError) as error:
            raise GenError(
                f"cannot fetch {url} ({error}); download it into --cache as {filename}"
            ) from error
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(text, encoding="utf-8")
    _FETCHED[url] = text
    hooks = parse_yaml(text, url)
    if not isinstance(hooks, list):
        raise GenError(f"{url} is not a list of hooks")
    return {hook["id"]: hook for hook in hooks}


# --------------------------------------------------------------------------------------
# Extraction.


def _version(rev: str) -> str:
    return rev[1:] if re.match(r"^v\d", rev) else rev


def _split_requirement(spec: str) -> tuple[str, str, str]:
    """Split an npm "name@version" or a PEP 508 "name<op>version" requirement."""
    if spec.startswith("@") or ("@" in spec and not re.search(r"[<>=!~]", spec)):
        name, _, version = spec.rpartition("@")
        return name, "==", version
    match = re.fullmatch(r"([A-Za-z0-9._-]+)\s*(==|>=|<=|~=|>|<|!=)\s*(\S+)", spec)
    if not match:
        raise GenError(f"cannot parse requirement {spec!r}")
    return match[1], match[2], match[3]


def extract_hooks(
    config: dict[str, Any], cache: Path | None, offline: bool, ci_skips: set[str]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    hooks: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    seen: dict[str, int] = {}
    for repo_entry in config["repos"]:
        repo, rev = repo_entry["repo"], repo_entry.get("rev")
        manifest = hook_manifest(repo, rev, cache, offline) if repo != "local" else {}
        tool_spec = REPO_TOOLS.get(repo.lower())
        if repo != "local":
            if tool_spec is None:
                raise GenError(f"unknown hook repository {repo}; add it to REPO_TOOLS")
            key, ecosystem, package = tool_spec
            version = _version(rev)
            requirement = (
                f"{package} @ git+{repo}@{rev}"
                if ecosystem == "git"
                else f"{package}=={version}"
            )
            tools.setdefault(
                key,
                {
                    "ecosystem": ecosystem,
                    "package": package,
                    "provides_hooks": [],
                    "requirement": requirement,
                    "source": {"repo": repo, "rev": rev},
                    "used": True,
                    "version": version,
                },
            )
        for entry in repo_entry["hooks"]:
            hook_id = entry["id"]
            if repo != "local" and hook_id not in manifest:
                raise GenError(f"hook {hook_id} is not defined by {repo}@{rev}")
            merged = {**manifest.get(hook_id, {}), **entry}
            seen[hook_id] = seen.get(hook_id, 0) + 1
            language = merged.get("language")
            data: dict[str, Any] = {
                "id": hook_id,
                "key": hook_id if seen[hook_id] == 1 else f"{hook_id}#{seen[hook_id]}",
                "repo": repo,
                "rev": rev,
                "upstream_language": language,
            }
            data.update({k: merged[k] for k in HOOK_KEYS if k in merged})
            data.setdefault("args", [])
            if language == "fail":
                role: dict[str, Any] = {"kind": "fail"}
                data["tool"] = None
            else:
                if hook_id not in HOOK_ROLES:
                    raise GenError(
                        f"hook {hook_id} has no entry in HOOK_ROLES; classify it"
                    )
                role = dict(HOOK_ROLES[hook_id])
                if repo == "local":
                    tool_key = str(merged["entry"]).split()[0]
                else:
                    tool_key = tool_spec[0]
                    if hook_id not in tools[tool_key]["provides_hooks"]:
                        tools[tool_key]["provides_hooks"].append(hook_id)
                data["tool"] = tool_key
            if hook_id == "oca-checks-odoo-module" and "--fix" in data["args"]:
                role = {"kind": "fixer", "writes": ["<matched>"]}
            if hook_id == "pylint_odoo" and "--exit-zero" in data["args"]:
                role["advisory"] = True
            if hook_id in ci_skips:
                role["ci_skip"] = True
            role.setdefault("writes", [])
            role.setdefault("rewrites_manifests", False)
            role.setdefault("rewrites_pre_commit_config", False)
            data.update(role)
            for dependency in merged.get("additional_dependencies", []):
                name, op, version = _split_requirement(dependency)
                is_npm = language == "node"
                record = tools.setdefault(
                    name,
                    {
                        "ecosystem": "npm" if is_npm else "pypi",
                        "package": name,
                        "provides_hooks": [],
                        "source": {
                            "additional_dependency": dependency,
                            "hook": hook_id,
                        },
                        "used": True,
                    },
                )
                if op == "==":
                    record["version"] = version
                    record["requirement"] = (
                        f"{name}@{version}" if is_npm else f"{name}=={version}"
                    )
                else:
                    record["version"] = None
                    record["constraint"] = f"{op}{version}"
                    record["requirement"] = f"{name}{op}{version}"
                if is_npm and hook_id == name.rpartition("/")[2]:
                    record["provides_hooks"].append(hook_id)
            hooks.append(data)
    return hooks, tools


def _split_alternatives(pattern: str) -> list[str]:
    parts, depth, in_class, current, index = [], 0, False, "", 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            current += pattern[index : index + 2]
            index += 2
            continue
        if in_class:
            in_class = char != "]"
        elif char == "[":
            in_class = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "|" and depth == 0:
            parts.append(current)
            current = ""
            index += 1
            continue
        current += char
        index += 1
    parts.append(current)
    return [part for part in parts if part]


def extract_exclude(raw: str) -> dict[str, Any]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "(?x)":
        raise GenError("OCA's top-level exclude is no longer a (?x) verbose regex")
    alternatives: list[dict[str, Any]] = []
    markers: dict[str, Any] = {}
    comment: list[str] = []
    for line in lines[1:]:
        text = line.strip()
        if not text:
            continue
        if text.startswith("#"):
            note = text.lstrip("#").strip()
            if note == "NOT INSTALLABLE ADDONS":
                markers = {"begin": text, "index": len(alternatives)}
            elif note == "END NOT INSTALLABLE ADDONS":
                markers["end"] = text
            else:
                comment.append(note)
            continue
        for part in _split_alternatives(text):
            alternatives.append(
                {
                    "comment": " ".join(comment),
                    "moved_to_per_hook": part in ("^.github/", r"^\.github/"),
                    "pattern": part,
                }
            )
        comment = []
    if not markers.get("end"):
        raise GenError(
            "the NOT INSTALLABLE ADDONS markers are missing from the exclude"
        )
    if not any(alt["moved_to_per_hook"] for alt in alternatives):
        raise GenError("OCA's exclude no longer holds '^.github/'")
    return {
        "alternatives": alternatives,
        "excluded_addons_markers": markers,
        "flags": "(?x)",
        "raw": raw,
    }


def parse_ini(body: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    section: str | None = None
    key: str | None = None
    for line in body.splitlines():
        text = line.strip()
        if not text or text.startswith(("#", ";")):
            continue
        if line[0] in " \t":
            if section is None or key is None:
                raise GenError(f"continuation line outside an option: {line!r}")
            sections[section][key] += "\n" + text
            continue
        if text.startswith("["):
            section, key = text.strip("[]"), None
            sections[section] = {}
            continue
        if section is None or "=" not in text:
            raise GenError(f"unexpected pylintrc line {line!r}")
        key, _, value = (part.strip() for part in text.partition("="))
        sections[section][key] = value
    return sections


def _items(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,\n]", value) if item.strip()]


def extract_pylint(files: dict[str, str]) -> dict[str, Any]:
    parsed = {
        name: parse_ini(files[name]) for name in (".pylintrc", ".pylintrc-mandatory")
    }
    messages = {
        name: {
            "disable": _items(ini["MESSAGES CONTROL"].get("disable", "")),
            "enable": _items(ini["MESSAGES CONTROL"].get("enable", "")),
        }
        for name, ini in parsed.items()
    }
    mandatory = set(messages[".pylintrc-mandatory"]["enable"])
    for section in ("MASTER", "IMPORTS", "ODOOLINT", "REPORTS"):
        if parsed[".pylintrc"].get(section) != parsed[".pylintrc-mandatory"].get(
            section
        ):
            raise GenError(
                f"[{section}] differs between .pylintrc and .pylintrc-mandatory"
            )
    ini = parsed[".pylintrc-mandatory"]
    return {
        "deprecated_modules": _items(ini["IMPORTS"]["deprecated-modules"]),
        "load_plugins": _items(ini["MASTER"]["load-plugins"]),
        "messages": messages,
        "odoolint": ini["ODOOLINT"],
        "optional_only": [
            m for m in messages[".pylintrc"]["enable"] if m not in mandatory
        ],
        "sections": parsed,
    }


def extract_esm_globs(eslint_config: str) -> list[str]:
    blocks = re.findall(
        r"files:\s*\[([^\]]*)\]\s*,\s*languageOptions:\s*\{[^}]*sourceType:\s*\"module\"",
        eslint_config,
        re.DOTALL,
    )
    if len(blocks) != 1:
        raise GenError(
            "cannot find the single ES-module files block in eslint.config.cjs"
        )
    return re.findall(r"[\"']([^\"']+)[\"']", blocks[0])


def extract_ci(rendered: dict[str, str]) -> dict[str, Any]:
    test = rendered[".github/workflows/test.yml"]
    pre_commit = rendered[".github/workflows/pre-commit.yml"]
    images = sorted(set(re.findall(r"container:\s*(\S+:\S+)", test)))
    by_flavor = {}
    for image in images:
        match = re.search(r"/py(\d+(?:\.\d+)?)-(odoo|ocb)(\d+\.\d+):", image)
        if not match:
            raise GenError(f"unexpected CI image name {image}")
        by_flavor[match[2]] = {"image": image, "python": match[1]}
    pythons = {value["python"] for value in by_flavor.values()}
    if len(pythons) != 1:
        raise GenError(f"CI images disagree on the runtime Python: {sorted(pythons)}")
    postgres = re.search(r"postgres:\n\s+image:\s*(\S+)", test)
    pre_commit_python = re.search(r'python-version:\s*"([^"]+)"', pre_commit)
    if not (postgres and pre_commit_python):
        raise GenError(
            "cannot read the PostgreSQL image or the pre-commit job's Python"
        )
    return {
        "images": by_flavor,
        "postgres_image": postgres[1],
        "pre_commit_python": pre_commit_python[1],
        "pre_commit_skip": sorted(set(CI_SKIP_RE.findall(pre_commit))),
        "runtime_python": pythons.pop(),
    }


def _walk(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key in sorted(value):
            segment = (
                key if re.fullmatch(r"[A-Za-z_][\w-]*", key) else f"[{json.dumps(key)}]"
            )
            if path and not segment.startswith("["):
                segment = "." + segment
            yield from _walk(value[key], path + segment)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            label = (
                json.dumps(item["key"])
                if isinstance(item, dict) and "key" in item
                else index
            )
            yield from _walk(item, f"{path}[{label}]")
    elif isinstance(value, str):
        yield path, value


# --------------------------------------------------------------------------------------
# Assembly.


def build_series(
    template_dir: Path,
    tag: str,
    commit: str | None,
    series: str,
    cache: Path | None,
    offline: bool,
    variant: str = "",
) -> dict[str, Any]:
    env = make_env(template_dir)
    questions = parse_yaml(
        (template_dir / "copier.yml").read_text(encoding="utf-8"), "copier.yml"
    )
    answers = copier_answers(env, questions, series, variant)
    wanted = (*MANAGED_FILES, *REFERENCE_FILES, *CI_WORKFLOWS)
    rendered = render_tree(env, template_dir, answers, wanted)
    for name in wanted:
        if name not in rendered:
            raise GenError(f"{series}: the template no longer renders {name}")
    config = parse_yaml(
        rendered[".pre-commit-config.yaml"], f"{series}/.pre-commit-config.yaml"
    )
    revs = repo_revs(env, template_dir, answers)
    ci = extract_ci(rendered)
    hooks, tools = extract_hooks(config, cache, offline, set(ci["pre_commit_skip"]))
    for rev_key, (tool_key, ecosystem, package) in UNUSED_REV_TOOLS.items():
        if rev_key in revs and tool_key not in tools:
            version = _version(revs[rev_key])
            tools[tool_key] = {
                "ecosystem": ecosystem,
                "package": package,
                "provides_hooks": [],
                "requirement": f"{package}=={version}",
                "source": {"template_rev": rev_key},
                "used": False,
                "version": version,
            }
    for tool_key, (ecosystem, package, note) in UNPINNED_TOOLS.items():
        tools.setdefault(
            tool_key,
            {
                "ecosystem": ecosystem,
                "note": note,
                "package": package,
                "provides_hooks": [],
                "requirement": package,
                "source": None,
                "used": False,
                "version": None,
            },
        )
    ruff = tomllib.loads(rendered[".ruff.toml"])
    language = config.get("default_language_version") or {}
    data: dict[str, Any] = {
        "_doc": DOC,
        "answers": {key: answers[key] for key in sorted(answers)},
        "ci": ci,
        "deviations": [],
        "eslint_esm_globs": extract_esm_globs(rendered["eslint.config.cjs"]),
        "exclude": extract_exclude(config["exclude"]),
        "files": {name: rendered[name] for name in MANAGED_FILES},
        "hooks": hooks,
        "node": {"default_language_version": str(language.get("node"))},
        "pylint": extract_pylint(rendered),
        "python": {
            "default_language_version": language.get("python"),
            "pre_commit_ci_python": ci["pre_commit_python"],
            "ruff_target_version": ruff.get("target-version"),
            "runtime_python": ci["runtime_python"],
        },
        "reference_files": {name: rendered[name] for name in REFERENCE_FILES},
        "ruff": ruff,
        "schema_version": SCHEMA_VERSION,
        "series": series,
        "template": {"commit": commit, "repo": TEMPLATE_REPO, "tag": tag},
        "template_revs": revs,
        "tools": {key: tools[key] for key in sorted(tools)},
    }
    data["placeholders"] = _placeholders(data, questions, variant)
    return data


def _placeholders(
    data: dict[str, Any], questions: dict[str, Any], variant: str
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    strings = list(
        _walk({k: v for k, v in data.items() if k not in ("_doc", "answers")}, "")
    )
    for name in PLACEHOLDER_QUESTIONS:
        token = placeholder(name, variant)
        spec = questions.get(name) or {}
        result[token] = {
            "oca_default": spec.get("default"),
            "question": name,
            "used_in": [path for path, text in strings if token in text],
        }
    return result


def check_placeholders(primary: dict[str, Any], alternate: dict[str, Any]) -> None:
    """Every answer-dependent byte must sit inside a placeholder token.

    The series is rendered twice with different tokens; mapping the first rendering's
    tokens onto the second's must reproduce the second exactly. A transformed answer
    (for example ``org_slug | lower``) would break that and is reported.
    """
    text = json.dumps(primary, sort_keys=True)
    for name in PLACEHOLDER_QUESTIONS:
        text = text.replace(placeholder(name), placeholder(name, "__alt"))
    if text != json.dumps(alternate, sort_keys=True):
        raise GenError(
            f"{primary['series']}: an organisation-specific answer reaches the output in a "
            "form other than its placeholder token"
        )


def _git(template_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(template_dir), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def template_commit(template_dir: Path, tag: str) -> str | None:
    """The checkout's commit, after checking it is the tag; None for a tarball."""
    if not (template_dir / ".git").exists():
        return None
    head = _git(template_dir, "rev-parse", "HEAD")
    tagged = _git(template_dir, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if head != tagged:
        raise GenError(f"{template_dir} is at {head}, not at tag {tag} ({tagged})")
    return head


def render_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "template", type=Path, help="checkout of OCA/oca-addons-repo-template at TAG"
    )
    parser.add_argument("tag", help="the template tag checked out, e.g. v1.48")
    parser.add_argument("--series", nargs="+", default=list(DEFAULT_SERIES))
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help=f"default: {DEFAULT_OUT}"
    )
    parser.add_argument("--cache", type=Path, help="directory caching hook manifests")
    parser.add_argument(
        "--offline", action="store_true", help="read hook manifests only from --cache"
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if any output file would change"
    )
    args = parser.parse_args(argv)
    if args.offline and not args.cache:
        parser.error("--offline needs --cache")
    template_dir = args.template.resolve()
    try:
        commit = template_commit(template_dir, args.tag)
        stale = []
        for series in args.series:
            data = build_series(
                template_dir, args.tag, commit, series, args.cache, args.offline
            )
            alternate = build_series(
                template_dir,
                args.tag,
                commit,
                series,
                args.cache,
                args.offline,
                "__alt",
            )
            check_placeholders(data, alternate)
            target = args.out / f"{series}.json"
            body = render_json(data)
            current = target.read_text(encoding="utf-8") if target.is_file() else None
            if args.check:
                if current != body:
                    stale.append(str(target))
                continue
            if current != body:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
                print(f"wrote {target}")
            else:
                print(f"unchanged {target}")
    except GenError as error:
        print(f"gen_series_data: {error}", file=sys.stderr)
        return 1
    if stale:
        print("stale series data: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
