from chatbot.app import _format_confluence, _format_jira


def test_format_jira() -> None:
    issues = [{"key": "ENG-1", "fields": {"summary": "Fix bug", "status": {"name": "In Progress"}}}]
    out = _format_jira(issues)
    assert "ENG-1" in out
    assert "Fix bug" in out


def test_format_confluence() -> None:
    pages = [{"title": "Runbook", "url": "https://example/wiki/runbook"}]
    out = _format_confluence(pages)
    assert "Runbook" in out
    assert "https://example/wiki/runbook" in out
