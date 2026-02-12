from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from typing import Any

import boto3
from botocore.exceptions import ClientError

from shared.bedrock_client import BedrockReviewClient
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger
from shared.schema import Finding, ReviewResult, parse_review_result
from worker.review_mapper import map_new_line_to_diff_position

logger = get_logger("pr_review_worker")

_dynamodb = boto3.client("dynamodb")
_cloudwatch = boto3.client("cloudwatch")

SAFE_PATCH_CHAR_BUDGET = int(os.getenv("PATCH_CHAR_BUDGET", "45000"))
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", str(7 * 24 * 60 * 60)))


SENSITIVE_FILE_PATTERNS = (
    ".env",
    "secrets",
    "secret",
    "id_rsa",
    ".pem",
    ".key",
    ".p12",
    "credentials",
)


def _is_sensitive_file(path: str) -> bool:
    lower = path.lower()
    return any(marker in lower for marker in SENSITIVE_FILE_PATTERNS)


def _emit_metric(metric_name: str, value: float, unit: str = "Count") -> None:
    namespace = os.getenv("METRICS_NAMESPACE", "AIPrReviewer")
    _cloudwatch.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                "MetricName": metric_name,
                "Unit": unit,
                "Value": value,
            }
        ],
    )


def _claim_idempotency(repo_full_name: str, pr_number: int, head_sha: str) -> bool:
    key = f"{repo_full_name}:{pr_number}:{head_sha}"
    expires_at = int(time.time()) + IDEMPOTENCY_TTL_SECONDS

    try:
        _dynamodb.put_item(
            TableName=os.environ["IDEMPOTENCY_TABLE"],
            Item={
                "idempotency_key": {"S": key},
                "expires_at": {"N": str(expires_at)},
                "created_at": {"N": str(int(time.time()))},
            },
            ConditionExpression="attribute_not_exists(idempotency_key)",
        )
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _build_prompt(pr: dict[str, Any], files: list[dict[str, Any]]) -> str:
    patch_budget = SAFE_PATCH_CHAR_BUDGET
    selected_files = []

    for file_obj in files:
        patch = file_obj.get("patch") or ""
        if not patch:
            continue

        truncated_patch = patch[: min(len(patch), 3000)]
        entry = {
            "filename": file_obj.get("filename"),
            "status": file_obj.get("status"),
            "additions": file_obj.get("additions"),
            "deletions": file_obj.get("deletions"),
            "changes": file_obj.get("changes"),
            "patch": truncated_patch,
        }
        candidate = json.dumps(entry)
        if len(candidate) > patch_budget:
            break
        selected_files.append(entry)
        patch_budget -= len(candidate)

    instruction = {
        "task": "Review this pull request and return only strict JSON that matches the requested schema.",
        "hard_rules": [
            "Do not output markdown.",
            "Never include secrets in output.",
            "Do not suggest patches for sensitive files (.env, secrets, keys, pem, credentials).",
            "For security findings, provide remediation guidance without copying secret material.",
        ],
        "output_schema": {
            "summary": "string",
            "overall_risk": "low|medium|high",
            "findings": [
                {
                    "type": "bug|security|style|performance|tests|docs",
                    "severity": "low|medium|high",
                    "file": "string",
                    "start_line": "number|null",
                    "end_line": "number|null",
                    "message": "string",
                    "suggested_patch": "string|null",
                }
            ],
        },
        "pull_request": {
            "title": pr.get("title"),
            "body": pr.get("body") or "",
            "base_ref": (pr.get("base") or {}).get("ref"),
            "head_ref": (pr.get("head") or {}).get("ref"),
            "changed_files": selected_files,
        },
    }

    return json.dumps(instruction)


def _sanitize_findings(findings: list[Finding]) -> list[Finding]:
    sanitized: list[Finding] = []
    for finding in findings:
        if _is_sensitive_file(finding.file):
            finding.suggested_patch = None
            if finding.type == "security":
                finding.message = (
                    "Sensitive file detected. Review access controls, rotate any exposed values, and "
                    "store secrets in a secure manager."
                )
        sanitized.append(finding)
    return sanitized


def _format_review_body(result: ReviewResult) -> str:
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for finding in result.findings:
        grouped[f"{finding.severity}:{finding.type}"].append(finding)

    lines = [
        "## AI PR Reviewer Summary",
        "",
        result.summary,
        "",
        f"Overall risk: **{result.overall_risk.upper()}**",
        "",
        "## Findings",
    ]

    if not result.findings:
        lines.append("- No significant issues found.")
        return "\n".join(lines)

    for group_key in sorted(grouped.keys()):
        lines.append(f"\n### {group_key}")
        for finding in grouped[group_key]:
            range_str = ""
            if finding.start_line is not None:
                if finding.end_line and finding.end_line != finding.start_line:
                    range_str = f" (lines {finding.start_line}-{finding.end_line})"
                else:
                    range_str = f" (line {finding.start_line})"
            lines.append(f"- `{finding.file}`{range_str}: {finding.message}")
            if finding.suggested_patch:
                lines.append("  - Suggested patch omitted from body; see inline comment when available.")

    return "\n".join(lines)


def _build_inline_comments(findings: list[Finding], files_by_name: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []

    for finding in findings:
        if finding.start_line is None:
            continue

        file_data = files_by_name.get(finding.file)
        if not file_data:
            continue

        patch = file_data.get("patch")
        if not patch:
            continue

        position = map_new_line_to_diff_position(patch, finding.start_line)
        if position is None:
            continue

        body = finding.message
        if finding.suggested_patch and not _is_sensitive_file(finding.file):
            body = f"{body}\n\nSuggested patch:\n```diff\n{finding.suggested_patch}\n```"

        comments.append(
            {
                "path": finding.file,
                "position": position,
                "body": body,
            }
        )

    return comments


def _process_record(record: dict[str, Any]) -> None:
    started = time.time()
    message = json.loads(record["body"])

    repo_full_name = message["repo_full_name"]
    pr_number = int(message["pr_number"])
    head_sha = message["head_sha"]
    delivery_id = message.get("delivery_id", "unknown")
    installation_id = message.get("installation_id")

    local_logger = get_logger(
        "pr_review_worker",
        delivery_id=delivery_id,
        repo=repo_full_name,
        pr_number=pr_number,
        sha=head_sha,
        correlation_id=f"{delivery_id}:{repo_full_name}:{pr_number}:{head_sha}",
    )

    if not _claim_idempotency(repo_full_name, pr_number, head_sha):
        local_logger.info("idempotency_skip")
        _emit_metric("reviews_success", 1)
        return

    owner, repo = repo_full_name.split("/", maxsplit=1)

    auth = GitHubAppAuth(
        app_ids_secret_arn=os.environ["GITHUB_APP_IDS_SECRET_ARN"],
        private_key_secret_arn=os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"],
        api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
    )

    token = auth.get_installation_token(
        installation_id_override=str(installation_id) if installation_id else None
    )
    gh = GitHubClient(token_provider=lambda: token, api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"))

    pr = gh.get_pull_request(owner, repo, pr_number)
    files = gh.get_pull_request_files(owner, repo, pr_number)

    prompt = _build_prompt(pr, files)

    bedrock = BedrockReviewClient(
        region=os.getenv("AWS_REGION", "us-gov-west-1"),
        model_id=os.environ["BEDROCK_MODEL_ID"],
        agent_id=os.getenv("BEDROCK_AGENT_ID") or None,
        agent_alias_id=os.getenv("BEDROCK_AGENT_ALIAS_ID") or None,
    )
    result = parse_review_result(bedrock.analyze_pr(prompt))
    result.findings = _sanitize_findings(result.findings)

    body = _format_review_body(result)
    files_by_name = {f.get("filename"): f for f in files}
    inline_comments = _build_inline_comments(result.findings, files_by_name)

    review_payload = {
        "repo": repo_full_name,
        "pr_number": pr_number,
        "body": body,
        "inline_comments_count": len(inline_comments),
    }

    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    if dry_run:
        local_logger.info("dry_run_review", extra={"extra": review_payload})
    else:
        gh.create_pull_review(
            owner=owner,
            repo=repo,
            pull_number=pr_number,
            body=body,
            commit_id=head_sha,
            comments=inline_comments or None,
        )
        local_logger.info("review_posted", extra={"extra": review_payload})

    duration_ms = (time.time() - started) * 1000
    _emit_metric("reviews_success", 1)
    _emit_metric("duration_ms", duration_ms, unit="Milliseconds")


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    failures: list[dict[str, str]] = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        try:
            _process_record(record)
        except Exception:  # noqa: BLE001
            logger.exception("record_processing_failed", extra={"message_id": message_id})
            _emit_metric("reviews_failed", 1)
            failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failures}
