import json
from unittest.mock import MagicMock, patch

from chatbot.app import (
    _format_confluence,
    _format_jira,
    _format_kb,
    _normalize_retrieval_mode,
    _validate_query_filter,
    handle_query,
    lambda_handler,
)


def test_format_jira() -> None:
    issues = [{"key": "ENG-1", "fields": {"summary": "Fix bug", "status": {"name": "In Progress"}}}]
    out = _format_jira(issues)
    assert "ENG-1" in out
    assert "Fix bug" in out


def test_format_confluence() -> None:
    pages = [{"title": "Runbook", "url": "https://example/wiki/runbook"}]
    out = _format_confluence(pages)
    assert "Runbook" in out
    assert "https://example/wiki/runbook" in out


def test_format_kb_basic() -> None:
    items = [{"title": "Deploy Guide", "uri": "s3://bucket/doc.json", "text": "Step 1: do the thing"}]
    out = _format_kb(items)
    assert "Deploy Guide" in out
    assert "s3://bucket/doc.json" in out
    assert "Step 1: do the thing" in out


def test_format_kb_truncation_with_ellipsis() -> None:
    long_text = "a" * 500
    items = [{"title": "Long", "uri": "", "text": long_text}]
    out = _format_kb(items)
    assert out.endswith("...")
    # First 400 chars should be present
    assert "a" * 400 in out


def test_normalize_retrieval_mode_valid() -> None:
    assert _normalize_retrieval_mode("live") == "live"
    assert _normalize_retrieval_mode("KB") == "kb"
    assert _normalize_retrieval_mode("  Hybrid  ") == "hybrid"


def test_normalize_retrieval_mode_invalid_returns_hybrid() -> None:
    assert _normalize_retrieval_mode("unknown") == "hybrid"
    assert _normalize_retrieval_mode("") == "hybrid"
    assert _normalize_retrieval_mode(None) == "hybrid"


def test_validate_query_filter_ok() -> None:
    assert _validate_query_filter("project=ENG order by updated DESC") is True


def test_validate_query_filter_rejects_injection() -> None:
    assert _validate_query_filter("project=ENG; DROP TABLE") is False
    assert _validate_query_filter("project=ENG -- comment") is False
    assert _validate_query_filter("x" * 501) is False


@patch("chatbot.app.BedrockChatClient")
@patch("chatbot.app.AtlassianClient")
def test_handle_query_live_mode(mock_atlassian_cls, mock_chat_cls) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "Live mode answer"
    mock_chat_cls.return_value = mock_chat

    mock_atlassian = MagicMock()
    mock_atlassian.search_jira.return_value = [{"key": "ENG-1", "fields": {"summary": "Fix"}}]
    mock_atlassian.search_confluence.return_value = [{"title": "Runbook", "url": "https://wiki/runbook"}]
    mock_atlassian_cls.return_value = mock_atlassian

    with patch.dict(
        "os.environ",
        {
            "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
            "CHATBOT_MODEL_ID": "anthropic.model",
        },
        clear=False,
    ):
        out = handle_query("what is broken", "project=ENG", "type=page", "corr-1", retrieval_mode="live")

    assert out["answer"] == "Live mode answer"
    assert out["sources"]["context_source"] == "live"
    assert out["sources"]["jira_count"] == 1
    assert out["sources"]["confluence_count"] == 1


@patch("chatbot.app.BedrockChatClient")
@patch("chatbot.app.BedrockKnowledgeBaseClient")
@patch("chatbot.app.AtlassianClient")
def test_handle_query_hybrid_prefers_kb(mock_atlassian_cls, mock_kb_cls, mock_chat_cls) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "KB answer"
    mock_chat_cls.return_value = mock_chat

    mock_kb = MagicMock()
    mock_kb.retrieve.return_value = [{"title": "Playbook", "uri": "s3://x", "text": "Do this."}]
    mock_kb_cls.return_value = mock_kb

    with patch.dict(
        "os.environ",
        {
            "BEDROCK_KNOWLEDGE_BASE_ID": "kb-123",
            "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
            "CHATBOT_MODEL_ID": "anthropic.model",
        },
        clear=False,
    ):
        out = handle_query("how to deploy", "project=ENG", "type=page", "corr-2", retrieval_mode="hybrid")

    assert out["sources"]["context_source"] == "kb"
    assert out["sources"]["kb_count"] == 1
    mock_atlassian_cls.assert_not_called()


@patch("chatbot.app.BedrockChatClient")
@patch("chatbot.app.BedrockKnowledgeBaseClient")
@patch("chatbot.app.AtlassianClient")
def test_handle_query_hybrid_falls_back_to_live(mock_atlassian_cls, mock_kb_cls, mock_chat_cls) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "Fallback answer"
    mock_chat_cls.return_value = mock_chat

    mock_kb = MagicMock()
    mock_kb.retrieve.return_value = []
    mock_kb_cls.return_value = mock_kb

    mock_atlassian = MagicMock()
    mock_atlassian.search_jira.return_value = [{"key": "ENG-9", "fields": {"summary": "Test"}}]
    mock_atlassian.search_confluence.return_value = [{"title": "Ops", "url": "https://wiki/ops"}]
    mock_atlassian_cls.return_value = mock_atlassian

    with patch.dict(
        "os.environ",
        {
            "BEDROCK_KNOWLEDGE_BASE_ID": "kb-123",
            "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
            "CHATBOT_MODEL_ID": "anthropic.model",
        },
        clear=False,
    ):
        out = handle_query("where is doc", "project=ENG", "type=page", "corr-3", retrieval_mode="hybrid")

    assert out["sources"]["context_source"] == "hybrid_fallback"
    assert out["sources"]["jira_count"] == 1
    assert out["sources"]["confluence_count"] == 1


@patch("chatbot.app.BedrockChatClient")
@patch("chatbot.app.BedrockKnowledgeBaseClient")
@patch("chatbot.app.AtlassianClient")
def test_handle_query_circuit_breaker(mock_atlassian_cls, mock_kb_cls, mock_chat_cls) -> None:
    """When KB retrieval throws, hybrid mode gracefully falls back to live."""
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "Circuit breaker fallback"
    mock_chat_cls.return_value = mock_chat

    mock_kb = MagicMock()
    mock_kb.retrieve.side_effect = RuntimeError("Bedrock is down")
    mock_kb_cls.return_value = mock_kb

    mock_atlassian = MagicMock()
    mock_atlassian.search_jira.return_value = [{"key": "ENG-10", "fields": {"summary": "CB"}}]
    mock_atlassian.search_confluence.return_value = []
    mock_atlassian_cls.return_value = mock_atlassian

    with patch.dict(
        "os.environ",
        {
            "BEDROCK_KNOWLEDGE_BASE_ID": "kb-123",
            "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
            "CHATBOT_MODEL_ID": "anthropic.model",
        },
        clear=False,
    ):
        out = handle_query("test", "project=ENG", "type=page", "corr-cb", retrieval_mode="hybrid")

    assert out["sources"]["context_source"] == "hybrid_fallback"
    assert out["sources"]["kb_count"] == 0
    assert out["sources"]["jira_count"] == 1


# --- lambda_handler HTTP layer tests ---

def _api_event(body: dict | None = None, method: str = "POST", headers: dict | None = None) -> dict:
    return {
        "requestContext": {"http": {"method": method}, "requestId": "req-test"},
        "headers": headers or {},
        "body": json.dumps(body) if body is not None else None,
    }


def test_lambda_handler_method_not_allowed() -> None:
    import chatbot.app as chatbot_mod
    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        out = lambda_handler(_api_event(method="GET"), None)
    assert out["statusCode"] == 405


def test_lambda_handler_query_too_long() -> None:
    import chatbot.app as chatbot_mod
    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        out = lambda_handler(_api_event(body={"query": "x" * 5000}), None)
    assert out["statusCode"] == 400
    assert "query_too_long" in json.loads(out["body"])["error"]


def test_lambda_handler_invalid_query_filter() -> None:
    import chatbot.app as chatbot_mod
    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        out = lambda_handler(_api_event(body={"query": "hello", "jira_jql": "ENG; DROP TABLE"}), None)
    assert out["statusCode"] == 400
    assert "invalid_query_filter" in json.loads(out["body"])["error"]


def test_lambda_handler_auth_required() -> None:
    import chatbot.app as chatbot_mod
    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": "my-secret"}, clear=False):
        out = lambda_handler(_api_event(body={"query": "test"}), None)
    assert out["statusCode"] == 401


def test_lambda_handler_auth_passed() -> None:
    import chatbot.app as chatbot_mod
    chatbot_mod._cached_api_token = None
    env = {
        "CHATBOT_API_TOKEN_SECRET_ARN": "",
        "CHATBOT_API_TOKEN": "my-secret",
        "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
        "CHATBOT_MODEL_ID": "model",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch("chatbot.app.handle_query", return_value={"answer": "ok", "sources": {}}):
            out = lambda_handler(
                _api_event(body={"query": "test"}, headers={"x-api-token": "my-secret"}),
                None,
            )
    assert out["statusCode"] == 200


@patch("chatbot.app.handle_query", side_effect=RuntimeError("boom"))
def test_lambda_handler_returns_500_on_internal_error(mock_hq) -> None:
    import chatbot.app as chatbot_mod
    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        out = lambda_handler(_api_event(body={"query": "test"}), None)
    assert out["statusCode"] == 500
    body = json.loads(out["body"])
    assert body["error"] == "internal_error"
    assert body["correlation_id"] == "req-test"
