from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

import boto3
from botocore.client import BaseClient

from shared.logging import get_logger

logger = get_logger("webhook_receiver")

ALLOWED_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}

_sqs = boto3.client("sqs")
_secrets = boto3.client("secretsmanager")
_cached_webhook_secret: bytes | None = None


def _get_header(headers: dict[str, str], key: str) -> str | None:
    target = key.lower()
    for k, v in (headers or {}).items():
        if k.lower() == target:
            return v
    return None


def _load_webhook_secret(secrets_client: BaseClient | None = None) -> bytes:
    global _cached_webhook_secret
    if _cached_webhook_secret is not None:
        return _cached_webhook_secret

    client = secrets_client or _secrets
    secret_arn = os.environ["WEBHOOK_SECRET_ARN"]
    response = client.get_secret_value(SecretId=secret_arn)
    secret = response.get("SecretString")
    if not secret:
        raise ValueError("Webhook secret must exist in SecretString")
    _cached_webhook_secret = secret.encode("utf-8")
    return _cached_webhook_secret


def verify_signature(raw_body: bytes, signature_header: str, secret: bytes) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _extract_raw_body(event: dict[str, Any]) -> bytes:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8")


def _repo_allowed(repo_full_name: str) -> bool:
    configured = os.getenv("GITHUB_ALLOWED_REPOS", "").strip()
    if not configured:
        return True
    allowed = {repo.strip() for repo in configured.split(",") if repo.strip()}
    return repo_full_name in allowed


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    headers = event.get("headers") or {}
    github_event = _get_header(headers, "X-GitHub-Event")
    delivery_id = _get_header(headers, "X-GitHub-Delivery")
    signature = _get_header(headers, "X-Hub-Signature-256")

    if github_event != "pull_request":
        return {"statusCode": 202, "body": json.dumps({"ignored": "non_pull_request_event"})}

    if not delivery_id:
        return {"statusCode": 400, "body": json.dumps({"error": "missing_delivery_id"})}

    raw_body = _extract_raw_body(event)
    secret = _load_webhook_secret()

    if not verify_signature(raw_body, signature or "", secret):
        logger.warning("signature_verification_failed", extra={"delivery_id": delivery_id})
        return {"statusCode": 401, "body": json.dumps({"error": "invalid_signature"})}

    payload = json.loads(raw_body.decode("utf-8"))
    action = payload.get("action")
    if action not in ALLOWED_ACTIONS:
        return {"statusCode": 202, "body": json.dumps({"ignored": "action_not_supported"})}

    pull_request = payload.get("pull_request") or {}
    repository = payload.get("repository") or {}
    installation = payload.get("installation") or {}

    repo_full_name = repository.get("full_name")
    pr_number = pull_request.get("number")
    head_sha = ((pull_request.get("head") or {}).get("sha"))

    if not repo_full_name or not pr_number or not head_sha:
        return {"statusCode": 400, "body": json.dumps({"error": "missing_required_fields"})}

    if not _repo_allowed(repo_full_name):
        logger.info(
            "repo_not_allowed",
            extra={"delivery_id": delivery_id, "repo": repo_full_name, "pr_number": pr_number, "sha": head_sha},
        )
        return {"statusCode": 202, "body": json.dumps({"ignored": "repo_not_allowed"})}

    message = {
        "delivery_id": delivery_id,
        "repo_full_name": repo_full_name,
        "pr_number": int(pr_number),
        "head_sha": head_sha,
        "installation_id": installation.get("id"),
        "event_action": action,
    }

    _sqs.send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps(message))

    logger.info(
        "webhook_enqueued",
        extra={"delivery_id": delivery_id, "repo": repo_full_name, "pr_number": pr_number, "sha": head_sha},
    )
    return {"statusCode": 202, "body": json.dumps({"status": "accepted"})}
