from shared.schema import Finding
from worker.app import _select_inline_comments


def _finding() -> Finding:
    return Finding(
        type="bug",
        severity="low",
        file="main.py",
        start_line=2,
        end_line=2,
        message="Issue",
        suggested_patch=None,
    )


def _files() -> dict:
    return {
        "main.py": {
            "patch": "@@ -1,2 +1,2 @@\n a\n-b\n+x"
        }
    }


def test_review_mode_summary_only() -> None:
    comments = _select_inline_comments([_finding()], _files(), "summary_only")
    assert comments == []


def test_review_mode_best_effort() -> None:
    comments = _select_inline_comments([_finding()], _files(), "inline_best_effort")
    assert len(comments) == 1


def test_review_mode_strict_inline_suppresses_unmapped() -> None:
    bad = Finding(
        type="bug",
        severity="low",
        file="main.py",
        start_line=999,
        end_line=999,
        message="Issue",
        suggested_patch=None,
    )
    comments = _select_inline_comments([bad], _files(), "strict_inline")
    assert comments == []
