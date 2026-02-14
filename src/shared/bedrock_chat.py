from __future__ import annotations

import os
from typing import Optional

import boto3
from botocore.client import BaseClient


def _normalize_guardrail_trace(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if normalized in {"enabled", "disabled"}:
        return normalized
    return None


class BedrockChatClient:
    def __init__(
        self,
        region: str,
        model_id: str,
        max_tokens: int | None = None,
        guardrail_identifier: str | None = None,
        guardrail_version: str | None = None,
        guardrail_trace: str | None = None,
        bedrock_runtime: Optional[BaseClient] = None,
    ) -> None:
        self._model_id = model_id
        self._max_tokens = max_tokens or int(os.getenv("CHATBOT_MAX_TOKENS", "1200"))
        self._guardrail_identifier = (guardrail_identifier or "").strip() or None
        self._guardrail_version = (guardrail_version or "").strip() or None
        self._guardrail_trace = _normalize_guardrail_trace(guardrail_trace)
        self._runtime = bedrock_runtime or boto3.client("bedrock-runtime", region_name=region)

    def answer(self, system_prompt: str, user_prompt: str) -> str:
        request: dict = {
            "modelId": self._model_id,
            "system": [{"text": system_prompt}],
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": user_prompt}],
                }
            ],
            "inferenceConfig": {
                "maxTokens": self._max_tokens,
                "temperature": 0.2,
            },
        }

        if self._guardrail_identifier and self._guardrail_version:
            guardrail_config = {
                "guardrailIdentifier": self._guardrail_identifier,
                "guardrailVersion": self._guardrail_version,
            }
            if self._guardrail_trace:
                guardrail_config["trace"] = self._guardrail_trace
            request["guardrailConfig"] = guardrail_config

        response = self._runtime.converse(
            **request,
        )
        content = (((response.get("output") or {}).get("message") or {}).get("content") or [])
        if not content or not isinstance(content[0], dict):
            return "I could not produce a response."
        return str(content[0].get("text") or "I could not produce a response.")
