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
