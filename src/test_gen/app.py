"""Test generation agent Lambda.

Supports two triggers:
- SQS (auto-trigger from worker after successful PR review).
- API Gateway ``POST /test-gen/generate`` — manual trigger.

Generated tests are delivered as either:
- A PR comment (``comment`` mode, default).
- A draft PR with test files (``draft_pr`` mode).
Controlled by env var ``TEST_GEN_DELIVERY_MODE``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from shared.bedrock_chat import BedrockChatClient
from shared.constants import DEFAULT_REGION
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger

logger = get_logger("test_gen")

# Files to skip when selecting testable targets
_SKIP_EXTENSIONS = frozenset({
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".lock",
    ".csv", ".svg", ".png", ".jpg", ".gif", ".ico", ".woff", ".woff2",
    ".map", ".min.js", ".min.css", ".d.ts",
})
_SKIP_PATTERNS = frozenset({
    "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock",
    ".gitignore", ".dockerignore", "Dockerfile", "Makefile",
    "LICENSE", "CHANGELOG", "requirements.txt",
})
_TEST_DIR_MARKERS = frozenset({"test_", "tests/", "test/", "__tests__/", "spec/", "_test."})


_SYSTEM_PROMPT = """\
You are an expert software test engineer. Given source code files that were \
changed in a pull request, generate comprehensive unit tests.

Rules:
- Detect the programming language and use the idiomatic test framework:
  * Python → pytest (use ``import pytest``, plain assert statements)
  * TypeScript/JavaScript → jest or vitest
  * Go → testing package
  * Java → JUnit 5
  * Other → best standard framework
- Generate ONE test file per changed source file.
- Format output as Markdown with a separate fenced code block per test file.
- Start each block with a comment line: ``# Test file: tests/test_<original>.py`` \
(adjust path/extension for the language).
- Cover: happy path, edge cases, error handling, boundary conditions.
- Mock external dependencies (APIs, databases, file I/O).
- Use descriptive test function names that explain the scenario.
- Do NOT import the real external services — mock them fully.
- Keep tests independent — no shared mutable state between tests.
- Output only Markdown. No explanations outside code blocks.
"""

MAX_FILES = int(os.getenv("TEST_GEN_MAX_FILES", "10"))


# ---- File filtering ----------------------------------------------------------


def _is_testable(filename: str) -> bool:
    """Determine whether a file is worth generating tests for."""
    if not filename:
        return False
    lower = filename.lower()
    # Skip test files themselves
    for marker in _TEST_DIR_MARKERS:
        if marker in lower:
            return False
    # Skip non-code files by extension
    for ext in _SKIP_EXTENSIONS:
        if lower.endswith(ext):
            return False
    # Skip known non-code filenames
    base = filename.rsplit("/", maxsplit=1)[-1] if "/" in filename else filename
    for pattern in _SKIP_PATTERNS:
        if base == pattern:
            return False
    return True


def _select_testable_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter PR files down to testable source files, capped at MAX_FILES."""
    return [f for f in files if f.get("status") != "removed" and _is_testable(f.get("filename", ""))][:MAX_FILES]


# ---- Prompt building ---------------------------------------------------------


def _build_user_prompt(
    files_with_content: list[dict[str, str]],
    pr_title: str,
    pr_number: int,
) -> str:
    """Build the user prompt from source file contents."""
    lines = [
        f"Pull Request #{pr_number}: {pr_title}",
        f"Changed files to generate tests for: {len(files_with_content)}",
        "",
    ]
    for f in files_with_content:
        lines.append(f"## File: {f['filename']}")
        lines.append(f"Patch (changes):\n```\n{f['patch']}\n```")
        if f.get("content"):
            lines.append(f"Full file content:\n```\n{f['content']}\n```")
        lines.append("")
    return "\n".join(lines)


# ---- Core generator ----------------------------------------------------------


def generate_tests(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    model_id: str,
    region: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Generate tests for a PR. Returns (markdown_output, testable_files)."""
    pr = gh.get_pull_request(owner, repo, pr_number)
    files = gh.get_pull_request_files(owner, repo, pr_number)

    testable = _select_testable_files(files)
    if not testable:
        logger.info("no_testable_files", extra={"extra": {"pr_number": pr_number}})
        return "", []

    logger.info("testable_files_selected", extra={"extra": {
        "pr_number": pr_number, "count": len(testable),
        "files": [f.get("filename") for f in testable],
    }})

    # Fetch full file contents for better test generation
    files_with_content: list[dict[str, str]] = []
    for f in testable:
        filename = f.get("filename", "")
        patch = f.get("patch") or ""
        content = ""
        try:
            content, _ = gh.get_file_contents(owner, repo, filename, head_sha)
        except Exception:  # noqa: BLE001
            logger.warning("file_content_fetch_failed", extra={"extra": {"file": filename}})
        files_with_content.append({
            "filename": filename,
            "patch": patch,
            "content": content,
        })

    user_prompt = _build_user_prompt(
        files_with_content,
        pr_title=pr.get("title") or "Untitled",
        pr_number=pr_number,
    )

    chat = BedrockChatClient(region=region, model_id=model_id, max_tokens=4000)
    output = chat.answer(_SYSTEM_PROMPT, user_prompt)
    return output, testable


# ---- Delivery ----------------------------------------------------------------


def _post_as_comment(
    gh: GitHubClient, owner: str, repo: str, pr_number: int, test_output: str,
) -> None:
    """Post generated tests as a collapsible PR comment."""
    body = (
        "## 🧪 AI-Generated Test Suggestions\n\n"
        "<details>\n<summary>Click to expand generated tests</summary>\n\n"
        f"{test_output}\n\n"
        "</details>\n\n"
        "_These tests are AI-generated suggestions. Review and adapt before committing._"
    )
    gh.create_issue_comment(owner, repo, pr_number, body)
    logger.info("test_comment_posted", extra={"extra": {"pr_number": pr_number}})


def _post_as_draft_pr(
    gh: GitHubClient,
    owner: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    base_ref: str,
    test_output: str,
) -> None:
    """Create a draft PR with the generated test files."""
    # Parse test file blocks from the markdown output
    test_files = _parse_test_files(test_output)
    if not test_files:
        logger.info("no_parseable_test_files", extra={"extra": {"pr_number": pr_number}})
        _post_as_comment(gh, owner, repo, pr_number, test_output)
        return

    branch_name = f"ai-tests/pr-{pr_number}-{head_sha[:8]}"

    # Create branch from base — resolve base SHA first; abort to comment on hard failure.
    try:
        base_ref_data = gh.get_ref(owner, repo, f"heads/{base_ref}")
        base_sha = ((base_ref_data.get("object") or {}).get("sha"))
        if not base_sha:
            raise ValueError("Could not resolve base SHA")
    except Exception:  # noqa: BLE001
        logger.warning("test_draft_pr_base_sha_failed", extra={"extra": {"base_ref": base_ref, "pr_number": pr_number}})
        _post_as_comment(gh, owner, repo, pr_number, test_output)
        return

    try:
        gh.create_ref(owner, repo, f"refs/heads/{branch_name}", base_sha)
    except Exception:  # noqa: BLE001
        # Branch likely already exists from a previous run — continue using it.
        pass

    # Commit test files
    for path, content in test_files:
        try:
            gh.put_file_contents(
                owner=owner,
                repo=repo,
                path=path,
                branch=branch_name,
                message=f"AI test suggestion: {path}",
                content=content,
            )
        except Exception:  # noqa: BLE001
            logger.warning("test_file_commit_failed", extra={"extra": {"path": path}})

    # Create draft PR — fall back to a comment if the PR already exists or the call fails.
    pr_body = (
        f"AI-generated test suggestions for PR #{pr_number}.\n\n"
        "**Review all tests before merging.** These are auto-generated and may "
        "need adjustments for your project's specific patterns."
    )
    try:
        gh.create_pull_request(
            owner=owner,
            repo=repo,
            title=f"AI Test Suggestions for #{pr_number}",
            head=branch_name,
            base=base_ref,
            body=pr_body,
        )
        logger.info("test_draft_pr_created", extra={"extra": {"pr_number": pr_number, "branch": branch_name}})
    except Exception:  # noqa: BLE001
        logger.warning("test_draft_pr_create_failed_fallback_to_comment", extra={"extra": {"pr_number": pr_number}})
        _post_as_comment(gh, owner, repo, pr_number, test_output)


def _is_safe_generated_test_path(path: str) -> bool:
    normalized = (path or "").strip().replace("\\", "/")
    if not normalized:
        return False
    if normalized.startswith("/") or normalized.startswith("./"):
        return False

    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return False

    lower = normalized.lower()
    allowed_prefixes = ("tests/", "test/", "__tests__/", "spec/")
    return lower.startswith(allowed_prefixes)


def _parse_test_files(markdown: str) -> list[tuple[str, str]]:
    """Extract (path, content) tuples from markdown code blocks.

    Expects blocks starting with a comment like:
        # Test file: tests/test_example.py
    """
    files: list[tuple[str, str]] = []
    in_block = False
    current_path = ""
    current_lines: list[str] = []

    for line in markdown.split("\n"):
        if line.strip().startswith("```") and not in_block:
            in_block = True
            current_lines = []
            continue
        if line.strip().startswith("```") and in_block:
            in_block = False
            if current_path and current_lines:
                files.append((current_path, "\n".join(current_lines)))
            current_path = ""
            current_lines = []
            continue
        if in_block:
            # Check for path comment on first non-empty line
            stripped = line.strip()
            if not current_path and stripped.startswith("#") and "test file:" in stripped.lower():
                path = stripped.split(":", 1)[1].strip()
                if path and _is_safe_generated_test_path(path):
                    current_path = path
                    continue
            current_lines.append(line)

    return files


# ---- Lambda handler ----------------------------------------------------------


def _process_sqs_record(record: dict[str, Any]) -> None:
    """Process a single SQS record (auto-triggered from worker)."""
    message = json.loads(record["body"])
    repo_full = message["repo_full_name"]
    pr_number = int(message["pr_number"])
    head_sha = message["head_sha"]
    base_ref = message.get("base_ref", "main")

    owner, repo = repo_full.split("/", maxsplit=1)
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    model_id = os.environ.get("TEST_GEN_MODEL_ID") or os.environ.get("BEDROCK_MODEL_ID", "")
    delivery_mode = os.getenv("TEST_GEN_DELIVERY_MODE", "comment").lower()
    dry_run = os.getenv("DRY_RUN", "false").lower() == "true"

    auth = GitHubAppAuth(
        app_ids_secret_arn=os.environ["GITHUB_APP_IDS_SECRET_ARN"],
        private_key_secret_arn=os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"],
        api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
    )
    token = auth.get_installation_token(
        installation_id_override=str(message.get("installation_id")) if message.get("installation_id") else None,
    )
    gh = GitHubClient(token_provider=lambda: token, api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"))

    test_output, testable = generate_tests(gh, owner, repo, pr_number, head_sha, model_id, region)
    if not test_output:
        return

    if dry_run:
        logger.info("dry_run_test_gen", extra={"extra": {
            "pr_number": pr_number, "delivery_mode": delivery_mode, "files": len(testable),
        }})
        return

    if delivery_mode == "draft_pr":
        _post_as_draft_pr(gh, owner, repo, pr_number, head_sha, base_ref, test_output)
    else:
        _post_as_comment(gh, owner, repo, pr_number, test_output)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Handle SQS records or API Gateway POST."""
    # Check for SQS trigger
    if "Records" in event:
        failures: list[dict[str, str]] = []
        for record in event["Records"]:
            try:
                _process_sqs_record(record)
            except Exception:  # noqa: BLE001
                logger.exception("test_gen_record_failed", extra={"messageId": record.get("messageId")})
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

    if not repo_full or not pr_number or "/" not in repo_full:
        return {"statusCode": 400, "body": json.dumps({
            "error": "missing_fields", "detail": "repo (owner/repo) and pr_number are required",
        })}

    owner, repo = repo_full.split("/", maxsplit=1)
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    model_id = os.environ.get("TEST_GEN_MODEL_ID") or os.environ.get("BEDROCK_MODEL_ID", "")
    delivery_mode = os.getenv("TEST_GEN_DELIVERY_MODE", "comment").lower()
    dry_run = str(body.get("dry_run", os.getenv("DRY_RUN", "false"))).lower() == "true"

    auth = GitHubAppAuth(
        app_ids_secret_arn=os.environ["GITHUB_APP_IDS_SECRET_ARN"],
        private_key_secret_arn=os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"],
        api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
    )
    token = auth.get_installation_token()
    gh = GitHubClient(token_provider=lambda: token, api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"))

    pr = gh.get_pull_request(owner, repo, int(pr_number))
    head_sha = (pr.get("head") or {}).get("sha") or ""
    base_ref = (pr.get("base") or {}).get("ref") or "main"

    try:
        test_output, testable = generate_tests(gh, owner, repo, int(pr_number), head_sha, model_id, region)
    except Exception:
        logger.exception("test_gen_failed")
        return {"statusCode": 500, "body": json.dumps({"error": "generation_failed"})}

    if not test_output:
        return {"statusCode": 200, "body": json.dumps({"status": "no_testable_files"})}

    if not dry_run:
        if delivery_mode == "draft_pr":
            _post_as_draft_pr(gh, owner, repo, int(pr_number), head_sha, base_ref, test_output)
        else:
            _post_as_comment(gh, owner, repo, int(pr_number), test_output)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "status": "generated",
            "delivery_mode": delivery_mode,
            "dry_run": dry_run,
            "files_analyzed": len(testable),
            "tests": test_output,
        }),
    }
