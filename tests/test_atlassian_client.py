from __future__ import annotations

from typing import Any

from shared.atlassian_client import AtlassianClient


class FakeSecrets:
    def get_secret_value(self, SecretId: str) -> dict:
        _ = SecretId
        secret = (
            '{"jira_base_url":"https://example.atlassian.net",'
            '"confluence_base_url":"https://example.atlassian.net",'
            '"email":"bot@example.com",'
            '"api_token":"tok"}'
        )
        return {
            "SecretString": secret
        }


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
    def request(self, method: str, url: str, headers=None, auth=None, timeout=None, **kwargs):
        if "/rest/api/3/search/jql" in url:
            return FakeResponse(200, {"issues": [{"key": "ENG-1"}]})
        if "/wiki/rest/api/search" in url:
            return FakeResponse(200, {"results": [{"title": "Runbook"}]})
        return FakeResponse(404, {})


def test_search_jira_and_confluence() -> None:
    client = AtlassianClient("arn:fake", secrets_client=FakeSecrets(), session=FakeSession())

    jira = client.search_jira("project=ENG")
    conf = client.search_confluence("type=page")

    assert jira[0]["key"] == "ENG-1"
    assert conf[0]["title"] == "Runbook"
