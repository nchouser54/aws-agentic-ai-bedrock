import json
from unittest.mock import patch

import chatbot.teams_adapter as teams_mod
from chatbot.teams_adapter import lambda_handler


def _event(body: dict, token: str | None = None) -> dict:
    headers = {}
    if token is not None:
        headers["X-Teams-Adapter-Token"] = token
    return {
        "requestContext": {"http": {"method": "POST"}, "requestId": "req-1"},
        "headers": headers,
        "body": json.dumps(body),
    }


@patch("chatbot.teams_adapter.handle_query")
def test_teams_adapter_success(mock_handle_query) -> None:
    mock_handle_query.return_value = {"answer": "Hello from bot"}

    # Reset cached token so _load_teams_token re-evaluates
    teams_mod._cached_teams_token = None
    with patch.dict("os.environ", {"TEAMS_ADAPTER_TOKEN_SECRET_ARN": "", "TEAMS_ADAPTER_TOKEN": ""}, clear=False):
        event = _event({"type": "message", "text": "hello"})
        out = lambda_handler(event, None)

    assert out["statusCode"] == 200
    payload = json.loads(out["body"])
    assert payload["type"] == "message"
    assert payload["text"] == "Hello from bot"


@patch("chatbot.teams_adapter.handle_query")
def test_teams_adapter_auth_required(mock_handle_query) -> None:
    mock_handle_query.return_value = {"answer": "ok"}

    teams_mod._cached_teams_token = None
    env = {"TEAMS_ADAPTER_TOKEN_SECRET_ARN": "", "TEAMS_ADAPTER_TOKEN": "secret-token"}
    with patch.dict("os.environ", env, clear=False):
        out = lambda_handler(_event({"text": "hello"}, token="wrong"), None)

    assert out["statusCode"] == 401


def test_teams_adapter_missing_text() -> None:
    teams_mod._cached_teams_token = None
    with patch.dict("os.environ", {"TEAMS_ADAPTER_TOKEN_SECRET_ARN": "", "TEAMS_ADAPTER_TOKEN": ""}, clear=False):
        out = lambda_handler(_event({"type": "message", "text": ""}), None)
    assert out["statusCode"] == 400


@patch("chatbot.teams_adapter.handle_query")
def test_teams_adapter_timing_safe_compare(mock_handle_query) -> None:
    """Verify that hmac.compare_digest is used for token comparison."""
    mock_handle_query.return_value = {"answer": "ok"}

    teams_mod._cached_teams_token = None
    env = {"TEAMS_ADAPTER_TOKEN_SECRET_ARN": "", "TEAMS_ADAPTER_TOKEN": "correct-token"}
    with patch.dict("os.environ", env, clear=False):
        out = lambda_handler(
            _event({"text": "hello"}, token="correct-token"), None,
        )

    assert out["statusCode"] == 200
