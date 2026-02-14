"""PR description generator Lambda.

Supports two triggers:
- SQS (auto-trigger from webhook receiver on PR open/synchronize).
- API Gateway ``POST /pr-description/generate`` — manual trigger.

Always appends an AI-generated summary section to the PR body, delimited by
HTML comment markers so it can be safely re-generated on ``synchronize`` events
without disturbing manually authored content.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from shared.atlassian_client import AtlassianClient
from shared.bedrock_chat import BedrockChatClient
from shared.constants import DEFAULT_REGION
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger

logger = get_logger("pr_description")

_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")

_AI_SECTION_START = "<!-- AI-GENERATED SUMMARY START -->"
_AI_SECTION_END = "<!-- AI-GENERATED SUMMARY END -->"

_SYSTEM_PROMPT = """\
You are an expert software engineer writing pull request descriptions.
Given a diff, commit messages, and optionally linked Jira tickets, produce a \
clear, structured PR description in Markdown.

Sections (skip empty sections):
- **Summary** — 2-3 sentence overview of what this PR does and why.
- **Changes** — bullet list of the key changes, grouped by area if applicable.
- **Linked Tickets** — list any Jira tickets with their summary and status.
- **Testing Notes** — suggest what should be tested and any edge cases.
- **Breaking Changes** — list any breaking changes (omit section if none).

Rules:
- Be concise — one line per bullet.
- Do not invent information. Use only the data provided.
- If Jira context is available, relate code changes to ticket requirements.
- Output only Markdown. No JSON, no code fences wrapping the whole output.
"""


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "f", "no", "n", "off", ""}:
            return False
    return default


# ---- Jira helpers ------------------------------------------------------------


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
    keys: list[str], credentials_secret_arn: str,
) -> list[dict[str, str]]:
    """Fetch Jira issue details for the given keys."""
    if not keys or not credentials_secret_arn:
        return []
    atlassian = AtlassianClient(credentials_secret_arn=credentials_secret_arn)
    results: list[dict[str, str]] = []
    for key in keys[:5]:
        try:
            issue = atlassian.get_jira_issue(key)
            fields = issue.get("fields") or {}
            results.append({
                "key": issue.get("key") or key,
                "summary": str(fields.get("summary") or ""),
                "type": str((fields.get("issuetype") or {}).get("name") or ""),
                "status": str((fields.get("status") or {}).get("name") or ""),
            })
        except Exception:  # noqa: BLE001
            logger.warning("jira_fetch_failed", extra={"extra": {"key": key}})
    return results


# ---- Prompt building ---------------------------------------------------------


def _build_user_prompt(
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    commit_messages: list[str],
    jira_context: list[dict[str, str]],
) -> str:
    """Build the user prompt from PR metadata, diff, commits, and Jira."""
    pr_number = pr.get("number")
    title = pr.get("title") or "Untitled"
    body = pr.get("body") or "(no description)"
    base = (pr.get("base") or {}).get("ref") or "main"
    head = (pr.get("head") or {}).get("ref") or "unknown"

    lines = [
        f"PR #{pr_number}: {title}",
        f"Branch: {head} → {base}",
        f"Existing description:\n{body}",
        "",
        "## Commit Messages",
    ]
    for msg in commit_messages:
        lines.append(f"- {msg}")

    lines.append("")
    lines.append("## Changed Files")
    for f in files[:30]:  # cap to avoid prompt overflow
        filename = f.get("filename") or ""
        status = f.get("status") or ""
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        patch = f.get("patch") or ""
        # Truncate large patches
        if len(patch) > 2000:
            patch = patch[:2000] + "\n... (truncated)"
        lines.append(f"### {filename} ({status}, +{additions}/-{deletions})")
        if patch:
            lines.append(f"```diff\n{patch}\n```")

    if jira_context:
        lines.append("")
        lines.append("## Linked Jira Tickets")
        for j in jira_context:
            lines.append(f"- {j['key']} [{j['type']}]: {j['summary']} (Status: {j['status']})")

    return "\n".join(lines)


# ---- Core generator ----------------------------------------------------------


def generate_description(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    atlassian_secret_arn: str,
    model_id: str,
    region: str,
) -> str:
    """Generate an AI PR description from diff + commits + Jira context."""
    pr = gh.get_pull_request(owner, repo, pr_number)
    files = gh.get_pull_request_files(owner, repo, pr_number)

    # Get commit messages
    try:
        commits = gh.list_pull_commits(owner, repo, pr_number)
        commit_messages = [
            ((c.get("commit") or {}).get("message") or "").split("\n")[0]
            for c in commits
        ]
    except Exception:  # noqa: BLE001
        commit_messages = []

    # Jira context
    jira_keys = _extract_jira_keys(pr)
    jira_context = _fetch_jira_context(jira_keys, atlassian_secret_arn)

    user_prompt = _build_user_prompt(pr, files, commit_messages, jira_context)

    chat = BedrockChatClient(region=region, model_id=model_id, max_tokens=2000)
    return chat.answer(_SYSTEM_PROMPT, user_prompt)


# ---- Body update with markers -----------------------------------------------


def _update_pr_body(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    existing_body: str,
    ai_description: str,
) -> None:
    """Append or replace the AI summary section in the PR body."""
    ai_section = f"\n\n{_AI_SECTION_START}\n## AI-Generated Summary\n\n{ai_description}\n{_AI_SECTION_END}"

    # Check if section already exists — replace it
    pattern = re.compile(
        re.escape(_AI_SECTION_START) + r".*?" + re.escape(_AI_SECTION_END),
        re.DOTALL,
    )
    if pattern.search(existing_body or ""):
        new_body = pattern.sub(ai_section.strip(), existing_body)
    else:
        new_body = (existing_body or "").rstrip() + ai_section

    gh.update_pull_request(owner, repo, pr_number, body=new_body)
    logger.info("pr_body_updated", extra={"extra": {"pr_number": pr_number}})


# ---- Lambda handler ----------------------------------------------------------


def _process_sqs_record(record: dict[str, Any]) -> None:
    """Process a single SQS record (auto-triggered from webhook)."""
    message = json.loads(record["body"])
    repo_full = message["repo_full_name"]
    pr_number = int(message["pr_number"])

    owner, repo = repo_full.split("/", maxsplit=1)
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    model_id = os.environ.get("PR_DESCRIPTION_MODEL_ID") or os.environ.get("BEDROCK_MODEL_ID", "")
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    atlassian_secret_arn = os.getenv("ATLASSIAN_CREDENTIALS_SECRET_ARN", "")

    auth = GitHubAppAuth(
        app_ids_secret_arn=os.environ["GITHUB_APP_IDS_SECRET_ARN"],
        private_key_secret_arn=os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"],
        api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
    )
    token = auth.get_installation_token(
        installation_id_override=str(message.get("installation_id")) if message.get("installation_id") else None,
    )
    gh = GitHubClient(token_provider=lambda: token, api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"))

    description = generate_description(gh, owner, repo, pr_number, atlassian_secret_arn, model_id, region)

    if dry_run:
        logger.info("dry_run_pr_description", extra={"extra": {"pr_number": pr_number}})
        return

    pr = gh.get_pull_request(owner, repo, pr_number)
    _update_pr_body(gh, owner, repo, pr_number, pr.get("body") or "", description)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Handle SQS records or API Gateway POST."""
    # SQS trigger
    if "Records" in event:
        failures: list[dict[str, str]] = []
        for record in event["Records"]:
            try:
                _process_sqs_record(record)
            except Exception:  # noqa: BLE001
                logger.exception("pr_description_record_failed", extra={"messageId": record.get("messageId")})
                failures.append({"itemIdentifier": record["messageId"]})
        return {"batchItemFailures": failures}

    # API Gateway trigger
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    method = http.get("method", "").upper()

    if method != "POST":
        return {"statusCode": 405, "body": json.dumps({"error": "method_not_allowed"})}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "invalid_json"})}

    repo_full = (body.get("repo") or "").strip()
    pr_number = body.get("pr_number")
    apply_to_pr = _as_bool(body.get("apply"), default=True)

    if not repo_full or not pr_number or "/" not in repo_full:
        return {"statusCode": 400, "body": json.dumps({
            "error": "missing_fields", "detail": "repo (owner/repo) and pr_number are required",
        })}

    owner, repo = repo_full.split("/", maxsplit=1)
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    model_id = os.environ.get("PR_DESCRIPTION_MODEL_ID") or os.environ.get("BEDROCK_MODEL_ID", "")
    dry_run = _as_bool(body.get("dry_run", os.getenv("DRY_RUN", "false")), default=False)
    atlassian_secret_arn = os.getenv("ATLASSIAN_CREDENTIALS_SECRET_ARN", "")

    auth = GitHubAppAuth(
        app_ids_secret_arn=os.environ["GITHUB_APP_IDS_SECRET_ARN"],
        private_key_secret_arn=os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"],
        api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
    )
    token = auth.get_installation_token()
    gh = GitHubClient(token_provider=lambda: token, api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"))

    try:
        description = generate_description(gh, owner, repo, int(pr_number), atlassian_secret_arn, model_id, region)
    except Exception:
        logger.exception("pr_description_generation_failed")
        return {"statusCode": 500, "body": json.dumps({"error": "generation_failed"})}

    if apply_to_pr and not dry_run:
        pr = gh.get_pull_request(owner, repo, int(pr_number))
        _update_pr_body(gh, owner, repo, int(pr_number), pr.get("body") or "", description)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "status": "generated",
            "applied": apply_to_pr and not dry_run,
            "dry_run": dry_run,
            "description": description,
        }),
    }
