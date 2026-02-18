import pytest

from shared.schema import TicketCompliance, parse_review_result


def test_schema_valid() -> None:
    payload = {
        "summary": "Looks mostly fine",
        "overall_risk": "low",
        "findings": [
            {
                "type": "style",
                "severity": "low",
                "file": "main.py",
                "start_line": 10,
                "end_line": 10,
                "message": "Nit",
                "suggested_patch": None,
            }
        ],
    }

    result = parse_review_result(payload)
    assert result.overall_risk == "low"
    assert len(result.findings) == 1
    assert result.ticket_compliance is None


def test_schema_invalid_extra_field() -> None:
    payload = {
        "summary": "x",
        "overall_risk": "low",
        "findings": [],
        "unexpected": True,
    }

    with pytest.raises(ValueError):
        parse_review_result(payload)


def test_schema_ticket_compliance_present() -> None:
    payload = {
        "summary": "Adds user auth behind PROJ-42 ticket",
        "overall_risk": "medium",
        "findings": [],
        "ticket_compliance": [
            {
                "ticket_key": "PROJ-42",
                "ticket_summary": "Add OAuth2 login flow",
                "fully_compliant": ["OAuth2 callback endpoint added", "Token storage implemented"],
                "not_compliant": ["Refresh token rotation not implemented"],
                "needs_human_verification": ["UI redirect tested in browser"],
            }
        ],
    }

    result = parse_review_result(payload)
    assert result.ticket_compliance is not None
    assert len(result.ticket_compliance) == 1
    tc = result.ticket_compliance[0]
    assert tc.ticket_key == "PROJ-42"
    assert len(tc.fully_compliant) == 2
    assert len(tc.not_compliant) == 1
    assert len(tc.needs_human_verification) == 1


def test_schema_ticket_compliance_empty_lists() -> None:
    """All compliance sub-lists may be empty — e.g. no issues found."""
    payload = {
        "summary": "Fully implements PROJ-7 with no gaps",
        "overall_risk": "low",
        "findings": [],
        "ticket_compliance": [
            {
                "ticket_key": "PROJ-7",
                "ticket_summary": "Add rate limiting middleware",
                "fully_compliant": ["Rate limiting middleware wired", "Unit tests added"],
                "not_compliant": [],
                "needs_human_verification": [],
            }
        ],
    }

    result = parse_review_result(payload)
    assert result.ticket_compliance is not None
    tc = result.ticket_compliance[0]
    assert tc.not_compliant == []
    assert tc.needs_human_verification == []


def test_schema_ticket_compliance_null() -> None:
    """Explicitly null ticket_compliance is valid (no Jira tickets linked)."""
    payload = {
        "summary": "Minor refactor, no ticket",
        "overall_risk": "low",
        "findings": [],
        "ticket_compliance": None,
    }
    result = parse_review_result(payload)
    assert result.ticket_compliance is None


def test_ticket_compliance_model_direct() -> None:
    tc = TicketCompliance(
        ticket_key="ABC-1",
        ticket_summary="Something",
        fully_compliant=["done"],
        not_compliant=[],
        needs_human_verification=["check UI"],
    )
    assert tc.ticket_key == "ABC-1"


def test_ticket_compliance_invalid_extra_field() -> None:
    with pytest.raises(Exception):
        TicketCompliance(
            ticket_key="ABC-1",
            ticket_summary="x",
            fully_compliant=[],
            not_compliant=[],
            needs_human_verification=[],
            unknown_field="oops",  # type: ignore[call-arg]
        )
