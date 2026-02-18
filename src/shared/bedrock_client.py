from __future__ import annotations

import importlib.resources
import json
import uuid
from typing import Any, Optional

import boto3
import jsonschema
from botocore.client import BaseClient


def _normalize_invoke_trace(value: str | None) -> str | None:
    normalized = (value or "").strip().upper()
    if normalized in {"ENABLED", "DISABLED", "ENABLED_FULL"}:
        return normalized
    return None


class BedrockReviewClient:
    def __init__(
        self,
        region: str,
        model_id: str,
        agent_id: Optional[str] = None,
        agent_alias_id: Optional[str] = None,
        guardrail_identifier: str | None = None,
        guardrail_version: str | None = None,
        guardrail_trace: str | None = None,
        agent_runtime: Optional[BaseClient] = None,
        bedrock_runtime: Optional[BaseClient] = None,
    ) -> None:
        self._model_id = model_id
        self._agent_id = agent_id
        self._agent_alias_id = agent_alias_id
        self._guardrail_identifier = (guardrail_identifier or "").strip() or None
        self._guardrail_version = (guardrail_version or "").strip() or None
        self._guardrail_trace = _normalize_invoke_trace(guardrail_trace)
        self._agent_runtime = agent_runtime or boto3.client("bedrock-agent-runtime", region_name=region)
        self._bedrock_runtime = bedrock_runtime or boto3.client("bedrock-runtime", region_name=region)

    def analyze_pr(self, prompt: str) -> dict:
        if self._agent_id and self._agent_alias_id:
            try:
                agent_result = self._invoke_agent(prompt)
                return self._parse_text_to_json(agent_result)
            except Exception:  # noqa: BLE001
                # Fall back to direct model invocation.
                pass

        model_result = self._invoke_model(prompt)
        return self._parse_text_to_json(model_result)

    def _invoke_agent(self, prompt: str) -> str:
        response = self._agent_runtime.invoke_agent(
            agentId=self._agent_id,
            agentAliasId=self._agent_alias_id,
            sessionId=f"pr-review-{uuid.uuid4()}",
            inputText=prompt,
        )

        chunks: list[str] = []
        for event in response.get("completion", []):
            chunk = event.get("chunk")
            if not chunk:
                continue
            raw = chunk.get("bytes", b"")
            if isinstance(raw, bytes):
                chunks.append(raw.decode("utf-8", errors="ignore"))
            else:
                chunks.append(str(raw))

        return "".join(chunks)

    def _invoke_model(self, prompt: str) -> str:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
        }

        invoke_kwargs: dict = {
            "modelId": self._model_id,
            "contentType": "application/json",
            "accept": "application/json",
            "body": json.dumps(body),
        }
        if self._guardrail_identifier and self._guardrail_version:
            invoke_kwargs["guardrailIdentifier"] = self._guardrail_identifier
            invoke_kwargs["guardrailVersion"] = self._guardrail_version
            if self._guardrail_trace:
                invoke_kwargs["trace"] = self._guardrail_trace

        response = self._bedrock_runtime.invoke_model(**invoke_kwargs)
        payload = json.loads(response["body"].read())
        content = payload.get("content", [])
        if not content:
            return json.dumps(payload)
        text = content[0].get("text")
        if not text:
            return json.dumps(payload)
        return text

    @staticmethod
    def _parse_text_to_json(text: str) -> dict:
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Bedrock response did not contain a JSON object")
        return json.loads(stripped[start : end + 1])

    # -- 2-stage planner / reviewer --------------------------------------------

    def invoke_planner(
        self,
        context: dict[str, Any],
        model_id: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Stage-1: call the light model to produce a triage plan.

        ``context`` is the PR context dict.
        ``model_id`` overrides the instance model (use BEDROCK_MODEL_LIGHT).
        ``system`` is the system prompt; defaults to planner_prompt.PLANNER_SYSTEM.
        Validates output against planner.schema.json.
        """
        from worker.prompts.planner_prompt import PLANNER_SYSTEM, build_planner_messages

        effective_model = model_id or self._model_id
        messages = build_planner_messages(context)
        sys_prompt = system or PLANNER_SYSTEM
        raw = self._invoke_model_with_system(sys_prompt, messages, effective_model, max_tokens=max_tokens)
        plan = self._parse_text_to_json(raw)
        validate_against_schema(plan, "planner.schema.json")
        return plan

    def invoke_reviewer(
        self,
        context: dict[str, Any],
        plan: dict[str, Any],
        model_id: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Stage-2: call the heavy model to produce the full review.

        ``context`` is the PR context dict.
        ``plan`` is the output of ``invoke_planner``.
        ``model_id`` overrides the instance model (use BEDROCK_MODEL_HEAVY).
        ``system`` is the system prompt; defaults to review_prompt.REVIEWER_SYSTEM.
        Validates output against review.schema.json.
        """
        from worker.prompts.review_prompt import REVIEWER_SYSTEM, build_reviewer_messages

        effective_model = model_id or self._model_id
        messages = build_reviewer_messages(context, plan)
        sys_prompt = system or REVIEWER_SYSTEM
        raw = self._invoke_model_with_system(sys_prompt, messages, effective_model, max_tokens=max_tokens)
        review = self._parse_text_to_json(raw)
        validate_against_schema(review, "review.schema.json")
        return review

    def _invoke_model_with_system(
        self,
        system: str,
        messages: list[dict],
        model_id: str,
        max_tokens: int = 2048,
    ) -> str:
        """Invoke Bedrock with an explicit system prompt and messages list."""
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "system": system,
            "messages": messages,
        }

        invoke_kwargs: dict = {
            "modelId": model_id,
            "contentType": "application/json",
            "accept": "application/json",
            "body": json.dumps(body),
        }
        if self._guardrail_identifier and self._guardrail_version:
            invoke_kwargs["guardrailIdentifier"] = self._guardrail_identifier
            invoke_kwargs["guardrailVersion"] = self._guardrail_version
            if self._guardrail_trace:
                invoke_kwargs["trace"] = self._guardrail_trace

        response = self._bedrock_runtime.invoke_model(**invoke_kwargs)
        payload = json.loads(response["body"].read())
        content = payload.get("content", [])
        if not content:
            return json.dumps(payload)
        text = content[0].get("text")
        if not text:
            return json.dumps(payload)
        return text


# ---------------------------------------------------------------------------
# Schema validation helper (module-level so tests can import directly)
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, dict] = {}


def _load_schema(schema_filename: str) -> dict:
    """Load a JSON schema from shared/schemas/, caching after first read."""
    if schema_filename not in _SCHEMA_CACHE:
        import pathlib

        schema_path = pathlib.Path(__file__).parent / "schemas" / schema_filename
        with open(schema_path, encoding="utf-8") as fh:
            _SCHEMA_CACHE[schema_filename] = json.load(fh)
    return _SCHEMA_CACHE[schema_filename]


def validate_against_schema(data: dict, schema_filename: str) -> None:
    """Validate ``data`` against the named schema file.

    Raises ``jsonschema.ValidationError`` on failure. The worker catches this
    and transitions the check run to 'completed / neutral' with an error message.
    """
    schema = _load_schema(schema_filename)
    jsonschema.validate(instance=data, schema=schema)
