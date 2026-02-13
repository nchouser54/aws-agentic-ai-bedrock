import json
from unittest.mock import MagicMock, patch

from chatbot.app import (
    _chunk_text,
    _format_confluence,
    _format_jira,
    _format_kb,
    _list_bedrock_models,
    _normalize_assistant_mode,
    _normalize_conversation_id,
    _normalize_llm_provider,
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


def test_normalize_assistant_mode() -> None:
    assert _normalize_assistant_mode("general") == "general"
    assert _normalize_assistant_mode("contextual") == "contextual"
    assert _normalize_assistant_mode("invalid") == "contextual"


def test_normalize_llm_provider() -> None:
    assert _normalize_llm_provider("bedrock") == "bedrock"
    assert _normalize_llm_provider("anthropic_direct") == "anthropic_direct"
    assert _normalize_llm_provider("other") == "bedrock"


def test_normalize_conversation_id() -> None:
    assert _normalize_conversation_id("thread_1") == "thread_1"
    assert _normalize_conversation_id("") is None


def test_normalize_conversation_id_invalid() -> None:
    try:
        _normalize_conversation_id("not valid spaces")
    except ValueError as exc:
        assert str(exc) == "conversation_id_invalid"
    else:
        raise AssertionError("Expected ValueError")


def test_chunk_text() -> None:
    small_chunks = _chunk_text("abcdefghij", 4)
    assert small_chunks == ["abcdefghij"]

    chunks = _chunk_text("abcdefghijklmnopqrstuv", 10)
    assert chunks == ["abcdefghijklmnopqrst", "uv"]


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
    assert out["sources"]["assistant_mode"] == "contextual"
    assert out["sources"]["provider"] == "bedrock"
    assert out["sources"]["jira_count"] == 1
    assert out["sources"]["confluence_count"] == 1
    assert out["sources"]["github_count"] == 0


@patch("chatbot.app.BedrockChatClient")
@patch("chatbot.app.GitHubClient")
@patch("chatbot.app.GitHubAppAuth")
@patch("chatbot.app.AtlassianClient")
def test_handle_query_live_mode_optional_github(
    mock_atlassian_cls,
    mock_auth_cls,
    mock_gh_cls,
    mock_chat_cls,
) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "Live mode answer"
    mock_chat_cls.return_value = mock_chat

    mock_atlassian = MagicMock()
    mock_atlassian.search_jira.return_value = []
    mock_atlassian.search_confluence.return_value = []
    mock_atlassian_cls.return_value = mock_atlassian

    mock_auth = MagicMock()
    mock_auth.get_installation_token.return_value = "tok"
    mock_auth_cls.return_value = mock_auth

    mock_gh = MagicMock()
    mock_gh.search_code.return_value = [
        {
            "path": "README.md",
            "html_url": "https://github.com/org/repo/blob/main/README.md",
            "repository": {"full_name": "org/repo", "default_branch": "main"},
        }
    ]
    mock_gh.get_file_contents.return_value = ("repo docs", "sha")
    mock_gh_cls.return_value = mock_gh

    env = {
        "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
        "CHATBOT_MODEL_ID": "anthropic.model",
        "GITHUB_CHAT_LIVE_ENABLED": "true",
        "GITHUB_CHAT_REPOS": "org/repo",
        "GITHUB_CHAT_MAX_RESULTS": "3",
        "GITHUB_APP_IDS_SECRET_ARN": "arn:ids",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ARN": "arn:key",
        "GITHUB_API_BASE": "https://api.github.com",
    }
    with patch.dict("os.environ", env, clear=False):
        out = handle_query("where docs", "project=ENG", "type=page", "corr-live-gh", retrieval_mode="live")

    assert out["sources"]["context_source"] == "live"
    assert out["sources"]["github_count"] == 1
    mock_gh.search_code.assert_called_once()


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


@patch("chatbot.app.BedrockChatClient")
def test_handle_query_general_mode_skips_context(mock_chat_cls) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "General answer"
    mock_chat_cls.return_value = mock_chat

    with patch.dict(
        "os.environ",
        {
            "CHATBOT_MODEL_ID": "anthropic.model",
            "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
        },
        clear=False,
    ):
        out = handle_query(
            "brainstorm migration plan",
            "project=ENG",
            "type=page",
            "corr-general",
            retrieval_mode="hybrid",
            assistant_mode="general",
            llm_provider="bedrock",
        )

    assert out["answer"] == "General answer"
    assert out["sources"]["assistant_mode"] == "general"
    assert out["sources"]["context_source"] == "none"
    assert out["sources"]["jira_count"] == 0


@patch("chatbot.app._load_anthropic_api_key", return_value="anthropic-key")
@patch("chatbot.app.AnthropicChatClient")
def test_handle_query_general_mode_anthropic_direct(mock_anthropic_cls, _mock_key) -> None:
    mock_client = MagicMock()
    mock_client.answer.return_value = "Anthropic direct answer"
    mock_anthropic_cls.return_value = mock_client

    with patch.dict(
        "os.environ",
        {
            "CHATBOT_ENABLE_ANTHROPIC_DIRECT": "true",
            "CHATBOT_ANTHROPIC_MODEL_ID": "claude-sonnet-4-5",
        },
        clear=False,
    ):
        out = handle_query(
            "write a summary",
            "order by updated DESC",
            "type=page",
            "corr-anth",
            assistant_mode="general",
            llm_provider="anthropic_direct",
        )

    assert out["answer"] == "Anthropic direct answer"
    assert out["sources"]["provider"] == "anthropic_direct"


@patch("chatbot.app._append_conversation_turn")
@patch("chatbot.app._load_conversation_history", return_value=[{"role": "user", "content": "prior q"}])
@patch("chatbot.app.BedrockChatClient")
def test_handle_query_stream_and_memory(
    mock_chat_cls,
    _mock_history,
    mock_append,
) -> None:
    mock_chat = MagicMock()
    mock_chat.answer.return_value = "This is a longer answer for stream testing."
    mock_chat_cls.return_value = mock_chat

    with patch.dict(
        "os.environ",
        {
            "CHATBOT_MODEL_ID": "anthropic.model",
            "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
        },
        clear=False,
    ):
        out = handle_query(
            "brainstorm migration plan",
            "project=ENG",
            "type=page",
            "corr-stream",
            retrieval_mode="hybrid",
            assistant_mode="general",
            llm_provider="bedrock",
            stream=True,
            stream_chunk_chars=8,
            conversation_id="team-thread",
        )

    assert out["conversation_id"] == "team-thread"
    assert out["stream"]["enabled"] is True
    assert out["stream"]["chunk_count"] > 1
    assert "chunks" in out["stream"]
    mock_append.assert_called_once()


def test_handle_query_model_not_allowed_raises_value_error() -> None:
    with patch.dict(
        "os.environ",
        {
            "CHATBOT_ALLOWED_MODEL_IDS": "amazon.nova-pro-v1:0,anthropic.claude-3-7-sonnet-v1:0",
            "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
        },
        clear=False,
    ):
        try:
            handle_query(
                "test",
                "order by updated DESC",
                "type=page",
                "corr-model",
                assistant_mode="general",
                llm_provider="bedrock",
                model_id="anthropic.claude-3-sonnet-20240229-v1:0",
            )
        except ValueError as exc:
            assert str(exc) == "model_not_allowed"
        else:
            raise AssertionError("Expected ValueError for disallowed model")


def test_list_bedrock_models_filters_active_and_allowlist() -> None:
    fake_bedrock = MagicMock()
    fake_bedrock.list_foundation_models.return_value = {
        "modelSummaries": [
            {
                "modelId": "amazon.nova-pro-v1:0",
                "modelName": "Nova Pro",
                "providerName": "Amazon",
                "inferenceTypesSupported": ["ON_DEMAND"],
                "outputModalities": ["TEXT"],
                "modelLifecycle": {"status": "ACTIVE"},
            },
            {
                "modelId": "anthropic.old",
                "modelName": "Old",
                "providerName": "Anthropic",
                "inferenceTypesSupported": ["ON_DEMAND"],
                "outputModalities": ["TEXT"],
                "modelLifecycle": {"status": "LEGACY"},
            },
        ]
    }

    with patch("chatbot.app.boto3.client", return_value=fake_bedrock):
        with patch.dict("os.environ", {"CHATBOT_ALLOWED_MODEL_IDS": "amazon.nova-pro-v1:0"}, clear=False):
            models = _list_bedrock_models("us-gov-west-1")

    assert len(models) == 1
    assert models[0]["model_id"] == "amazon.nova-pro-v1:0"


# --- lambda_handler HTTP layer tests ---

def _api_event(body: dict | None = None, method: str = "POST", headers: dict | None = None) -> dict:
    return {
        "rawPath": "/chatbot/query",
        "requestContext": {"http": {"method": method, "path": "/chatbot/query"}, "requestId": "req-test"},
        "headers": headers or {},
        "body": json.dumps(body) if body is not None else None,
    }


def _ws_event(body: dict | None = None, route_key: str = "query", headers: dict | None = None) -> dict:
    return {
        "requestContext": {
            "routeKey": route_key,
            "connectionId": "abc123",
            "domainName": "ws.example.com",
            "stage": "prod",
            "requestId": "req-ws",
        },
        "body": json.dumps(body) if body is not None else None,
        "headers": headers or {},
    }


def test_lambda_handler_method_not_allowed() -> None:
    import chatbot.app as chatbot_mod
    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        event = _api_event(method="GET")
        event["rawPath"] = "/chatbot/unknown"
        event["requestContext"]["http"]["path"] = "/chatbot/unknown"
        out = lambda_handler(event, None)
    assert out["statusCode"] == 405


@patch("chatbot.app._list_bedrock_models", return_value=[{"model_id": "amazon.nova-pro-v1:0"}])
def test_lambda_handler_models_route(mock_models) -> None:
    import chatbot.app as chatbot_mod
    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        event = _api_event(method="GET")
        event["rawPath"] = "/chatbot/models"
        event["requestContext"]["http"]["path"] = "/chatbot/models"
        out = lambda_handler(event, None)

    assert out["statusCode"] == 200
    body = json.loads(out["body"])
    assert body["count"] == 1
    assert body["models"][0]["model_id"] == "amazon.nova-pro-v1:0"
    mock_models.assert_called_once()


@patch(
    "chatbot.app._generate_image",
    return_value={
        "images": ["ZmFrZV9iYXNlNjQ="],
        "count": 1,
        "model_id": "amazon.nova-canvas-v1:0",
        "size": "1024x1024",
    },
)
def test_lambda_handler_image_route(mock_image) -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        event = _api_event(body={"query": "Draw a skyline"})
        event["rawPath"] = "/chatbot/image"
        event["requestContext"]["http"]["path"] = "/chatbot/image"
        out = lambda_handler(event, None)

    assert out["statusCode"] == 200
    body = json.loads(out["body"])
    assert body["count"] == 1
    assert body["model_id"] == "amazon.nova-canvas-v1:0"
    mock_image.assert_called_once()


def test_lambda_handler_image_prompt_blocked() -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    env = {
        "CHATBOT_API_TOKEN_SECRET_ARN": "",
        "CHATBOT_API_TOKEN": "",
        "CHATBOT_IMAGE_SAFETY_ENABLED": "true",
        "CHATBOT_IMAGE_BANNED_TERMS": "graphic gore,nudity",
    }
    with patch.dict("os.environ", env, clear=False):
        event = _api_event(body={"query": "Create graphic gore battle art"})
        event["rawPath"] = "/chatbot/image"
        event["requestContext"]["http"]["path"] = "/chatbot/image"
        out = lambda_handler(event, None)

    assert out["statusCode"] == 400
    body = json.loads(out["body"])
    assert body["error"] == "image_prompt_blocked"


@patch("chatbot.app._generate_image", return_value={"images": ["ZmFrZQ=="], "count": 1})
@patch("chatbot.app._enforce_image_rate_quotas", side_effect=ValueError("rate_limit_exceeded"))
def test_lambda_handler_image_rate_limit(_mock_quota, _mock_generate) -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        event = _api_event(body={"query": "Draw a skyline"})
        event["rawPath"] = "/chatbot/image"
        event["requestContext"]["http"]["path"] = "/chatbot/image"
        out = lambda_handler(event, None)

    assert out["statusCode"] == 429
    body = json.loads(out["body"])
    assert body["error"] == "rate_limit_exceeded"


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


def test_lambda_handler_memory_clear_route() -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        with patch("chatbot.app._clear_conversation_memory", return_value=3) as clear_conv:
            event = _api_event(body={"conversation_id": "team-thread"})
            event["rawPath"] = "/chatbot/memory/clear"
            event["requestContext"]["http"]["path"] = "/chatbot/memory/clear"
            out = lambda_handler(event, None)

    assert out["statusCode"] == 200
    body = json.loads(out["body"])
    assert body["cleared"] is True
    assert body["deleted_items"] == 3
    clear_conv.assert_called_once()


def test_lambda_handler_memory_clear_all_route() -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        with patch("chatbot.app._clear_all_memory_for_actor", return_value=7) as clear_all:
            event = _api_event(body={})
            event["rawPath"] = "/chatbot/memory/clear-all"
            event["requestContext"]["http"]["path"] = "/chatbot/memory/clear-all"
            out = lambda_handler(event, None)

    assert out["statusCode"] == 200
    body = json.loads(out["body"])
    assert body["cleared"] is True
    assert body["deleted_items"] == 7
    assert body["scope"] == "actor"
    clear_all.assert_called_once()


def test_lambda_handler_emits_metrics_for_successful_query() -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    env = {
        "CHATBOT_API_TOKEN_SECRET_ARN": "",
        "CHATBOT_API_TOKEN": "",
        "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
        "CHATBOT_MODEL_ID": "model",
    }
    with patch.dict("os.environ", env, clear=False):
        with patch("chatbot.app._emit_metric") as emit_metric:
            with patch("chatbot.app.handle_query", return_value={"answer": "ok", "sources": {}}):
                out = lambda_handler(_api_event(body={"query": "test"}), None)

    assert out["statusCode"] == 200
    metric_names = [call.args[0] for call in emit_metric.call_args_list]
    assert "ChatbotRequestCount" in metric_names
    assert "ChatbotLatencyMs" in metric_names


def test_lambda_handler_websocket_streaming_query() -> None:
    response = {
        "answer": "hello world",
        "conversation_id": "thread-1",
        "stream": {"enabled": True, "chunk_count": 2, "chunks": ["hello ", "world"]},
        "sources": {"provider": "bedrock"},
    }

    with patch("chatbot.app.handle_query", return_value=response):
        with patch("chatbot.app._ws_send") as ws_send:
            out = lambda_handler(_ws_event(body={"action": "query", "query": "test"}), None)

    assert out["statusCode"] == 200
    sent_types = [call.args[2].get("type") for call in ws_send.call_args_list]
    assert sent_types == ["chunk", "chunk", "done"]


def test_lambda_handler_websocket_unsupported_route() -> None:
    out = lambda_handler(_ws_event(body={"action": "noop"}, route_key="noop"), None)
    assert out["statusCode"] == 400


def test_lambda_handler_websocket_connect_unauthorized() -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": "my-secret"}, clear=False):
        out = lambda_handler(_ws_event(route_key="$connect"), None)

    assert out["statusCode"] == 401


def test_lambda_handler_websocket_connect_authorized() -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": "my-secret"}, clear=False):
        out = lambda_handler(_ws_event(route_key="$connect", headers={"x-api-token": "my-secret"}), None)

    assert out["statusCode"] == 200


def test_lambda_handler_websocket_query_unauthorized_sends_error() -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": "my-secret"}, clear=False):
        with patch("chatbot.app._ws_send") as ws_send:
            out = lambda_handler(_ws_event(body={"action": "query", "query": "test"}), None)

    assert out["statusCode"] == 200
    ws_send.assert_called_once()
    assert ws_send.call_args.args[2]["error"] == "unauthorized"


@patch("chatbot.app.handle_query", side_effect=ValueError("rate_limit_exceeded"))
def test_lambda_handler_returns_429_on_rate_limit(_mock_hq) -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
        out = lambda_handler(_api_event(body={"query": "test"}), None)

    assert out["statusCode"] == 429
    body = json.loads(out["body"])
    assert body["error"] == "rate_limit_exceeded"


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


@patch("chatbot.app.handle_query", side_effect=RuntimeError("boom"))
def test_lambda_handler_emits_server_error_metric(_mock_hq) -> None:
    import chatbot.app as chatbot_mod

    chatbot_mod._cached_api_token = None
    with patch("chatbot.app._emit_metric") as emit_metric:
        with patch.dict("os.environ", {"CHATBOT_API_TOKEN_SECRET_ARN": "", "CHATBOT_API_TOKEN": ""}, clear=False):
            out = lambda_handler(_api_event(body={"query": "test"}), None)

    assert out["statusCode"] == 500
    metric_names = [call.args[0] for call in emit_metric.call_args_list]
    assert "ChatbotErrorCount" in metric_names
    assert "ChatbotServerErrorCount" in metric_names
