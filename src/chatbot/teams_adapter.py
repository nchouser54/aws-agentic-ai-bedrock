from __future__ import annotations

import json
import os
from typing import Any

from chatbot.app import handle_query


def _get_header(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == target:
            return value
    return None


def _authorized(headers: dict[str, str]) -> bool:
    expected = os.getenv("TEAMS_ADAPTER_TOKEN", "").strip()
    if not expected:
        return True
    provided = _get_header(headers, "X-Teams-Adapter-Token") or ""
    return provided == expected


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

    correlation_id = event.get("requestContext", {}).get("requestId", "unknown")
    result = handle_query(text, jira_jql, confluence_cql, correlation_id)

    activity = {
        "type": "message",
        "text": result["answer"],
    }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(activity),
    }
