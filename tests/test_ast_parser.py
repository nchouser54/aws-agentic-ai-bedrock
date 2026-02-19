"""Tests for the AST-aware source code parser (shared/ast_parser.py)."""

from __future__ import annotations

import pytest

from shared.ast_parser import (
    ParsedFile,
    SymbolDoc,
    build_symbol_text,
    detect_language,
    parse_file,
    symbol_doc_id,
)

# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_python(self) -> None:
        assert detect_language("src/main.py") == "python"

    def test_typescript(self) -> None:
        assert detect_language("app/index.ts") == "typescript"

    def test_tsx(self) -> None:
        assert detect_language("components/Button.tsx") == "typescript"

    def test_javascript(self) -> None:
        assert detect_language("src/utils.js") == "javascript"

    def test_go(self) -> None:
        assert detect_language("cmd/server.go") == "go"

    def test_java(self) -> None:
        assert detect_language("src/Main.java") == "java"

    def test_kotlin(self) -> None:
        assert detect_language("app/Main.kt") == "kotlin"

    def test_unknown(self) -> None:
        assert detect_language("Makefile") == "other"

    def test_no_extension(self) -> None:
        assert detect_language("Dockerfile") == "other"

    def test_case_insensitive(self) -> None:
        assert detect_language("UTILS.PY") == "python"


# ---------------------------------------------------------------------------
# Python AST parsing
# ---------------------------------------------------------------------------


_PYTHON_SOURCE = """
def add(a, b):
    \"\"\"Return a + b.\"\"\"
    return a + b


def _helper(x):
    return x * 2


class Calculator:
    \"\"\"A simple calculator.\"\"\"

    def multiply(self, a, b):
        return a * b

    def divide(self, a, b):
        if b == 0:
            raise ValueError("division by zero")
        return a / b
"""


class TestParsePython:
    def test_top_level_functions_found(self) -> None:
        result = parse_file("src/calc.py", _PYTHON_SOURCE)
        names = {s.symbol_name for s in result.symbols}
        assert "add" in names
        assert "_helper" in names

    def test_class_found(self) -> None:
        result = parse_file("src/calc.py", _PYTHON_SOURCE)
        names = {s.symbol_name for s in result.symbols}
        assert "Calculator" in names

    def test_methods_found(self) -> None:
        result = parse_file("src/calc.py", _PYTHON_SOURCE)
        names = {s.symbol_name for s in result.symbols}
        assert "Calculator.multiply" in names
        assert "Calculator.divide" in names

    def test_symbol_types_correct(self) -> None:
        result = parse_file("src/calc.py", _PYTHON_SOURCE)
        sym_map = {s.symbol_name: s for s in result.symbols}
        assert sym_map["add"].symbol_type == "function"
        assert sym_map["Calculator"].symbol_type == "class"
        assert sym_map["Calculator.multiply"].symbol_type == "method"

    def test_docstring_extracted(self) -> None:
        result = parse_file("src/calc.py", _PYTHON_SOURCE)
        sym_map = {s.symbol_name: s for s in result.symbols}
        assert "Return a + b" in sym_map["add"].docstring
        assert "simple calculator" in sym_map["Calculator"].docstring

    def test_line_numbers_positive(self) -> None:
        result = parse_file("src/calc.py", _PYTHON_SOURCE)
        for sym in result.symbols:
            assert sym.line_start > 0

    def test_language_is_python(self) -> None:
        result = parse_file("src/calc.py", _PYTHON_SOURCE)
        assert result.language == "python"

    def test_syntax_error_returns_empty(self) -> None:
        result = parse_file("bad.py", "def broken(")
        assert isinstance(result, ParsedFile)
        assert result.symbols == []

    def test_empty_source_returns_empty(self) -> None:
        result = parse_file("empty.py", "")
        assert result.symbols == []


class TestParseUnsupportedLanguage:
    def test_other_language_returns_empty_symbols(self) -> None:
        result = parse_file("notes.txt", "just plain text")
        assert result.language == "other"
        assert result.symbols == []


# ---------------------------------------------------------------------------
# JS/TS regex parsing
# ---------------------------------------------------------------------------


_JS_SOURCE = """\
export function greet(name) {
    return `Hello, ${name}`;
}

const double = (n) => n * 2;

class Greeter {
    sayHello(name) {
        return `Hello ${name}`;
    }
}
"""


class TestParseJavaScript:
    def test_function_found(self) -> None:
        result = parse_file("src/utils.js", _JS_SOURCE)
        names = {s.symbol_name for s in result.symbols}
        assert "greet" in names

    def test_class_found(self) -> None:
        result = parse_file("src/utils.js", _JS_SOURCE)
        names = {s.symbol_name for s in result.symbols}
        assert "Greeter" in names

    def test_language_javascript(self) -> None:
        result = parse_file("src/utils.js", _JS_SOURCE)
        assert result.language == "javascript"


# ---------------------------------------------------------------------------
# Go parsing
# ---------------------------------------------------------------------------

_GO_SOURCE = """\
package main

func main() {
    run()
}

func (s *Server) handleRequest(w http.ResponseWriter, r *http.Request) {
    // handle
}
"""


class TestParseGo:
    def test_top_level_func(self) -> None:
        result = parse_file("main.go", _GO_SOURCE)
        names = {s.symbol_name for s in result.symbols}
        assert "main" in names

    def test_receiver_method(self) -> None:
        result = parse_file("main.go", _GO_SOURCE)
        names = {s.symbol_name for s in result.symbols}
        assert "handleRequest" in names


# ---------------------------------------------------------------------------
# build_symbol_text
# ---------------------------------------------------------------------------


class TestBuildSymbolText:
    def test_includes_path_and_name(self) -> None:
        sym = SymbolDoc(
            symbol_type="function",
            symbol_name="my_func",
            signature="def my_func(x: int) -> str:",
            docstring="Does something.",
            line_start=10,
            line_end=20,
            language="python",
            body_snippet="def my_func(x: int) -> str:\n    return str(x)",
        )
        text = build_symbol_text(sym, "src/utils.py")
        assert "src/utils.py" in text
        assert "my_func" in text
        assert "Does something" in text
        assert "function" in text


# ---------------------------------------------------------------------------
# symbol_doc_id
# ---------------------------------------------------------------------------


class TestSymbolDocId:
    def test_stable_deterministic(self) -> None:
        id1 = symbol_doc_id("owner/repo", "src/utils.py", "my_func", "main")
        id2 = symbol_doc_id("owner/repo", "src/utils.py", "my_func", "main")
        assert id1 == id2

    def test_different_params_give_different_ids(self) -> None:
        id1 = symbol_doc_id("owner/repo", "src/utils.py", "func_a", "main")
        id2 = symbol_doc_id("owner/repo", "src/utils.py", "func_b", "main")
        assert id1 != id2

    def test_short_hex_string(self) -> None:
        doc_id = symbol_doc_id("owner/repo", "src/utils.py", "my_func", "main")
        assert len(doc_id) == 16
        assert all(c in "0123456789abcdef" for c in doc_id)
