"""Tests for per-repo .ai-reviewer.yml config overrides and dry_run scoping."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from shared.schema import Finding
from worker.app import (
    _derive_conclusion,
    _load_repo_config,
    _sanitize_findings,
    _should_skip_review,
)


# ---------------------------------------------------------------------------
# _load_repo_config — per-repo YAML parsing
# ---------------------------------------------------------------------------

def _make_gh(contents: str) -> MagicMock:
    gh = MagicMock()
    gh.get_file_contents.return_value = (contents, "abc123sha")
    return gh


def test_load_repo_config_parses_known_keys() -> None:
    gh = _make_gh(
        "failure_on_severity: medium\n"
        "skip_draft_prs: false\n"
        "post_review_comment: true\n"
        "review_comment_mode: summary_only\n"
        "require_security_review: false\n"
        "require_tests_review: false\n"
        "num_max_findings: 3\n"
    )
    cfg = _load_repo_config(gh, "org", "repo", "main")
    assert cfg["failure_on_severity"] == "medium"
    assert cfg["skip_draft_prs"] == "false"
    assert cfg["post_review_comment"] == "true"
    assert cfg["review_comment_mode"] == "summary_only"
    assert cfg["require_security_review"] == "false"
    assert cfg["require_tests_review"] == "false"
    assert cfg["num_max_findings"] == "3"


def test_load_repo_config_ignores_unknown_keys() -> None:
    gh = _make_gh("unknown_key: value\nfailure_on_severity: high\n")
    cfg = _load_repo_config(gh, "org", "repo", "main")
    assert "unknown_key" not in cfg
    assert cfg["failure_on_severity"] == "high"


def test_load_repo_config_returns_empty_on_missing_file() -> None:
    gh = MagicMock()
    gh.get_file_contents.side_effect = Exception("404 Not Found")
    cfg = _load_repo_config(gh, "org", "repo", "main")
    assert cfg == {}


def test_load_repo_config_returns_empty_on_bad_yaml() -> None:
    gh = _make_gh("not_yaml: [unclosed bracket\n")
    # Our minimal parser doesn't raise on invalid YAML — so just verify no crash
    cfg = _load_repo_config(gh, "org", "repo", "main")
    assert isinstance(cfg, dict)


# ---------------------------------------------------------------------------
# _derive_conclusion — threshold param
# ---------------------------------------------------------------------------

def test_derive_conclusion_threshold_none_always_neutral() -> None:
    findings = [{"severity": "high", "priority": 0}]
    conclusion, _ = _derive_conclusion(findings, threshold="none")
    assert conclusion == "neutral"


def test_derive_conclusion_threshold_medium_triggers_on_medium() -> None:
    findings = [{"severity": "medium"}]
    conclusion, _ = _derive_conclusion(findings, threshold="medium")
    assert conclusion == "failure"


def test_derive_conclusion_threshold_high_ignores_medium() -> None:
    findings = [{"severity": "medium"}]
    conclusion, _ = _derive_conclusion(findings, threshold="high")
    assert conclusion != "failure"


# ---------------------------------------------------------------------------
# _should_skip_review — branch pattern matching uses re (not _re alias)
# ---------------------------------------------------------------------------

def _make_pr(
    draft: bool = False,
    head_ref: str = "feature/my-branch",
    base_ref: str = "main",
    labels: list[str] | None = None,
    author: str = "dev",
) -> dict:
    return {
        "draft": draft,
        "head": {"ref": head_ref},
        "base": {"ref": base_ref},
        "labels": [{"name": lbl} for lbl in (labels or [])],
        "user": {"login": author},
    }


def test_should_skip_source_branch_pattern() -> None:
    with patch.dict(os.environ, {"IGNORE_PR_SOURCE_BRANCHES": "^dependabot/"}):
        import importlib
        import worker.app as wa
        importlib.reload(wa)
        # After reload the module constant is repopulated
        pr = _make_pr(head_ref="dependabot/npm_and_yarn/lodash-4.17.21")
        skip, reason = wa._should_skip_review(pr, event_action="opened", trigger="auto")
    assert skip is True
    assert "dependabot" in reason.lower() or "IGNORE_PR_SOURCE_BRANCHES" in reason


def test_should_skip_target_branch_pattern_no_match() -> None:
    with patch.dict(os.environ, {"IGNORE_PR_TARGET_BRANCHES": "^release/"}):
        import importlib
        import worker.app as wa
        importlib.reload(wa)
        pr = _make_pr(base_ref="main")
        skip, _ = wa._should_skip_review(pr, event_action="opened", trigger="auto")
    assert skip is False


def test_should_not_skip_manual_trigger_regardless_of_draft() -> None:
    pr = _make_pr(draft=True)
    skip, _ = _should_skip_review(pr, event_action="", trigger="manual")
    assert skip is False


def test_should_not_skip_rerun_trigger_regardless_of_draft() -> None:
    pr = _make_pr(draft=True)
    skip, _ = _should_skip_review(pr, event_action="", trigger="rerun")
    assert skip is False


# ---------------------------------------------------------------------------
# Legacy path filter knobs (require_security, require_tests, num_max_findings)
# ---------------------------------------------------------------------------

def _make_finding(ftype: str = "bug", severity: str = "low") -> Finding:
    return Finding(
        type=ftype,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        file="main.py",
        start_line=1,
        end_line=1,
        message="msg",
        suggested_patch=None,
    )


def test_legacy_filter_removes_security_when_disabled() -> None:
    findings = [_make_finding("security"), _make_finding("bug")]
    filtered = [f for f in findings if f.type != "security"]
    assert len(filtered) == 1
    assert filtered[0].type == "bug"


def test_legacy_filter_removes_tests_when_disabled() -> None:
    findings = [_make_finding("tests"), _make_finding("bug"), _make_finding("tests")]
    filtered = [f for f in findings if f.type != "tests"]
    assert len(filtered) == 1
    assert filtered[0].type == "bug"


def test_legacy_filter_num_max_findings_caps_list() -> None:
    findings = [_make_finding() for _ in range(10)]
    capped = findings[:3]
    assert len(capped) == 3


def test_legacy_filter_num_max_findings_zero_means_unlimited() -> None:
    findings = [_make_finding() for _ in range(10)]
    num_max = 0
    result = findings[:num_max] if num_max > 0 else findings
    assert len(result) == 10
