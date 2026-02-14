"""Tests for the PR description generator Lambda."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from pr_description.app import (
    _AI_SECTION_END,
    _AI_SECTION_START,
    _build_user_prompt,
    _extract_jira_keys,
    _update_pr_body,
    generate_description,
    lambda_handler,
)


# -- Jira key extraction -------------------------------------------------------


class TestExtractJiraKeys:
    def test_extracts_from_title(self) -> None:
        pr = {"title": "PROJ-123: fix login", "body": "", "head": {"ref": "feature"}}
        assert _extract_jira_keys(pr) == ["PROJ-123"]

    def test_extracts_from_body(self) -> None:
        pr = {"title": "fix login", "body": "Closes PROJ-456", "head": {"ref": "feature"}}
        assert _extract_jira_keys(pr) == ["PROJ-456"]

    def test_extracts_from_branch(self) -> None:
        pr = {"title": "fix", "body": "", "head": {"ref": "PROJ-789/fix-login"}}
        assert _extract_jira_keys(pr) == ["PROJ-789"]

    def test_deduplicates(self) -> None:
        pr = {"title": "PROJ-1: fix", "body": "See PROJ-1", "head": {"ref": "PROJ-1/fix"}}
        assert _extract_jira_keys(pr) == ["PROJ-1"]

    def test_multiple_keys(self) -> None:
        pr = {"title": "PROJ-1, PROJ-2: updates", "body": "", "head": {"ref": "feature"}}
        keys = _extract_jira_keys(pr)
        assert "PROJ-1" in keys
        assert "PROJ-2" in keys

    def test_no_keys(self) -> None:
        pr = {"title": "fix login", "body": "no tickets", "head": {"ref": "feature"}}
        assert _extract_jira_keys(pr) == []


# -- Prompt building -----------------------------------------------------------


def test_build_user_prompt() -> None:
    pr = {
        "number": 42, "title": "feat: add auth", "body": "Adds auth",
        "base": {"ref": "main"}, "head": {"ref": "feat-auth"},
    }
    files = [
        {"filename": "src/auth.py", "status": "added", "additions": 50, "deletions": 0, "patch": "+def login():"},
    ]
    commits = ["feat: add auth module", "fix: typo in auth"]
    jira = [{"key": "PROJ-1", "type": "Story", "summary": "Add auth", "status": "In Progress"}]

    prompt = _build_user_prompt(pr, files, commits, jira)
    assert "PR #42" in prompt
    assert "feat: add auth" in prompt
    assert "src/auth.py" in prompt
    assert "PROJ-1" in prompt
    assert "feat: add auth module" in prompt


def test_build_user_prompt_truncates_large_patches() -> None:
    long_patch = "+" * 3000
    files = [{"filename": "big.py", "status": "modified", "additions": 100, "deletions": 0, "patch": long_patch}]
    prompt = _build_user_prompt(
        {"number": 1, "title": "t", "body": "", "base": {"ref": "main"}, "head": {"ref": "b"}},
        files, [], [],
    )
    assert "(truncated)" in prompt


# -- Body update ---------------------------------------------------------------


class TestUpdatePrBody:
    def test_appends_section(self) -> None:
        gh = MagicMock()
        _update_pr_body(gh, "o", "r", 1, "Original description", "AI summary here")
        gh.update_pull_request.assert_called_once()
        call_kwargs = gh.update_pull_request.call_args
        new_body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body") or call_kwargs[0][3]
        assert _AI_SECTION_START in new_body
        assert "AI summary here" in new_body
        assert "Original description" in new_body

    def test_replaces_existing_section(self) -> None:
        gh = MagicMock()
        existing = f"Desc\n\n{_AI_SECTION_START}\nold summary\n{_AI_SECTION_END}\n\nfooter"
        _update_pr_body(gh, "o", "r", 1, existing, "new summary")
        call_kwargs = gh.update_pull_request.call_args
        new_body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body") or call_kwargs[0][3]
        assert "new summary" in new_body
        assert "old summary" not in new_body
        assert new_body.count(_AI_SECTION_START) == 1

    def test_handles_empty_body(self) -> None:
        gh = MagicMock()
        _update_pr_body(gh, "o", "r", 1, "", "summary")
        call_kwargs = gh.update_pull_request.call_args
        new_body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body") or call_kwargs[0][3]
        assert "summary" in new_body


# -- Generate description ------------------------------------------------------


@patch("pr_description.app.BedrockChatClient")
@patch("pr_description.app._fetch_jira_context")
def test_generate_description(mock_jira: MagicMock, mock_chat_cls: MagicMock) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "## Summary\n\nFixes login bug"
    mock_chat_cls.return_value = mock_chat
    mock_jira.return_value = []

    gh = MagicMock()
    gh.get_pull_request.return_value = {
        "number": 1, "title": "fix: login", "body": "Fixes login",
        "head": {"ref": "fix-login", "sha": "abc"}, "base": {"ref": "main"},
    }
    gh.get_pull_request_files.return_value = [
        {"filename": "src/auth.py", "status": "modified", "additions": 5, "deletions": 2, "patch": "@@ ..."},
    ]
    gh.list_pull_commits.return_value = [
        {"sha": "abc", "commit": {"message": "fix: login bug"}},
    ]

    result = generate_description(gh, "o", "r", 1, "", "claude", "us-gov-west-1")
    assert "login" in result.lower()
    mock_chat.answer.assert_called_once()


# -- Lambda handler tests ------------------------------------------------------


@patch("pr_description.app.BedrockChatClient")
@patch("pr_description.app._fetch_jira_context")
@patch("pr_description.app.GitHubAppAuth")
def test_lambda_handler_api_gateway(mock_auth_cls: MagicMock, mock_jira: MagicMock, mock_chat_cls: MagicMock) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "Generated description"
    mock_chat_cls.return_value = mock_chat
    mock_jira.return_value = []

    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth

    with patch("pr_description.app.GitHubClient") as mock_gh_cls:
        gh = MagicMock()
        gh.get_pull_request.return_value = {
            "number": 1, "title": "feat", "body": "desc",
            "head": {"ref": "b", "sha": "sha"}, "base": {"ref": "main"},
        }
        gh.get_pull_request_files.return_value = [
            {"filename": "a.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "@@"},
        ]
        gh.list_pull_commits.return_value = [{"sha": "c1", "commit": {"message": "feat"}}]
        mock_gh_cls.return_value = gh

        with patch.dict("os.environ", {
            "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
            "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
            "BEDROCK_MODEL_ID": "claude",
        }):
            event = {
                "requestContext": {"http": {"method": "POST"}},
                "body": json.dumps({"repo": "o/r", "pr_number": 1, "apply": False}),
            }
            result = lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "generated"
    assert body["applied"] is False


@patch("pr_description.app.BedrockChatClient")
@patch("pr_description.app._fetch_jira_context")
@patch("pr_description.app.GitHubAppAuth")
def test_lambda_handler_apply_string_false(
    mock_auth_cls: MagicMock,
    mock_jira: MagicMock,
    mock_chat_cls: MagicMock,
) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "Generated description"
    mock_chat_cls.return_value = mock_chat
    mock_jira.return_value = []

    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth

    with patch("pr_description.app.GitHubClient") as mock_gh_cls:
        gh = MagicMock()
        gh.get_pull_request.return_value = {
            "number": 1, "title": "feat", "body": "desc",
            "head": {"ref": "b", "sha": "sha"}, "base": {"ref": "main"},
        }
        gh.get_pull_request_files.return_value = [
            {"filename": "a.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "@@"},
        ]
        gh.list_pull_commits.return_value = [{"sha": "c1", "commit": {"message": "feat"}}]
        mock_gh_cls.return_value = gh

        with patch.dict("os.environ", {
            "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
            "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
            "BEDROCK_MODEL_ID": "claude",
        }):
            event = {
                "requestContext": {"http": {"method": "POST"}},
                "body": json.dumps({"repo": "o/r", "pr_number": 1, "apply": "false"}),
            }
            result = lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["applied"] is False
    gh.update_pull_request.assert_not_called()


def test_lambda_handler_bad_method() -> None:
    event = {"requestContext": {"http": {"method": "DELETE"}}, "body": "{}"}
    result = lambda_handler(event, None)
    assert result["statusCode"] == 405


def test_lambda_handler_missing_repo() -> None:
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "body": json.dumps({"pr_number": 1}),
    }
    with patch.dict("os.environ", {
        "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
        "BEDROCK_MODEL_ID": "claude",
    }):
        result = lambda_handler(event, None)
    assert result["statusCode"] == 400


def test_lambda_handler_invalid_json() -> None:
    event = {
        "requestContext": {"http": {"method": "POST"}},
        "body": "{bad json}",
    }
    result = lambda_handler(event, None)
    assert result["statusCode"] == 400


@patch("pr_description.app.BedrockChatClient")
@patch("pr_description.app._fetch_jira_context")
@patch("pr_description.app.GitHubAppAuth")
def test_lambda_handler_sqs_trigger(mock_auth_cls: MagicMock, mock_jira: MagicMock, mock_chat_cls: MagicMock) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "AI summary"
    mock_chat_cls.return_value = mock_chat
    mock_jira.return_value = []

    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth

    with patch("pr_description.app.GitHubClient") as mock_gh_cls:
        gh = MagicMock()
        gh.get_pull_request.return_value = {
            "number": 5, "title": "feat", "body": "existing desc",
            "head": {"ref": "b", "sha": "sha"}, "base": {"ref": "main"},
        }
        gh.get_pull_request_files.return_value = [
            {"filename": "a.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "@@"},
        ]
        gh.list_pull_commits.return_value = [{"sha": "c1", "commit": {"message": "feat"}}]
        mock_gh_cls.return_value = gh

        with patch.dict("os.environ", {
            "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
            "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
            "BEDROCK_MODEL_ID": "claude",
            "DRY_RUN": "true",
        }):
            event = {
                "Records": [{
                    "messageId": "msg-1",
                    "body": json.dumps({
                        "repo_full_name": "o/r",
                        "pr_number": 5,
                        "head_sha": "sha",
                        "installation_id": "12345",
                    }),
                }],
            }
            result = lambda_handler(event, None)

    assert result["batchItemFailures"] == []
