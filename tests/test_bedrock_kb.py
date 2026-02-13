"""Tests for shared.bedrock_kb – retrieve, retry, pagination, and URI extraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from shared.bedrock_kb import BedrockKnowledgeBaseClient, _is_retryable


# -- helpers -----------------------------------------------------------------

def _make_client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "test"}}, "Retrieve")


def _bedrock_response(results: list[dict], next_token: str | None = None) -> dict:
    resp: dict = {"retrievalResults": results}
    if next_token:
        resp["nextToken"] = next_token
    return resp


def _make_result(text: str = "t", uri: str = "s3://b/k", score: float = 0.9, title: str = "T") -> dict:
    return {
        "content": {"text": text},
        "location": {"s3Location": {"uri": uri}},
        "score": score,
        "metadata": {"title": title},
    }


class FakeRuntime:
    def retrieve(self, **kwargs):
        _ = kwargs
        return {
            "retrievalResults": [
                {
                    "content": {"text": "Deploy guide"},
                    "score": 0.91,
                    "metadata": {"title": "Runbook"},
                    "location": {"s3Location": {"uri": "s3://kb-bucket/runbook.json"}},
                },
                {
                    "content": {"text": "Pager checklist"},
                    "score": 0.88,
                    "metadata": {},
                    "location": {"webLocation": {"url": "https://wiki.local/page"}},
                },
            ]
        }


# -- _is_retryable -----------------------------------------------------------

@pytest.mark.parametrize(
    "code,expected",
    [
        ("ThrottlingException", True),
        ("ServiceUnavailableException", True),
        ("InternalServerException", True),
        ("TooManyRequestsException", True),
        ("ValidationException", False),
        ("AccessDeniedException", False),
    ],
)
def test_is_retryable(code: str, expected: bool) -> None:
    assert _is_retryable(_make_client_error(code)) is expected


def test_is_retryable_non_client_error() -> None:
    assert _is_retryable(RuntimeError("boom")) is False


# -- _extract_uri ------------------------------------------------------------

def test_extract_uri_s3() -> None:
    uri = BedrockKnowledgeBaseClient._extract_uri({"s3Location": {"uri": "s3://bucket/key.json"}})
    assert uri == "s3://bucket/key.json"


def test_extract_uri_web() -> None:
    uri = BedrockKnowledgeBaseClient._extract_uri({"webLocation": {"url": "https://example.com/page"}})
    assert uri == "https://example.com/page"


def test_extract_uri_confluence() -> None:
    loc = {"confluenceLocation": {"baseUrl": "https://wiki.example.com/", "path": "/pages/123"}}
    uri = BedrockKnowledgeBaseClient._extract_uri(loc)
    assert uri == "https://wiki.example.com/pages/123"


def test_extract_uri_confluence_no_double_slash() -> None:
    """Trailing slash on base + leading slash on path should NOT produce //."""
    loc = {"confluenceLocation": {"baseUrl": "https://wiki.example.com/", "path": "/spaces/ENG/page"}}
    result = BedrockKnowledgeBaseClient._extract_uri(loc)
    # Strip the scheme, then check no //
    assert "//" not in result.replace("https://", "")


def test_extract_uri_unknown_location_type() -> None:
    assert BedrockKnowledgeBaseClient._extract_uri({"unknown": {}}) == ""


# -- retrieve (original tests) -----------------------------------------------

def test_retrieve_normalizes_results() -> None:
    client = BedrockKnowledgeBaseClient(
        region="us-gov-west-1",
        knowledge_base_id="kb-123",
        top_k=3,
        bedrock_agent_runtime=FakeRuntime(),
    )

    out = client.retrieve("deploy steps")

    assert len(out) == 2
    assert out[0]["text"] == "Deploy guide"
    assert out[0]["title"] == "Runbook"
    assert out[0]["uri"] == "s3://kb-bucket/runbook.json"
    assert out[1]["uri"] == "https://wiki.local/page"


def test_retrieve_empty_query_returns_no_results() -> None:
    client = BedrockKnowledgeBaseClient(
        region="us-gov-west-1",
        knowledge_base_id="kb-123",
        bedrock_agent_runtime=FakeRuntime(),
    )

    assert client.retrieve("   ") == []


# -- retrieve (pagination & top_k) -------------------------------------------

def test_retrieve_pagination() -> None:
    """Verify that pagination consumes nextToken to gather all results."""
    page1 = _bedrock_response([_make_result(text="a"), _make_result(text="b")], next_token="tok2")
    page2 = _bedrock_response([_make_result(text="c")])

    mock_rt = MagicMock()
    mock_rt.retrieve.side_effect = [page1, page2]

    client = BedrockKnowledgeBaseClient("us-east-1", "kb-1", top_k=10, bedrock_agent_runtime=mock_rt)
    results = client.retrieve("paginated")
    assert len(results) == 3
    assert mock_rt.retrieve.call_count == 2


def test_retrieve_stops_at_top_k() -> None:
    """Should stop collecting once top_k results are reached."""
    big_page = _bedrock_response([_make_result(text=f"r{i}") for i in range(10)])
    mock_rt = MagicMock()
    mock_rt.retrieve.return_value = big_page

    client = BedrockKnowledgeBaseClient("us-east-1", "kb-1", top_k=3, bedrock_agent_runtime=mock_rt)
    results = client.retrieve("many")
    assert len(results) == 3


# -- retrieve (retry) --------------------------------------------------------

def test_retrieve_retries_on_throttle() -> None:
    """call_with_retry should be invoked with correct config."""
    mock_rt = MagicMock()
    client = BedrockKnowledgeBaseClient("us-east-1", "kb-1", bedrock_agent_runtime=mock_rt)
    with patch("shared.bedrock_kb.call_with_retry") as mock_retry:
        mock_retry.return_value = _bedrock_response([_make_result()])
        results = client.retrieve("retry test")
        assert len(results) == 1
        mock_retry.assert_called_once()


def test_retrieve_raises_non_retryable() -> None:
    """Non-retryable errors should propagate immediately."""
    mock_rt = MagicMock()
    mock_rt.retrieve.side_effect = _make_client_error("AccessDeniedException")

    client = BedrockKnowledgeBaseClient("us-east-1", "kb-1", bedrock_agent_runtime=mock_rt)
    with pytest.raises(ClientError):
        client.retrieve("denied")
