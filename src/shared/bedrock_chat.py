from __future__ import annotations

import json
import os
from typing import Optional

import boto3
from botocore.client import BaseClient


class BedrockChatClient:
    def __init__(
        self,
        region: str,
        model_id: str,
        max_tokens: int | None = None,
        bedrock_runtime: Optional[BaseClient] = None,
    ) -> None:
        self._model_id = model_id
        self._max_tokens = max_tokens or int(os.getenv("CHATBOT_MAX_TOKENS", "1200"))
        self._runtime = bedrock_runtime or boto3.client("bedrock-runtime", region_name=region)

    def answer(self, system_prompt: str, user_prompt: str) -> str:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self._max_tokens,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_prompt}],
                }
            ],
        }
        response = self._runtime.invoke_model(
            modelId=self._model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        payload = json.loads(response["body"].read())
        content = payload.get("content", [])
        if not content:
            return "I could not produce a response."
        return content[0].get("text", "I could not produce a response.")
