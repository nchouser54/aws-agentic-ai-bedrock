"""Release notes generator Lambda.

Triggered via API Gateway POST /release-notes/generate.

Accepts:
    {
        "repo": "owner/repo",                # required
        "tag": "v1.5.0",                     # required — tag to generate notes for
        "previous_tag": "v1.4.0",            # optional — auto-detected if omitted
        "update_release": true,              # optional — update existing GitHub Release body
        "dry_run": false                     # optional — return notes without posting
    }

Gathers all merged PRs between the two tags, extracts Jira issue keys,
fetches Jira context, and uses Bedrock to generate categorised release notes.
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

logger = get_logger("release_notes")

_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")

_SYSTEM_PROMPT = """\
You are a technical writer producing release notes for a software project.
Given a list of merged pull requests and their linked Jira tickets, produce
clean, user-facing Markdown release notes.

Rules:
- Group items under these headings (skip empty groups): Features, Bug Fixes, \
Improvements, Documentation, Breaking Changes, Other.
- Each item is a single bullet: "- **PR #N**: description (JIRA-KEY)" or just \
"- **PR #N**: description" if no Jira key.
- Use the Jira issue type to decide the section. PRs without a Jira key go to \
"Other" unless the PR title clearly fits a category.
- Keep descriptions concise — one line each.
- Do not invent information. Use only the data provided.
- At the top, write a brief 1-2 sentence overview of the release.
- Output only Markdown. No JSON, no code fences.
"""


def _extract_jira_keys_from_prs(prs: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map PR number -> list of Jira keys found in title + body + branch."""
    pr_keys: dict[str, list[str]] = {}
    for pr in prs:
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
        pr_keys[str(pr.get("number"))] = keys
    return pr_keys


def _fetch_jira_issues(
    all_keys: set[str],
    credentials_secret_arn: str,
) -> dict[str, dict[str, str]]:
    """Fetch Jira issue details. Returns key -> {summary, type, status}."""
    if not all_keys or not credentials_secret_arn:
        return {}

    atlassian = AtlassianClient(credentials_secret_arn=credentials_secret_arn)
    issues: dict[str, dict[str, str]] = {}
    for key in sorted(all_keys):
        try:
            issue = atlassian.get_jira_issue(key)
            fields = issue.get("fields") or {}
            issues[issue.get("key") or key] = {
                "summary": str(fields.get("summary") or ""),
                "type": str((fields.get("issuetype") or {}).get("name") or ""),
                "status": str((fields.get("status") or {}).get("name") or ""),
            }
        except Exception:  # noqa: BLE001
            logger.warning("jira_fetch_failed", extra={"extra": {"key": key}})
    return issues


def _build_user_prompt(
    tag: str,
    previous_tag: str,
    prs: list[dict[str, Any]],
    pr_jira_map: dict[str, list[str]],
    jira_issues: dict[str, dict[str, str]],
) -> str:
    """Compose the user prompt listing all PRs and their Jira context."""
    lines = [
        f"Release: {tag} (since {previous_tag})",
        f"Total merged PRs: {len(prs)}",
        "",
        "## Merged Pull Requests",
    ]

    for pr in prs:
        pr_num = str(pr.get("number"))
        title = pr.get("title") or "Untitled"
        author = (pr.get("user") or {}).get("login") or "unknown"
        keys = pr_jira_map.get(pr_num, [])
        jira_parts: list[str] = []
        for k in keys:
            info = jira_issues.get(k)
            if info:
                jira_parts.append(
                    f"{k} [{info['type']}]: {info['summary']} ({info['status']})"
                )
            else:
                jira_parts.append(k)
        jira_str = " | ".join(jira_parts) if jira_parts else "No linked ticket"
        lines.append(f"- PR #{pr_num} by @{author}: {title}")
        lines.append(f"  Jira: {jira_str}")

    return "\n".join(lines)


def _detect_previous_tag(
    gh: GitHubClient, owner: str, repo: str, current_tag: str,
) -> str | None:
    """Find the tag immediately before current_tag in the tag list."""
    tags = gh.list_tags(owner, repo, per_page=50)
    tag_names = [t.get("name") for t in tags]
    try:
        idx = tag_names.index(current_tag)
    except ValueError:
        return None
    if idx + 1 < len(tag_names):
        return tag_names[idx + 1]
    return None


def generate_release_notes(
    gh: GitHubClient,
    owner: str,
    repo: str,
    tag: str,
    previous_tag: str,
    atlassian_secret_arn: str,
    model_id: str,
    region: str,
) -> str:
    """Core logic: gather PRs, fetch Jira, call Bedrock, return Markdown."""
    prs = gh.list_merged_pulls_between(owner, repo, previous_tag, tag)
    logger.info(
        "prs_collected",
        extra={"extra": {"tag": tag, "previous_tag": previous_tag, "pr_count": len(prs)}},
    )

    pr_jira_map = _extract_jira_keys_from_prs(prs)
    all_keys: set[str] = set()
    for keys in pr_jira_map.values():
        all_keys.update(keys)

    jira_issues = _fetch_jira_issues(all_keys, atlassian_secret_arn)

    user_prompt = _build_user_prompt(tag, previous_tag, prs, pr_jira_map, jira_issues)

    chat = BedrockChatClient(region=region, model_id=model_id, max_tokens=2000)
    return chat.answer(_SYSTEM_PROMPT, user_prompt)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """API Gateway proxy handler for release notes generation."""
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
    tag = (body.get("tag") or "").strip()

    if not repo_full or not tag or "/" not in repo_full:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "missing_fields", "detail": "repo (owner/repo) and tag are required"}),
        }

    owner, repo = repo_full.split("/", maxsplit=1)
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    dry_run = str(body.get("dry_run", os.getenv("DRY_RUN", "false"))).lower() == "true"
    update_release = body.get("update_release", False)

    # Authenticate as GitHub App
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

    # Determine previous tag
    previous_tag = (body.get("previous_tag") or "").strip()
    if not previous_tag:
        previous_tag = _detect_previous_tag(gh, owner, repo, tag) or ""
    if not previous_tag:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "error": "no_previous_tag",
                "detail": f"Could not auto-detect a tag before {tag}. Provide previous_tag explicitly.",
            }),
        }

    atlassian_secret_arn = os.getenv("ATLASSIAN_CREDENTIALS_SECRET_ARN", "")
    model_id = os.environ.get("RELEASE_NOTES_MODEL_ID") or os.environ.get("BEDROCK_MODEL_ID", "")

    try:
        notes = generate_release_notes(
            gh=gh,
            owner=owner,
            repo=repo,
            tag=tag,
            previous_tag=previous_tag,
            atlassian_secret_arn=atlassian_secret_arn,
            model_id=model_id,
            region=region,
        )
    except Exception:
        logger.exception("release_notes_generation_failed")
        return {"statusCode": 500, "body": json.dumps({"error": "generation_failed"})}

    # Optionally update the GitHub Release body
    release_url = ""
    if update_release and not dry_run:
        try:
            release = gh.get_release_by_tag(owner, repo, tag)
            release_id = release.get("id")
            if release_id:
                updated = gh.update_release(owner, repo, int(release_id), notes)
                release_url = updated.get("html_url") or ""
        except Exception:  # noqa: BLE001
            logger.warning("release_update_failed", extra={"extra": {"tag": tag}})

    logger.info(
        "release_notes_generated",
        extra={"extra": {"tag": tag, "previous_tag": previous_tag, "dry_run": dry_run, "chars": len(notes)}},
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "tag": tag,
            "previous_tag": previous_tag,
            "release_notes": notes,
            "release_url": release_url,
            "dry_run": dry_run,
        }),
    }
