import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


RiskLevel = Literal["low", "medium", "high"]
FindingType = Literal["bug", "security", "style", "performance", "tests", "docs"]


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: FindingType
    severity: RiskLevel
    file: str
    start_line: Optional[int]
    end_line: Optional[int]
    message: str
    suggested_patch: Optional[str]

    @field_validator("file")
    @classmethod
    def validate_file(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("file cannot be empty")
        return value


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str
    overall_risk: RiskLevel
    findings: list[Finding]


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_candidate(raw_text: str) -> str:
    stripped = raw_text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    match = _JSON_BLOCK_RE.search(raw_text)
    if not match:
        raise ValueError("No JSON object found in model response")
    return match.group(0)


def parse_review_result(raw: str | dict) -> ReviewResult:
    if isinstance(raw, dict):
        return ReviewResult.model_validate(raw)

    candidate = _extract_json_candidate(raw)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError("Model output is not valid JSON") from exc

    try:
        return ReviewResult.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"Model output failed schema validation: {exc}") from exc
