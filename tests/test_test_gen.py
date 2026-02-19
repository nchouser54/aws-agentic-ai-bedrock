"""Tests for the test generation agent Lambda."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

from test_gen.app import (
    _handle_file_request,
    _is_safe_generated_test_path,
    _is_testable,
    _parse_test_files,
    _post_as_draft_pr,
    _select_testable_files,
    generate_tests,
    generate_tests_for_file,
    lambda_handler,
)


# -- File filtering tests ------------------------------------------------------


class TestIsTestable:
    def test_python_source_file(self) -> None:
        assert _is_testable("src/main.py") is True

    def test_test_file_excluded(self) -> None:
        assert _is_testable("tests/test_main.py") is False
        assert _is_testable("test_main.py") is False

    def test_markdown_excluded(self) -> None:
        assert _is_testable("README.md") is False

    def test_image_excluded(self) -> None:
        assert _is_testable("logo.png") is False

    def test_lock_file_excluded(self) -> None:
        assert _is_testable("package-lock.json") is False
        assert _is_testable("yarn.lock") is False

    def test_empty_filename(self) -> None:
        assert _is_testable("") is False

    def test_js_source_file(self) -> None:
        assert _is_testable("src/utils/helpers.js") is True

    def test_typescript_definition_excluded(self) -> None:
        assert _is_testable("types.d.ts") is False

    def test_spec_dir_excluded(self) -> None:
        assert _is_testable("spec/helper_spec.rb") is False

    def test_go_source_file(self) -> None:
        assert _is_testable("cmd/main.go") is True

    def test_go_test_file_excluded(self) -> None:
        assert _is_testable("cmd/main_test.go") is False


class TestSelectTestableFiles:
    def test_filters_and_caps(self) -> None:
        files = [
            {"filename": "src/main.py", "status": "modified"},
            {"filename": "README.md", "status": "modified"},
            {"filename": "tests/test_main.py", "status": "added"},
            {"filename": "src/utils.py", "status": "added"},
            {"filename": "src/deleted.py", "status": "removed"},
        ]
        result = _select_testable_files(files)
        filenames = [f["filename"] for f in result]
        assert "src/main.py" in filenames
        assert "src/utils.py" in filenames
        assert "README.md" not in filenames
        assert "tests/test_main.py" not in filenames
        assert "src/deleted.py" not in filenames


# -- Parse test files tests ----------------------------------------------------


class TestParseTestFiles:
    def test_parses_single_file(self) -> None:
        markdown = """```python
# Test file: tests/test_main.py
import pytest

def test_example():
    assert True
```"""
        files = _parse_test_files(markdown)
        assert len(files) == 1
        assert files[0][0] == "tests/test_main.py"
        assert "def test_example" in files[0][1]

    def test_parses_multiple_files(self) -> None:
        markdown = """```python
# Test file: tests/test_a.py
def test_a(): pass
```

```python
# Test file: tests/test_b.py
def test_b(): pass
```"""
        files = _parse_test_files(markdown)
        assert len(files) == 2
        assert files[0][0] == "tests/test_a.py"
        assert files[1][0] == "tests/test_b.py"

    def test_skips_blocks_without_marker(self) -> None:
        markdown = """```python
# Just some code
x = 1
```"""
        files = _parse_test_files(markdown)
        assert len(files) == 0

    def test_rejects_unsafe_test_paths(self) -> None:
        markdown = """```python
# Test file: ../../.github/workflows/pwn.yml
print("bad")
```

```python
# Test file: /tmp/test_main.py
print("bad")
```

```python
# Test file: tests/test_safe.py
def test_safe(): pass
```"""
        files = _parse_test_files(markdown)
        assert len(files) == 1
        assert files[0][0] == "tests/test_safe.py"


# -- Generate tests -----------------------------------------------------------


@patch("test_gen.app.BedrockChatClient")
def test_generate_tests(mock_chat_cls: MagicMock) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "```python\n# Test file: tests/test_main.py\ndef test_it(): pass\n```"
    mock_chat_cls.return_value = mock_chat

    gh = MagicMock()
    gh.get_pull_request.return_value = {"number": 1, "title": "feat: add login"}
    gh.get_pull_request_files.return_value = [
        {"filename": "src/main.py", "status": "modified", "patch": "@@ -1 +1 @@\n-old\n+new"},
    ]
    gh.get_file_contents.return_value = {"content": "bmV3X2NvZGU=", "encoding": "base64"}

    output, testable = generate_tests(gh, "o", "r", 1, "sha123", "claude", "us-gov-west-1")
    assert "test_main" in output
    assert len(testable) == 1
    mock_chat.answer.assert_called_once()


@patch("test_gen.app.BedrockChatClient")
def test_generate_tests_no_testable_files(mock_chat_cls: MagicMock) -> None:
    gh = MagicMock()
    gh.get_pull_request.return_value = {"number": 1, "title": "docs: update readme"}
    gh.get_pull_request_files.return_value = [
        {"filename": "README.md", "status": "modified"},
        {"filename": "CHANGELOG.md", "status": "modified"},
    ]

    output, testable = generate_tests(gh, "o", "r", 1, "sha123", "claude", "us-gov-west-1")
    assert output == ""
    assert len(testable) == 0
    mock_chat_cls.assert_not_called()


# -- Lambda handler tests ------------------------------------------------------


@patch("test_gen.app.BedrockChatClient")
@patch("test_gen.app.GitHubAppAuth")
def test_lambda_handler_api_gateway(mock_auth_cls: MagicMock, mock_chat_cls: MagicMock) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "```python\n# Test file: tests/test_main.py\ndef test_it(): pass\n```"
    mock_chat_cls.return_value = mock_chat

    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth

    with patch("test_gen.app.GitHubClient") as mock_gh_cls:
        gh = MagicMock()
        gh.get_pull_request.return_value = {
            "number": 1, "title": "feat", "head": {"sha": "sha1"}, "base": {"ref": "main"},
        }
        gh.get_pull_request_files.return_value = [{"filename": "src/main.py", "status": "modified", "patch": "@@"}]
        gh.get_file_contents.return_value = {"content": "Y29kZQ==", "encoding": "base64"}
        mock_gh_cls.return_value = gh

        with patch.dict("os.environ", {
            "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
            "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
            "BEDROCK_MODEL_ID": "claude",
            "TEST_GEN_DELIVERY_MODE": "comment",
        }):
            event = {
                "requestContext": {"http": {"method": "POST"}},
                "body": json.dumps({"repo": "o/r", "pr_number": 1}),
            }
            result = lambda_handler(event, None)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "generated"


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


# -- _post_as_draft_pr error handling tests ------------------------------------


def test_post_as_draft_pr_falls_back_to_comment_when_base_sha_unresolvable() -> None:
    """If get_ref raises, _post_as_draft_pr must fall back to a PR comment."""
    gh = MagicMock()
    gh.get_ref.side_effect = Exception("404 Not Found")
    test_output = "```python\n# Test file: tests/test_x.py\ndef test_x(): pass\n```"

    with patch("test_gen.app._post_as_comment") as mock_comment:
        _post_as_draft_pr(gh, "o", "r", 42, "abc12345", "main", test_output)

    mock_comment.assert_called_once_with(gh, "o", "r", 42, test_output)
    gh.put_file_contents.assert_not_called()
    gh.create_pull_request.assert_not_called()


def test_post_as_draft_pr_falls_back_to_comment_when_create_pr_fails() -> None:
    """If create_pull_request raises (e.g. 422 PR already exists), fall back to comment."""
    gh = MagicMock()
    gh.get_ref.return_value = {"object": {"sha": "base_sha"}}
    gh.create_ref.return_value = {}
    gh.put_file_contents.return_value = {}
    gh.create_pull_request.side_effect = Exception("Unprocessable Entity")
    test_output = "```python\n# Test file: tests/test_x.py\ndef test_x(): pass\n```"

    with patch("test_gen.app._post_as_comment") as mock_comment:
        _post_as_draft_pr(gh, "o", "r", 42, "abc12345", "main", test_output)

    mock_comment.assert_called_once_with(gh, "o", "r", 42, test_output)


def test_post_as_draft_pr_existing_branch_is_reused() -> None:
    """create_ref raising (branch exists) should NOT abort; commits should proceed."""
    gh = MagicMock()
    gh.get_ref.return_value = {"object": {"sha": "base_sha"}}
    gh.create_ref.side_effect = Exception("branch already exists")
    gh.put_file_contents.return_value = {}
    gh.create_pull_request.return_value = {"number": 99, "html_url": "http://example.com/99"}
    test_output = "```python\n# Test file: tests/test_x.py\ndef test_x(): pass\n```"

    with patch("test_gen.app._post_as_comment") as mock_comment:
        _post_as_draft_pr(gh, "o", "r", 42, "abc12345", "main", test_output)

    mock_comment.assert_not_called()
    gh.put_file_contents.assert_called_once()
    gh.create_pull_request.assert_called_once()
