from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.common import github_client, parse_repo

mcp = FastMCP("github-release-ops")


@mcp.tool()
def list_tags(repo_full_name: str, per_page: int = 30) -> list[dict[str, Any]]:
    """List repository tags (newest first)."""
    owner, repo = parse_repo(repo_full_name)
    page_size = max(1, min(int(per_page), 100))
    return github_client().list_tags(owner, repo, per_page=page_size)


@mcp.tool()
def get_latest_release(repo_full_name: str) -> dict[str, Any]:
    """Get latest release metadata for a repository."""
    owner, repo = parse_repo(repo_full_name)
    return github_client().get_latest_release(owner, repo)


@mcp.tool()
def get_release_by_tag(repo_full_name: str, tag: str) -> dict[str, Any]:
    """Get release by tag name."""
    owner, repo = parse_repo(repo_full_name)
    tag_name = (tag or "").strip()
    if not tag_name:
        raise ValueError("tag must not be empty")
    return github_client().get_release_by_tag(owner, repo, tag_name)


@mcp.tool()
def compare_commits(repo_full_name: str, base: str, head: str) -> dict[str, Any]:
    """Compare commits/tags/branches and return changed files + commits."""
    owner, repo = parse_repo(repo_full_name)
    base_ref = (base or "").strip()
    head_ref = (head or "").strip()
    if not base_ref or not head_ref:
        raise ValueError("both base and head are required")
    return github_client().compare_commits(owner, repo, base_ref, head_ref)


@mcp.tool()
def list_merged_prs_between(repo_full_name: str, base_sha: str, head_sha: str) -> list[dict[str, Any]]:
    """Return merged PRs whose merge commits are between base and head."""
    owner, repo = parse_repo(repo_full_name)
    base_value = (base_sha or "").strip()
    head_value = (head_sha or "").strip()
    if not base_value or not head_value:
        raise ValueError("both base_sha and head_sha are required")
    return github_client().list_merged_pulls_between(owner, repo, base_value, head_value)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
