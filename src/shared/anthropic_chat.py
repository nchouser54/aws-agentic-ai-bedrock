from __future__ import annotations

import json
from typing import Any
from typing import Callable

import requests


class AnthropicChatClient:
    def __init__(
        self,
        api_key: str,
        model_id: str,
        api_base: str = "https://api.anthropic.com",
        max_tokens: int = 1200,
        timeout_seconds: int = 30,
    ) -> None:
        self._api_key = api_key.strip()
        self._model_id = model_id.strip()
        self._api_base = api_base.rstrip("/")
        self._max_tokens = max_tokens
        self._timeout_seconds = timeout_seconds

    def _request_payload(self, system_prompt: str, user_prompt: str, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model_id,
            "max_tokens": self._max_tokens,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        }
        if stream:
            payload["stream"] = True
        return payload

    def answer(self, system_prompt: str, user_prompt: str) -> str:
        resp = requests.post(
            f"{self._api_base}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=self._request_payload(system_prompt=system_prompt, user_prompt=user_prompt, stream=False),
            timeout=self._timeout_seconds,
        )
        resp.raise_for_status()

        payload: dict[str, Any] = resp.json()
        content = payload.get("content", [])
        if not content:
            return "I could not produce a response."

        first = content[0] if isinstance(content[0], dict) else {}
        text = first.get("text")
        if isinstance(text, str) and text.strip():
            return text
        return "I could not produce a response."

    def stream_answer(
        self,
        system_prompt: str,
        user_prompt: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        resp = requests.post(
            f"{self._api_base}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=self._request_payload(system_prompt=system_prompt, user_prompt=user_prompt, stream=True),
            timeout=self._timeout_seconds,
            stream=True,
        )
        resp.raise_for_status()

        chunks: list[str] = []
        for raw_line in resp.iter_lines(decode_unicode=True):
            line = str(raw_line or "").strip()
            if not line.startswith("data:"):
                continue

            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue

            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if str(event.get("type") or "") != "content_block_delta":
                continue

            delta = str(((event.get("delta") or {}).get("text")) or "")
            if not delta:
                continue
            chunks.append(delta)
            if on_delta:
                on_delta(delta)

        if not chunks:
            return "I could not produce a response."
        return "".join(chunks)
