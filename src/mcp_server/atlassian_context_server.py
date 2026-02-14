from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_server.common import atlassian_client

mcp = FastMCP("atlassian-context")


@mcp.tool()
def get_jira_issue(issue_key: str) -> dict[str, Any]:
    """Fetch Jira issue details by key (example: PROJ-123)."""
    key = (issue_key or "").strip().upper()
    if not key:
        raise ValueError("issue_key must not be empty")
    return atlassian_client().get_jira_issue(key)


@mcp.tool()
def search_jira(jql: str, max_results: int = 10) -> list[dict[str, Any]]:
    """Search Jira issues with JQL."""
    query = (jql or "").strip()
    if not query:
        raise ValueError("jql must not be empty")
    limit = max(1, min(int(max_results), 50))
    return atlassian_client().search_jira(query, max_results=limit)


@mcp.tool()
def get_confluence_page(page_id: str, body_format: str = "storage") -> dict[str, Any]:
    """Fetch Confluence page details by page ID."""
    pid = (page_id or "").strip()
    if not pid:
        raise ValueError("page_id must not be empty")
    fmt = (body_format or "storage").strip() or "storage"
    return atlassian_client().get_confluence_page(pid, body_format=fmt)


@mcp.tool()
def search_confluence(cql: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search Confluence content using CQL."""
    query = (cql or "").strip()
    if not query:
        raise ValueError("cql must not be empty")
    page_limit = max(1, min(int(limit), 50))
    return atlassian_client().search_confluence(query, limit=page_limit)


@mcp.tool()
def get_atlassian_platform() -> dict[str, str]:
    """Return configured Atlassian platform (cloud or datacenter)."""
    client = atlassian_client()
    return {"platform": client.platform}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
