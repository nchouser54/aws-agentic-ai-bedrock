from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from html import unescape
from typing import Any

import boto3

from shared.atlassian_client import AtlassianClient
from shared.constants import DEFAULT_REGION
from shared.logging import get_logger

logger = get_logger("confluence_kb_sync")

_HTML_TAG_RE = re.compile(r"<[^>]+>")

_SYNC_STATE_KEY = "confluence_sync"


def _strip_html(value: str) -> str:
    text = unescape(value or "")
    text = _HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_confluence_doc(page: dict[str, Any]) -> dict[str, Any]:
    page_id = str(page.get("id") or "")
    title = str(page.get("title") or "Untitled")
    links = page.get("_links") or {}
    url = str(page.get("url") or links.get("webui") or "")

    body = page.get("body") or {}
    storage = body.get("storage") or {}
    view = body.get("view") or {}
    raw = str(storage.get("value") or view.get("value") or "")

    return {
        "id": page_id,
        "title": title,
        "url": url,
        "updated_at": page.get("version", {}).get("when") or page.get("lastUpdated") or "",
        "text": _strip_html(raw),
    }


def _get_last_sync_time(dynamodb: Any, table_name: str) -> str | None:
    """Read last sync timestamp from DynamoDB. Returns ISO string or None."""
    try:
        resp = dynamodb.get_item(
            TableName=table_name,
            Key={"sync_key": {"S": _SYNC_STATE_KEY}},
        )
        item = resp.get("Item")
        if item:
            return item.get("last_sync_time", {}).get("S")
    except Exception:
        logger.warning("failed_to_read_sync_state")
    return None


def _set_last_sync_time(dynamodb: Any, table_name: str, iso_time: str) -> None:
    """Write last sync timestamp to DynamoDB."""
    try:
        dynamodb.put_item(
            TableName=table_name,
            Item={
                "sync_key": {"S": _SYNC_STATE_KEY},
                "last_sync_time": {"S": iso_time},
            },
        )
    except Exception:
        logger.exception("failed_to_write_sync_state")


def lambda_handler(_event: dict[str, Any], _context: Any) -> dict[str, Any]:
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    credentials_secret_arn = os.environ["ATLASSIAN_CREDENTIALS_SECRET_ARN"]
    knowledge_base_id = os.environ["BEDROCK_KNOWLEDGE_BASE_ID"]
    data_source_id = os.environ["BEDROCK_KB_DATA_SOURCE_ID"]
    bucket = os.environ["KB_SYNC_BUCKET"]
    prefix = os.getenv("KB_SYNC_PREFIX", "confluence")
    cql = os.getenv("CONFLUENCE_SYNC_CQL", "type=page order by lastmodified desc")
    limit = int(os.getenv("CONFLUENCE_SYNC_LIMIT", "25"))
    sync_state_table = os.getenv("KB_SYNC_STATE_TABLE", "")

    atlassian = AtlassianClient(credentials_secret_arn=credentials_secret_arn)
    s3 = boto3.client("s3", region_name=region)
    bedrock_agent = boto3.client("bedrock-agent", region_name=region)
    dynamodb = boto3.client("dynamodb", region_name=region) if sync_state_table else None

    # Incremental delta sync: if we have a last sync time, append to CQL
    effective_cql = cql
    if dynamodb and sync_state_table:
        last_sync = _get_last_sync_time(dynamodb, sync_state_table)
        if last_sync:
            effective_cql = f'{cql} AND lastmodified > "{last_sync}"'
            logger.info("delta_sync_enabled", extra={"extra": {"last_sync": last_sync, "cql": effective_cql}})

    sync_start_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    results = atlassian.search_confluence(effective_cql, limit=limit)
    uploaded = 0
    failed = 0

    for result in results:
        content = result.get("content") or {}
        page_id = str(result.get("id") or content.get("id") or "").strip()
        if not page_id:
            continue

        try:
            page = atlassian.get_confluence_page(page_id)
            document = _build_confluence_doc(page)
            if not document["text"]:
                continue

            key = f"{prefix.rstrip('/')}/pages/{page_id}.json"
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(document).encode("utf-8"),
                ContentType="application/json",
            )
            uploaded += 1
        except Exception:
            logger.exception("page_sync_failed", extra={"extra": {"page_id": page_id}})
            failed += 1
            continue

    ingestion_job_id = ""
    if uploaded > 0:
        response = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
            clientToken=str(uuid.uuid4()),
            description="Confluence sync from chatbot platform",
        )
        ingestion_job_id = str((response.get("ingestionJob") or {}).get("ingestionJobId") or "")

    # Update delta sync checkpoint on success
    if dynamodb and sync_state_table and uploaded > 0:
        _set_last_sync_time(dynamodb, sync_state_table, sync_start_time)

    logger.info(
        "kb_sync_completed",
        extra={
            "extra": {
                "uploaded": uploaded,
                "failed": failed,
                "candidate_results": len(results),
                "knowledge_base_id": knowledge_base_id,
                "ingestion_job_id": ingestion_job_id,
            }
        },
    )

    return {
        "uploaded": uploaded,
        "failed": failed,
        "candidate_results": len(results),
        "knowledge_base_id": knowledge_base_id,
        "ingestion_job_id": ingestion_job_id,
    }
