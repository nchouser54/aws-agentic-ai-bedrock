import json
from unittest.mock import MagicMock

from shared.bedrock_client import BedrockReviewClient


class _BodyReader:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _review_text_payload() -> dict:
    review = {
        "summary": "ok",
        "overall_risk": "low",
        "findings": [],
    }
    return {"content": [{"text": json.dumps(review)}]}


def test_review_client_without_guardrail_omits_guardrail_fields() -> None:
    runtime = MagicMock()
    runtime.invoke_model.return_value = {"body": _BodyReader(_review_text_payload())}

    client = BedrockReviewClient(
        region="us-gov-west-1",
        model_id="anthropic.model",
        agent_runtime=MagicMock(),
        bedrock_runtime=runtime,
    )
    result = client.analyze_pr("prompt")

    assert result["overall_risk"] == "low"
    kwargs = runtime.invoke_model.call_args.kwargs
    assert "guardrailIdentifier" not in kwargs
    assert "guardrailVersion" not in kwargs
    assert "trace" not in kwargs


def test_review_client_with_guardrail_adds_invoke_model_fields() -> None:
    runtime = MagicMock()
    runtime.invoke_model.return_value = {"body": _BodyReader(_review_text_payload())}

    client = BedrockReviewClient(
        region="us-gov-west-1",
        model_id="anthropic.model",
        guardrail_identifier="gr-123",
        guardrail_version="1",
        guardrail_trace="enabled_full",
        agent_runtime=MagicMock(),
        bedrock_runtime=runtime,
    )
    result = client.analyze_pr("prompt")

    assert result["summary"] == "ok"
    kwargs = runtime.invoke_model.call_args.kwargs
    assert kwargs["guardrailIdentifier"] == "gr-123"
    assert kwargs["guardrailVersion"] == "1"
    assert kwargs["trace"] == "ENABLED_FULL"
