"""Tests for kb_sync.app – sync, error isolation, and delta sync."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from kb_sync.app import (
    _build_confluence_doc,
    _get_last_sync_time,
    _set_last_sync_time,
    _strip_html,
    lambda_handler,
)


def test_strip_html() -> None:
    raw = "<p>Hello <strong>world</strong> &amp; team</p>"
    assert _strip_html(raw) == "Hello world & team"


def test_build_confluence_doc() -> None:
    page = {
        "id": "123",
        "title": "Incident Runbook",
        "_links": {"webui": "https://wiki.example/pages/123"},
        "body": {"storage": {"value": "<h1>Runbook</h1><p>Step one.</p>"}},
        "version": {"when": "2026-02-12T00:00:00.000Z"},
    }

    doc = _build_confluence_doc(page)
    assert doc["id"] == "123"
    assert doc["title"] == "Incident Runbook"
    assert doc["url"] == "https://wiki.example/pages/123"
    assert "Runbook" in doc["text"]
    assert "Step one." in doc["text"]


# -- delta sync helpers ------------------------------------------------------

def test_get_last_sync_time_returns_value() -> None:
    mock_ddb = MagicMock()
    mock_ddb.get_item.return_value = {
        "Item": {"sync_key": {"S": "confluence_sync"}, "last_sync_time": {"S": "2026-01-01 12:00"}}
    }
    assert _get_last_sync_time(mock_ddb, "sync-table") == "2026-01-01 12:00"


def test_get_last_sync_time_returns_none_on_missing() -> None:
    mock_ddb = MagicMock()
    mock_ddb.get_item.return_value = {}
    assert _get_last_sync_time(mock_ddb, "sync-table") is None


def test_get_last_sync_time_returns_none_on_error() -> None:
    mock_ddb = MagicMock()
    mock_ddb.get_item.side_effect = RuntimeError("DDB down")
    assert _get_last_sync_time(mock_ddb, "sync-table") is None


def test_set_last_sync_time() -> None:
    mock_ddb = MagicMock()
    _set_last_sync_time(mock_ddb, "sync-table", "2026-01-01 12:00")
    mock_ddb.put_item.assert_called_once()
    args = mock_ddb.put_item.call_args
    assert args.kwargs["Item"]["last_sync_time"]["S"] == "2026-01-01 12:00"


def test_set_last_sync_time_swallows_error() -> None:
    mock_ddb = MagicMock()
    mock_ddb.put_item.side_effect = RuntimeError("DDB down")
    # Should not raise
    _set_last_sync_time(mock_ddb, "sync-table", "2026-01-01 12:00")


# -- lambda_handler integration tests ----------------------------------------

_BASE_ENV = {
    "ATLASSIAN_CREDENTIALS_SECRET_ARN": "arn:fake",
    "BEDROCK_KNOWLEDGE_BASE_ID": "kb-1",
    "BEDROCK_KB_DATA_SOURCE_ID": "ds-1",
    "KB_SYNC_BUCKET": "my-bucket",
    "KB_SYNC_PREFIX": "confluence",
    "CONFLUENCE_SYNC_CQL": "type=page",
    "CONFLUENCE_SYNC_LIMIT": "10",
    "KB_SYNC_STATE_TABLE": "",
}


@patch("kb_sync.app.boto3")
@patch("kb_sync.app.AtlassianClient")
def test_lambda_handler_uploads_and_starts_ingestion(mock_atlassian_cls, mock_boto) -> None:
    """Happy path: pages fetched, uploaded to S3, ingestion started."""
    mock_atlassian = MagicMock()
    mock_atlassian.search_confluence.return_value = [{"id": "100", "content": {"id": "100"}}]
    mock_atlassian.get_confluence_page.return_value = {
        "id": "100",
        "title": "Deploy",
        "_links": {"webui": "/pages/100"},
        "body": {"storage": {"value": "<p>Steps</p>"}},
        "version": {"when": "2026-06-01T00:00:00Z"},
    }
    mock_atlassian_cls.return_value = mock_atlassian

    mock_s3 = MagicMock()
    mock_bedrock = MagicMock()
    mock_bedrock.start_ingestion_job.return_value = {"ingestionJob": {"ingestionJobId": "job-1"}}
    mock_ddb = MagicMock()

    def _client_factory(service, **kwargs):
        return {"s3": mock_s3, "bedrock-agent": mock_bedrock, "dynamodb": mock_ddb}[service]

    mock_boto.client.side_effect = _client_factory

    with patch.dict("os.environ", _BASE_ENV, clear=False):
        result = lambda_handler({}, None)

    assert result["uploaded"] == 1
    assert result["failed"] == 0
    assert result["ingestion_job_id"] == "job-1"
    mock_s3.put_object.assert_called_once()
    mock_bedrock.start_ingestion_job.assert_called_once()


@patch("kb_sync.app.boto3")
@patch("kb_sync.app.AtlassianClient")
def test_lambda_handler_skips_failed_pages(mock_atlassian_cls, mock_boto) -> None:
    """Error isolation: a failing page is skipped, other pages continue."""
    mock_atlassian = MagicMock()
    mock_atlassian.search_confluence.return_value = [
        {"id": "200", "content": {"id": "200"}},
        {"id": "201", "content": {"id": "201"}},
    ]

    def _get_page(page_id, **kwargs):
        if page_id == "200":
            raise RuntimeError("API error")
        return {
            "id": "201",
            "title": "Good page",
            "_links": {},
            "body": {"storage": {"value": "<p>OK</p>"}},
            "version": {},
        }

    mock_atlassian.get_confluence_page.side_effect = _get_page
    mock_atlassian_cls.return_value = mock_atlassian

    mock_s3 = MagicMock()
    mock_bedrock = MagicMock()
    mock_bedrock.start_ingestion_job.return_value = {"ingestionJob": {"ingestionJobId": "job-2"}}

    def _client_factory(service, **kwargs):
        return {"s3": mock_s3, "bedrock-agent": mock_bedrock, "dynamodb": MagicMock()}[service]

    mock_boto.client.side_effect = _client_factory

    with patch.dict("os.environ", _BASE_ENV, clear=False):
        result = lambda_handler({}, None)

    assert result["uploaded"] == 1
    assert result["failed"] == 1


@patch("kb_sync.app.boto3")
@patch("kb_sync.app.AtlassianClient")
def test_lambda_handler_no_ingestion_when_zero_uploads(mock_atlassian_cls, mock_boto) -> None:
    """When no pages are uploaded, ingestion job should NOT be started."""
    mock_atlassian = MagicMock()
    mock_atlassian.search_confluence.return_value = []
    mock_atlassian_cls.return_value = mock_atlassian

    mock_bedrock = MagicMock()

    def _client_factory(service, **kwargs):
        return {"s3": MagicMock(), "bedrock-agent": mock_bedrock, "dynamodb": MagicMock()}[service]

    mock_boto.client.side_effect = _client_factory

    with patch.dict("os.environ", _BASE_ENV, clear=False):
        result = lambda_handler({}, None)

    assert result["uploaded"] == 0
    mock_bedrock.start_ingestion_job.assert_not_called()


@patch("kb_sync.app.boto3")
@patch("kb_sync.app.AtlassianClient")
def test_lambda_handler_delta_sync_appends_cql(mock_atlassian_cls, mock_boto) -> None:
    """When DynamoDB has a last_sync_time, CQL should include the filter."""
    mock_atlassian = MagicMock()
    mock_atlassian.search_confluence.return_value = []
    mock_atlassian_cls.return_value = mock_atlassian

    mock_ddb = MagicMock()
    mock_ddb.get_item.return_value = {
        "Item": {"sync_key": {"S": "confluence_sync"}, "last_sync_time": {"S": "2026-01-01 12:00"}}
    }

    def _client_factory(service, **kwargs):
        return {"s3": MagicMock(), "bedrock-agent": MagicMock(), "dynamodb": mock_ddb}[service]

    mock_boto.client.side_effect = _client_factory

    env = {**_BASE_ENV, "KB_SYNC_STATE_TABLE": "sync-table"}
    with patch.dict("os.environ", env, clear=False):
        lambda_handler({}, None)

    actual_cql = mock_atlassian.search_confluence.call_args[0][0]
    assert 'lastmodified > "2026-01-01 12:00"' in actual_cql
