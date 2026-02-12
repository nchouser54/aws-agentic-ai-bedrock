from __future__ import annotations

import json
from typing import Any, Optional

import boto3
import requests
from botocore.client import BaseClient

from shared.retry import call_with_retry


class AtlassianClient:
    def __init__(
        self,
        credentials_secret_arn: str,
        secrets_client: Optional[BaseClient] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._credentials_secret_arn = credentials_secret_arn
        self._secrets = secrets_client or boto3.client("secretsmanager")
        self._session = session or requests.Session()
        self._credentials_cache: Optional[dict[str, str]] = None

    def _load_credentials(self) -> dict[str, str]:
        if self._credentials_cache:
            return self._credentials_cache

        response = self._secrets.get_secret_value(SecretId=self._credentials_secret_arn)
        secret = response.get("SecretString")
        if not secret:
            raise ValueError("Atlassian credentials secret missing SecretString")

        data = json.loads(secret)
        required = ["jira_base_url", "confluence_base_url", "email", "api_token"]
        for key in required:
            if key not in data or not str(data[key]).strip():
                raise ValueError(f"Atlassian credentials missing field: {key}")

        self._credentials_cache = {
            "jira_base_url": data["jira_base_url"].rstrip("/"),
            "confluence_base_url": data["confluence_base_url"].rstrip("/"),
            "email": data["email"],
            "api_token": data["api_token"],
        }
        return self._credentials_cache

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        creds = self._load_credentials()
        base_headers = kwargs.pop("headers", {})

        def _do() -> requests.Response:
            headers = dict(base_headers)
            headers.update({"Accept": "application/json"})
            return self._session.request(
                method,
                url,
                headers=headers,
                auth=(creds["email"], creds["api_token"]),
                timeout=20,
                **kwargs,
            )

        response = call_with_retry(
            operation_name=f"atlassian_{method}_{url}",
            fn=_do,
            is_retryable_exception=lambda exc: isinstance(exc, requests.RequestException),
            is_retryable_result=lambda r: r.status_code in {403, 429} or r.status_code >= 500,
        )
        response.raise_for_status()
        return response

    def get_jira_issue(self, issue_key: str) -> dict[str, Any]:
        creds = self._load_credentials()
        url = f"{creds['jira_base_url']}/rest/api/3/issue/{issue_key}"
        response = self._request(
            "GET",
            url,
            params={"fields": "summary,description,status,issuetype,priority,assignee"},
        )
        return response.json()

    def search_jira(self, jql: str, max_results: int = 5) -> list[dict[str, Any]]:
        creds = self._load_credentials()
        url = f"{creds['jira_base_url']}/rest/api/3/search/jql"
        response = self._request("GET", url, params={"jql": jql, "maxResults": max_results})
        return response.json().get("issues", [])

    def get_confluence_page(self, page_id: str) -> dict[str, Any]:
        creds = self._load_credentials()
        url = f"{creds['confluence_base_url']}/wiki/api/v2/pages/{page_id}"
        response = self._request("GET", url)
        return response.json()

    def search_confluence(self, cql: str, limit: int = 5) -> list[dict[str, Any]]:
        creds = self._load_credentials()
        url = f"{creds['confluence_base_url']}/wiki/rest/api/search"
        response = self._request("GET", url, params={"cql": cql, "limit": limit})
        return response.json().get("results", [])
