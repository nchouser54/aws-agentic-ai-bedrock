"""Language-aware source code parser for Knowledge Base ingestion.

Extracts per-symbol (function, class, method) documents from source files,
enriching the Bedrock KB with fine-grained, searchable entries rather than
whole-file blobs.

Supports:
- Python  — stdlib ``ast`` module (accurate)
- JS / TS  — regex heuristics
- Go       — regex heuristics
- Java / Kotlin — regex heuristics
- Other    — single file-level fallback doc
"""

from __future__ import annotations

import ast
import hashlib
import re
import textwrap
from dataclasses import dataclass, field
from typing import Literal

Language = Literal["python", "javascript", "typescript", "go", "java", "kotlin", "other"]

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SymbolDoc:
    """Represents a single extracted symbol (function / class / method)."""

    symbol_type: Literal["function", "class", "method", "file"]
    symbol_name: str
    signature: str
    docstring: str
    line_start: int
    line_end: int
    language: Language
    body_snippet: str  # first ~30 lines of the body


@dataclass
class ParsedFile:
    """Result of parsing one source file."""

    language: Language
    symbols: list[SymbolDoc] = field(default_factory=list)
    """Empty when the file produces only a file-level doc."""


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_EXT_MAP: dict[str, Language] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
}


def detect_language(filename: str) -> Language:
    """Return the language for a filename based on its extension."""
    dot = filename.rfind(".")
    if dot == -1:
        return "other"
    return _EXT_MAP.get(filename[dot:].lower(), "other")


# ---------------------------------------------------------------------------
# Python parser (ast-based)
# ---------------------------------------------------------------------------

_SNIPPET_LINES = 30


def _first_n_lines(lines: list[str], start: int, n: int = _SNIPPET_LINES) -> str:
    """Return up to *n* lines of source starting at 0-based *start*."""
    return "\n".join(lines[start : start + n])


def _python_docstring(node: ast.AST) -> str:
    return ast.get_docstring(node) or ""


def _python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef, source_lines: list[str]) -> str:
    """Reconstruct the ``def`` line(s) as the signature."""
    # node.lineno is 1-based
    idx = node.lineno - 1
    raw = source_lines[idx].strip()
    # walk forward while the def line is not yet closed
    end = idx
    while end < len(source_lines) - 1 and not raw.endswith(":"):
        end += 1
        raw += " " + source_lines[end].strip()
    return raw


def _parse_python(source: str) -> list[SymbolDoc]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    docs: list[SymbolDoc] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            docs.append(
                SymbolDoc(
                    symbol_type="class",
                    symbol_name=node.name,
                    signature=f"class {node.name}",
                    docstring=_python_docstring(node),
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    language="python",
                    body_snippet=_first_n_lines(lines, node.lineno - 1),
                )
            )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    docs.append(
                        SymbolDoc(
                            symbol_type="method",
                            symbol_name=f"{node.name}.{item.name}",
                            signature=_python_signature(item, lines),
                            docstring=_python_docstring(item),
                            line_start=item.lineno,
                            line_end=item.end_lineno or item.lineno,
                            language="python",
                            body_snippet=_first_n_lines(lines, item.lineno - 1),
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Only top-level functions here (methods handled above)
            # Check if parent is a class (skip; already captured above)
            docs.append(
                SymbolDoc(
                    symbol_type="function",
                    symbol_name=node.name,
                    signature=_python_signature(node, lines),
                    docstring=_python_docstring(node),
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    language="python",
                    body_snippet=_first_n_lines(lines, node.lineno - 1),
                )
            )

    # Deduplicate — methods appear in both the outer walk and the class body walk
    seen: set[tuple[str, int]] = set()
    unique: list[SymbolDoc] = []
    for d in docs:
        key = (d.symbol_name, d.line_start)
        if key not in seen:
            seen.add(key)
            unique.append(d)

    return unique


# ---------------------------------------------------------------------------
# Regex-based parsers for JS/TS/Go/Java/Kotlin
# ---------------------------------------------------------------------------

# JS/TS: function declarations, arrow functions assigned to const/let, class defs
_JS_FUNC_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
    re.MULTILINE,
)
_JS_ARROW_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(",
    re.MULTILINE,
)
_JS_CLASS_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)",
    re.MULTILINE,
)
_JS_METHOD_RE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|static|async|override)\s+)*(\w+)\s*\([^)]*\)\s*(?::\s*\w[\w<>, |]*?)?\s*\{",
    re.MULTILINE,
)

# Go
_GO_FUNC_RE = re.compile(
    r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(",
    re.MULTILINE,
)

# Java / Kotlin
_JAVA_METHOD_RE = re.compile(
    r"^[ \t]+(?:(?:public|private|protected|static|final|abstract|synchronized|override|suspend|inline|fun|void)\s+)*"
    r"(?:\w[\w<>, \[\]]*\s+)?(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+(?:,\s*\w+)*)?\s*\{",
    re.MULTILINE,
)
_JAVA_CLASS_RE = re.compile(
    r"^(?:[ \t]+)?(?:(?:public|private|protected|abstract|final|open)\s+)*(?:class|interface|enum|object)\s+(\w+)",
    re.MULTILINE,
)


def _line_of(source: str, char_offset: int) -> int:
    """Return 1-based line number for a character offset in *source*."""
    return source.count("\n", 0, char_offset) + 1


def _parse_regex(
    source: str, language: Language, patterns: list[tuple[re.Pattern[str], Literal["function", "class", "method"]]]
) -> list[SymbolDoc]:
    lines = source.splitlines()
    docs: list[SymbolDoc] = []
    for pattern, sym_type in patterns:
        for m in pattern.finditer(source):
            name = m.group(1)
            lineno = _line_of(source, m.start())
            docs.append(
                SymbolDoc(
                    symbol_type=sym_type,
                    symbol_name=name,
                    signature=lines[lineno - 1].strip() if lineno <= len(lines) else "",
                    docstring="",
                    line_start=lineno,
                    line_end=lineno,  # end unknown from one-pass regex
                    language=language,
                    body_snippet=_first_n_lines(lines, lineno - 1),
                )
            )
    return docs


def _parse_js_ts(source: str, language: Language) -> list[SymbolDoc]:
    patterns: list[tuple[re.Pattern[str], Literal["function", "class", "method"]]] = [
        (_JS_CLASS_RE, "class"),
        (_JS_FUNC_RE, "function"),
        (_JS_ARROW_RE, "function"),
        (_JS_METHOD_RE, "method"),
    ]
    return _parse_regex(source, language, patterns)


def _parse_go(source: str) -> list[SymbolDoc]:
    return _parse_regex(source, "go", [(_GO_FUNC_RE, "function")])


def _parse_java_kotlin(source: str, language: Language) -> list[SymbolDoc]:
    patterns: list[tuple[re.Pattern[str], Literal["function", "class", "method"]]] = [
        (_JAVA_CLASS_RE, "class"),
        (_JAVA_METHOD_RE, "method"),
    ]
    return _parse_regex(source, language, patterns)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_file(filename: str, source: str) -> ParsedFile:
    """Parse *source* and return a :class:`ParsedFile` with extracted symbols.

    Falls back to an empty ``ParsedFile`` (no symbols) if the language is
    unsupported; the caller should emit a single file-level KB doc in that case.
    """
    language = detect_language(filename)
    if language == "python":
        symbols = _parse_python(source)
    elif language in ("javascript", "typescript"):
        symbols = _parse_js_ts(source, language)
    elif language == "go":
        symbols = _parse_go(source)
    elif language in ("java", "kotlin"):
        symbols = _parse_java_kotlin(source, language)
    else:
        symbols = []

    return ParsedFile(language=language, symbols=symbols)


def build_symbol_text(sym: SymbolDoc, path: str) -> str:
    """Render a symbol into a human-readable block suitable as KB doc text."""
    parts = [
        f"File: {path}",
        f"Symbol: {sym.symbol_name} ({sym.symbol_type})",
        f"Lines: {sym.line_start}–{sym.line_end}",
        f"Signature: {sym.signature}",
    ]
    if sym.docstring:
        parts.append(f"\nDocstring:\n{textwrap.indent(sym.docstring, '  ')}")
    parts.append(f"\nSource snippet:\n{textwrap.indent(sym.body_snippet, '  ')}")
    return "\n".join(parts)


def symbol_doc_id(repo: str, path: str, symbol_name: str, ref: str) -> str:
    """Stable, URL-safe identifier for a symbol document."""
    raw = f"{repo}/{ref}/{path}#{symbol_name}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]
