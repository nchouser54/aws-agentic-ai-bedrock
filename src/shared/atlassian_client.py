from __future__ import annotations

import json
from typing import Any, Optional

import boto3
import requests
from botocore.client import BaseClient

from shared.retry import call_with_retry

# Supported platform values for the optional "platform" field in the
# Atlassian credentials secret.  When absent the client defaults to "cloud".
PLATFORM_CLOUD = "cloud"
PLATFORM_DATACENTER = "datacenter"
_VALID_PLATFORMS = {PLATFORM_CLOUD, PLATFORM_DATACENTER}


class AtlassianClient:
    """Atlassian REST client that auto-detects Cloud vs Data Center/Server.

    The deployment type is controlled by an optional ``platform`` field in the
    Secrets Manager JSON payload (``"cloud"`` or ``"datacenter"``).  API paths,
    query parameters and the REST API version are adjusted automatically:

    **Jira**
    - Cloud: ``/rest/api/3/`` – ``search/jql`` endpoint
    - Data Center/Server: ``/rest/api/2/`` – ``search`` endpoint

    **Confluence**
    - Cloud: ``/wiki/api/v2/pages/{id}`` + ``/wiki/rest/api/search``
    - Data Center/Server: ``/rest/api/content/{id}`` + ``/rest/api/search``

    Authentication uses HTTP Basic in both cases.  For Cloud, provide
    ``email`` + ``api_token``.  For Data Center, provide your local
    ``username`` (in the ``email`` field) and a
    **personal access token / password** (in the ``api_token`` field).
    """

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

    # -- credentials -----------------------------------------------------------

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

        platform = data.get("platform", PLATFORM_CLOUD).lower().strip()
        if platform not in _VALID_PLATFORMS:
            raise ValueError(
                f"Invalid Atlassian platform '{platform}'. Must be one of: {', '.join(sorted(_VALID_PLATFORMS))}"
            )

        self._credentials_cache = {
            "jira_base_url": data["jira_base_url"].rstrip("/"),
            "confluence_base_url": data["confluence_base_url"].rstrip("/"),
            "email": data["email"],
            "api_token": data["api_token"],
            "platform": platform,
        }
        return self._credentials_cache

    @property
    def platform(self) -> str:
        """Return ``'cloud'`` or ``'datacenter'`` after credentials load."""
        return self._load_credentials()["platform"]

    def _is_datacenter(self) -> bool:
        return self.platform == PLATFORM_DATACENTER

    # -- HTTP helper -----------------------------------------------------------

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

    # -- Jira ------------------------------------------------------------------

    def get_jira_issue(self, issue_key: str) -> dict[str, Any]:
        creds = self._load_credentials()
        api_version = "2" if self._is_datacenter() else "3"
        url = f"{creds['jira_base_url']}/rest/api/{api_version}/issue/{issue_key}"
        response = self._request(
            "GET",
            url,
            params={"fields": "summary,description,status,issuetype,priority,assignee"},
        )
        return response.json()

    def search_jira(self, jql: str, max_results: int = 5) -> list[dict[str, Any]]:
        creds = self._load_credentials()
        if self._is_datacenter():
            # Data Center / Server uses /rest/api/2/search
            url = f"{creds['jira_base_url']}/rest/api/2/search"
        else:
            # Cloud uses /rest/api/3/search/jql
            url = f"{creds['jira_base_url']}/rest/api/3/search/jql"
        response = self._request("GET", url, params={"jql": jql, "maxResults": max_results})
        return response.json().get("issues", [])

    # -- Confluence ------------------------------------------------------------

    def get_confluence_page(self, page_id: str, body_format: str = "storage") -> dict[str, Any]:
        creds = self._load_credentials()
        if self._is_datacenter():
            # Data Center / Server: /rest/api/content/{id}?expand=body.storage
            url = f"{creds['confluence_base_url']}/rest/api/content/{page_id}"
            response = self._request("GET", url, params={"expand": f"body.{body_format}"})
        else:
            # Cloud: /wiki/api/v2/pages/{id}?body-format=storage
            url = f"{creds['confluence_base_url']}/wiki/api/v2/pages/{page_id}"
            response = self._request("GET", url, params={"body-format": body_format})
        return response.json()

    def search_confluence(self, cql: str, limit: int = 5) -> list[dict[str, Any]]:
        creds = self._load_credentials()
        if self._is_datacenter():
            # Data Center / Server: /rest/api/search (no /wiki/ prefix)
            url = f"{creds['confluence_base_url']}/rest/api/search"
        else:
            # Cloud: /wiki/rest/api/search
            url = f"{creds['confluence_base_url']}/wiki/rest/api/search"
        response = self._request("GET", url, params={"cql": cql, "limit": limit})
        return response.json().get("results", [])
