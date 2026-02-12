from __future__ import annotations

from typing import Any

from shared.github_client import GitHubClient


class FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method: str, url: str, headers=None, timeout=None, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/pulls/1/files"):
            params = kwargs.get("params", {})
            page = params.get("page", 1)
            if page == 1:
                return FakeResponse(200, [{"filename": "a.py"}])
            return FakeResponse(200, [])
        if url.endswith("/pulls/1"):
            return FakeResponse(200, {"number": 1, "title": "test"})
        if url.endswith("/reviews"):
            return FakeResponse(200, {"id": 777})
        return FakeResponse(404, {"message": "not found"})


def test_get_pull_request_and_files() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)

    pr = client.get_pull_request("o", "r", 1)
    files = client.get_pull_request_files("o", "r", 1)

    assert pr["number"] == 1
    assert files == [{"filename": "a.py"}]


def test_create_pull_review() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)

    out = client.create_pull_review("o", "r", 1, "body", "sha", comments=[{"path": "a.py", "position": 1, "body": "x"}])
    assert out["id"] == 777
