from __future__ import annotations

from typing import Any

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

    def answer(self, system_prompt: str, user_prompt: str) -> str:
        resp = requests.post(
            f"{self._api_base}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
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
            },
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
