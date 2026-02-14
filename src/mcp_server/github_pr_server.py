from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.common import github_client, parse_repo

mcp = FastMCP("github-pr-intelligence")


@mcp.tool()
def list_open_pull_requests(repo_full_name: str, per_page: int = 20) -> list[dict[str, Any]]:
    """List open pull requests for a repository."""
    owner, repo = parse_repo(repo_full_name)
    per_page = max(1, min(int(per_page), 100))
    pulls = github_client().list_pulls(owner=owner, repo=repo, state="open", per_page=per_page)
    return [
        {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "state": pr.get("state"),
            "author": (pr.get("user") or {}).get("login"),
            "updated_at": pr.get("updated_at"),
            "html_url": pr.get("html_url"),
        }
        for pr in pulls
    ]


@mcp.tool()
def get_pull_request(repo_full_name: str, pull_number: int) -> dict[str, Any]:
    """Get full pull request details for one PR."""
    owner, repo = parse_repo(repo_full_name)
    pr = github_client().get_pull_request(owner, repo, int(pull_number))
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "body": pr.get("body"),
        "author": (pr.get("user") or {}).get("login"),
        "base_ref": ((pr.get("base") or {}).get("ref")),
        "head_ref": ((pr.get("head") or {}).get("ref")),
        "mergeable": pr.get("mergeable"),
        "draft": pr.get("draft"),
        "updated_at": pr.get("updated_at"),
        "html_url": pr.get("html_url"),
    }


@mcp.tool()
def get_pull_request_files(repo_full_name: str, pull_number: int) -> list[dict[str, Any]]:
    """List changed files for a pull request with patch metadata."""
    owner, repo = parse_repo(repo_full_name)
    files = github_client().get_pull_request_files(owner, repo, int(pull_number))
    return [
        {
            "filename": f.get("filename"),
            "status": f.get("status"),
            "additions": f.get("additions"),
            "deletions": f.get("deletions"),
            "changes": f.get("changes"),
            "patch": f.get("patch"),
        }
        for f in files
    ]


@mcp.tool()
def search_repository_code(repo_full_name: str, query: str, per_page: int = 10) -> list[dict[str, Any]]:
    """Search code within a specific repository."""
    owner, repo = parse_repo(repo_full_name)
    q = (query or "").strip()
    if not q:
        raise ValueError("query must not be empty")

    per_page = max(1, min(int(per_page), 50))
    scoped_query = f"{q} repo:{owner}/{repo}"
    results = github_client().search_code(scoped_query, per_page=per_page)
    return [
        {
            "name": item.get("name"),
            "path": item.get("path"),
            "sha": item.get("sha"),
            "url": item.get("html_url"),
            "repository": ((item.get("repository") or {}).get("full_name")),
        }
        for item in results
    ]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
