from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from typing import Any

import boto3
from botocore.client import BaseClient

from shared.logging import get_logger

logger = get_logger("webhook_receiver")

ALLOWED_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}

# Manual trigger: comment containing this phrase (case-insensitive) triggers a review.
# Configurable via REVIEW_TRIGGER_PHRASE env var. Also matches @<BOT_USERNAME> review.
_DEFAULT_TRIGGER_PHRASE = "/review"

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


def _is_manual_trigger(comment_body: str) -> bool:
    """Return True if the comment body contains a recognized trigger phrase."""
    trigger = os.getenv("REVIEW_TRIGGER_PHRASE", _DEFAULT_TRIGGER_PHRASE).strip()
    bot_username = os.getenv("BOT_USERNAME", "").strip()
    text = comment_body.strip().lower()

    # Match exact trigger phrase (e.g. /review) or @bot review / @bot /review
    if trigger.lower() in text:
        return True
    if bot_username and re.search(rf"@{re.escape(bot_username.lower())}\s+(/?review)", text):
        return True
    return False


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    headers = event.get("headers") or {}
    github_event = _get_header(headers, "X-GitHub-Event")
    delivery_id = _get_header(headers, "X-GitHub-Delivery")
    signature = _get_header(headers, "X-Hub-Signature-256")

    if github_event not in {"pull_request", "issue_comment"}:
        return {"statusCode": 202, "body": json.dumps({"ignored": "non_pull_request_event"})}

    if not delivery_id:
        return {"statusCode": 400, "body": json.dumps({"error": "missing_delivery_id"})}

    raw_body = _extract_raw_body(event)
    secret = _load_webhook_secret()

    if not verify_signature(raw_body, signature or "", secret):
        logger.warning("signature_verification_failed", extra={"delivery_id": delivery_id})
        return {"statusCode": 401, "body": json.dumps({"error": "invalid_signature"})}

    payload = json.loads(raw_body.decode("utf-8"))

    # ---- issue_comment: manual trigger path ----------------------------------
    if github_event == "issue_comment":
        return _handle_issue_comment(payload, delivery_id)

    # ---- pull_request: auto trigger path ------------------------------------
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

    return _enqueue_review(
        delivery_id=delivery_id,
        repo_full_name=repo_full_name,
        pr_number=int(pr_number),
        head_sha=head_sha,
        installation_id=(payload.get("installation") or {}).get("id"),
        event_action=action,
        trigger="auto",
    )


def _handle_issue_comment(payload: dict[str, Any], delivery_id: str) -> dict[str, Any]:
    """Handle issue_comment events for manual /review triggers on PRs."""
    action = payload.get("action")
    if action not in {"created", "edited"}:
        return {"statusCode": 202, "body": json.dumps({"ignored": "comment_action_not_supported"})}

    # Only handle PR comments (issues have pull_request key in the issue object)
    issue = payload.get("issue") or {}
    if not issue.get("pull_request"):
        return {"statusCode": 202, "body": json.dumps({"ignored": "not_a_pr_comment"})}

    comment = payload.get("comment") or {}
    comment_body = comment.get("body") or ""
    if not _is_manual_trigger(comment_body):
        return {"statusCode": 202, "body": json.dumps({"ignored": "no_trigger_phrase"})}

    repository = payload.get("repository") or {}
    installation = payload.get("installation") or {}

    repo_full_name = repository.get("full_name")
    pr_number = issue.get("number")

    if not repo_full_name or not pr_number:
        return {"statusCode": 400, "body": json.dumps({"error": "missing_required_fields"})}

    if not _repo_allowed(repo_full_name):
        return {"statusCode": 202, "body": json.dumps({"ignored": "repo_not_allowed"})}

    # Fetch the current head SHA from the PR — use the pull_request URL stored in the issue
    pr_url = (issue.get("pull_request") or {}).get("url") or ""
    head_sha = _fetch_pr_head_sha_from_url(pr_url)
    if not head_sha:
        logger.warning("manual_trigger_head_sha_missing", extra={"delivery_id": delivery_id, "pr_number": pr_number})
        return {"statusCode": 500, "body": json.dumps({"error": "could_not_resolve_head_sha"})}

    logger.info(
        "manual_review_triggered",
        extra={"delivery_id": delivery_id, "repo": repo_full_name, "pr_number": pr_number, "sha": head_sha},
    )

    return _enqueue_review(
        delivery_id=delivery_id,
        repo_full_name=repo_full_name,
        pr_number=int(pr_number),
        head_sha=head_sha,
        installation_id=installation.get("id"),
        event_action="manual",
        trigger="manual",
    )


def _fetch_pr_head_sha_from_url(pr_api_url: str) -> str | None:
    """Resolve the current head SHA of a PR from its API URL.

    The issue_comment payload gives us the PR API URL in issue.pull_request.url.
    We call it using the GitHub App token obtained from the env.
    """
    if not pr_api_url:
        return None

    # Import here to avoid circular imports; these are only needed for the manual path
    import requests
    from shared.github_app_auth import GitHubAppAuth

    try:
        auth = GitHubAppAuth(
            app_ids_secret_arn=os.environ["GITHUB_APP_IDS_SECRET_ARN"],
            private_key_secret_arn=os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"],
            api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
        )
        token = auth.get_installation_token()
        resp = requests.get(
            pr_api_url,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10,
        )
        resp.raise_for_status()
        pr_data = resp.json()
        return (pr_data.get("head") or {}).get("sha")
    except Exception:  # noqa: BLE001
        logger.exception("fetch_pr_head_sha_failed")
        return None


def _enqueue_review(
    delivery_id: str,
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
    installation_id: Any,
    event_action: str,
    trigger: str = "auto",
) -> dict[str, Any]:
    """Send an SQS message to the review worker and optionally the PR description queue."""
    message = {
        "delivery_id": delivery_id,
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "installation_id": installation_id,
        "event_action": event_action,
        "trigger": trigger,
    }

    _sqs.send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps(message))

    # Fan-out: enqueue PR description generation if enabled (auto triggers only)
    pr_desc_queue = os.getenv("PR_DESCRIPTION_QUEUE_URL")
    if pr_desc_queue and trigger == "auto":
        try:
            _sqs.send_message(QueueUrl=pr_desc_queue, MessageBody=json.dumps(message))
            logger.info("pr_description_enqueued", extra={"delivery_id": delivery_id, "pr_number": pr_number})
        except Exception:  # noqa: BLE001
            logger.warning("pr_description_enqueue_failed", extra={"delivery_id": delivery_id})

    logger.info(
        "webhook_enqueued",
        extra={"delivery_id": delivery_id, "repo": repo_full_name, "pr_number": pr_number, "sha": head_sha, "trigger": trigger},
    )
    return {"statusCode": 202, "body": json.dumps({"status": "accepted"})}
