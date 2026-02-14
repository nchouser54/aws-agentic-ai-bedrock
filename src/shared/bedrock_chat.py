from __future__ import annotations

import os
from typing import Any, Callable, Optional

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

    def _build_request(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
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
        return request

    @staticmethod
    def _capture_telemetry(telemetry: dict[str, Any] | None, payload: dict[str, Any] | None) -> None:
        if telemetry is None or not isinstance(payload, dict):
            return
        stop_reason = str(payload.get("stopReason") or payload.get("stop_reason") or "").strip()
        if stop_reason:
            telemetry["stop_reason"] = stop_reason
            if "guardrail" in stop_reason.lower():
                telemetry["guardrail_intervened"] = True
        action = str(payload.get("guardrailAction") or payload.get("action") or "").strip()
        if action:
            telemetry["guardrail_action"] = action
            if action.lower() not in {"allow", "allowed", "none", "pass"}:
                telemetry["guardrail_intervened"] = True
        nested_guardrail = payload.get("guardrail")
        if isinstance(nested_guardrail, dict):
            nested_action = str(nested_guardrail.get("action") or "").strip()
            if nested_action:
                telemetry["guardrail_action"] = nested_action
                if nested_action.lower() not in {"allow", "allowed", "none", "pass"}:
                    telemetry["guardrail_intervened"] = True

    def answer(self, system_prompt: str, user_prompt: str, telemetry: dict[str, Any] | None = None) -> str:
        request = self._build_request(system_prompt, user_prompt)

        response = self._runtime.converse(
            **request,
        )
        self._capture_telemetry(telemetry, response)
        content = (((response.get("output") or {}).get("message") or {}).get("content") or [])
        if not content or not isinstance(content[0], dict):
            return "I could not produce a response."
        return str(content[0].get("text") or "I could not produce a response.")

    def stream_answer(
        self,
        system_prompt: str,
        user_prompt: str,
        on_delta: Callable[[str], None] | None = None,
        telemetry: dict[str, Any] | None = None,
    ) -> str:
        request = self._build_request(system_prompt, user_prompt)
        if not hasattr(self._runtime, "converse_stream"):
            text = self.answer(system_prompt=system_prompt, user_prompt=user_prompt, telemetry=telemetry)
            if on_delta and text:
                on_delta(text)
            return text

        response = self._runtime.converse_stream(**request)
        chunks: list[str] = []
        stream = response.get("stream") or []
        for event in stream:
            if not isinstance(event, dict):
                continue

            for exception_key in (
                "internalServerException",
                "modelStreamErrorException",
                "throttlingException",
                "validationException",
            ):
                if exception_key in event:
                    raise RuntimeError(exception_key)

            delta = ((event.get("contentBlockDelta") or {}).get("delta") or {})
            text = str(delta.get("text") or "")
            if text:
                chunks.append(text)
                if on_delta:
                    on_delta(text)

            self._capture_telemetry(telemetry, event.get("metadata") if isinstance(event.get("metadata"), dict) else None)
            self._capture_telemetry(
                telemetry,
                event.get("messageStop") if isinstance(event.get("messageStop"), dict) else None,
            )

        if not chunks:
            return "I could not produce a response."
        return "".join(chunks)
