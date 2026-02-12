import json
from unittest.mock import patch

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

    event = _event({"type": "message", "text": "hello"})
    out = lambda_handler(event, None)

    assert out["statusCode"] == 200
    payload = json.loads(out["body"])
    assert payload["type"] == "message"
    assert payload["text"] == "Hello from bot"


@patch("chatbot.teams_adapter.handle_query")
def test_teams_adapter_auth_required(mock_handle_query) -> None:
    mock_handle_query.return_value = {"answer": "ok"}

    with patch("chatbot.teams_adapter.os.getenv", return_value="secret-token"):
        out = lambda_handler(_event({"text": "hello"}, token="wrong"), None)

    assert out["statusCode"] == 401


def test_teams_adapter_missing_text() -> None:
    out = lambda_handler(_event({"type": "message", "text": ""}), None)
    assert out["statusCode"] == 400
