"""Sprint / standup report generator Lambda.

Supports two triggers:
- API Gateway ``POST /reports/sprint`` — on-demand report generation.
- EventBridge schedule — automated periodic reports.

For API Gateway, the JSON body may contain:
    {
        "repo": "owner/repo",
        "jira_project": "PROJ",
        "jira_jql": "...",              # optional override
        "report_type": "standup|sprint",
        "days_back": 1
    }

Scheduled mode reads configuration entirely from environment variables.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.atlassian_client import AtlassianClient
from shared.bedrock_chat import BedrockChatClient
from shared.constants import DEFAULT_REGION
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger

logger = get_logger("sprint_report")

_SYSTEM_PROMPT = """\
You are a technical project manager producing concise team reports.
Given Jira ticket status data and recent GitHub activity, produce a \
well-structured Markdown report.

Rules:
- Use the report_type to decide format:
  * "standup" — brief daily standup. Sections: Done Yesterday, In Progress \
Today, Blocked / Needs Attention, Key PRs.
  * "sprint" — full sprint summary. Sections: Sprint Overview (1-2 sentences), \
Completed, In Progress, Not Started, Blocked, PRs Merged, Key Commits, \
Risks & Highlights.
- Each item is a bullet with ticket key or PR number, title, assignee/author.
- Group Jira items by status category (Done, In Progress, To Do, Blocked).
- Keep it concise — one line per item.
- Do not invent data. Use only the information provided.
- Output only Markdown. No JSON, no code fences.
"""

# ---- Jira data ---------------------------------------------------------------


def _fetch_jira_sprint_data(
    atlassian: AtlassianClient, jql: str,
) -> list[dict[str, str]]:
    """Fetch Jira issues matching the JQL and return a simplified list."""
    try:
        issues = atlassian.search_jira(jql, max_results=50)
    except Exception:  # noqa: BLE001
        logger.warning("jira_sprint_fetch_failed")
        return []

    results: list[dict[str, str]] = []
    for issue in issues:
        fields = issue.get("fields") or {}
        results.append({
            "key": issue.get("key") or "",
            "summary": str(fields.get("summary") or ""),
            "status": str((fields.get("status") or {}).get("name") or ""),
            "status_category": str(
                ((fields.get("status") or {}).get("statusCategory") or {}).get("name") or ""
            ),
            "type": str((fields.get("issuetype") or {}).get("name") or ""),
            "assignee": str((fields.get("assignee") or {}).get("displayName") or "Unassigned"),
            "priority": str((fields.get("priority") or {}).get("name") or ""),
        })
    return results


# ---- GitHub data -------------------------------------------------------------


def _fetch_github_activity(
    gh: GitHubClient, owner: str, repo: str, since_iso: str,
) -> dict[str, list[dict[str, str]]]:
    """Gather recent merged PRs and commits since *since_iso*."""
    prs_raw = gh.list_pulls(owner, repo, state="closed", sort="updated", direction="desc", per_page=50)
    merged_prs = [
        {
            "number": str(pr.get("number")),
            "title": pr.get("title") or "",
            "author": (pr.get("user") or {}).get("login") or "unknown",
            "merged_at": pr.get("merged_at") or "",
        }
        for pr in prs_raw
        if pr.get("merged_at") and pr["merged_at"] >= since_iso
    ]

    commits_raw = gh.list_commits(owner, repo, since=since_iso, per_page=30)
    commits = [
        {
            "sha": (c.get("sha") or "")[:8],
            "message": ((c.get("commit") or {}).get("message") or "").split("\n")[0],
            "author": ((c.get("commit") or {}).get("author") or {}).get("name") or "unknown",
            "date": ((c.get("commit") or {}).get("author") or {}).get("date") or "",
        }
        for c in commits_raw
    ]

    return {"merged_prs": merged_prs, "commits": commits}


# ---- Prompt ------------------------------------------------------------------


def _build_user_prompt(
    report_type: str,
    repo: str,
    jira_data: list[dict[str, str]],
    github_activity: dict[str, list[dict[str, str]]],
    days_back: int,
) -> str:
    """Compose the user prompt from Jira + GitHub data."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"Report type: {report_type}",
        f"Repository: {repo}",
        f"Date: {now_str}",
        f"Window: last {days_back} day(s)",
        "",
    ]

    # Jira section
    if jira_data:
        lines.append("## Jira Tickets")
        for item in jira_data:
            lines.append(
                f"- [{item['key']}] {item['summary']} | Status: {item['status']} "
                f"({item['status_category']}) | Type: {item['type']} | "
                f"Assignee: {item['assignee']} | Priority: {item['priority']}"
            )
    else:
        lines.append("## Jira Tickets\nNo Jira data available.")

    lines.append("")

    # GitHub section
    merged = github_activity.get("merged_prs", [])
    commits = github_activity.get("commits", [])
    lines.append("## GitHub Activity")
    if merged:
        lines.append("### Merged PRs")
        for pr in merged:
            lines.append(f"- PR #{pr['number']} by @{pr['author']}: {pr['title']} (merged {pr['merged_at'][:10]})")
    else:
        lines.append("### Merged PRs\nNone in this window.")

    if commits:
        lines.append("### Recent Commits")
        for c in commits:
            lines.append(f"- {c['sha']} by {c['author']}: {c['message']}")
    else:
        lines.append("### Recent Commits\nNone in this window.")

    return "\n".join(lines)


# ---- Core generator ----------------------------------------------------------


def generate_report(
    gh: GitHubClient,
    owner: str,
    repo: str,
    atlassian: AtlassianClient | None,
    jql: str,
    report_type: str,
    days_back: int,
    model_id: str,
    region: str,
) -> str:
    """Orchestrate data gathering → prompt building → Bedrock call."""
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    jira_data: list[dict[str, str]] = []
    if atlassian and jql:
        jira_data = _fetch_jira_sprint_data(atlassian, jql)
        logger.info("jira_data_fetched", extra={"extra": {"count": len(jira_data)}})

    github_activity = _fetch_github_activity(gh, owner, repo, since_iso)
    logger.info(
        "github_activity_fetched",
        extra={"extra": {
            "merged_prs": len(github_activity.get("merged_prs", [])),
            "commits": len(github_activity.get("commits", [])),
        }},
    )

    user_prompt = _build_user_prompt(report_type, f"{owner}/{repo}", jira_data, github_activity, days_back)
    chat = BedrockChatClient(region=region, model_id=model_id, max_tokens=2000)
    return chat.answer(_SYSTEM_PROMPT, user_prompt)


# ---- Lambda handler ----------------------------------------------------------


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Handle API Gateway (POST) and EventBridge (scheduled) triggers."""
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    model_id = os.environ.get("SPRINT_REPORT_MODEL_ID") or os.environ.get("BEDROCK_MODEL_ID", "")

    # Detect trigger type
    request_context = event.get("requestContext")
    is_api_gateway = request_context is not None and "http" in (request_context or {})

    if is_api_gateway:
        method = (request_context.get("http") or {}).get("method", "").upper()
        if method != "POST":
            return {"statusCode": 405, "body": json.dumps({"error": "method_not_allowed"})}

        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return {"statusCode": 400, "body": json.dumps({"error": "invalid_json"})}

        repo_full = (body.get("repo") or "").strip()
        jira_project = (body.get("jira_project") or "").strip()
        jql = (body.get("jira_jql") or "").strip()
        report_type = (body.get("report_type") or "standup").strip().lower()
        days_back = int(body.get("days_back", 1 if report_type == "standup" else 14))
    else:
        # EventBridge / scheduled trigger — read from env vars
        repo_full = os.getenv("SPRINT_REPORT_REPO", "").strip()
        jira_project = os.getenv("SPRINT_REPORT_JIRA_PROJECT", "").strip()
        jql = os.getenv("SPRINT_REPORT_JQL", "").strip()
        report_type = os.getenv("SPRINT_REPORT_TYPE", "standup").strip().lower()
        days_back = int(os.getenv("SPRINT_REPORT_DAYS_BACK", "1"))

    if not repo_full or "/" not in repo_full:
        msg = {"error": "missing_fields", "detail": "repo (owner/repo) is required"}
        if is_api_gateway:
            return {"statusCode": 400, "body": json.dumps(msg)}
        logger.error("missing_repo_config", extra={"extra": msg})
        return msg

    owner, repo = repo_full.split("/", maxsplit=1)

    # Default JQL if only project provided
    if not jql and jira_project:
        jql = f"project = {jira_project} AND sprint in openSprints() ORDER BY status ASC"

    # Authenticate GitHub
    auth = GitHubAppAuth(
        app_ids_secret_arn=os.environ["GITHUB_APP_IDS_SECRET_ARN"],
        private_key_secret_arn=os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"],
        api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
    )
    token = auth.get_installation_token()
    gh = GitHubClient(
        token_provider=lambda: token,
        api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
    )

    # Atlassian client (optional)
    atlassian_secret_arn = os.getenv("ATLASSIAN_CREDENTIALS_SECRET_ARN", "")
    atlassian = AtlassianClient(credentials_secret_arn=atlassian_secret_arn) if atlassian_secret_arn else None

    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    try:
        report = generate_report(
            gh=gh,
            owner=owner,
            repo=repo,
            atlassian=atlassian,
            jql=jql,
            report_type=report_type,
            days_back=days_back,
            model_id=model_id,
            region=region,
        )
    except Exception:
        logger.exception("report_generation_failed")
        if is_api_gateway:
            return {"statusCode": 500, "body": json.dumps({"error": "generation_failed"})}
        return {"error": "generation_failed"}

    result = {
        "report_type": report_type,
        "repo": repo_full,
        "days_back": days_back,
        "dry_run": dry_run,
        "report": report,
    }

    if is_api_gateway:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(result),
        }
    return result
