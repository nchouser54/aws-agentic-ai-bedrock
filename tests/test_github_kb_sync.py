from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from github_kb_sync.app import _api_base_to_web_base, _matches, _parse_repo, lambda_handler


def test_parse_repo() -> None:
    assert _parse_repo("org/repo") == ("org", "repo")
    assert _parse_repo("org") is None
    assert _parse_repo("/") is None


def test_api_base_to_web_base() -> None:
    assert _api_base_to_web_base("https://api.github.com") == "https://github.com"
    assert _api_base_to_web_base("https://ghe.example.com/api/v3") == "https://ghe.example.com"


def test_matches() -> None:
    patterns = ["README.md", "docs/**", "**/*.md"]
    assert _matches("README.md", patterns)
    assert _matches("docs/setup.md", patterns)
    assert not _matches("src/app.py", patterns)


@patch("github_kb_sync.app.boto3.client")
@patch("github_kb_sync.app.GitHubClient")
@patch("github_kb_sync.app.GitHubAppAuth")
def test_lambda_handler_happy_path(mock_auth_cls, mock_gh_cls, mock_boto_client) -> None:
    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "token"
    mock_auth_cls.return_value = mock_auth

    mock_gh = MagicMock()
    mock_gh.get_repository.return_value = {"default_branch": "main"}
    mock_gh.list_repository_files.return_value = ["README.md", "docs/runbook.md", "src/app.py"]
    mock_gh.get_file_contents.side_effect = [
        ("repo readme", "sha1"),
        ("runbook content", "sha2"),
    ]
    mock_gh_cls.return_value = mock_gh

    mock_s3 = MagicMock()
    mock_bedrock = MagicMock()
    mock_bedrock.start_ingestion_job.return_value = {"ingestionJob": {"ingestionJobId": "job-123"}}

    def _client(name: str, **_kwargs):
        if name == "s3":
            return mock_s3
        if name == "bedrock-agent":
            return mock_bedrock
        raise AssertionError(name)

    mock_boto_client.side_effect = _client

    env = {
        "AWS_REGION": "us-gov-west-1",
        "GITHUB_API_BASE": "https://ghe.example.com/api/v3",
        "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
        "BEDROCK_KNOWLEDGE_BASE_ID": "kb-1",
        "BEDROCK_KB_DATA_SOURCE_ID": "ds-1",
        "KB_SYNC_BUCKET": "bucket-1",
        "GITHUB_KB_REPOS": "org/repo",
        "GITHUB_KB_INCLUDE_PATTERNS": "README.md,docs/**",
        "GITHUB_KB_SYNC_PREFIX": "github",
        "GITHUB_KB_MAX_FILES_PER_REPO": "10",
    }

    with patch.dict("os.environ", env, clear=False):
        out = lambda_handler({}, None)

    assert out["uploaded"] == 2
    assert out["failed"] == 0
    assert out["repos_processed"] == 1
    assert out["ingestion_job_id"] == "job-123"
    assert mock_s3.put_object.call_count == 2

    # Validate document contains expected source URL base conversion
    first_body = mock_s3.put_object.call_args_list[0].kwargs["Body"]
    payload = json.loads(first_body.decode("utf-8"))
    assert payload["url"].startswith("https://ghe.example.com/org/repo/blob/main/")


@patch("github_kb_sync.app.boto3.client")
@patch("github_kb_sync.app.GitHubClient")
@patch("github_kb_sync.app.GitHubAppAuth")
def test_lambda_handler_no_uploads_skips_ingestion(mock_auth_cls, mock_gh_cls, mock_boto_client) -> None:
    mock_auth_cls.return_value = MagicMock()

    mock_gh = MagicMock()
    mock_gh.get_repository.return_value = {"default_branch": "main"}
    mock_gh.list_repository_files.return_value = ["src/app.py"]
    mock_gh_cls.return_value = mock_gh

    mock_s3 = MagicMock()
    mock_bedrock = MagicMock()

    def _client(name: str, **_kwargs):
        if name == "s3":
            return mock_s3
        if name == "bedrock-agent":
            return mock_bedrock
        raise AssertionError(name)

    mock_boto_client.side_effect = _client

    env = {
        "AWS_REGION": "us-gov-west-1",
        "GITHUB_API_BASE": "https://api.github.com",
        "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
        "BEDROCK_KNOWLEDGE_BASE_ID": "kb-1",
        "BEDROCK_KB_DATA_SOURCE_ID": "ds-1",
        "KB_SYNC_BUCKET": "bucket-1",
        "GITHUB_KB_REPOS": "org/repo",
        "GITHUB_KB_INCLUDE_PATTERNS": "README.md",
    }

    with patch.dict("os.environ", env, clear=False):
        out = lambda_handler({}, None)

    assert out["uploaded"] == 0
    assert out["ingestion_job_id"] == ""
    mock_bedrock.start_ingestion_job.assert_not_called()
