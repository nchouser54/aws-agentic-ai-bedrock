from __future__ import annotations

import base64
from typing import Callable, Optional

import requests

from shared.retry import call_with_retry


class GitHubClient:
    def __init__(
        self,
        token_provider: Callable[[], str],
        api_base: str = "https://api.github.com",
        session: Optional[requests.Session] = None,
    ) -> None:
        self._token_provider = token_provider
        self._api_base = api_base.rstrip("/")
        self._session = session or requests.Session()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self._api_base}{path}"
        base_headers = kwargs.pop("headers", {})

        def _do_request() -> requests.Response:
            headers = dict(base_headers)
            headers.update(
                {
                    "Authorization": f"token {self._token_provider()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )
            return self._session.request(method, url, headers=headers, timeout=20, **kwargs)

        response = call_with_retry(
            operation_name=f"github_{method}_{path}",
            fn=_do_request,
            is_retryable_exception=lambda exc: isinstance(exc, requests.RequestException),
            is_retryable_result=lambda r: r.status_code in {403, 429} or r.status_code >= 500,
        )
        response.raise_for_status()
        return response

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> dict:
        response = self._request("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}")
        return response.json()

    def search_code(self, query: str, per_page: int = 10) -> list[dict]:
        response = self._request(
            "GET",
            "/search/code",
            params={"q": query, "per_page": per_page},
        )
        return response.json().get("items", [])

    def get_repository(self, owner: str, repo: str) -> dict:
        response = self._request("GET", f"/repos/{owner}/{repo}")
        return response.json()

    def get_pull_request_files(self, owner: str, repo: str, pull_number: int) -> list[dict]:
        page = 1
        files: list[dict] = []
        while True:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{pull_number}/files",
                params={"per_page": 100, "page": page},
            )
            page_data = response.json()
            if not page_data:
                break
            files.extend(page_data)
            if len(page_data) < 100:
                break
            page += 1
        return files

    def create_pull_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
        commit_id: Optional[str] = None,
        comments: Optional[list[dict]] = None,
    ) -> dict:
        payload: dict = {
            "event": "COMMENT",
            "body": body,
        }
        if commit_id:
            payload["commit_id"] = commit_id
        if comments:
            payload["comments"] = comments

        response = self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            json=payload,
        )
        return response.json()

    def get_ref(self, owner: str, repo: str, ref: str) -> dict:
        response = self._request("GET", f"/repos/{owner}/{repo}/git/ref/{ref}")
        return response.json()

    def create_ref(self, owner: str, repo: str, ref: str, sha: str) -> dict:
        response = self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": ref, "sha": sha},
        )
        return response.json()

    def get_file_contents(self, owner: str, repo: str, path: str, ref: str) -> tuple[str, str]:
        response = self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params={"ref": ref})
        data = response.json()
        encoded = data.get("content", "").replace("\n", "")
        decoded = base64.b64decode(encoded).decode("utf-8")
        return decoded, data["sha"]

    def list_repository_files(self, owner: str, repo: str, ref: str) -> list[str]:
        """List all file paths in a repository tree for a given ref/branch."""
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{ref}",
            params={"recursive": "1"},
        )
        data = response.json()
        tree = data.get("tree") or []
        return [str(item.get("path") or "") for item in tree if item.get("type") == "blob" and item.get("path")]

    def put_file_contents(
        self,
        owner: str,
        repo: str,
        path: str,
        branch: str,
        message: str,
        content: str,
        sha: Optional[str] = None,
    ) -> dict:
        payload: dict = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        response = self._request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{path}",
            json=payload,
        )
        return response.json()

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str,
    ) -> dict:
        response = self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
            },
        )
        return response.json()

    # -- releases & tags -------------------------------------------------------

    def list_tags(self, owner: str, repo: str, per_page: int = 30) -> list[dict]:
        """Return repository tags, newest first."""
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/tags",
            params={"per_page": per_page},
        )
        return response.json()

    def compare_commits(
        self, owner: str, repo: str, base: str, head: str,
    ) -> dict:
        """Compare two commits/tags/branches. Returns commits & files between them."""
        response = self._request(
            "GET", f"/repos/{owner}/{repo}/compare/{base}...{head}",
        )
        return response.json()

    def list_merged_pulls_between(
        self,
        owner: str,
        repo: str,
        base_sha: str,
        head_sha: str,
    ) -> list[dict]:
        """Return merged PRs whose merge_commit_sha appears between base and head."""
        comparison = self.compare_commits(owner, repo, base_sha, head_sha)
        commit_shas = {c.get("sha") for c in comparison.get("commits", [])}

        merged_prs: list[dict] = []
        page = 1
        while True:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls",
                params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100, "page": page},
            )
            pulls = response.json()
            if not pulls:
                break
            for pr in pulls:
                merge_sha = pr.get("merge_commit_sha")
                if pr.get("merged_at") and merge_sha in commit_shas:
                    merged_prs.append(pr)
                    commit_shas.discard(merge_sha)
            if not commit_shas or len(pulls) < 100:
                break
            page += 1
        return merged_prs

    def get_release_by_tag(self, owner: str, repo: str, tag: str) -> dict:
        response = self._request(
            "GET", f"/repos/{owner}/{repo}/releases/tags/{tag}",
        )
        return response.json()

    def get_latest_release(self, owner: str, repo: str) -> dict:
        response = self._request(
            "GET", f"/repos/{owner}/{repo}/releases/latest",
        )
        return response.json()

    def create_release(
        self,
        owner: str,
        repo: str,
        tag_name: str,
        name: str,
        body: str,
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict:
        response = self._request(
            "POST",
            f"/repos/{owner}/{repo}/releases",
            json={
                "tag_name": tag_name,
                "name": name,
                "body": body,
                "draft": draft,
                "prerelease": prerelease,
            },
        )
        return response.json()

    def update_release(
        self, owner: str, repo: str, release_id: int, body: str,
    ) -> dict:
        response = self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/releases/{release_id}",
            json={"body": body},
        )
        return response.json()

    # -- pulls & issues --------------------------------------------------------

    def list_pulls(
        self,
        owner: str,
        repo: str,
        state: str = "closed",
        sort: str = "updated",
        direction: str = "desc",
        per_page: int = 30,
    ) -> list[dict]:
        """List pull requests with basic filtering."""
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": state,
                "sort": sort,
                "direction": direction,
                "per_page": per_page,
            },
        )
        return response.json()

    def list_commits(
        self,
        owner: str,
        repo: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        sha: Optional[str] = None,
        per_page: int = 30,
    ) -> list[dict]:
        """List commits with optional date filtering (ISO 8601 timestamps)."""
        params: dict = {"per_page": per_page}
        if since:
            params["since"] = since
        if until:
            params["until"] = until
        if sha:
            params["sha"] = sha
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits",
            params=params,
        )
        return response.json()

    def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str,
    ) -> dict:
        """Post a comment on an issue or pull request."""
        response = self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        return response.json()

    def update_pull_request(
        self, owner: str, repo: str, pull_number: int, **kwargs,
    ) -> dict:
        """Update a pull request (body, title, state, etc.)."""
        response = self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/pulls/{pull_number}",
            json=kwargs,
        )
        return response.json()

    def list_pull_commits(
        self, owner: str, repo: str, pull_number: int,
    ) -> list[dict]:
        """List commits on a pull request."""
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/commits",
            params={"per_page": 100},
        )
        return response.json()
