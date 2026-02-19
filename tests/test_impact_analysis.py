"""Tests for the impact analysis Lambda (impact_analysis/app.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from impact_analysis.app import (
    _compute_risk_score,
    _format_pr_comment,
    _retrieve_coverage_for_file,
    _retrieve_symbols_for_file,
    lambda_handler,
    run_impact_analysis,
)


# ---------------------------------------------------------------------------
# _compute_risk_score
# ---------------------------------------------------------------------------

class TestComputeRiskScore:
    def test_high_many_callers(self) -> None:
        assert _compute_risk_score(5, []) == "high"

    def test_high_low_coverage(self) -> None:
        gaps = [{"coverage_pct": 40.0}] * 2
        assert _compute_risk_score(1, gaps) == "high"

    def test_medium_few_callers(self) -> None:
        assert _compute_risk_score(2, []) == "medium"

    def test_medium_one_gap(self) -> None:
        assert _compute_risk_score(1, [{"coverage_pct": 30.0}]) == "medium"

    def test_low(self) -> None:
        assert _compute_risk_score(0, []) == "low"

    def test_low_high_coverage_gap(self) -> None:
        # A gap with good coverage (90%) does not count as low-coverage,
        # and 1 caller alone does not reach the "medium" threshold of 2+.
        assert _compute_risk_score(1, [{"coverage_pct": 90.0}]) == "low"


# ---------------------------------------------------------------------------
# _format_pr_comment
# ---------------------------------------------------------------------------

class TestFormatPrComment:
    def test_contains_risk_label(self) -> None:
        result = {
            "risk_score": "high",
            "changed_files": ["src/auth.py"],
            "impacted_callers": [{"title": "login_view", "uri": "src/api.py"}],
            "recommended_tests": ["tests/test_auth.py"],
            "coverage_gaps": [{"file": "src/auth.py", "coverage_pct": 45.0, "uncovered_functions": []}],
        }
        comment = _format_pr_comment(result)
        assert "HIGH" in comment
        assert "login_view" in comment
        assert "tests/test_auth.py" in comment
        assert "45.0%" in comment

    def test_unknown_risk_handled(self) -> None:
        result = {
            "risk_score": "unknown",
            "changed_files": [],
            "impacted_callers": [],
            "recommended_tests": [],
            "coverage_gaps": [],
        }
        comment = _format_pr_comment(result)
        assert "UNKNOWN" in comment


# ---------------------------------------------------------------------------
# KB retrieval helpers (unit-level with mocked KB)
# ---------------------------------------------------------------------------

class TestRetrieveSymbolsForFile:
    def test_filters_by_path(self) -> None:
        kb = MagicMock()
        kb.retrieve.return_value = [
            {"text": "File: src/auth.py\nSymbol: verify_token", "uri": "s3://bucket/src/auth.py.json", "title": "verify_token (function)", "score": 0.9},
            {"text": "File: src/other.py\nSymbol: something_else", "uri": "s3://bucket/src/other.py", "title": "something_else", "score": 0.8},
        ]
        results = _retrieve_symbols_for_file(kb, "owner/repo", "src/auth.py")
        # Should only include the auth.py result
        assert len(results) == 1
        assert "verify_token" in results[0]["text"]

    def test_empty_kb_results(self) -> None:
        kb = MagicMock()
        kb.retrieve.return_value = []
        results = _retrieve_symbols_for_file(kb, "owner/repo", "src/missing.py")
        assert results == []


class TestRetrieveCoverageForFile:
    def test_parses_coverage_pct(self) -> None:
        kb = MagicMock()
        kb.retrieve.return_value = [
            {
                "text": "File: src/auth.py\nLine coverage: 45.0% (9/20 lines) — low\nUntested functions: refresh_token",
                "uri": "s3://bucket/coverage/owner/repo/main/src/auth.py.json",
                "title": "Coverage: auth.py",
                "score": 0.95,
            }
        ]
        cov = _retrieve_coverage_for_file(kb, "owner/repo", "src/auth.py")
        assert cov is not None
        assert cov["coverage_pct"] == pytest.approx(45.0)
        assert "refresh_token" in cov["uncovered_functions"]

    def test_no_coverage_returns_none(self) -> None:
        kb = MagicMock()
        kb.retrieve.return_value = [
            {"text": "Just a code snippet with no coverage info", "uri": "s3://x", "title": "t", "score": 0.5}
        ]
        cov = _retrieve_coverage_for_file(kb, "owner/repo", "src/auth.py")
        assert cov is None


# ---------------------------------------------------------------------------
# run_impact_analysis (integration with mocked KB + LLM)
# ---------------------------------------------------------------------------

class TestRunImpactAnalysis:
    def _make_kb(self) -> MagicMock:
        kb = MagicMock()
        kb.retrieve.return_value = [
            {
                "text": "File: src/auth.py\nSymbol: verify_token (function)\nLine coverage: 80.0%",
                "uri": "s3://bucket/repos/owner/repo/main/src/auth.py.verify_token.json",
                "title": "verify_token (function)",
                "score": 0.9,
            }
        ]
        return kb

    @patch("impact_analysis.app.BedrockChatClient")
    def test_returns_structure(self, mock_chat_cls: MagicMock) -> None:
        mock_chat = MagicMock()
        mock_chat.answer.return_value = '["tests/test_auth.py"]'
        mock_chat_cls.return_value = mock_chat

        kb = self._make_kb()
        result = run_impact_analysis(
            repo="owner/repo",
            ref="main",
            files_changed=["src/auth.py"],
            model_id="anthropic.claude-3-5-sonnet",
            region="us-east-1",
            kb=kb,
        )

        assert result["status"] == "ok"
        assert result["repo"] == "owner/repo"
        assert "changed_files" in result
        assert "changed_symbols" in result
        assert "impacted_callers" in result
        assert "recommended_tests" in result
        assert "risk_score" in result
        assert result["risk_score"] in ("low", "medium", "high")

    @patch("impact_analysis.app.BedrockChatClient")
    def test_empty_files_not_called(self, mock_chat_cls: MagicMock) -> None:
        kb = MagicMock()
        kb.retrieve.return_value = []
        mock_chat = MagicMock()
        mock_chat.answer.return_value = "[]"
        mock_chat_cls.return_value = mock_chat

        result = run_impact_analysis(
            repo="owner/repo",
            ref="main",
            files_changed=[],
            model_id="m",
            region="us-east-1",
            kb=kb,
        )
        assert result["changed_files"] == []
        assert result["risk_score"] == "low"

    @patch("impact_analysis.app.BedrockChatClient")
    def test_llm_failure_graceful(self, mock_chat_cls: MagicMock) -> None:
        mock_chat = MagicMock()
        mock_chat.answer.side_effect = RuntimeError("timeout")
        mock_chat_cls.return_value = mock_chat

        kb = MagicMock()
        kb.retrieve.return_value = []

        result = run_impact_analysis(
            repo="owner/repo",
            ref="main",
            files_changed=["src/auth.py"],
            model_id="m",
            region="us-east-1",
            kb=kb,
        )
        # Should still return a valid structure even when LLM fails
        assert result["status"] == "ok"
        assert isinstance(result["recommended_tests"], list)


# ---------------------------------------------------------------------------
# lambda_handler
# ---------------------------------------------------------------------------

class TestLambdaHandler:
    def _event(self, body: dict) -> dict:
        return {
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps(body),
        }

    def test_missing_repo_returns_400(self) -> None:
        resp = lambda_handler(self._event({"files_changed": ["src/a.py"]}), None)
        assert resp["statusCode"] == 400

    def test_missing_files_changed_returns_400(self) -> None:
        resp = lambda_handler(self._event({"repo": "o/r"}), None)
        assert resp["statusCode"] == 400

    def test_empty_files_changed_returns_400(self) -> None:
        resp = lambda_handler(self._event({"repo": "o/r", "files_changed": []}), None)
        assert resp["statusCode"] == 400

    def test_no_kb_configured_returns_503(self) -> None:
        # BEDROCK_KNOWLEDGE_BASE_ID is not in env
        resp = lambda_handler(self._event({"repo": "o/r", "files_changed": ["src/a.py"]}), None)
        assert resp["statusCode"] == 503

    def test_get_returns_405(self) -> None:
        event = {"requestContext": {"http": {"method": "GET"}}, "body": "{}"}
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 405

    def test_invalid_json_returns_400(self) -> None:
        event = {"requestContext": {"http": {"method": "POST"}}, "body": "bad json"}
        resp = lambda_handler(event, None)
        assert resp["statusCode"] == 400

    @patch("impact_analysis.app.BedrockKnowledgeBaseClient")
    @patch("impact_analysis.app.BedrockChatClient")
    @patch.dict("os.environ", {"BEDROCK_KNOWLEDGE_BASE_ID": "kb-id", "BEDROCK_MODEL_ID": "m"})
    def test_successful_analysis(self, mock_chat_cls: MagicMock, mock_kb_cls: MagicMock) -> None:
        mock_chat = MagicMock()
        mock_chat.answer.return_value = '["tests/test_auth.py"]'
        mock_chat_cls.return_value = mock_chat

        mock_kb = MagicMock()
        mock_kb.retrieve.return_value = []
        mock_kb_cls.return_value = mock_kb

        resp = lambda_handler(
            self._event({"repo": "owner/repo", "ref": "main", "files_changed": ["src/auth.py"]}),
            None,
        )
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "ok"
        assert "risk_score" in body
