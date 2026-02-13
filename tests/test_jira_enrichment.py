"""Tests for worker Jira enrichment: key extraction, context fetching, prompt integration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from worker.app import _build_prompt, _extract_jira_keys, _fetch_jira_context


# -- _extract_jira_keys ------------------------------------------------------

def test_extract_jira_keys_from_title() -> None:
    pr = {"title": "ENG-123 fix login", "body": "", "head": {"ref": "feature/login"}}
    assert _extract_jira_keys(pr) == ["ENG-123"]


def test_extract_jira_keys_from_branch() -> None:
    pr = {"title": "fix stuff", "body": "", "head": {"ref": "feature/ENG-456-login-fix"}}
    assert _extract_jira_keys(pr) == ["ENG-456"]


def test_extract_jira_keys_from_body() -> None:
    pr = {"title": "update", "body": "Closes PROJ-10 and PROJ-20", "head": {"ref": "main"}}
    assert _extract_jira_keys(pr) == ["PROJ-10", "PROJ-20"]


def test_extract_jira_keys_deduplicates() -> None:
    pr = {"title": "ENG-1 fix", "body": "Relates to ENG-1", "head": {"ref": "ENG-1-fix"}}
    assert _extract_jira_keys(pr) == ["ENG-1"]


def test_extract_jira_keys_none_found() -> None:
    pr = {"title": "fix typo", "body": "small change", "head": {"ref": "fix-typo"}}
    assert _extract_jira_keys(pr) == []


def test_extract_jira_keys_mixed_sources() -> None:
    pr = {
        "title": "ENG-100 implement feature",
        "body": "Also see DEVOPS-50",
        "head": {"ref": "feature/ENG-100-new-thing"},
    }
    keys = _extract_jira_keys(pr)
    assert keys == ["ENG-100", "DEVOPS-50"]


# -- _fetch_jira_context -----------------------------------------------------

@patch("worker.app.AtlassianClient")
def test_fetch_jira_context_success(mock_cls) -> None:
    mock_client = MagicMock()
    mock_client.get_jira_issue.return_value = {
        "key": "ENG-1",
        "fields": {
            "summary": "Fix login",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Bug"},
            "description": "User cannot log in",
        },
    }
    mock_cls.return_value = mock_client

    issues = _fetch_jira_context(["ENG-1"], "arn:fake:secret")
    assert len(issues) == 1
    assert issues[0]["key"] == "ENG-1"
    assert issues[0]["summary"] == "Fix login"
    assert issues[0]["type"] == "Bug"


@patch("worker.app.AtlassianClient")
def test_fetch_jira_context_skips_failures(mock_cls) -> None:
    mock_client = MagicMock()
    mock_client.get_jira_issue.side_effect = RuntimeError("API error")
    mock_cls.return_value = mock_client

    issues = _fetch_jira_context(["ENG-1"], "arn:fake:secret")
    assert issues == []


def test_fetch_jira_context_empty_keys() -> None:
    assert _fetch_jira_context([], "arn:fake") == []


def test_fetch_jira_context_no_secret_arn() -> None:
    assert _fetch_jira_context(["ENG-1"], "") == []


@patch("worker.app.AtlassianClient")
def test_fetch_jira_context_limits_to_max(mock_cls) -> None:
    mock_client = MagicMock()
    mock_client.get_jira_issue.return_value = {
        "key": "X-1",
        "fields": {"summary": "s", "status": {"name": "Open"}, "issuetype": {"name": "Task"}},
    }
    mock_cls.return_value = mock_client

    keys = [f"ENG-{i}" for i in range(20)]
    issues = _fetch_jira_context(keys, "arn:fake", max_issues=3)
    assert len(issues) == 3


# -- _build_prompt with Jira context -----------------------------------------

def test_build_prompt_without_jira() -> None:
    pr = {"title": "fix", "body": "", "base": {"ref": "main"}, "head": {"ref": "fix"}}
    prompt = json.loads(_build_prompt(pr, []))
    assert "linked_jira_issues" not in prompt
    # Hard rules should not mention Jira
    assert not any("Jira" in r for r in prompt["hard_rules"])


def test_build_prompt_with_jira() -> None:
    pr = {"title": "ENG-1 fix", "body": "", "base": {"ref": "main"}, "head": {"ref": "fix"}}
    jira_issues = [{"key": "ENG-1", "summary": "Fix login", "type": "Bug", "status": "Open", "description": "..."}]
    prompt = json.loads(_build_prompt(pr, [], jira_issues=jira_issues))
    assert prompt["linked_jira_issues"] == jira_issues
    # Hard rules should include Jira verification
    assert any("Jira" in r for r in prompt["hard_rules"])
