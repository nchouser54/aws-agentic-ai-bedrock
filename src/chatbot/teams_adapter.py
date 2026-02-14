from __future__ import annotations

import hmac
import json
import os
from typing import Any

import boto3

from chatbot.app import handle_query

_cached_teams_token: str | None = None
_secrets_client: Any | None = None


def _get_secrets_client() -> Any:
    global _secrets_client  # noqa: PLW0603
    if _secrets_client is None:
        _secrets_client = boto3.client("secretsmanager")
    return _secrets_client


def _load_teams_token() -> str:
    """Load Teams adapter token from Secrets Manager or env var, with caching."""
    global _cached_teams_token  # noqa: PLW0603
    if _cached_teams_token is not None:
        return _cached_teams_token

    secret_arn = os.getenv("TEAMS_ADAPTER_TOKEN_SECRET_ARN", "").strip()
    if secret_arn:
        client = _get_secrets_client()
        resp = client.get_secret_value(SecretId=secret_arn)
        _cached_teams_token = (resp.get("SecretString") or "").strip()
    else:
        _cached_teams_token = os.getenv("TEAMS_ADAPTER_TOKEN", "").strip()
    return _cached_teams_token


def _get_header(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == target:
            return value
    return None


def _authorized(headers: dict[str, str]) -> bool:
    expected = _load_teams_token()
    if not expected:
        return True
    provided = _get_header(headers, "X-Teams-Adapter-Token") or ""
    return hmac.compare_digest(provided, expected)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method != "POST":
        return {"statusCode": 405, "body": json.dumps({"error": "method_not_allowed"})}

    headers = event.get("headers") or {}
    if not _authorized(headers):
        return {"statusCode": 401, "body": json.dumps({"error": "unauthorized"})}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "invalid_json"})}

    text = str(body.get("text") or "").strip()
    if not text:
        return {"statusCode": 400, "body": json.dumps({"error": "text_required"})}

    channel_data = body.get("channelData") or {}
    jira_jql = str(channel_data.get("jira_jql") or "").strip() or "order by updated DESC"
    confluence_cql = str(channel_data.get("confluence_cql") or "").strip() or "type=page order by lastmodified desc"
    retrieval_mode = str(channel_data.get("retrieval_mode") or "").strip() or None

    correlation_id = event.get("requestContext", {}).get("requestId", "unknown")
    result = handle_query(text, jira_jql, confluence_cql, correlation_id, retrieval_mode=retrieval_mode)

    activity = {
        "type": "message",
        "text": result["answer"],
    }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(activity),
    }
