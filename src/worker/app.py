from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from typing import Any

import boto3
from botocore.exceptions import ClientError

from shared.atlassian_client import AtlassianClient
from shared.bedrock_client import BedrockReviewClient
from shared.constants import DEFAULT_REGION
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger
from shared.schema import Finding, ReviewResult, parse_review_result
from worker.patch_apply import PatchApplyError, apply_unified_patch
from worker.review_mapper import map_new_line_to_diff_position

logger = get_logger("pr_review_worker")

_dynamodb = boto3.client("dynamodb")
_cloudwatch = boto3.client("cloudwatch")
_sqs = boto3.client("sqs")

SAFE_PATCH_CHAR_BUDGET = int(os.getenv("PATCH_CHAR_BUDGET", "45000"))
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", str(7 * 24 * 60 * 60)))
AUTO_PR_MAX_FILES = int(os.getenv("AUTO_PR_MAX_FILES", "5"))
AUTO_PR_BRANCH_PREFIX = os.getenv("AUTO_PR_BRANCH_PREFIX", "ai-autofix")
REVIEW_COMMENT_MODE = os.getenv("REVIEW_COMMENT_MODE", "inline_best_effort")


_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")


def _extract_jira_keys(pr: dict[str, Any]) -> list[str]:
    """Extract unique Jira issue keys from PR title, body, and branch name."""
    sources = [
        pr.get("title") or "",
        pr.get("body") or "",
        (pr.get("head") or {}).get("ref") or "",
    ]
    keys: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for match in _JIRA_KEY_RE.findall(source):
            if match not in seen:
                seen.add(match)
                keys.append(match)
    return keys


def _fetch_jira_context(
    jira_keys: list[str],
    credentials_secret_arn: str,
    max_issues: int = 5,
) -> list[dict[str, Any]]:
    """Fetch Jira issue details for the given keys. Failures are silently skipped."""
    if not jira_keys or not credentials_secret_arn:
        return []

    atlassian = AtlassianClient(credentials_secret_arn=credentials_secret_arn)
    issues: list[dict[str, Any]] = []
    for key in jira_keys[:max_issues]:
        try:
            issue = atlassian.get_jira_issue(key)
            fields = issue.get("fields") or {}
            issues.append({
                "key": issue.get("key") or key,
                "summary": str(fields.get("summary") or ""),
                "status": str((fields.get("status") or {}).get("name") or ""),
                "type": str((fields.get("issuetype") or {}).get("name") or ""),
                "description": str(fields.get("description") or "")[:500],
            })
        except Exception:  # noqa: BLE001
            logger.warning("jira_fetch_failed", extra={"extra": {"key": key}})
    return issues


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
    try:
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
    except Exception:  # noqa: BLE001
        logger.warning(
            "metric_emit_failed",
            extra={"extra": {"metric_name": metric_name, "namespace": namespace}},
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


def _build_prompt(
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    jira_issues: list[dict[str, Any]] | None = None,
) -> str:
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

    hard_rules = [
        "Do not output markdown.",
        "Never include secrets in output.",
        "Do not suggest patches for sensitive files (.env, secrets, keys, pem, credentials).",
        "For security findings, provide remediation guidance without copying secret material.",
    ]
    if jira_issues:
        hard_rules.append(
            "Verify code changes align with the linked Jira ticket requirements. "
            "Flag any discrepancies between the ticket scope and the actual changes."
        )

    instruction: dict[str, Any] = {
        "task": "Review this pull request and return only strict JSON that matches the requested schema.",
        "hard_rules": hard_rules,
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

    if jira_issues:
        instruction["linked_jira_issues"] = jira_issues

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


def _build_inline_comments(
    findings: list[Finding],
    files_by_name: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    comments: list[dict[str, Any]] = []
    unmapped_count = 0

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
            unmapped_count += 1
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

    return comments, unmapped_count


def _select_inline_comments(
    findings: list[Finding],
    files_by_name: dict[str, dict[str, Any]],
    review_mode: str,
) -> list[dict[str, Any]]:
    mode = (review_mode or "inline_best_effort").strip().lower()
    comments, unmapped = _build_inline_comments(findings, files_by_name)

    if mode == "summary_only":
        return []
    if mode == "strict_inline" and unmapped > 0:
        return []
    return comments


def _autopr_enabled() -> bool:
    return os.getenv("AUTO_PR_ENABLED", "false").lower() == "true"


def _build_autopr_changes(
    gh: GitHubClient,
    owner: str,
    repo: str,
    head_ref: str,
    findings: list[Finding],
) -> list[tuple[str, str, str]]:
    """Build a list of (path, old_sha, updated_content) changes for safe fixable findings."""
    updates: list[tuple[str, str, str]] = []
    updated_files: set[str] = set()

    for finding in findings:
        if not finding.suggested_patch:
            continue
        if _is_sensitive_file(finding.file):
            continue
        if finding.file in updated_files:
            continue
        if len(updates) >= AUTO_PR_MAX_FILES:
            break

        try:
            original_content, sha = gh.get_file_contents(owner, repo, finding.file, head_ref)
            updated_content = apply_unified_patch(original_content, finding.suggested_patch)
        except (PatchApplyError, ValueError):
            continue

        if updated_content == original_content:
            continue

        updates.append((finding.file, sha, updated_content))
        updated_files.add(finding.file)

    return updates


def _create_autofix_pr(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr: dict[str, Any],
    findings: list[Finding],
    local_logger,
    dry_run: bool,
) -> None:
    if not _autopr_enabled():
        return

    head = pr.get("head") or {}
    base = pr.get("base") or {}
    head_sha = head.get("sha")
    head_ref = head.get("ref")
    base_ref = base.get("ref")

    if not head_sha or not head_ref or not base_ref:
        local_logger.info("auto_pr_skipped_missing_refs")
        return

    changes = _build_autopr_changes(gh, owner, repo, head_ref, findings)
    if not changes:
        local_logger.info("auto_pr_skipped_no_applicable_changes")
        return

    short_sha = head_sha[:8]
    branch_name = f"{AUTO_PR_BRANCH_PREFIX}/pr-{pr.get('number')}-{short_sha}"

    if dry_run:
        local_logger.info(
            "dry_run_auto_pr",
            extra={
                "extra": {
                    "branch": branch_name,
                    "base": base_ref,
                    "files": [path for path, _, _ in changes],
                    "count": len(changes),
                }
            },
        )
        return

    base_ref_data = gh.get_ref(owner, repo, f"heads/{base_ref}")
    base_sha = ((base_ref_data.get("object") or {}).get("sha"))
    if not base_sha:
        local_logger.info("auto_pr_skipped_base_sha_missing")
        return

    try:
        gh.create_ref(owner, repo, f"refs/heads/{branch_name}", base_sha)
    except Exception:  # noqa: BLE001
        # Branch likely already exists; continue using it.
        pass

    for path, file_sha, content in changes:
        gh.put_file_contents(
            owner=owner,
            repo=repo,
            path=path,
            branch=branch_name,
            message=f"AI autofix: update {path}",
            content=content,
            sha=file_sha,
        )

    source_pr_number = pr.get("number")
    source_pr_title = pr.get("title") or "PR"
    body = (
        f"Automated follow-up fixes generated from AI review of #{source_pr_number}.\n\n"
        "Please validate all changes before merge."
    )
    title = f"AI Autofix for #{source_pr_number}: {source_pr_title}"

    created_pr = gh.create_pull_request(
        owner=owner,
        repo=repo,
        title=title,
        head=branch_name,
        base=base_ref,
        body=body,
    )
    local_logger.info(
        "auto_pr_created",
        extra={"extra": {"auto_pr_number": created_pr.get("number"), "auto_pr_url": created_pr.get("html_url")}},
    )


def _enqueue_test_gen(
    repo_full_name: str,
    pr_number: int,
    head_sha: str,
    pr: dict[str, Any],
    local_logger: Any,
) -> None:
    """Optionally enqueue a test-generation job after a successful review."""
    queue_url = os.getenv("TEST_GEN_QUEUE_URL")
    if not queue_url:
        return
    base_ref = (pr.get("base") or {}).get("ref") or "main"
    message = {
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "base_ref": base_ref,
    }
    try:
        _sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))
        local_logger.info("test_gen_enqueued", extra={"extra": {"pr_number": pr_number}})
    except Exception:  # noqa: BLE001
        local_logger.warning("test_gen_enqueue_failed", extra={"extra": {"pr_number": pr_number}})


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

    # Enrich prompt with linked Jira issue context
    jira_issues: list[dict[str, Any]] = []
    atlassian_secret_arn = os.getenv("ATLASSIAN_CREDENTIALS_SECRET_ARN", "")
    if atlassian_secret_arn:
        jira_keys = _extract_jira_keys(pr)
        if jira_keys:
            local_logger.info("jira_keys_detected", extra={"extra": {"keys": jira_keys}})
            jira_issues = _fetch_jira_context(jira_keys, atlassian_secret_arn)

    prompt = _build_prompt(pr, files, jira_issues=jira_issues or None)

    bedrock = BedrockReviewClient(
        region=os.getenv("AWS_REGION", DEFAULT_REGION),
        model_id=os.environ["BEDROCK_MODEL_ID"],
        agent_id=os.getenv("BEDROCK_AGENT_ID") or None,
        agent_alias_id=os.getenv("BEDROCK_AGENT_ALIAS_ID") or None,
    )
    result = parse_review_result(bedrock.analyze_pr(prompt))
    result.findings = _sanitize_findings(result.findings)

    body = _format_review_body(result)
    files_by_name = {f.get("filename"): f for f in files}
    inline_comments = _select_inline_comments(result.findings, files_by_name, REVIEW_COMMENT_MODE)

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

    _create_autofix_pr(
        gh=gh,
        owner=owner,
        repo=repo,
        pr=pr,
        findings=result.findings,
        local_logger=local_logger,
        dry_run=dry_run,
    )

    # Chain: enqueue test generation if enabled
    _enqueue_test_gen(repo_full_name, pr_number, head_sha, pr, local_logger)

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
