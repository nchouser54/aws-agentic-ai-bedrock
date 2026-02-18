"""Build the PR context dict fed to the 2-stage Bedrock planner/reviewer.

Environment variables:
  MAX_REVIEW_FILES    – max files to include (default 30)
  MAX_DIFF_BYTES      – max bytes of diff per file before truncation (default 8000)
  SKIP_PATTERNS       – comma-separated glob/substring patterns to exclude
                        (default includes common generated/lock files)
"""
from __future__ import annotations

import fnmatch
import os
from typing import Any

DEFAULT_SKIP_PATTERNS = [
    # lockfiles & generated
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "Pipfile.lock",
    "poetry.lock",
    "go.sum",
    # binary / media
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.ico",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.eot",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.gz",
    # build artefacts
    "dist/*",
    "build/*",
    "*.min.js",
    "*.min.css",
    # vendor
    "vendor/*",
    "node_modules/*",
    # sensitive (will be included as skipped, not content)
    ".env",
    "*.pem",
    "*.key",
    "*.p12",
    "*secrets*",
    "*credentials*",
]

SENSITIVE_PATTERNS = [".env", "*.pem", "*.key", "*.p12", "*secrets*", "*credentials*", "id_rsa*"]

MAX_REVIEW_FILES = int(os.getenv("MAX_REVIEW_FILES", "30"))
MAX_DIFF_BYTES = int(os.getenv("MAX_DIFF_BYTES", "8000"))
# P2-A: total budget across all files (default = per-file limit × max files)
MAX_TOTAL_DIFF_BYTES = int(os.getenv("MAX_TOTAL_DIFF_BYTES", str(MAX_DIFF_BYTES * MAX_REVIEW_FILES)))
# P2-A: what to do when a file patch exceeds MAX_DIFF_BYTES: "clip" (default) or "skip"
LARGE_PATCH_POLICY = os.getenv("LARGE_PATCH_POLICY", "clip").lower()


def _load_skip_patterns() -> list[str]:
    env_val = os.getenv("SKIP_PATTERNS", "")
    extra = [p.strip() for p in env_val.split(",") if p.strip()] if env_val else []
    return DEFAULT_SKIP_PATTERNS + extra


def _matches_any(path: str, patterns: list[str]) -> bool:
    lower = path.lower()
    for pattern in patterns:
        if fnmatch.fnmatch(lower, pattern.lower()):
            return True
        # Also check plain substring for patterns without wildcards
        if "*" not in pattern and pattern.lower() in lower:
            return True
    return False


def _is_sensitive(path: str) -> bool:
    return _matches_any(path, SENSITIVE_PATTERNS)


def build_pr_context(
    pr: dict[str, Any],
    files: list[dict[str, Any]],
    jira_issues: list[dict[str, Any]] | None = None,
    skip_patterns: list[str] | None = None,
    max_files: int | None = None,
    max_diff_bytes: int | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Assemble the context dict for the planner/reviewer prompts.

    Returns:
        (context, reviewed_files, skipped_files)
    """
    patterns = skip_patterns if skip_patterns is not None else _load_skip_patterns()
    effective_max_files = max_files if max_files is not None else MAX_REVIEW_FILES
    effective_max_diff = max_diff_bytes if max_diff_bytes is not None else MAX_DIFF_BYTES
    large_patch_policy = LARGE_PATCH_POLICY
    # 0 means unlimited total budget
    total_diff_budget = MAX_TOTAL_DIFF_BYTES if MAX_TOTAL_DIFF_BYTES > 0 else float("inf")

    # P2-A: prioritise files with the most changes so reviewers see the largest diffs first
    sorted_files = sorted(files, key=lambda f: int(f.get("changes") or 0), reverse=True)

    reviewed_files: list[str] = []
    skipped_files: list[str] = []
    selected: list[dict[str, Any]] = []
    truncation_note: str | None = None
    total_bytes_used = 0

    for file_obj in sorted_files:
        filename = file_obj.get("filename", "")

        if _is_sensitive(filename):
            skipped_files.append(f"{filename} — sensitive file")
            continue

        if _matches_any(filename, patterns):
            skipped_files.append(f"{filename} — matches skip pattern")
            continue

        if len(selected) >= effective_max_files:
            skipped_files.append(f"{filename} — file limit reached ({effective_max_files})")
            continue

        patch = file_obj.get("patch") or ""
        was_truncated = False
        patch_bytes = patch.encode("utf-8")

        if len(patch_bytes) > effective_max_diff:
            if large_patch_policy == "skip":
                skipped_files.append(f"{filename} — oversized patch ({len(patch_bytes)} bytes)")
                continue
            # default "clip"
            patch = patch_bytes[:effective_max_diff].decode("utf-8", errors="ignore")
            was_truncated = True

        patch_len = len(patch.encode("utf-8"))
        if total_bytes_used + patch_len > total_diff_budget:
            skipped_files.append(f"{filename} — total diff budget exhausted")
            continue
        total_bytes_used += patch_len

        entry: dict[str, Any] = {
            "filename": filename,
            "status": file_obj.get("status"),
            "additions": file_obj.get("additions"),
            "deletions": file_obj.get("deletions"),
            "changes": file_obj.get("changes"),
        }
        if patch:
            entry["patch"] = patch
        if was_truncated:
            entry["patch_truncated"] = True

        selected.append(entry)
        reviewed_files.append(filename)

    if skipped_files:
        truncation_note = (
            f"{len(skipped_files)} file(s) were not reviewed: "
            + "; ".join(s.split(" — ")[1] if " — " in s else "excluded" for s in skipped_files[:5])
        )
        if len(skipped_files) > 5:
            truncation_note += f" (and {len(skipped_files) - 5} more)"

    pr_meta: dict[str, Any] = {
        "title": pr.get("title"),
        "body": (pr.get("body") or "")[:1000],  # cap PR description
        "base_ref": (pr.get("base") or {}).get("ref"),
        "head_ref": (pr.get("head") or {}).get("ref"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files_total": pr.get("changed_files"),
        "changed_files": selected,
    }

    context: dict[str, Any] = {"pull_request": pr_meta}
    if jira_issues:
        context["linked_jira_issues"] = jira_issues
    if truncation_note:
        context["truncation_note"] = truncation_note

    return context, reviewed_files, skipped_files
