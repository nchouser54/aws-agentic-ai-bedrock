"""Tests for the sprint report agent Lambda."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from sprint_report.app import (
    _build_user_prompt,
    _fetch_github_activity,
    _fetch_jira_sprint_data,
    generate_report,
    lambda_handler,
)


# -- Helpers -------------------------------------------------------------------


def _mock_gh() -> MagicMock:
    gh = MagicMock()
    gh.list_pulls.return_value = [
        {
            "number": 10, "title": "feat: add login",
            "merged_at": "2024-06-01T12:00:00Z",
            "user": {"login": "dev1"},
        },
    ]
    gh.list_commits.return_value = [
        {
            "sha": "abc12345",
            "commit": {"message": "fix: bug", "author": {"name": "dev1", "date": "2024-06-01"}},
            "author": {"login": "dev1"},
        },
    ]
    return gh


def _jira_data() -> list[dict[str, Any]]:
    return [
        {
            "key": "PROJ-1", "summary": "Login page", "status": "In Progress",
            "status_category": "indeterminate", "type": "Story", "assignee": "dev1", "priority": "High",
        },
        {
            "key": "PROJ-2", "summary": "Logout bug", "status": "Done",
            "status_category": "done", "type": "Bug", "assignee": "dev2", "priority": "Medium",
        },
    ]


# -- Unit tests ----------------------------------------------------------------


def test_build_user_prompt_standup() -> None:
    github_activity = {
        "merged_prs": [{"number": "10", "title": "feat", "author": "dev1", "merged_at": "2024-06-01"}],
        "commits": [{"sha": "abc12345", "message": "fix", "author": "dev1", "date": "2024-06-01"}],
    }
    prompt = _build_user_prompt("standup", "org/repo", _jira_data(), github_activity, 1)
    assert "standup" in prompt.lower()
    assert "PROJ-1" in prompt
    assert "org/repo" in prompt


def test_build_user_prompt_sprint() -> None:
    github_activity = {"merged_prs": [], "commits": []}
    prompt = _build_user_prompt("sprint", "org/repo", _jira_data(), github_activity, 7)
    assert "sprint" in prompt.lower()
    assert "PROJ-2" in prompt


def test_fetch_github_activity() -> None:
    gh = _mock_gh()
    activity = _fetch_github_activity(gh, "o", "r", "2024-06-01T00:00:00Z")
    assert len(activity["merged_prs"]) == 1
    assert len(activity["commits"]) == 1
    gh.list_pulls.assert_called_once()
    gh.list_commits.assert_called_once()


def test_fetch_jira_sprint_data() -> None:
    mock_atlassian = MagicMock()
    mock_atlassian.search_jira.return_value = [
        {
            "key": "PROJ-1",
            "fields": {
                "summary": "Login page",
                "status": {"name": "In Progress", "statusCategory": {"name": "indeterminate"}},
                "issuetype": {"name": "Story"},
                "assignee": {"displayName": "Dev One"},
                "priority": {"name": "High"},
            },
        }
    ]
    data = _fetch_jira_sprint_data(mock_atlassian, "project = PROJ")
    assert len(data) == 1
    assert data[0]["key"] == "PROJ-1"


@patch("sprint_report.app.BedrockChatClient")
@patch("sprint_report.app.AtlassianClient")
@patch("sprint_report.app.GitHubAppAuth")
def test_generate_report(mock_auth_cls: MagicMock, mock_atlassian_cls: MagicMock, mock_chat_cls: MagicMock) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "## Daily Standup Report\n\n**Done:** Login page"
    mock_chat_cls.return_value = mock_chat

    mock_atlassian = MagicMock()
    mock_atlassian.search_jira.return_value = []
    mock_atlassian_cls.return_value = mock_atlassian

    gh = _mock_gh()
    report = generate_report(
        gh=gh,
        owner="org",
        repo="repo",
        atlassian=mock_atlassian,
        jql="project = PROJ",
        report_type="standup",
        days_back=1,
        model_id="claude",
        region="us-gov-west-1",
    )
    assert "Standup" in report or "standup" in report.lower() or len(report) > 0
    mock_chat.answer.assert_called_once()


@patch("sprint_report.app.BedrockChatClient")
@patch("sprint_report.app.AtlassianClient")
@patch("sprint_report.app.GitHubClient")
@patch("sprint_report.app.GitHubAppAuth")
def test_lambda_handler_api_gateway(
    mock_auth_cls: MagicMock, mock_gh_cls: MagicMock,
    mock_atlassian_cls: MagicMock, mock_chat_cls: MagicMock,
) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "Report content"
    mock_chat_cls.return_value = mock_chat
    mock_atlassian = MagicMock()
    mock_atlassian.search_jira.return_value = []
    mock_atlassian_cls.return_value = mock_atlassian
    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth
    gh = MagicMock()
    gh.list_pulls.return_value = []
    gh.list_commits.return_value = []
    mock_gh_cls.return_value = gh

    with patch.dict("os.environ", {
        "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
        "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:atlas",
        "BEDROCK_MODEL_ID": "claude",
    }):
        event = {
            "requestContext": {"http": {"method": "POST"}},
            "body": json.dumps({
                "repo": "org/repo",
                "jira_project": "PROJ",
                "report_type": "standup",
            }),
        }
        result = lambda_handler(event, None)
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["report_type"] == "standup"


def test_lambda_handler_bad_method() -> None:
    event = {"requestContext": {"http": {"method": "GET"}}, "body": "{}"}
    result = lambda_handler(event, None)
    assert result["statusCode"] == 405


def test_lambda_handler_missing_fields() -> None:
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps({}),
    }
    with patch.dict("os.environ", {
        "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
        "BEDROCK_MODEL_ID": "claude",
    }):
        result = lambda_handler(event, None)
    assert result["statusCode"] == 400
