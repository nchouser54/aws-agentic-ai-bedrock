from unittest.mock import MagicMock, patch

from chatbot.github_oauth_authorizer import _parse_bearer_token, lambda_handler


def _event(auth_header: str | None) -> dict:
    headers = {}
    if auth_header is not None:
        headers["Authorization"] = auth_header
    return {
        "headers": headers,
        "requestContext": {"requestId": "req-123"},
    }


def _response(status_code: int, payload: dict | list) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_parse_bearer_token_variants() -> None:
    assert _parse_bearer_token({"Authorization": "Bearer abc"}) == "abc"
    assert _parse_bearer_token({"authorization": "bearer xyz"}) == "xyz"
    assert _parse_bearer_token({"Authorization": "Token xyz"}) == ""
    assert _parse_bearer_token({}) == ""


@patch("chatbot.github_oauth_authorizer.requests.get")
def test_lambda_handler_denies_without_token(mock_get) -> None:
    out = lambda_handler(_event(None), None)
    assert out == {"isAuthorized": False}
    mock_get.assert_not_called()


@patch("chatbot.github_oauth_authorizer.requests.get")
def test_lambda_handler_allows_github_user_without_org_restriction(mock_get) -> None:
    mock_get.return_value = _response(200, {"login": "octocat"})
    env = {
        "GITHUB_API_BASE": "https://api.github.com",
        "GITHUB_OAUTH_ALLOWED_ORGS": "",
    }
    with patch.dict("os.environ", env, clear=False):
        out = lambda_handler(_event("Bearer valid-token"), None)

    assert out["isAuthorized"] is True
    assert out["context"]["github_login"] == "octocat"


@patch("chatbot.github_oauth_authorizer.requests.get")
def test_lambda_handler_denies_if_org_not_allowed(mock_get) -> None:
    mock_get.side_effect = [
        _response(200, {"login": "octocat"}),
        _response(200, [{"login": "another-org"}]),
    ]

    env = {
        "GITHUB_API_BASE": "https://api.github.com",
        "GITHUB_OAUTH_ALLOWED_ORGS": "my-org,eng-org",
    }
    with patch.dict("os.environ", env, clear=False):
        out = lambda_handler(_event("Bearer valid-token"), None)

    assert out == {"isAuthorized": False}


@patch("chatbot.github_oauth_authorizer.requests.get")
def test_lambda_handler_allows_if_org_allowed(mock_get) -> None:
    mock_get.side_effect = [
        _response(200, {"login": "octocat"}),
        _response(200, [{"login": "eng-org"}]),
    ]

    env = {
        "GITHUB_API_BASE": "https://api.github.com",
        "GITHUB_OAUTH_ALLOWED_ORGS": "my-org,eng-org",
    }
    with patch.dict("os.environ", env, clear=False):
        out = lambda_handler(_event("Bearer valid-token"), None)

    assert out["isAuthorized"] is True
    assert out["context"]["auth_provider"] == "github_oauth"
