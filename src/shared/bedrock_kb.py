from __future__ import annotations

from typing import Any, Optional

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from shared.retry import RetryConfig, call_with_retry

_KB_RETRY_CONFIG = RetryConfig(max_attempts=3, base_delay_seconds=0.5, max_delay_seconds=5.0)

_RETRYABLE_ERROR_CODES = frozenset({
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
    "TooManyRequestsException",
})


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        return code in _RETRYABLE_ERROR_CODES
    return False


class BedrockKnowledgeBaseClient:
    def __init__(
        self,
        region: str,
        knowledge_base_id: str,
        top_k: int = 5,
        bedrock_agent_runtime: Optional[BaseClient] = None,
    ) -> None:
        self._knowledge_base_id = knowledge_base_id
        self._top_k = max(1, top_k)
        self._runtime = bedrock_agent_runtime or boto3.client("bedrock-agent-runtime", region_name=region)

    def _do_retrieve(self, text: str, next_token: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "knowledgeBaseId": self._knowledge_base_id,
            "retrievalQuery": {"text": text},
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {
                    "numberOfResults": self._top_k,
                }
            },
        }
        if next_token:
            kwargs["nextToken"] = next_token

        return call_with_retry(
            operation_name="bedrock_kb_retrieve",
            fn=lambda: self._runtime.retrieve(**kwargs),
            is_retryable_exception=_is_retryable,
            config=_KB_RETRY_CONFIG,
        )

    @staticmethod
    def _extract_uri(location: dict[str, Any]) -> str:
        if "s3Location" in location:
            return (location.get("s3Location") or {}).get("uri") or ""
        if "webLocation" in location:
            return (location.get("webLocation") or {}).get("url") or ""
        if "confluenceLocation" in location:
            conf = location.get("confluenceLocation") or {}
            base = (conf.get("baseUrl") or "").rstrip("/")
            path = (conf.get("path") or "").lstrip("/")
            if base and path:
                return f"{base}/{path}"
            return base or path
        return ""

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        text = (query or "").strip()
        if not text:
            return []

        normalized: list[dict[str, Any]] = []
        next_token: str | None = None

        while True:
            response = self._do_retrieve(text, next_token)

            for result in response.get("retrievalResults", []):
                content = result.get("content") or {}
                location = result.get("location") or {}
                score = result.get("score")
                metadata = result.get("metadata") or {}

                normalized.append(
                    {
                        "text": str(content.get("text") or ""),
                        "score": score,
                        "uri": self._extract_uri(location),
                        "title": str(metadata.get("title") or metadata.get("source") or ""),
                    }
                )

                if len(normalized) >= self._top_k:
                    return normalized

            next_token = response.get("nextToken")
            if not next_token:
                break

        return normalized
