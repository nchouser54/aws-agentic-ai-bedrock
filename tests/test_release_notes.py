"""Tests for release_notes.app — key extraction, prompt building, lambda handler."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from release_notes.app import (
    _build_user_prompt,
    _detect_previous_tag,
    _extract_jira_keys_from_prs,
    generate_release_notes,
    lambda_handler,
)


# -- _extract_jira_keys_from_prs --------------------------------------------

def test_extract_jira_keys_from_prs() -> None:
    prs = [
        {"number": 1, "title": "ENG-10 feature", "body": "also DEVOPS-5", "head": {"ref": "feat"}},
        {"number": 2, "title": "fix typo", "body": "", "head": {"ref": "fix-typo"}},
        {"number": 3, "title": "update", "body": "", "head": {"ref": "feature/ENG-20-thing"}},
    ]
    result = _extract_jira_keys_from_prs(prs)
    assert result["1"] == ["ENG-10", "DEVOPS-5"]
    assert result["2"] == []
    assert result["3"] == ["ENG-20"]


# -- _build_user_prompt ------------------------------------------------------

def test_build_user_prompt_includes_pr_details() -> None:
    prs = [{"number": 42, "title": "Add feature", "user": {"login": "alice"}, "head": {"ref": "feat"}}]
    pr_map = {"42": ["ENG-1"]}
    jira = {"ENG-1": {"summary": "Add feat", "type": "Feature", "status": "Done"}}

    prompt = _build_user_prompt("v2.0", "v1.0", prs, pr_map, jira)
    assert "v2.0" in prompt
    assert "v1.0" in prompt
    assert "PR #42" in prompt
    assert "@alice" in prompt
    assert "ENG-1 [Feature]" in prompt


def test_build_user_prompt_no_jira() -> None:
    prs = [{"number": 7, "title": "Quick fix", "user": {"login": "bob"}, "head": {"ref": "fix"}}]
    pr_map = {"7": []}
    prompt = _build_user_prompt("v1.1", "v1.0", prs, pr_map, {})
    assert "No linked ticket" in prompt


# -- _detect_previous_tag ---------------------------------------------------

def test_detect_previous_tag_found() -> None:
    gh = MagicMock()
    gh.list_tags.return_value = [{"name": "v2.0"}, {"name": "v1.5"}, {"name": "v1.0"}]
    assert _detect_previous_tag(gh, "owner", "repo", "v2.0") == "v1.5"


def test_detect_previous_tag_first_tag() -> None:
    gh = MagicMock()
    gh.list_tags.return_value = [{"name": "v1.0"}]
    assert _detect_previous_tag(gh, "owner", "repo", "v1.0") is None


def test_detect_previous_tag_not_found() -> None:
    gh = MagicMock()
    gh.list_tags.return_value = [{"name": "v2.0"}, {"name": "v1.0"}]
    assert _detect_previous_tag(gh, "owner", "repo", "v3.0") is None


# -- generate_release_notes --------------------------------------------------

@patch("release_notes.app.BedrockChatClient")
@patch("release_notes.app.AtlassianClient")
def test_generate_release_notes(mock_atlassian_cls, mock_chat_cls) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "## Release v2.0\n- **PR #1**: new feature"
    mock_chat_cls.return_value = mock_chat

    mock_atlassian = MagicMock()
    mock_atlassian.get_jira_issue.return_value = {
        "key": "ENG-10",
        "fields": {
            "summary": "New feature",
            "issuetype": {"name": "Story"},
            "status": {"name": "Done"},
        },
    }
    mock_atlassian_cls.return_value = mock_atlassian

    gh = MagicMock()
    gh.list_merged_pulls_between.return_value = [
        {
            "number": 1,
            "title": "ENG-10 new feature",
            "body": "",
            "user": {"login": "dev"},
            "head": {"ref": "feat"},
            "merged_at": "2026-01-15T00:00:00Z",
            "merge_commit_sha": "abc",
        },
    ]

    notes = generate_release_notes(
        gh=gh,
        owner="my-org",
        repo="my-repo",
        tag="v2.0",
        previous_tag="v1.0",
        atlassian_secret_arn="arn:fake",
        model_id="anthropic.model",
        region="us-east-1",
    )
    assert "Release v2.0" in notes
    mock_chat.answer.assert_called_once()


# -- lambda_handler ----------------------------------------------------------

def _api_event(body: dict | None = None, method: str = "POST") -> dict:
    return {
        "requestContext": {"http": {"method": method}},
        "body": json.dumps(body) if body is not None else None,
    }


def test_lambda_handler_rejects_get() -> None:
    out = lambda_handler(_api_event(method="GET"), None)
    assert out["statusCode"] == 405


def test_lambda_handler_rejects_missing_fields() -> None:
    out = lambda_handler(_api_event(body={"repo": "owner/repo"}), None)
    assert out["statusCode"] == 400
    assert "missing_fields" in json.loads(out["body"])["error"]


def test_lambda_handler_rejects_bad_repo() -> None:
    out = lambda_handler(_api_event(body={"repo": "noslash", "tag": "v1"}), None)
    assert out["statusCode"] == 400


@patch("release_notes.app.generate_release_notes", return_value="# Notes")
@patch("release_notes.app.GitHubClient")
@patch("release_notes.app.GitHubAppAuth")
def test_lambda_handler_success(mock_auth_cls, mock_gh_cls, mock_gen) -> None:
    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth

    mock_gh = MagicMock()
    mock_gh_cls.return_value = mock_gh

    with patch.dict(
        "os.environ",
        {
            "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
            "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
            "BEDROCK_MODEL_ID": "model",
        },
        clear=False,
    ):
        out = lambda_handler(
            _api_event(body={
                "repo": "my-org/my-repo",
                "tag": "v2.0",
                "previous_tag": "v1.0",
            }),
            None,
        )

    assert out["statusCode"] == 200
    body = json.loads(out["body"])
    assert body["release_notes"] == "# Notes"
    assert body["tag"] == "v2.0"
    assert body["previous_tag"] == "v1.0"


@patch("release_notes.app.generate_release_notes", return_value="# Notes")
@patch("release_notes.app.GitHubClient")
@patch("release_notes.app.GitHubAppAuth")
def test_lambda_handler_update_release_string_false(mock_auth_cls, mock_gh_cls, _mock_gen) -> None:
    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth

    mock_gh = MagicMock()
    mock_gh_cls.return_value = mock_gh

    with patch.dict(
        "os.environ",
        {
            "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
            "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
            "BEDROCK_MODEL_ID": "model",
        },
        clear=False,
    ):
        out = lambda_handler(
            _api_event(body={
                "repo": "my-org/my-repo",
                "tag": "v2.0",
                "previous_tag": "v1.0",
                "update_release": "false",
                "dry_run": "false",
            }),
            None,
        )

    assert out["statusCode"] == 200
    body = json.loads(out["body"])
    assert body["release_url"] == ""
    mock_gh.get_release_by_tag.assert_not_called()


@patch("release_notes.app._detect_previous_tag", return_value=None)
@patch("release_notes.app.GitHubClient")
@patch("release_notes.app.GitHubAppAuth")
def test_lambda_handler_no_previous_tag(mock_auth_cls, mock_gh_cls, mock_detect) -> None:
    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth
    mock_gh_cls.return_value = MagicMock()

    with patch.dict(
        "os.environ",
        {
            "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
            "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
            "BEDROCK_MODEL_ID": "model",
        },
        clear=False,
    ):
        out = lambda_handler(
            _api_event(body={"repo": "org/repo", "tag": "v1.0"}),
            None,
        )

    assert out["statusCode"] == 400
    assert "no_previous_tag" in json.loads(out["body"])["error"]
