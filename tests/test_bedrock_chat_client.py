from shared.bedrock_chat import BedrockChatClient


class _FakeRuntime:
    def __init__(self) -> None:
        self.last_kwargs: dict | None = None

    def converse(self, **kwargs) -> dict:
        self.last_kwargs = kwargs
        return {"output": {"message": {"content": [{"text": "ok"}]}}}


def test_bedrock_chat_client_without_guardrail() -> None:
    runtime = _FakeRuntime()
    client = BedrockChatClient(
        region="us-gov-west-1",
        model_id="anthropic.model",
        bedrock_runtime=runtime,
    )

    out = client.answer("system", "user")

    assert out == "ok"
    assert runtime.last_kwargs is not None
    assert "guardrailConfig" not in runtime.last_kwargs


def test_bedrock_chat_client_with_guardrail_config() -> None:
    runtime = _FakeRuntime()
    client = BedrockChatClient(
        region="us-gov-west-1",
        model_id="anthropic.model",
        guardrail_identifier="gr-123",
        guardrail_version="1",
        guardrail_trace="enabled",
        bedrock_runtime=runtime,
    )

    _ = client.answer("system", "user")

    assert runtime.last_kwargs is not None
    assert runtime.last_kwargs["guardrailConfig"] == {
        "guardrailIdentifier": "gr-123",
        "guardrailVersion": "1",
        "trace": "enabled",
    }


def test_bedrock_chat_client_ignores_invalid_trace() -> None:
    runtime = _FakeRuntime()
    client = BedrockChatClient(
        region="us-gov-west-1",
        model_id="anthropic.model",
        guardrail_identifier="gr-123",
        guardrail_version="DRAFT",
        guardrail_trace="bad-value",
        bedrock_runtime=runtime,
    )

    _ = client.answer("system", "user")

    assert runtime.last_kwargs is not None
    assert runtime.last_kwargs["guardrailConfig"] == {
        "guardrailIdentifier": "gr-123",
        "guardrailVersion": "DRAFT",
    }
