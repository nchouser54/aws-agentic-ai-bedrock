from __future__ import annotations

import json
import os
from typing import Any

from shared.atlassian_client import AtlassianClient
from shared.bedrock_chat import BedrockChatClient
from shared.logging import get_logger

logger = get_logger("jira_confluence_chatbot")


def _format_jira(issues: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for issue in issues:
        key = issue.get("key", "UNKNOWN")
        fields = issue.get("fields", {})
        summary = fields.get("summary", "")
        status = (fields.get("status") or {}).get("name", "")
        rows.append(f"- {key}: {summary} (status={status})")
    return "\n".join(rows) if rows else "No Jira issues found."


def _format_confluence(results: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in results:
        title = item.get("title") or (item.get("content") or {}).get("title") or "Untitled"
        url = (item.get("url") or item.get("_links", {}).get("webui") or "")
        rows.append(f"- {title} {url}".strip())
    return "\n".join(rows) if rows else "No Confluence pages found."


def handle_query(
    query: str,
    jira_jql: str,
    confluence_cql: str,
    correlation_id: str,
) -> dict[str, Any]:
    local_logger = get_logger("jira_confluence_chatbot", correlation_id=correlation_id)

    atlassian = AtlassianClient(credentials_secret_arn=os.environ["ATLASSIAN_CREDENTIALS_SECRET_ARN"])

    jira_items = atlassian.search_jira(jira_jql, max_results=5)
    conf_items = atlassian.search_confluence(confluence_cql, limit=5)

    context_blob = {
        "jira": _format_jira(jira_items),
        "confluence": _format_confluence(conf_items),
    }

    system_prompt = (
        "You are an enterprise engineering assistant. Use provided Jira and Confluence context only. "
        "If information is missing, state assumptions explicitly."
    )
    user_prompt = (
        f"User question:\n{query}\n\n"
        f"Jira context:\n{context_blob['jira']}\n\n"
        f"Confluence context:\n{context_blob['confluence']}\n"
    )

    chatbot = BedrockChatClient(
        region=os.getenv("AWS_REGION", "us-gov-west-1"),
        model_id=os.getenv("CHATBOT_MODEL_ID", os.environ.get("BEDROCK_MODEL_ID", "")),
    )
    answer = chatbot.answer(system_prompt=system_prompt, user_prompt=user_prompt)

    local_logger.info(
        "chatbot_answered",
        extra={"extra": {"jira_items": len(jira_items), "confluence_items": len(conf_items)}},
    )

    return {
        "answer": answer,
        "sources": {
            "jira_count": len(jira_items),
            "confluence_count": len(conf_items),
        },
    }


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    if event.get("requestContext", {}).get("http", {}).get("method") != "POST":
        return {"statusCode": 405, "body": json.dumps({"error": "method_not_allowed"})}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "invalid_json"})}

    query = str(body.get("query") or "").strip()
    if not query:
        return {"statusCode": 400, "body": json.dumps({"error": "query_required"})}

    jira_jql = str(body.get("jira_jql") or "").strip() or "order by updated DESC"
    confluence_cql = str(body.get("confluence_cql") or "").strip() or "type=page order by lastmodified desc"

    correlation_id = event.get("requestContext", {}).get("requestId", "unknown")
    response_body = handle_query(query, jira_jql, confluence_cql, correlation_id)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response_body),
    }
