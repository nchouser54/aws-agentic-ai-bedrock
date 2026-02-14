from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.common import atlassian_client, github_client, parse_repo

mcp = FastMCP("org-unified-context")


@mcp.tool()
def github_list_open_pull_requests(repo_full_name: str, per_page: int = 20) -> list[dict[str, Any]]:
    """List open GitHub pull requests for a repository."""
    owner, repo = parse_repo(repo_full_name)
    page_size = max(1, min(int(per_page), 100))
    pulls = github_client().list_pulls(owner=owner, repo=repo, state="open", per_page=page_size)
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
def github_search_repository_code(repo_full_name: str, query: str, per_page: int = 10) -> list[dict[str, Any]]:
    """Search code in a GitHub repository."""
    owner, repo = parse_repo(repo_full_name)
    q = (query or "").strip()
    if not q:
        raise ValueError("query must not be empty")
    page_size = max(1, min(int(per_page), 50))
    scoped = f"{q} repo:{owner}/{repo}"
    return github_client().search_code(scoped, per_page=page_size)


@mcp.tool()
def jira_search(jql: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search Jira issues with JQL."""
    query = (jql or "").strip()
    if not query:
        raise ValueError("jql must not be empty")
    limit = max(1, min(int(max_results), 50))
    return atlassian_client().search_jira(query, max_results=limit)


@mcp.tool()
def confluence_search(cql: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search Confluence pages/content with CQL."""
    query = (cql or "").strip()
    if not query:
        raise ValueError("cql must not be empty")
    page_limit = max(1, min(int(limit), 50))
    return atlassian_client().search_confluence(query, limit=page_limit)


@mcp.tool()
def health_context() -> dict[str, str]:
    """Return quick health/context metadata for configured providers."""
    return {
        "github_api_base": "configured",
        "atlassian_platform": atlassian_client().platform,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
