from __future__ import annotations

from typing import Any

import pytest

from shared.atlassian_client import AtlassianClient


# ---------------------------------------------------------------------------
# Helpers shared by Cloud and Data Center tests
# ---------------------------------------------------------------------------

def _make_secrets(platform: str = "cloud") -> "FakeSecrets":
    """Return a FakeSecrets that injects the given platform."""
    return FakeSecrets(platform=platform)


class FakeSecrets:
    def __init__(self, platform: str = "cloud"):
        base_jira = "https://jira.corp.example.com" if platform == "datacenter" else "https://example.atlassian.net"
        base_conf = "https://confluence.corp.example.com" if platform == "datacenter" else "https://example.atlassian.net"
        import json
        self._secret = json.dumps({
            "jira_base_url": base_jira,
            "confluence_base_url": base_conf,
            "email": "bot@example.com",
            "api_token": "tok",
            "platform": platform,
        })

    def get_secret_value(self, SecretId: str) -> dict:
        _ = SecretId
        return {"SecretString": self._secret}


class FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.last_request_kwargs: dict = {}

    def request(self, method: str, url: str, headers=None, auth=None, timeout=None, **kwargs):
        self.last_request_kwargs = {"method": method, "url": url, "params": kwargs.get("params")}
        # Cloud routes
        if "/rest/api/3/search/jql" in url:
            return FakeResponse(200, {"issues": [{"key": "ENG-1"}]})
        if "/wiki/rest/api/search" in url:
            return FakeResponse(200, {"results": [{"title": "Runbook"}]})
        if "/wiki/api/v2/pages/" in url:
            return FakeResponse(200, {"id": "123", "title": "Page", "body": {"storage": {"value": "<p>ok</p>"}}})
        # Data Center routes
        if "/rest/api/2/search" in url:
            return FakeResponse(200, {"issues": [{"key": "DC-1"}]})
        if "/rest/api/content/" in url:
            return FakeResponse(200, {"id": "456", "title": "DC Page", "body": {"storage": {"value": "<p>dc</p>"}}})
        if "/rest/api/search" in url:
            return FakeResponse(200, {"results": [{"title": "DC Runbook"}]})
        # Jira issue (both platforms)
        if "/rest/api/3/issue/" in url or "/rest/api/2/issue/" in url:
            return FakeResponse(200, {"key": "TEST-1", "fields": {"summary": "Test issue"}})
        return FakeResponse(404, {})


# ---------------------------------------------------------------------------
# Cloud tests (existing)
# ---------------------------------------------------------------------------

def test_search_jira_and_confluence() -> None:
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("cloud"), session=FakeSession())

    jira = client.search_jira("project=ENG")
    conf = client.search_confluence("type=page")

    assert jira[0]["key"] == "ENG-1"
    assert conf[0]["title"] == "Runbook"


def test_get_confluence_page_sends_body_format() -> None:
    """Critical fix C1: body-format=storage must be sent as a query param."""
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("cloud"), session=session)

    result = client.get_confluence_page("123")
    assert result["id"] == "123"
    # Verify body-format param was passed (Cloud V2 API)
    assert session.last_request_kwargs["params"] == {"body-format": "storage"}


def test_get_confluence_page_custom_body_format() -> None:
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("cloud"), session=session)

    client.get_confluence_page("123", body_format="atlas_doc_format")
    assert session.last_request_kwargs["params"] == {"body-format": "atlas_doc_format"}


def test_cloud_jira_uses_api_v3() -> None:
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("cloud"), session=session)
    client.get_jira_issue("TEST-1")
    assert "/rest/api/3/issue/TEST-1" in session.last_request_kwargs["url"]


def test_cloud_confluence_search_uses_wiki_prefix() -> None:
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("cloud"), session=session)
    client.search_confluence("type=page")
    assert "/wiki/rest/api/search" in session.last_request_kwargs["url"]


# ---------------------------------------------------------------------------
# Data Center tests
# ---------------------------------------------------------------------------

def test_datacenter_jira_uses_api_v2() -> None:
    """Data Center / Server uses /rest/api/2/ instead of /rest/api/3/."""
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("datacenter"), session=session)
    client.get_jira_issue("TEST-1")
    assert "/rest/api/2/issue/TEST-1" in session.last_request_kwargs["url"]
    assert "jira.corp.example.com" in session.last_request_kwargs["url"]


def test_datacenter_jira_search_uses_api_v2() -> None:
    """Data Center uses /rest/api/2/search (not /search/jql)."""
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("datacenter"), session=session)
    results = client.search_jira("project=DC")
    assert results[0]["key"] == "DC-1"
    assert "/rest/api/2/search" in session.last_request_kwargs["url"]
    assert "/search/jql" not in session.last_request_kwargs["url"]


def test_datacenter_confluence_page_uses_content_api() -> None:
    """Data Center uses /rest/api/content/{id} with expand=body.storage (not /wiki/api/v2/)."""
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("datacenter"), session=session)
    result = client.get_confluence_page("456")
    assert result["id"] == "456"
    assert "/rest/api/content/456" in session.last_request_kwargs["url"]
    assert "/wiki/" not in session.last_request_kwargs["url"]
    assert session.last_request_kwargs["params"] == {"expand": "body.storage"}


def test_datacenter_confluence_search_no_wiki_prefix() -> None:
    """Data Center uses /rest/api/search (no /wiki/ prefix)."""
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=_make_secrets("datacenter"), session=session)
    results = client.search_confluence("type=page")
    assert results[0]["title"] == "DC Runbook"
    assert "/rest/api/search" in session.last_request_kwargs["url"]
    assert "/wiki/" not in session.last_request_kwargs["url"]


def test_platform_defaults_to_cloud() -> None:
    """When platform field is omitted, default to cloud API paths."""
    import json
    class NoplatformSecrets:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps({
                "jira_base_url": "https://example.atlassian.net",
                "confluence_base_url": "https://example.atlassian.net",
                "email": "bot@example.com",
                "api_token": "tok",
            })}
    session = FakeSession()
    client = AtlassianClient("arn:fake", secrets_client=NoplatformSecrets(), session=session)
    assert client.platform == "cloud"
    client.search_jira("project=ENG")
    assert "/rest/api/3/" in session.last_request_kwargs["url"]


def test_invalid_platform_raises() -> None:
    """Invalid platform value should raise ValueError."""
    import json
    class BadPlatformSecrets:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps({
                "jira_base_url": "https://example.com",
                "confluence_base_url": "https://example.com",
                "email": "bot@example.com",
                "api_token": "tok",
                "platform": "invalid_platform",
            })}
    client = AtlassianClient("arn:fake", secrets_client=BadPlatformSecrets(), session=FakeSession())
    with pytest.raises(ValueError, match="Invalid Atlassian platform"):
        client.search_jira("project=X")
