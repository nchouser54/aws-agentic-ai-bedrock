import pytest

from shared.schema import parse_review_result


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


def test_schema_invalid_extra_field() -> None:
    payload = {
        "summary": "x",
        "overall_risk": "low",
        "findings": [],
        "unexpected": True,
    }

    with pytest.raises(ValueError):
        parse_review_result(payload)
