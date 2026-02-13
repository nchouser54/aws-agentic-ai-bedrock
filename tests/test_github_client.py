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
        if url.endswith("/pulls/1/commits"):
            return FakeResponse(200, [{"sha": "pr-c1", "commit": {"message": "pr commit"}}])
        if url.endswith("/pulls/1/files"):
            params = kwargs.get("params", {})
            page = params.get("page", 1)
            if page == 1:
                return FakeResponse(200, [{"filename": "a.py"}])
            return FakeResponse(200, [])
        if url.endswith("/pulls/1"):
            return FakeResponse(200, {"number": 1, "title": "test"})
        if url.endswith("/repos/o/r") and method == "GET":
            return FakeResponse(200, {"name": "r", "default_branch": "main"})
        if "/git/trees/" in url and method == "GET":
            return FakeResponse(
                200,
                {
                    "tree": [
                        {"type": "blob", "path": "README.md"},
                        {"type": "tree", "path": "docs"},
                        {"type": "blob", "path": "docs/guide.md"},
                    ]
                },
            )
        if url.endswith("/reviews"):
            return FakeResponse(200, {"id": 777})
        if "/releases/tags/" in url:
            return FakeResponse(200, {"id": 1, "tag_name": "v2.0"})
        if url.endswith("/releases/latest"):
            return FakeResponse(200, {"id": 1, "tag_name": "v2.0"})
        if "/compare/" in url:
            return FakeResponse(200, {
                "commits": [{"sha": "aaa"}, {"sha": "bbb"}],
                "files": [{"filename": "f.py"}],
            })
        if url.endswith("/search/code"):
            return FakeResponse(200, {"items": [{"path": "docs/guide.md", "repository": {"full_name": "o/r"}}]})
        if "/tags" in url:
            return FakeResponse(200, [{"name": "v2.0"}, {"name": "v1.5"}, {"name": "v1.0"}])
        if url.endswith("/releases") and method == "POST":
            return FakeResponse(200, {"id": 2, "html_url": "https://github.com/o/r/releases/2"})
        if "/releases/" in url and method == "PATCH":
            return FakeResponse(200, {"id": 1, "body": "updated"})
        if url.endswith("/pulls") and method == "GET":
            return FakeResponse(200, [{"number": 10, "title": "feat"}])
        if url.endswith("/commits") and method == "GET":
            return FakeResponse(200, [{"sha": "c1", "commit": {"message": "fix: bug"}}])
        if "/issues/" in url and url.endswith("/comments") and method == "POST":
            return FakeResponse(200, {"id": 42, "body": kwargs.get("json", {}).get("body", "")})
        if url.endswith("/pulls/1") and method == "PATCH":
            return FakeResponse(200, {"number": 1, "body": kwargs.get("json", {}).get("body", "updated")})
        return FakeResponse(404, {"message": "not found"})


def test_get_pull_request_and_files() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)

    pr = client.get_pull_request("o", "r", 1)
    files = client.get_pull_request_files("o", "r", 1)

    assert pr["number"] == 1
    assert files == [{"filename": "a.py"}]


def test_get_repository() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    repo = client.get_repository("o", "r")
    assert repo["default_branch"] == "main"


def test_list_repository_files() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    files = client.list_repository_files("o", "r", "main")
    assert files == ["README.md", "docs/guide.md"]


def test_list_tags() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    tags = client.list_tags("o", "r")
    assert len(tags) == 3
    assert tags[0]["name"] == "v2.0"


def test_compare_commits() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    result = client.compare_commits("o", "r", "v1.0", "v2.0")
    assert len(result["commits"]) == 2


def test_search_code() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    items = client.search_code("repo:o/r docs", per_page=5)
    assert len(items) == 1
    assert items[0]["path"] == "docs/guide.md"


def test_create_release() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    release = client.create_release("o", "r", "v3.0", "v3.0", "notes")
    assert release["id"] == 2


def test_get_release_by_tag() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    release = client.get_release_by_tag("o", "r", "v2.0")
    assert release["tag_name"] == "v2.0"


def test_update_release() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    result = client.update_release("o", "r", 1, "new body")
    assert result["body"] == "updated"


def test_create_pull_review() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)

    out = client.create_pull_review("o", "r", 1, "body", "sha", comments=[{"path": "a.py", "position": 1, "body": "x"}])
    assert out["id"] == 777


def test_list_pulls() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    pulls = client.list_pulls("o", "r")
    assert len(pulls) == 1
    assert pulls[0]["number"] == 10


def test_list_commits() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    commits = client.list_commits("o", "r", since="2024-01-01T00:00:00Z")
    assert len(commits) == 1
    assert commits[0]["sha"] == "c1"


def test_list_pull_commits() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    commits = client.list_pull_commits("o", "r", 1)
    assert len(commits) == 1
    assert commits[0]["sha"] == "pr-c1"


def test_create_issue_comment() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    comment = client.create_issue_comment("o", "r", 1, "nice work!")
    assert comment["id"] == 42
    assert comment["body"] == "nice work!"


def test_update_pull_request() -> None:
    session = FakeSession()
    client = GitHubClient(token_provider=lambda: "tok", session=session)
    result = client.update_pull_request("o", "r", 1, body="new body")
    assert result["number"] == 1
