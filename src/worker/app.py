from __future__ import annotations

import datetime
import json
import os
import re
import time
from collections import defaultdict
from typing import Any

import boto3
from botocore.exceptions import ClientError

from shared.atlassian_client import AtlassianClient
from shared.bedrock_chat import BedrockChatClient
from shared.bedrock_client import BedrockReviewClient
from shared.bedrock_kb import BedrockKnowledgeBaseClient
from shared.constants import DEFAULT_REGION
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger
from shared.schema import Finding, ReviewResult, parse_review_result
from worker.build_context import build_pr_context
from worker.patch_apply import PatchApplyError, apply_unified_patch
from worker.render_markdown import render_check_run_body, render_pr_review_body
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
CHECK_RUN_NAME = os.getenv("CHECK_RUN_NAME", "AI PR Reviewer")
BEDROCK_MODEL_LIGHT = os.getenv("BEDROCK_MODEL_LIGHT", "")
BEDROCK_MODEL_HEAVY = os.getenv("BEDROCK_MODEL_HEAVY", "")
INCREMENTAL_REVIEW_ENABLED = os.getenv("INCREMENTAL_REVIEW_ENABLED", "true").lower() == "true"
PR_REVIEW_STATE_TABLE = os.getenv("PR_REVIEW_STATE_TABLE", "")
# Config filter knobs (pr-agent style)
SKIP_DRAFT_PRS = os.getenv("SKIP_DRAFT_PRS", "true").lower() == "true"
IGNORE_PR_AUTHORS = {a.strip() for a in os.getenv("IGNORE_PR_AUTHORS", "").split(",") if a.strip()}
IGNORE_PR_LABELS = {lb.strip() for lb in os.getenv("IGNORE_PR_LABELS", "").split(",") if lb.strip()}
# When non-empty, auto-reviews only run if the PR already has one of these labels.
# Manual/rerun triggers bypass this check. Comma-separated label names.
REVIEW_TRIGGER_LABELS: frozenset[str] = frozenset(
    lb.strip() for lb in os.getenv("REVIEW_TRIGGER_LABELS", "").split(",") if lb.strip()
)
IGNORE_PR_SOURCE_BRANCHES_RAW = [p.strip() for p in os.getenv("IGNORE_PR_SOURCE_BRANCHES", "").split(",") if p.strip()]
IGNORE_PR_TARGET_BRANCHES_RAW = [p.strip() for p in os.getenv("IGNORE_PR_TARGET_BRANCHES", "").split(",") if p.strip()]
NUM_MAX_FINDINGS = int(os.getenv("NUM_MAX_FINDINGS", "0"))  # 0 = unlimited
REQUIRE_SECURITY_REVIEW = os.getenv("REQUIRE_SECURITY_REVIEW", "true").lower() == "true"
REQUIRE_TESTS_REVIEW = os.getenv("REQUIRE_TESTS_REVIEW", "true").lower() == "true"
REVIEW_EFFORT_ESTIMATE = os.getenv("REVIEW_EFFORT_ESTIMATE", "false").lower() == "true"
FAILURE_ON_SEVERITY = os.getenv("FAILURE_ON_SEVERITY", "high")  # "high", "medium", or "none"

# KB-augmented review: retrieve relevant docs from Bedrock Knowledge Base before review.
# Set BEDROCK_KB_REVIEW_ENABLED=true and ensure BEDROCK_KNOWLEDGE_BASE_ID is populated.
BEDROCK_KB_REVIEW_ENABLED = os.getenv("BEDROCK_KB_REVIEW_ENABLED", "false").lower() == "true"
BEDROCK_KB_REVIEW_TOP_K = int(os.getenv("BEDROCK_KB_REVIEW_TOP_K", "5"))
# Max characters of KB context to include in the review prompt (default ~8 KB)
BEDROCK_KB_REVIEW_MAX_CHARS = int(os.getenv("BEDROCK_KB_REVIEW_MAX_CHARS", "8000"))

# Post a plain-text summary comment on the PR conversation thread in addition to
# the Check Run. Useful for teams that want the verdict visible without navigating
# to the Checks tab. Set POST_REVIEW_COMMENT=true to enable.
POST_REVIEW_COMMENT = os.getenv("POST_REVIEW_COMMENT", "false").lower() == "true"


_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")

# Supported keys that .ai-reviewer.yml may override (all values are strings).
_REPO_CONFIG_KEYS = frozenset({
    "skip_draft_prs",
    "failure_on_severity",
    "review_trigger_labels",
    "ignore_pr_authors",
    "ignore_pr_labels",
    "ignore_pr_source_branches",
    "ignore_pr_target_branches",
    "post_review_comment",
    "review_comment_mode",
    "require_security_review",
    "require_tests_review",
    "num_max_findings",
})


def _load_repo_config(gh: "GitHubClient", owner: str, repo: str, ref: str) -> dict[str, str]:
    """Fetch per-repo overrides from .ai-reviewer.yml at the PR head ref.

    Returns a dict of string key/value pairs for recognised config keys.
    Silently returns empty dict on any error (file absent, YAML parse error, etc.).
    The file format is simple flat YAML, e.g.::

        failure_on_severity: medium
        skip_draft_prs: false
        post_review_comment: true
        ignore_pr_labels: wip, do-not-review
    """
    try:
        raw_yaml, _ = gh.get_file_contents(owner, repo, ".ai-reviewer.yml", ref)

        # Minimal YAML parser — only flat key: value lines, no deps on pyyaml
        config: dict[str, str] = {}
        for line in raw_yaml.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip().strip("\"'")
            if key in _REPO_CONFIG_KEYS:
                config[key] = value
        return config
    except Exception:  # noqa: BLE001
        return {}


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


def _fetch_kb_context(
    query: str,
    region: str,
    knowledge_base_id: str,
    top_k: int = 5,
    max_chars: int = 8000,
) -> list[dict[str, Any]]:
    """Retrieve relevant KB passages for the given query.

    Returns a list of {text, uri, score} dicts, truncated to max_chars total.
    Failures are silently suppressed — KB enrichment is best-effort.
    """
    if not knowledge_base_id or not query:
        return []
    try:
        kb = BedrockKnowledgeBaseClient(
            region=region,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
        )
        results = kb.retrieve(query)
        # Trim to fit within the prompt budget
        selected: list[dict[str, Any]] = []
        chars_used = 0
        for item in results:
            text = str(item.get("text") or "")
            if not text:
                continue
            remaining = max_chars - chars_used
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[:remaining]
            selected.append({
                "text": text,
                "uri": item.get("uri") or "",
                "score": item.get("score"),
            })
            chars_used += len(text)
        return selected
    except Exception:  # noqa: BLE001
        logger.warning("kb_context_fetch_failed")
        return []


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


# ---------------------------------------------------------------------------
# Incremental review: track last reviewed SHA per PR
# ---------------------------------------------------------------------------

def _pr_state_key(repo_full_name: str, pr_number: int) -> str:
    return f"{repo_full_name}:{pr_number}"


def _get_last_reviewed_sha(repo_full_name: str, pr_number: int) -> str | None:
    """Return the head SHA from the most recent completed review, or None."""
    if not PR_REVIEW_STATE_TABLE:
        return None
    try:
        response = _dynamodb.get_item(
            TableName=PR_REVIEW_STATE_TABLE,
            Key={"pr_key": {"S": _pr_state_key(repo_full_name, pr_number)}},
            ProjectionExpression="last_reviewed_sha",
        )
        item = response.get("Item") or {}
        return (item.get("last_reviewed_sha") or {}).get("S") or None
    except Exception:  # noqa: BLE001
        logger.warning("get_last_reviewed_sha_failed")
        return None


def _set_last_reviewed_sha(
    repo_full_name: str,
    pr_number: int,
    sha: str,
    *,
    overall_risk: str = "unknown",
    finding_count: int = 0,
    verdict: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    """Persist the head SHA and review metadata for incremental diff tracking."""
    if not PR_REVIEW_STATE_TABLE:
        return
    expires_at = int(time.time()) + (30 * 24 * 60 * 60)  # 30-day TTL
    try:
        _dynamodb.put_item(
            TableName=PR_REVIEW_STATE_TABLE,
            Item={
                "pr_key": {"S": _pr_state_key(repo_full_name, pr_number)},
                "last_reviewed_sha": {"S": sha},
                "updated_at": {"N": str(int(time.time()))},
                "expires_at": {"N": str(expires_at)},
                "overall_risk": {"S": overall_risk},
                "finding_count": {"N": str(finding_count)},
                "verdict": {"S": verdict},
                "input_tokens": {"N": str(input_tokens)},
                "output_tokens": {"N": str(output_tokens)},
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("set_last_reviewed_sha_failed")


def _get_review_history(repo_full_name: str, pr_number: int) -> dict[str, Any] | None:
    """Return the most recent stored review metadata for a PR, or None."""
    if not PR_REVIEW_STATE_TABLE:
        return None
    try:
        response = _dynamodb.get_item(
            TableName=PR_REVIEW_STATE_TABLE,
            Key={"pr_key": {"S": _pr_state_key(repo_full_name, pr_number)}},
        )
        item = response.get("Item") or {}
        if not item:
            return None
        return {
            "pr_key": (item.get("pr_key") or {}).get("S"),
            "last_reviewed_sha": (item.get("last_reviewed_sha") or {}).get("S"),
            "updated_at": int((item.get("updated_at") or {"N": "0"}).get("N", 0)),
            "overall_risk": (item.get("overall_risk") or {}).get("S", "unknown"),
            "finding_count": int((item.get("finding_count") or {"N": "0"}).get("N", 0)),
            "verdict": (item.get("verdict") or {}).get("S", ""),
            "input_tokens": int((item.get("input_tokens") or {"N": "0"}).get("N", 0)),
            "output_tokens": int((item.get("output_tokens") or {"N": "0"}).get("N", 0)),
        }
    except Exception:  # noqa: BLE001
        logger.warning("get_review_history_failed")
        return None


# ---------------------------------------------------------------------------
# Review skip filters (pr-agent style config knobs)
# ---------------------------------------------------------------------------

import re as _re


def _should_skip_review(
    pr: dict[str, Any],
    event_action: str,
    trigger: str,
    skip_draft_prs_override: bool | None = None,
) -> tuple[bool, str]:
    """Check whether this PR review should be skipped based on configured filters.

    Returns (skip: bool, reason: str).
    Manual and rerun triggers always bypass author/label/branch filters.
    skip_draft_prs_override allows per-repo .ai-reviewer.yml to override the global flag.
    """
    if trigger in {"manual", "rerun"}:
        return False, ""

    # Skip draft PRs (configurable; defaults to True; per-repo overridable)
    effective_skip_drafts = SKIP_DRAFT_PRS if skip_draft_prs_override is None else skip_draft_prs_override
    if effective_skip_drafts and pr.get("draft"):
        return True, "PR is a draft (SKIP_DRAFT_PRS=true)"

    # Require a specific label before reviewing (opt-in mode)
    if REVIEW_TRIGGER_LABELS:
        labels = {str(lbl.get("name") or "") for lbl in (pr.get("labels") or [])}
        if not (REVIEW_TRIGGER_LABELS & labels):
            return True, f"PR does not have any of the required trigger label(s): {', '.join(sorted(REVIEW_TRIGGER_LABELS))}"

    # Ignore PR by author
    if IGNORE_PR_AUTHORS:
        author = str((pr.get("user") or {}).get("login") or "")
        if author in IGNORE_PR_AUTHORS:
            return True, f"PR author '{author}' is in IGNORE_PR_AUTHORS"

    # Ignore PR by label
    if IGNORE_PR_LABELS:
        labels = {str(lbl.get("name") or "") for lbl in (pr.get("labels") or [])}
        matched = IGNORE_PR_LABELS & labels
        if matched:
            return True, f"PR has ignored label(s): {', '.join(sorted(matched))}"

    # Ignore PR by source branch
    if IGNORE_PR_SOURCE_BRANCHES_RAW:
        head_ref = str((pr.get("head") or {}).get("ref") or "")
        for pattern in IGNORE_PR_SOURCE_BRANCHES_RAW:
            if _re.search(pattern, head_ref):
                return True, f"Source branch '{head_ref}' matches IGNORE_PR_SOURCE_BRANCHES pattern '{pattern}'"

    # Ignore PR by target branch
    if IGNORE_PR_TARGET_BRANCHES_RAW:
        base_ref = str((pr.get("base") or {}).get("ref") or "")
        for pattern in IGNORE_PR_TARGET_BRANCHES_RAW:
            if _re.search(pattern, base_ref):
                return True, f"Target branch '{base_ref}' matches IGNORE_PR_TARGET_BRANCHES pattern '{pattern}'"

    return False, ""


# ---------------------------------------------------------------------------
# Structured verdict derivation
# ---------------------------------------------------------------------------

def _derive_conclusion(findings: list[dict[str, Any]], threshold: str | None = None) -> tuple[str, str]:
    """Map review findings to a GitHub Check Run conclusion and a verdict string.

    Returns (conclusion, verdict_line) where conclusion is one of:
    success | neutral | failure
    """
    high_count = 0
    medium_count = 0
    for f in findings:
        priority = int(f.get("priority", 2)) if "priority" in f else -1
        severity = str(f.get("severity", "")).lower()
        is_high = priority == 0 or severity == "high"
        is_medium = priority == 1 or severity == "medium"
        if is_high:
            high_count += 1
        elif is_medium:
            medium_count += 1

    effective_threshold = (threshold or FAILURE_ON_SEVERITY).lower()
    if effective_threshold == "none":
        conclusion = "neutral"
    elif effective_threshold == "medium" and (high_count > 0 or medium_count > 0):
        conclusion = "failure"
    elif high_count > 0:
        conclusion = "failure"
    else:
        conclusion = "neutral" if findings else "success"

    if conclusion == "failure":
        verdict = "❌ Changes Required"
    elif findings:
        verdict = "💬 Suggestions"
    else:
        verdict = "✅ LGTM"

    return conclusion, verdict


def _build_prompt(
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    jira_issues: list[dict[str, Any]] | None = None,
    kb_passages: list[dict[str, Any]] | None = None,
) -> str:
    """Legacy single-stage prompt builder (kept for backwards compat / fallback)."""
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
    if kb_passages:
        hard_rules.append(
            "Use the provided org_knowledge_base passages as authoritative coding standards and "
            "architecture guidance. Flag violations as findings."
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
    if kb_passages:
        instruction["org_knowledge_base"] = kb_passages

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
    """Format a ReviewResult (legacy schema) into a markdown review body."""
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


def _format_review_body_from_dict(review: dict[str, Any]) -> str:
    """Format a validated review dict (new 2-stage schema) for PR review body."""
    return render_pr_review_body(review)


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


def _now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


import contextlib


@contextlib.contextmanager
def _suppress_check_run_errors(log):
    """Suppress and log check-run update failures so they never block the review."""
    try:
        yield
    except Exception:  # noqa: BLE001
        log.warning("check_run_update_failed")


def _process_record(record: dict[str, Any]) -> None:
    started = time.time()
    message = json.loads(record["body"])

    # Support both legacy flat schema and new nested schema from TS receiver
    repo_full_name = message.get("repo_full_name") or (message.get("repo") or {}).get("fullName") or ""
    pr_number = int(message.get("pr_number") or (message.get("pr") or {}).get("number") or 0)
    head_sha = message.get("head_sha") or (message.get("pr") or {}).get("headSha") or ""
    delivery_id = message.get("delivery_id") or message.get("deliveryId") or "unknown"
    installation_id = message.get("installation_id") or message.get("installationId")

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

    # -- Per-repo config override (.ai-reviewer.yml) --------------------------
    head_ref = (pr.get("head") or {}).get("ref") or head_sha
    repo_cfg = _load_repo_config(gh, owner, repo, head_ref)
    if repo_cfg:
        local_logger.info("repo_config_loaded", extra={"extra": {"keys": list(repo_cfg.keys())}})

    def _cfg_bool(key: str, default: bool) -> bool:
        val = repo_cfg.get(key)
        if val is None:
            return default
        return val.lower() not in {"false", "0", "no", "off"}

    effective_skip_draft = _cfg_bool("skip_draft_prs", SKIP_DRAFT_PRS)
    effective_post_comment = _cfg_bool("post_review_comment", POST_REVIEW_COMMENT)
    effective_failure_on_severity = repo_cfg.get("failure_on_severity", FAILURE_ON_SEVERITY)

    # -- Skip filters (pr-agent style) ----------------------------------------
    trigger = message.get("trigger", "auto")
    should_skip, skip_reason = _should_skip_review(
        pr,
        event_action=message.get("event_action", ""),
        trigger=trigger,
        skip_draft_prs_override=effective_skip_draft,
    )
    if should_skip:
        local_logger.info("review_skipped", extra={"extra": {"reason": skip_reason}})
        if not dry_run:
            try:
                cr = gh.create_check_run(
                    owner=owner, repo=repo, head_sha=head_sha, name=CHECK_RUN_NAME,
                    status="completed", conclusion="skipped",
                    started_at=_now_iso(), output={"title": CHECK_RUN_NAME, "summary": f"Skipped: {skip_reason}"},
                )
                local_logger.info("check_run_skipped", extra={"extra": {"check_run_id": cr.get("id")}})
            except Exception:  # noqa: BLE001
                pass
        return

    # -- Determine review scope: full vs incremental ---------------------------
    event_action = message.get("event_action", "")
    is_incremental = False
    incremental_base_sha: str | None = None

    if (
        INCREMENTAL_REVIEW_ENABLED
        and trigger != "manual"
        and event_action == "synchronize"
        and PR_REVIEW_STATE_TABLE
    ):
        incremental_base_sha = _get_last_reviewed_sha(repo_full_name, pr_number)
        if incremental_base_sha and incremental_base_sha != head_sha:
            is_incremental = True
            local_logger.info("incremental_review_mode", extra={"extra": {"base_sha": incremental_base_sha, "head_sha": head_sha}})

    files = gh.get_pull_request_files(owner, repo, pr_number)

    if is_incremental and incremental_base_sha:
        try:
            comparison = gh.compare_commits(owner, repo, incremental_base_sha, head_sha)
            incremental_files = comparison.get("files") or []
            if incremental_files:
                files = incremental_files
                local_logger.info("incremental_diff_fetched", extra={"extra": {"file_count": len(files)}})
            else:
                local_logger.info("incremental_diff_empty_fallback_to_full")
                is_incremental = False
        except Exception:  # noqa: BLE001
            local_logger.warning("incremental_diff_failed_fallback_to_full")
            is_incremental = False

    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    # -- Create Check Run: in_progress ----------------------------------------
    check_run_id: int | None = None
    if not dry_run:
        try:
            cr = gh.create_check_run(
                owner=owner,
                repo=repo,
                head_sha=head_sha,
                name=CHECK_RUN_NAME,
                status="in_progress",
                started_at=_now_iso(),
            )
            check_run_id = cr.get("id")
            local_logger.info("check_run_created", extra={"extra": {"check_run_id": check_run_id}})
        except Exception:  # noqa: BLE001
            local_logger.warning("check_run_create_failed")

    # -- Jira context ---------------------------------------------------------
    jira_issues: list[dict[str, Any]] = []
    atlassian_secret_arn = os.getenv("ATLASSIAN_CREDENTIALS_SECRET_ARN", "")
    if atlassian_secret_arn:
        jira_keys = _extract_jira_keys(pr)
        if jira_keys:
            local_logger.info("jira_keys_detected", extra={"extra": {"keys": jira_keys}})
            jira_issues = _fetch_jira_context(jira_keys, atlassian_secret_arn)

    # -- KB context (org standards, architecture docs, etc.) ------------------
    kb_passages: list[dict[str, Any]] = []
    if BEDROCK_KB_REVIEW_ENABLED:
        kb_id = os.getenv("BEDROCK_KNOWLEDGE_BASE_ID", "")
        if kb_id:
            pr_title = pr.get("title") or ""
            pr_body = (pr.get("body") or "")[:500]
            kb_query = f"{pr_title}\n{pr_body}".strip()
            kb_passages = _fetch_kb_context(
                query=kb_query,
                region=os.getenv("AWS_REGION", DEFAULT_REGION),
                knowledge_base_id=kb_id,
                top_k=BEDROCK_KB_REVIEW_TOP_K,
                max_chars=BEDROCK_KB_REVIEW_MAX_CHARS,
            )
            if kb_passages:
                local_logger.info("kb_context_fetched", extra={"extra": {"passages": len(kb_passages)}})

    # -- Run 2-stage Bedrock review -------------------------------------------
    bedrock = BedrockReviewClient(
        region=os.getenv("AWS_REGION", DEFAULT_REGION),
        model_id=os.environ["BEDROCK_MODEL_ID"],
        agent_id=os.getenv("BEDROCK_AGENT_ID") or None,
        agent_alias_id=os.getenv("BEDROCK_AGENT_ALIAS_ID") or None,
        guardrail_identifier=os.getenv("BEDROCK_GUARDRAIL_ID") or None,
        guardrail_version=os.getenv("BEDROCK_GUARDRAIL_VERSION") or None,
        guardrail_trace=os.getenv("BEDROCK_GUARDRAIL_TRACE") or None,
    )

    model_light = BEDROCK_MODEL_LIGHT or os.environ.get("BEDROCK_MODEL_ID", "")
    model_heavy = BEDROCK_MODEL_HEAVY or os.environ.get("BEDROCK_MODEL_ID", "")

    two_stage_enabled = bool(BEDROCK_MODEL_LIGHT and BEDROCK_MODEL_HEAVY)
    review_dict: dict[str, Any] | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    try:
        context, reviewed_files, skipped_files = build_pr_context(
            pr, files, jira_issues=jira_issues or None, kb_passages=kb_passages or None
        )

        if two_stage_enabled:
            local_logger.info("two_stage_review_start")
            plan, in_tok_p, out_tok_p = bedrock.invoke_planner(context, model_id=model_light)
            total_input_tokens += in_tok_p
            total_output_tokens += out_tok_p
            local_logger.info("planner_complete", extra={"extra": {"risk": plan.get("overall_risk_estimate"), "input_tokens": in_tok_p, "output_tokens": out_tok_p}})
            review_dict, in_tok_r, out_tok_r = bedrock.invoke_reviewer(context, plan, model_id=model_heavy)
            total_input_tokens += in_tok_r
            total_output_tokens += out_tok_r
            local_logger.info("reviewer_complete", extra={"extra": {"risk": review_dict.get("overall_risk"), "input_tokens": in_tok_r, "output_tokens": out_tok_r}})
            local_logger.info("token_usage", extra={"extra": {"total_input": total_input_tokens, "total_output": total_output_tokens}})

            # Inject file lists into review for rendering
            if "files_reviewed" not in review_dict or not review_dict["files_reviewed"]:
                review_dict["files_reviewed"] = reviewed_files
            if "files_skipped" not in review_dict or not review_dict["files_skipped"]:
                review_dict["files_skipped"] = skipped_files

            # -- Config knob filters -----------------------------------------
            findings_list: list[dict[str, Any]] = list(review_dict.get("findings") or [])
            if not REQUIRE_SECURITY_REVIEW:
                findings_list = [f for f in findings_list if f.get("type") != "security"]
            if not REQUIRE_TESTS_REVIEW:
                findings_list = [f for f in findings_list if f.get("type") != "tests"]
            if NUM_MAX_FINDINGS > 0:
                findings_list = findings_list[:NUM_MAX_FINDINGS]
            review_dict["findings"] = findings_list

    except Exception as exc:  # noqa: BLE001
        local_logger.exception("two_stage_review_failed", extra={"extra": {"error": str(exc)}})
        review_dict = None

    # -- Fallback to legacy single-stage if 2-stage failed or not configured --
    if review_dict is None:
        local_logger.info("falling_back_to_single_stage")
        prompt = _build_prompt(pr, files, jira_issues=jira_issues or None, kb_passages=kb_passages or None)
        legacy_result = parse_review_result(bedrock.analyze_pr(prompt))
        legacy_result.findings = _sanitize_findings(legacy_result.findings)

        body = _format_review_body(legacy_result)
        files_by_name = {f.get("filename"): f for f in files}
        inline_comments = _select_inline_comments(legacy_result.findings, files_by_name, REVIEW_COMMENT_MODE)

        legacy_findings_dicts = [
            {"severity": f.severity, "type": f.type, "message": f.message}
            for f in legacy_result.findings
        ]
        conclusion, verdict = _derive_conclusion(legacy_findings_dicts, threshold=effective_failure_on_severity)
        incremental_prefix = "[Incremental] " if is_incremental else ""
        check_output = {
            "title": f"{incremental_prefix}{CHECK_RUN_NAME} {verdict} (fallback mode)",
            "summary": legacy_result.summary or "Review complete.",
            "text": body,
        }

        review_payload = {
            "repo": repo_full_name,
            "pr_number": pr_number,
            "body": body,
            "inline_comments_count": len(inline_comments),
            "mode": "legacy",
        }

        if dry_run:
            local_logger.info("dry_run_review", extra={"extra": review_payload})
        else:
            gh.create_pull_review(
                owner=owner, repo=repo, pull_number=pr_number,
                body=body, commit_id=head_sha, comments=inline_comments or None,
            )
            local_logger.info("review_posted", extra={"extra": review_payload})

            if check_run_id:
                with _suppress_check_run_errors(local_logger):
                    gh.update_check_run(
                        owner=owner, repo=repo, check_run_id=check_run_id,
                        status="completed", conclusion=conclusion,
                        completed_at=_now_iso(), output=check_output,
                    )

        _create_autofix_pr(gh=gh, owner=owner, repo=repo, pr=pr,
                           findings=legacy_result.findings, local_logger=local_logger, dry_run=dry_run)
        _enqueue_test_gen(repo_full_name, pr_number, head_sha, pr, local_logger)
        if PR_REVIEW_STATE_TABLE:
            _set_last_reviewed_sha(repo_full_name, pr_number, head_sha)
        _emit_metric("reviews_success", 1)
        _emit_metric("duration_ms", (time.time() - started) * 1000, unit="Milliseconds")
        return

    # -- 2-stage path: render and post ----------------------------------------
    findings_for_verdict = list(review_dict.get("findings") or [])
    conclusion, verdict = _derive_conclusion(findings_for_verdict, threshold=effective_failure_on_severity)
    body = render_check_run_body(review_dict, verdict=verdict)
    summary_text = review_dict.get("summary") or "Review complete."
    overall_risk = review_dict.get("overall_risk", "unknown")
    finding_count = len(findings_for_verdict)
    incremental_prefix = "[Incremental] " if is_incremental else ""

    # Build inline comments from 2-stage findings
    files_by_name = {f.get("filename"): f for f in files}
    inline_comments_2stage: list[dict[str, Any]] = []
    for finding in (review_dict.get("findings") or []):
        file_data = files_by_name.get(finding.get("file", ""))
        if not file_data:
            continue
        patch = file_data.get("patch")
        if not patch or finding.get("start_line") is None:
            continue
        if _is_sensitive_file(finding.get("file", "")):
            continue
        position = map_new_line_to_diff_position(patch, finding["start_line"])
        if position is None:
            continue
        comment_body = finding.get("message", "")
        if finding.get("suggested_patch"):
            comment_body += f"\n\nSuggested patch:\n```diff\n{finding['suggested_patch']}\n```"
        inline_comments_2stage.append({
            "path": finding["file"],
            "position": position,
            "body": comment_body,
        })

    if REVIEW_COMMENT_MODE == "summary_only":
        inline_comments_2stage = []

    check_output = {
        "title": f"{incremental_prefix}{CHECK_RUN_NAME} {verdict} · risk={overall_risk} · {finding_count} finding(s)",
        "summary": summary_text[:65000],
        "text": body,
    }

    review_payload = {
        "repo": repo_full_name,
        "pr_number": pr_number,
        "risk": overall_risk,
        "findings": finding_count,
        "inline_comments": len(inline_comments_2stage),
        "mode": "two_stage",
    }

    if dry_run:
        local_logger.info("dry_run_review", extra={"extra": review_payload})
    else:
        gh.create_pull_review(
            owner=owner, repo=repo, pull_number=pr_number,
            body=body[:65000], commit_id=head_sha,
            comments=inline_comments_2stage or None,
        )
        local_logger.info("review_posted", extra={"extra": review_payload})

        if check_run_id:
            with _suppress_check_run_errors(local_logger):
                gh.update_check_run(
                    owner=owner, repo=repo, check_run_id=check_run_id,
                    status="completed", conclusion=conclusion,
                    completed_at=_now_iso(), output=check_output,
                )

        # Optionally post a plain PR comment summarising the verdict
        if effective_post_comment:
            try:
                comment_lines = [
                    f"**{CHECK_RUN_NAME}** — {verdict}",
                    f"",
                    f"Risk: **{overall_risk.upper()}** · {finding_count} finding(s)",
                    f"",
                    (review_dict.get("summary") or "").strip(),
                ]
                gh.create_issue_comment(
                    owner=owner, repo=repo,
                    issue_number=pr_number,
                    body="\n".join(comment_lines).strip(),
                )
                local_logger.info("review_comment_posted")
            except Exception:  # noqa: BLE001
                local_logger.warning("review_comment_post_failed")

    # Emit token-usage metrics
    if total_input_tokens or total_output_tokens:
        _emit_metric("bedrock_input_tokens", total_input_tokens)
        _emit_metric("bedrock_output_tokens", total_output_tokens)

    # Adapt review_dict findings to Finding objects for autofix/test-gen
    adapted_findings: list[Finding] = []
    for f in (review_dict.get("findings") or []):
        try:
            adapted_findings.append(Finding(
                type=f.get("type", "bug"),
                severity="high" if f.get("priority", 2) == 0 else ("medium" if f.get("priority", 2) == 1 else "low"),
                file=f.get("file", ""),
                start_line=f.get("start_line"),
                end_line=f.get("end_line"),
                message=f.get("message", ""),
                suggested_patch=f.get("suggested_patch"),
            ))
        except Exception:  # noqa: BLE001
            pass

    _create_autofix_pr(gh=gh, owner=owner, repo=repo, pr=pr,
                       findings=adapted_findings, local_logger=local_logger, dry_run=dry_run)
    _enqueue_test_gen(repo_full_name, pr_number, head_sha, pr, local_logger)
    if PR_REVIEW_STATE_TABLE:
        _set_last_reviewed_sha(
            repo_full_name, pr_number, head_sha,
            overall_risk=overall_risk,
            finding_count=finding_count,
            verdict=verdict,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

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