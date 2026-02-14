from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import boto3

from shared.atlassian_client import AtlassianClient
from shared.anthropic_chat import AnthropicChatClient
from shared.bedrock_chat import BedrockChatClient
from shared.bedrock_kb import BedrockKnowledgeBaseClient
from shared.constants import DEFAULT_REGION, MAX_QUERY_FILTER_LENGTH, MAX_QUERY_LENGTH
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger

logger = get_logger("jira_confluence_chatbot")
ALLOWED_RETRIEVAL_MODES = {"live", "kb", "hybrid"}
ALLOWED_ASSISTANT_MODES = {"contextual", "general"}
ALLOWED_LLM_PROVIDERS = {"bedrock", "anthropic_direct"}
_VALID_CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_VALID_FEEDBACK_SENTIMENTS = {"positive", "negative", "neutral"}
_SAFETY_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions?", re.IGNORECASE),
    re.compile(r"(system|developer)\s+prompt", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?(rules|instructions?)", re.IGNORECASE),
    re.compile(r"override\s+(the\s+)?(policy|instructions?)", re.IGNORECASE),
)
_SAFETY_EXFILTRATION_PATTERNS = (
    re.compile(
        r"(show|reveal|dump|print|send|exfiltrat\w*)\s+.{0,50}"
        r"(api[\s_-]?key|secret|token|password|private[\s_-]?key|credential|env(?:ironment)?\s*var)",
        re.IGNORECASE,
    ),
    re.compile(r"BEGIN\s+(RSA|OPENSSH|EC)\s+PRIVATE\s+KEY", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
_SENSITIVE_STORE_PATTERNS = (
    re.compile(r"BEGIN\s+(RSA|OPENSSH|EC)\s+PRIVATE\s+KEY", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{20,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
)
_cloudwatch: Any | None = None

_cached_api_token: str | None = None
_cached_anthropic_api_key: str | None = None
_dynamodb_client_cached: Any | None = None
_secrets_client_cached: Any | None = None


def _secrets_client() -> Any:
    global _secrets_client_cached  # noqa: PLW0603
    if _secrets_client_cached is None:
        _secrets_client_cached = boto3.client("secretsmanager")
    return _secrets_client_cached


def _dynamodb_client() -> Any:
    global _dynamodb_client_cached  # noqa: PLW0603
    if _dynamodb_client_cached is None:
        _dynamodb_client_cached = boto3.client("dynamodb", region_name=os.getenv("AWS_REGION", DEFAULT_REGION))
    return _dynamodb_client_cached


def _metrics_namespace() -> str:
    return os.getenv("METRICS_NAMESPACE", "AIPrReviewer")


def _cloudwatch_client() -> Any:
    global _cloudwatch  # noqa: PLW0603
    if _cloudwatch is None:
        _cloudwatch = boto3.client("cloudwatch")
    return _cloudwatch


def _emit_metric(
    metric_name: str,
    value: float,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
) -> None:
    if os.getenv("CHATBOT_METRICS_ENABLED", "true").strip().lower() != "true":
        return

    # Avoid external AWS calls during local unit tests.
    if os.getenv("PYTEST_CURRENT_TEST"):
        return

    metric_dims = [
        {"Name": str(name), "Value": str(dim_value)}
        for name, dim_value in (dimensions or {}).items()
    ]
    try:
        _cloudwatch_client().put_metric_data(
            Namespace=_metrics_namespace(),
            MetricData=[
                {
                    "MetricName": metric_name,
                    "Unit": unit,
                    "Value": value,
                    "Dimensions": metric_dims,
                }
            ],
        )
    except Exception:
        logger.warning(
            "chatbot_metric_emit_failed",
            extra={"extra": {"metric_name": metric_name}},
        )


def _route_name(path: str) -> str:
    if path.endswith("/chatbot/query"):
        return "query"
    if path.endswith("/chatbot/image"):
        return "image"
    if path.endswith("/chatbot/models"):
        return "models"
    if path.endswith("/chatbot/feedback"):
        return "feedback"
    return "other"


def _respond(
    *,
    method: str,
    path: str,
    started_at: float,
    status_code: int,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    route = _route_name(path)
    base_dimensions = {
        "Route": route,
        "Method": method,
    }

    _emit_metric(
        "ChatbotRequestCount",
        1,
        dimensions={**base_dimensions, "StatusCode": str(status_code)},
    )

    duration_ms = max(0.0, (time.time() - started_at) * 1000.0)
    _emit_metric("ChatbotLatencyMs", duration_ms, unit="Milliseconds", dimensions=base_dimensions)

    if status_code >= 400:
        _emit_metric("ChatbotErrorCount", 1, dimensions={**base_dimensions, "StatusCode": str(status_code)})
    if status_code >= 500:
        _emit_metric("ChatbotServerErrorCount", 1, dimensions=base_dimensions)

    response: dict[str, Any] = {
        "statusCode": status_code,
        "body": json.dumps(payload),
    }
    if headers is not None:
        response["headers"] = headers
    return response


def _error_status_code(error_code: str) -> int:
    normalized = (error_code or "").strip().lower()
    if normalized in {"rate_limit_exceeded", "conversation_budget_exceeded"}:
        return 429
    if normalized in {
        "provider_not_allowed",
        "model_not_allowed",
        "anthropic_direct_disabled",
        "data_exfiltration_attempt",
    }:
        return 403
    if normalized in {"quota_backend_unavailable", "dynamodb_unavailable"}:
        return 503
    return 400


def _load_api_token() -> str:
    """Load chatbot API token from Secrets Manager or env var, with caching."""
    global _cached_api_token  # noqa: PLW0603
    if _cached_api_token is not None:
        return _cached_api_token

    secret_arn = os.getenv("CHATBOT_API_TOKEN_SECRET_ARN", "").strip()
    if secret_arn:
        client = _secrets_client()
        resp = client.get_secret_value(SecretId=secret_arn)
        _cached_api_token = (resp.get("SecretString") or "").strip()
    else:
        _cached_api_token = os.getenv("CHATBOT_API_TOKEN", "").strip()
    return _cached_api_token


def _validate_query_filter(value: str) -> bool:
    """Reject CQL/JQL strings that look suspicious or exceed length."""
    if len(value) > MAX_QUERY_FILTER_LENGTH:
        return False
    # Block common injection markers
    for marker in (";", "--", "/*", "*/"):
        if marker in value:
            return False
    return True


def _normalize_assistant_mode(value: str | None) -> str:
    mode = (value or os.getenv("CHATBOT_DEFAULT_ASSISTANT_MODE", "contextual")).strip().lower()
    if mode not in ALLOWED_ASSISTANT_MODES:
        return "contextual"
    return mode


def _normalize_llm_provider(value: str | None) -> str:
    provider = (value or os.getenv("CHATBOT_LLM_PROVIDER", "bedrock")).strip().lower()
    if provider not in ALLOWED_LLM_PROVIDERS:
        return "bedrock"
    return provider


def _allowed_llm_providers() -> set[str]:
    raw = os.getenv("CHATBOT_ALLOWED_LLM_PROVIDERS", "").strip()
    if raw:
        allowed = {item.strip().lower() for item in raw.split(",") if item.strip()}
        filtered = {item for item in allowed if item in ALLOWED_LLM_PROVIDERS}
        return filtered or {"bedrock"}

    providers = {"bedrock"}
    if os.getenv("CHATBOT_ENABLE_ANTHROPIC_DIRECT", "false").strip().lower() == "true":
        providers.add("anthropic_direct")
    return providers


def _validate_provider(provider: str) -> None:
    if provider not in _allowed_llm_providers():
        raise ValueError("provider_not_allowed")


def _default_bedrock_model_ids() -> set[str]:
    defaults: set[str] = set()
    for env_name in ("CHATBOT_MODEL_ID", "BEDROCK_MODEL_ID"):
        candidate = os.getenv(env_name, "").strip()
        if candidate:
            defaults.add(candidate)
    return defaults


def _allowed_bedrock_model_ids() -> set[str]:
    raw = os.getenv("CHATBOT_ALLOWED_MODEL_IDS", "").strip()
    if raw:
        return {item.strip() for item in raw.split(",") if item.strip()}
    return _default_bedrock_model_ids()


def _allowed_anthropic_model_ids() -> set[str]:
    raw = os.getenv("CHATBOT_ALLOWED_ANTHROPIC_MODEL_IDS", "").strip()
    if raw:
        return {item.strip() for item in raw.split(",") if item.strip()}
    default_model = os.getenv("CHATBOT_ANTHROPIC_MODEL_ID", "claude-sonnet-4-5").strip()
    return {default_model} if default_model else set()


def _validate_bedrock_model_id(model_id: str) -> None:
    if not model_id:
        raise ValueError("model_id_required")
    allowlist = _allowed_bedrock_model_ids()
    if not allowlist or model_id not in allowlist:
        raise ValueError("model_not_allowed")


def _validate_anthropic_model_id(model_id: str) -> None:
    if not model_id:
        raise ValueError("model_id_required")
    allowlist = _allowed_anthropic_model_ids()
    if not allowlist or model_id not in allowlist:
        raise ValueError("model_not_allowed")


def _validate_model_policy(provider: str, model_id: str) -> None:
    _validate_provider(provider)
    if provider == "anthropic_direct":
        _validate_anthropic_model_id(model_id)
        return
    _validate_bedrock_model_id(model_id)


def _load_anthropic_api_key() -> str:
    global _cached_anthropic_api_key  # noqa: PLW0603
    if _cached_anthropic_api_key is not None:
        return _cached_anthropic_api_key

    secret_arn = os.getenv("CHATBOT_ANTHROPIC_API_KEY_SECRET_ARN", "").strip()
    if secret_arn:
        client = _secrets_client()
        resp = client.get_secret_value(SecretId=secret_arn)
        _cached_anthropic_api_key = (resp.get("SecretString") or "").strip()
    else:
        _cached_anthropic_api_key = os.getenv("CHATBOT_ANTHROPIC_API_KEY", "").strip()

    return _cached_anthropic_api_key


def _resolve_model_id(provider: str, requested_model_id: str | None) -> str:
    requested = (requested_model_id or "").strip()
    if provider == "anthropic_direct":
        return requested or os.getenv("CHATBOT_ANTHROPIC_MODEL_ID", "claude-sonnet-4-5")
    return requested or os.getenv("CHATBOT_MODEL_ID", os.environ.get("BEDROCK_MODEL_ID", ""))


def _chat_memory_enabled() -> bool:
    return os.getenv("CHATBOT_MEMORY_ENABLED", "false").strip().lower() == "true"


def _chat_memory_table() -> str:
    return os.getenv("CHATBOT_MEMORY_TABLE", "").strip()


def _memory_compaction_chars() -> int:
    return max(2000, int(os.getenv("CHATBOT_MEMORY_COMPACTION_CHARS", "12000")))


def _user_requests_per_minute_limit() -> int:
    return max(1, int(os.getenv("CHATBOT_USER_REQUESTS_PER_MINUTE", "120")))


def _conversation_requests_per_minute_limit() -> int:
    return max(1, int(os.getenv("CHATBOT_CONVERSATION_REQUESTS_PER_MINUTE", "60")))


def _quota_fail_open() -> bool:
    return os.getenv("CHATBOT_QUOTA_FAIL_OPEN", "false").strip().lower() == "true"


def _image_user_requests_per_minute_limit() -> int:
    return max(1, int(os.getenv("CHATBOT_IMAGE_USER_REQUESTS_PER_MINUTE", "30")))


def _image_conversation_requests_per_minute_limit() -> int:
    return max(1, int(os.getenv("CHATBOT_IMAGE_CONVERSATION_REQUESTS_PER_MINUTE", "10")))


def _image_safety_enabled() -> bool:
    return os.getenv("CHATBOT_IMAGE_SAFETY_ENABLED", "true").strip().lower() == "true"


def _image_banned_terms() -> list[str]:
    raw = os.getenv(
        "CHATBOT_IMAGE_BANNED_TERMS",
        "explicit sexual,nudity,child sexual,self-harm,graphic gore,extreme violence,dismemberment",
    )
    return [term.strip().lower() for term in raw.split(",") if term.strip()]


def _websocket_default_chunk_chars() -> int:
    return max(20, int(os.getenv("CHATBOT_WEBSOCKET_DEFAULT_CHUNK_CHARS", "120")))


def _rerank_enabled() -> bool:
    return os.getenv("CHATBOT_RERANK_ENABLED", "true").strip().lower() == "true"


def _rerank_top_k_per_source() -> int:
    return max(1, int(os.getenv("CHATBOT_RERANK_TOP_K_PER_SOURCE", "3")))


def _prompt_safety_enabled() -> bool:
    return os.getenv("CHATBOT_PROMPT_SAFETY_ENABLED", "true").strip().lower() == "true"


def _context_safety_block_request() -> bool:
    return os.getenv("CHATBOT_CONTEXT_SAFETY_BLOCK_REQUEST", "false").strip().lower() == "true"


def _safety_scan_char_limit() -> int:
    return max(256, int(os.getenv("CHATBOT_SAFETY_SCAN_CHAR_LIMIT", "8000")))


def _context_max_chars_per_source() -> int:
    return max(256, int(os.getenv("CHATBOT_CONTEXT_MAX_CHARS_PER_SOURCE", "3500")))


def _context_max_total_chars() -> int:
    return max(1024, int(os.getenv("CHATBOT_CONTEXT_MAX_TOTAL_CHARS", "12000")))


def _budgets_enabled() -> bool:
    return os.getenv("CHATBOT_BUDGETS_ENABLED", "false").strip().lower() == "true"


def _budget_table() -> str:
    explicit = os.getenv("CHATBOT_BUDGET_TABLE", "").strip()
    if explicit:
        return explicit
    return _chat_memory_table()


def _budget_soft_limit_usd() -> float:
    try:
        return max(0.0, float(os.getenv("CHATBOT_BUDGET_SOFT_LIMIT_USD", "0.50")))
    except ValueError:
        return 0.5


def _budget_hard_limit_usd() -> float:
    try:
        hard = max(0.0, float(os.getenv("CHATBOT_BUDGET_HARD_LIMIT_USD", "1.00")))
    except ValueError:
        hard = 1.0
    return max(hard, _budget_soft_limit_usd())


def _budget_ttl_days() -> int:
    return max(1, int(os.getenv("CHATBOT_BUDGET_TTL_DAYS", "90")))


def _router_low_cost_model(provider: str) -> str:
    if provider == "anthropic_direct":
        return (os.getenv("CHATBOT_ROUTER_LOW_COST_ANTHROPIC_MODEL_ID", "") or "").strip()
    return (os.getenv("CHATBOT_ROUTER_LOW_COST_BEDROCK_MODEL_ID", "") or "").strip()


def _router_high_quality_model(provider: str, fallback: str) -> str:
    if provider == "anthropic_direct":
        candidate = (os.getenv("CHATBOT_ROUTER_HIGH_QUALITY_ANTHROPIC_MODEL_ID", "") or "").strip()
    else:
        candidate = (os.getenv("CHATBOT_ROUTER_HIGH_QUALITY_BEDROCK_MODEL_ID", "") or "").strip()
    return candidate or fallback


def _budget_storage_key(actor_id: str, conversation_id: str | None) -> str:
    conv = conversation_id or "default"
    return f"budget#{actor_id}#{conv}"


def _estimate_tokens(value: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _query_complexity(query: str) -> str:
    text = str(query or "").strip().lower()
    if not text:
        return "low"

    tokens = re.findall(r"[a-z0-9_]+", text)
    if len(tokens) >= 36:
        return "high"
    if len(tokens) <= 10:
        return "low"

    complexity_hints = (
        "root cause",
        "tradeoff",
        "architecture",
        "threat model",
        "postmortem",
        "multi-step",
        "compare",
        "migration plan",
    )
    if any(hint in text for hint in complexity_hints):
        return "high"
    return "medium"


def _normalize_conversation_id(value: str | None) -> str | None:
    candidate = (value or "").strip()
    if not candidate:
        return None
    if not _VALID_CONVERSATION_ID_RE.match(candidate):
        raise ValueError("conversation_id_invalid")
    return candidate


def _actor_id(event: dict[str, Any]) -> str:
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}

    jwt_claims = ((authorizer.get("jwt") or {}).get("claims") or {}) if isinstance(authorizer, dict) else {}
    if isinstance(jwt_claims, dict):
        for key in ("sub", "preferred_username", "email"):
            val = str(jwt_claims.get(key) or "").strip()
            if val:
                return f"jwt:{val}"

    if isinstance(authorizer, dict):
        principal = str(authorizer.get("principalId") or "").strip()
        if principal:
            return f"authorizer:{principal}"

    headers = event.get("headers") or {}
    token = ""
    for key, value in headers.items():
        if str(key).lower() == "x-api-token":
            token = str(value or "").strip()
            break
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return f"token:{token_hash}"

    return "anonymous"


def _conversation_storage_key(actor_id: str, conversation_id: str) -> str:
    return f"conv#{actor_id}#{conversation_id}"


def _extract_context_text(source: str, item: dict[str, Any]) -> str:
    if source == "jira":
        fields = item.get("fields") or {}
        return " ".join(
            part
            for part in [
                str(item.get("key") or ""),
                str(fields.get("summary") or ""),
                str((fields.get("status") or {}).get("name") or ""),
                str(fields.get("description") or ""),
            ]
            if part
        )
    if source == "confluence":
        return " ".join(
            part
            for part in [
                str(item.get("title") or (item.get("content") or {}).get("title") or ""),
                str(item.get("url") or item.get("_links", {}).get("webui") or ""),
                str(item.get("excerpt") or ""),
                str(item.get("body") or ""),
            ]
            if part
        )
    if source == "knowledge_base":
        return " ".join(
            part
            for part in [
                str(item.get("title") or ""),
                str(item.get("uri") or ""),
                str(item.get("text") or ""),
            ]
            if part
        )
    if source == "github":
        return " ".join(
            part
            for part in [
                str(item.get("repo") or ""),
                str(item.get("path") or ""),
                str(item.get("url") or ""),
                str(item.get("text") or ""),
            ]
            if part
        )
    return str(item)


def _detect_safety_categories(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    scanned = text[: _safety_scan_char_limit()]

    categories: set[str] = set()
    for pattern in _SAFETY_INJECTION_PATTERNS:
        if pattern.search(scanned):
            categories.add("prompt_injection")
            break

    for pattern in _SAFETY_EXFILTRATION_PATTERNS:
        if pattern.search(scanned):
            categories.add("data_exfiltration")
            break

    return sorted(categories)


def _emit_safety_event(stage: str, source: str, category: str) -> None:
    _emit_metric(
        "ChatbotSafetyEventCount",
        1,
        dimensions={
            "Route": "query",
            "Method": "POST",
            "Stage": stage,
            "Source": source,
            "Category": category,
        },
    )


def _emit_sensitive_store_skip(target: str) -> None:
    _emit_metric(
        "ChatbotSensitiveStoreSkippedCount",
        1,
        dimensions={"Route": "query", "Method": "POST", "Target": target},
    )


def _contains_sensitive_storage_content(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False

    scanned = text[: _safety_scan_char_limit()]
    for pattern in _SENSITIVE_STORE_PATTERNS:
        if pattern.search(scanned):
            return True
    return False


def _enforce_prompt_safety(query: str, local_logger: Any) -> None:
    if not _prompt_safety_enabled():
        return

    categories = _detect_safety_categories(query)
    if not categories:
        return

    for category in categories:
        _emit_safety_event("user_input", "query", category)

    local_logger.warning(
        "chatbot_prompt_safety_rejected",
        extra={"extra": {"categories": categories}},
    )
    if "data_exfiltration" in categories:
        raise ValueError("data_exfiltration_attempt")
    raise ValueError("unsafe_prompt_detected")


def _sanitize_context_items(source: str, items: list[dict[str, Any]], local_logger: Any) -> tuple[list[dict[str, Any]], int]:
    if not _prompt_safety_enabled():
        return items, 0

    filtered: list[dict[str, Any]] = []
    blocked = 0
    for item in items:
        categories = _detect_safety_categories(_extract_context_text(source, item))
        if not categories:
            filtered.append(item)
            continue

        blocked += 1
        for category in categories:
            _emit_safety_event("retrieved_context", source, category)
        local_logger.warning(
            "chatbot_context_item_blocked",
            extra={"extra": {"source": source, "categories": categories}},
        )
        if _context_safety_block_request():
            if "data_exfiltration" in categories:
                raise ValueError("data_exfiltration_attempt")
            raise ValueError("unsafe_context_detected")

    return filtered, blocked


def _tokenize_for_rerank(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]{2,}", str(value or "").lower())}


def _rerank_context_items(query: str, source: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _rerank_enabled() or len(items) <= 1:
        return items

    query_terms = _tokenize_for_rerank(query)
    if not query_terms:
        return items[: _rerank_top_k_per_source()]

    scored: list[tuple[float, int, dict[str, Any]]] = []
    for idx, item in enumerate(items):
        text = _extract_context_text(source, item)
        item_terms = _tokenize_for_rerank(text)
        overlap = len(query_terms & item_terms)
        phrase_hits = 1 if str(query or "").strip().lower() in str(text).lower() else 0
        score = (overlap * 10.0) + (phrase_hits * 3.0)
        scored.append((score, -idx, item))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    top_k = _rerank_top_k_per_source()
    return [item for _score, _idx, item in scored[:top_k]]


def _load_model_pricing() -> dict[str, dict[str, float]]:
    raw = (os.getenv("CHATBOT_MODEL_PRICING_JSON", "") or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("chatbot_model_pricing_json_invalid")
        return {}

    pricing: dict[str, dict[str, float]] = {}
    if not isinstance(payload, dict):
        return pricing

    for model_id, row in payload.items():
        if not isinstance(row, dict):
            continue
        try:
            input_per_1k = float(row.get("input_per_1k") or row.get("input") or 0.0)
            output_per_1k = float(row.get("output_per_1k") or row.get("output") or 0.0)
        except (TypeError, ValueError):
            continue
        pricing[str(model_id)] = {
            "input_per_1k": max(0.0, input_per_1k),
            "output_per_1k": max(0.0, output_per_1k),
        }
    return pricing


def _estimate_cost_usd(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _load_model_pricing().get(model_id, {})
    input_price = float(pricing.get("input_per_1k") or 0.0)
    output_price = float(pricing.get("output_per_1k") or 0.0)
    return ((prompt_tokens / 1000.0) * input_price) + ((completion_tokens / 1000.0) * output_price)


def _load_budget_state(actor_id: str, conversation_id: str | None) -> dict[str, Any]:
    state = {
        "enabled": _budgets_enabled(),
        "tracked": False,
        "spent_usd": 0.0,
        "request_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }
    if not _budgets_enabled():
        return state

    table = _budget_table()
    if not table:
        return state

    key = _budget_storage_key(actor_id, conversation_id)
    try:
        resp = _dynamodb_client().get_item(
            TableName=table,
            Key={
                "conversation_id": {"S": key},
                "timestamp_ms": {"N": "0"},
            },
            ConsistentRead=False,
        )
    except Exception:
        logger.warning("chat_budget_read_failed", extra={"extra": {"conversation_id": key}})
        return state

    item = resp.get("Item") or {}
    if not item:
        return state

    state["tracked"] = True
    try:
        state["spent_usd"] = float(str((item.get("cost_usd") or {}).get("N") or "0"))
        state["request_count"] = int(str((item.get("request_count") or {}).get("N") or "0"))
        state["input_tokens"] = int(str((item.get("input_tokens") or {}).get("N") or "0"))
        state["output_tokens"] = int(str((item.get("output_tokens") or {}).get("N") or "0"))
    except ValueError:
        pass
    return state


def _record_budget_usage(
    *,
    actor_id: str,
    conversation_id: str | None,
    model_id: str,
    routing_reason: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost_usd: float,
) -> None:
    if not _budgets_enabled():
        return

    table = _budget_table()
    if not table:
        return

    key = _budget_storage_key(actor_id, conversation_id)
    now_ms = int(time.time() * 1000)
    expires_at = int(time.time()) + (_budget_ttl_days() * 24 * 60 * 60)
    payload = {
        "updated_at_ms": now_ms,
        "last_model_id": model_id,
        "last_route_reason": routing_reason,
        "last_prompt_tokens": prompt_tokens,
        "last_completion_tokens": completion_tokens,
        "last_estimated_cost_usd": round(estimated_cost_usd, 8),
    }

    try:
        _dynamodb_client().update_item(
            TableName=table,
            Key={
                "conversation_id": {"S": key},
                "timestamp_ms": {"N": "0"},
            },
            UpdateExpression=(
                "SET #role = :role, #content = :content, #expires_at = :expires_at "
                "ADD #request_count :request_count, #input_tokens :input_tokens, "
                "#output_tokens :output_tokens, #cost_usd :cost_usd"
            ),
            ExpressionAttributeNames={
                "#role": "role",
                "#content": "content",
                "#expires_at": "expires_at",
                "#request_count": "request_count",
                "#input_tokens": "input_tokens",
                "#output_tokens": "output_tokens",
                "#cost_usd": "cost_usd",
            },
            ExpressionAttributeValues={
                ":role": {"S": "budget"},
                ":content": {"S": json.dumps(payload, ensure_ascii=True)},
                ":expires_at": {"N": str(expires_at)},
                ":request_count": {"N": "1"},
                ":input_tokens": {"N": str(max(0, prompt_tokens))},
                ":output_tokens": {"N": str(max(0, completion_tokens))},
                ":cost_usd": {"N": f"{max(0.0, estimated_cost_usd):.8f}"},
            },
        )
    except Exception:
        logger.warning("chat_budget_write_failed", extra={"extra": {"conversation_id": key}})


def _is_model_allowed(provider: str, model_id: str) -> bool:
    try:
        _validate_model_policy(provider, model_id)
    except ValueError:
        return False
    return True


def _route_model_with_budget(
    provider: str,
    initial_model_id: str,
    query: str,
    actor_id: str,
    conversation_id: str | None,
) -> tuple[str, dict[str, Any]]:
    high_quality_model = _router_high_quality_model(provider, initial_model_id)
    routed_model = initial_model_id
    low_cost_model = _router_low_cost_model(provider)
    complexity = _query_complexity(query)
    budget_state = _load_budget_state(actor_id, conversation_id)
    soft_limit = _budget_soft_limit_usd()
    hard_limit = _budget_hard_limit_usd()

    reason = "default"
    if high_quality_model != initial_model_id:
        if _is_model_allowed(provider, high_quality_model):
            routed_model = high_quality_model
        else:
            reason = "high_quality_model_not_allowed"

    if budget_state["enabled"] and budget_state["spent_usd"] >= hard_limit:
        raise ValueError("conversation_budget_exceeded")

    if low_cost_model and _is_model_allowed(provider, low_cost_model):
        if budget_state["enabled"] and budget_state["spent_usd"] >= soft_limit:
            routed_model = low_cost_model
            reason = "budget_soft_limit"
        elif complexity == "low":
            routed_model = low_cost_model
            reason = "low_complexity"
        else:
            reason = "high_complexity"
    elif low_cost_model:
        reason = "low_cost_model_not_allowed"

    _emit_metric(
        "ChatbotModelRouteCount",
        1,
        dimensions={
            "Route": "query",
            "Method": "POST",
            "Provider": provider,
            "Reason": reason,
        },
    )

    return routed_model, {
        "enabled": bool(budget_state.get("enabled")),
        "tracked": bool(budget_state.get("tracked")),
        "spent_usd": round(float(budget_state.get("spent_usd") or 0.0), 8),
        "soft_limit_usd": soft_limit,
        "hard_limit_usd": hard_limit,
        "request_count": int(budget_state.get("request_count") or 0),
        "complexity": complexity,
        "route_reason": reason,
        "requested_model_id": initial_model_id,
        "model_id": routed_model,
    }


def _response_cache_enabled() -> bool:
    return os.getenv("CHATBOT_RESPONSE_CACHE_ENABLED", "false").strip().lower() == "true"


def _response_cache_table() -> str:
    explicit = os.getenv("CHATBOT_RESPONSE_CACHE_TABLE", "").strip()
    if explicit:
        return explicit
    return _chat_memory_table()


def _response_cache_ttl_seconds() -> int:
    return max(30, int(os.getenv("CHATBOT_RESPONSE_CACHE_TTL_SECONDS", "300")))


def _response_cache_min_query_length() -> int:
    return max(1, int(os.getenv("CHATBOT_RESPONSE_CACHE_MIN_QUERY_LENGTH", "12")))


def _response_cache_max_answer_chars() -> int:
    return max(200, int(os.getenv("CHATBOT_RESPONSE_CACHE_MAX_ANSWER_CHARS", "16000")))


def _response_cache_stopwords() -> set[str]:
    return {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "with",
        "you",
        "your",
    }


def _normalize_cache_token(value: str) -> str:
    token = str(value or "").strip().lower()
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        token = token[:-1]
    return token


def _semantic_query_signature(query: str) -> str:
    raw_tokens = [_normalize_cache_token(tok) for tok in re.findall(r"[a-z0-9_]{2,}", str(query or "").lower())]
    stopwords = _response_cache_stopwords()
    filtered = [tok for tok in raw_tokens if tok not in stopwords]
    selected = sorted(set(filtered or raw_tokens))
    return " ".join(selected[:32]).strip()


def _response_cache_key(
    *,
    query: str,
    assistant_mode: str,
    retrieval_mode: str,
    provider: str,
    model_id: str,
    conversation_id: str | None,
    history_text: str,
    jira_jql: str,
    confluence_cql: str,
) -> str:
    payload = {
        "v": 1,
        "query_semantic": _semantic_query_signature(query),
        "assistant_mode": assistant_mode,
        "retrieval_mode": retrieval_mode,
        "provider": provider,
        "model_id": model_id,
        "conversation_id": conversation_id or "",
        "history_digest": hashlib.sha256(history_text.encode("utf-8")).hexdigest()[:16] if history_text else "",
        "jira_jql": jira_jql if assistant_mode == "contextual" else "",
        "confluence_cql": confluence_cql if assistant_mode == "contextual" else "",
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _response_cache_partition_key(actor_id: str, cache_key: str) -> str:
    return f"resp_cache#{actor_id}#{cache_key}"


def _load_cached_response(actor_id: str, cache_key: str) -> dict[str, Any] | None:
    if not _response_cache_enabled():
        return None

    table = _response_cache_table()
    if not table:
        return None

    partition_key = _response_cache_partition_key(actor_id, cache_key)
    try:
        resp = _dynamodb_client().get_item(
            TableName=table,
            Key={
                "conversation_id": {"S": partition_key},
                "timestamp_ms": {"N": "0"},
            },
            ConsistentRead=False,
        )
    except Exception:
        logger.warning("chat_response_cache_read_failed", extra={"extra": {"conversation_id": partition_key}})
        return None

    item = resp.get("Item") or {}
    if not item:
        return None

    try:
        expires_at = int(str((item.get("expires_at") or {}).get("N") or "0"))
    except ValueError:
        expires_at = 0
    if expires_at and expires_at <= int(time.time()):
        return None

    content = str((item.get("content") or {}).get("S") or "").strip()
    if not content:
        return None

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    answer = str(payload.get("answer") or "").strip()
    if not answer:
        return None

    sources = payload.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    citations = payload.get("citations")
    if not isinstance(citations, list):
        citations = []

    return {
        "answer": answer,
        "sources": sources,
        "citations": citations,
        "stored_at_ms": int(payload.get("stored_at_ms") or 0),
    }


def _store_cached_response(actor_id: str, cache_key: str, payload: dict[str, Any]) -> bool:
    if not _response_cache_enabled():
        return False

    table = _response_cache_table()
    if not table:
        return False

    answer = str(payload.get("answer") or "").strip()
    if not answer or len(answer) > _response_cache_max_answer_chars():
        return False

    sources = payload.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    citations = payload.get("citations")
    if not isinstance(citations, list):
        citations = []
    sensitivity_probe = json.dumps(
        {"answer": answer, "citations": citations},
        ensure_ascii=True,
    )
    if _contains_sensitive_storage_content(sensitivity_probe):
        _emit_sensitive_store_skip("response_cache")
        return False

    now_ms = int(time.time() * 1000)
    expires_at = int(time.time()) + _response_cache_ttl_seconds()
    record = {
        "answer": answer,
        "sources": sources,
        "citations": citations,
        "stored_at_ms": now_ms,
    }
    partition_key = _response_cache_partition_key(actor_id, cache_key)

    try:
        _dynamodb_client().put_item(
            TableName=table,
            Item={
                "conversation_id": {"S": partition_key},
                "timestamp_ms": {"N": "0"},
                "role": {"S": "response_cache"},
                "content": {"S": json.dumps(record, ensure_ascii=True)},
                "expires_at": {"N": str(expires_at)},
            },
        )
    except Exception:
        logger.warning("chat_response_cache_write_failed", extra={"extra": {"conversation_id": partition_key}})
        return False

    _emit_metric("ChatbotCacheStoreCount", 1, dimensions={"Route": "query", "Method": "POST"})
    return True


def _response_cache_lock_ttl_seconds() -> int:
    return max(5, min(60, int(os.getenv("CHATBOT_RESPONSE_CACHE_LOCK_TTL_SECONDS", "15"))))


def _response_cache_lock_wait_ms() -> int:
    return max(50, min(1000, int(os.getenv("CHATBOT_RESPONSE_CACHE_LOCK_WAIT_MS", "150"))))


def _response_cache_lock_wait_attempts() -> int:
    return max(1, min(20, int(os.getenv("CHATBOT_RESPONSE_CACHE_LOCK_WAIT_ATTEMPTS", "6"))))


def _response_cache_lock_partition_key(actor_id: str, cache_key: str) -> str:
    return f"resp_cache_lock#{actor_id}#{cache_key}"


def _is_conditional_check_failed(error: Exception) -> bool:
    code = str((((getattr(error, "response", {}) or {}).get("Error") or {}).get("Code") or ""))
    return code == "ConditionalCheckFailedException"


def _acquire_response_cache_lock(actor_id: str, cache_key: str) -> bool:
    if not _response_cache_enabled():
        return False

    table = _response_cache_table()
    if not table:
        return False

    now = int(time.time())
    expires_at = now + _response_cache_lock_ttl_seconds()
    lock_key = _response_cache_lock_partition_key(actor_id, cache_key)
    try:
        _dynamodb_client().put_item(
            TableName=table,
            Item={
                "conversation_id": {"S": lock_key},
                "timestamp_ms": {"N": "0"},
                "role": {"S": "response_cache_lock"},
                "content": {"S": "1"},
                "expires_at": {"N": str(expires_at)},
            },
            ConditionExpression="attribute_not_exists(conversation_id) OR expires_at < :now",
            ExpressionAttributeValues={
                ":now": {"N": str(now)},
            },
        )
        return True
    except Exception as exc:
        if _is_conditional_check_failed(exc):
            return False
        logger.warning("chat_response_cache_lock_failed", extra={"extra": {"conversation_id": lock_key}})
        return False


def _release_response_cache_lock(actor_id: str, cache_key: str) -> None:
    table = _response_cache_table()
    if not table:
        return

    lock_key = _response_cache_lock_partition_key(actor_id, cache_key)
    try:
        _dynamodb_client().delete_item(
            TableName=table,
            Key={
                "conversation_id": {"S": lock_key},
                "timestamp_ms": {"N": "0"},
            },
        )
    except Exception:
        logger.warning("chat_response_cache_lock_release_failed", extra={"extra": {"conversation_id": lock_key}})


def _record_quota_event_and_validate(bucket_key: str, limit: int) -> None:
    if not _chat_memory_enabled():
        return

    table = _chat_memory_table()
    if not table:
        return

    now_ms = int(time.time() * 1000)
    minute_bucket_ms = (now_ms // 60_000) * 60_000
    expires_at = int(time.time()) + 2 * 24 * 60 * 60

    client = _dynamodb_client()
    try:
        client.update_item(
            TableName=table,
            Key={
                "conversation_id": {"S": bucket_key},
                "timestamp_ms": {"N": str(minute_bucket_ms)},
            },
            UpdateExpression=(
                "SET #role = :role, #content = :content, #expires_at = :expires_at "
                "ADD #request_count :inc"
            ),
            ConditionExpression="attribute_not_exists(#request_count) OR #request_count < :limit",
            ExpressionAttributeNames={
                "#role": "role",
                "#content": "content",
                "#expires_at": "expires_at",
                "#request_count": "request_count",
            },
            ExpressionAttributeValues={
                ":role": {"S": "quota_counter"},
                ":content": {"S": "1"},
                ":expires_at": {"N": str(expires_at)},
                ":inc": {"N": "1"},
                ":limit": {"N": str(max(1, limit))},
            },
        )
    except Exception as exc:
        if _is_conditional_check_failed(exc):
            raise ValueError("rate_limit_exceeded")
        _emit_metric(
            "ChatbotQuotaBackendErrorCount",
            1,
            dimensions={"BucketPrefix": bucket_key.split("#", 1)[0] if "#" in bucket_key else bucket_key},
        )
        logger.warning("chat_quota_check_failed", extra={"extra": {"bucket_key": bucket_key}})
        if not _quota_fail_open():
            raise ValueError("quota_backend_unavailable")


def _enforce_rate_quotas(actor_id: str, conversation_id: str | None) -> None:
    conv = conversation_id or "default"
    _record_quota_event_and_validate(
        bucket_key=f"quota_user#{actor_id}",
        limit=_user_requests_per_minute_limit(),
    )
    _record_quota_event_and_validate(
        bucket_key=f"quota_conv#{actor_id}#{conv}",
        limit=_conversation_requests_per_minute_limit(),
    )


def _enforce_image_rate_quotas(actor_id: str, conversation_id: str | None) -> None:
    conv = conversation_id or "default"
    _record_quota_event_and_validate(
        bucket_key=f"quota_img_user#{actor_id}",
        limit=_image_user_requests_per_minute_limit(),
    )
    _record_quota_event_and_validate(
        bucket_key=f"quota_img_conv#{actor_id}#{conv}",
        limit=_image_conversation_requests_per_minute_limit(),
    )


def _enforce_image_prompt_policy(prompt: str) -> None:
    if not _image_safety_enabled():
        return

    normalized_prompt = prompt.lower()
    for banned in _image_banned_terms():
        if banned in normalized_prompt:
            raise ValueError("image_prompt_blocked")


def _summarize_history(history: list[dict[str, str]], max_items: int = 10) -> str:
    if not history:
        return ""

    rows: list[str] = []
    for item in history[:max_items]:
        role = "U" if item.get("role") == "user" else "A"
        snippet = str(item.get("content") or "").strip().replace("\n", " ")
        rows.append(f"- {role}: {snippet[:160]}")

    return "Conversation summary:\n" + "\n".join(rows)


def _track_conversation_index(actor_id: str, conversation_id: str) -> None:
    if not _chat_memory_enabled():
        return

    table = _chat_memory_table()
    if not table:
        return

    now_ms = int(time.time() * 1000)
    expires_at = int(time.time()) + 60 * 24 * 60 * 60
    client = _dynamodb_client()

    try:
        client.put_item(
            TableName=table,
            Item={
                "conversation_id": {"S": f"conv_index#{actor_id}"},
                "timestamp_ms": {"N": str(now_ms)},
                "role": {"S": "index"},
                "content": {"S": conversation_id},
                "expires_at": {"N": str(expires_at)},
            },
        )
    except Exception:
        logger.warning("chat_memory_index_write_failed", extra={"extra": {"actor_id": actor_id}})


def _ws_client(event: dict[str, Any]) -> Any:
    request_context = event.get("requestContext") or {}
    domain_name = str(request_context.get("domainName") or "").strip()
    stage = str(request_context.get("stage") or "").strip()
    if not domain_name or not stage:
        raise ValueError("websocket_context_missing")

    endpoint = f"https://{domain_name}/{stage}"
    return boto3.client(
        "apigatewaymanagementapi",
        endpoint_url=endpoint,
        region_name=os.getenv("AWS_REGION", DEFAULT_REGION),
    )


def _ws_send(event: dict[str, Any], connection_id: str, payload: dict[str, Any]) -> None:
    try:
        client = _ws_client(event)
        client.post_to_connection(ConnectionId=connection_id, Data=json.dumps(payload).encode("utf-8"))
    except Exception:
        logger.warning("chatbot_websocket_send_failed", extra={"extra": {"connection_id": connection_id}})


def _load_conversation_history(actor_id: str, conversation_id: str | None) -> list[dict[str, str]]:
    if not conversation_id or not _chat_memory_enabled():
        return []

    table = _chat_memory_table()
    if not table:
        return []

    conversation_key = _conversation_storage_key(actor_id, conversation_id)

    max_turns = max(1, int(os.getenv("CHATBOT_MEMORY_MAX_TURNS", "6")))
    client = _dynamodb_client()
    try:
        resp = client.query(
            TableName=table,
            KeyConditionExpression="conversation_id = :cid",
            ExpressionAttributeValues={":cid": {"S": conversation_key}},
            ScanIndexForward=False,
            Limit=max_turns * 2,
        )
    except Exception:
        logger.warning("chat_memory_read_failed", extra={"extra": {"conversation_id": conversation_key}})
        return []

    items = list(resp.get("Items") or [])
    items.reverse()

    history: list[dict[str, str]] = []
    for item in items:
        role = str((item.get("role") or {}).get("S") or "").strip().lower()
        content = str((item.get("content") or {}).get("S") or "").strip()
        if role == "summary" and content:
            history.append({"role": "assistant", "content": f"[Conversation Summary]\n{content}"})
            continue
        if role not in {"user", "assistant"} or not content:
            continue
        history.append({"role": role, "content": content})

    return history[-(max_turns * 2) :]


def _append_conversation_turn(actor_id: str, conversation_id: str | None, user_query: str, answer: str) -> None:
    if not conversation_id or not _chat_memory_enabled():
        return

    if _contains_sensitive_storage_content(user_query) or _contains_sensitive_storage_content(answer):
        _emit_sensitive_store_skip("memory")
        logger.info(
            "chat_memory_store_skipped_sensitive",
            extra={"extra": {"conversation_id": conversation_id, "actor_id": actor_id}},
        )
        return

    table = _chat_memory_table()
    if not table:
        return

    conversation_key = _conversation_storage_key(actor_id, conversation_id)

    ttl_days = max(1, int(os.getenv("CHATBOT_MEMORY_TTL_DAYS", "30")))
    now_ms = int(time.time() * 1000)
    expires_at = int(time.time()) + (ttl_days * 24 * 60 * 60)
    client = _dynamodb_client()

    # Best-effort compaction summary for large histories.
    history = _load_conversation_history(actor_id, conversation_id)
    total_chars = sum(len(str(item.get("content") or "")) for item in history)
    if total_chars > _memory_compaction_chars():
        summary = _summarize_history(history)
        try:
            client.put_item(
                TableName=table,
                Item={
                    "conversation_id": {"S": conversation_key},
                    "timestamp_ms": {"N": str(now_ms - 1)},
                    "role": {"S": "summary"},
                    "content": {"S": summary},
                    "expires_at": {"N": str(expires_at)},
                },
            )
        except Exception:
            logger.warning("chat_memory_compaction_failed", extra={"extra": {"conversation_id": conversation_key}})

    try:
        client.put_item(
            TableName=table,
            Item={
                "conversation_id": {"S": conversation_key},
                "timestamp_ms": {"N": str(now_ms)},
                "role": {"S": "user"},
                "content": {"S": user_query},
                "expires_at": {"N": str(expires_at)},
            },
        )
        client.put_item(
            TableName=table,
            Item={
                "conversation_id": {"S": conversation_key},
                "timestamp_ms": {"N": str(now_ms + 1)},
                "role": {"S": "assistant"},
                "content": {"S": answer},
                "expires_at": {"N": str(expires_at)},
            },
        )
        _track_conversation_index(actor_id, conversation_id)
    except Exception:
        logger.warning("chat_memory_write_failed", extra={"extra": {"conversation_id": conversation_key}})


def _delete_partition_items(partition_key: str) -> int:
    table = _chat_memory_table()
    if not table:
        return 0

    client = _dynamodb_client()
    deleted = 0

    try:
        resp = client.query(
            TableName=table,
            KeyConditionExpression="conversation_id = :cid",
            ExpressionAttributeValues={":cid": {"S": partition_key}},
            ProjectionExpression="conversation_id, timestamp_ms",
        )
        for item in (resp.get("Items") or []):
            client.delete_item(
                TableName=table,
                Key={
                    "conversation_id": item["conversation_id"],
                    "timestamp_ms": item["timestamp_ms"],
                },
            )
            deleted += 1
    except Exception:
        logger.warning("chat_memory_delete_failed", extra={"extra": {"conversation_id": partition_key}})

    return deleted


def _clear_conversation_memory(actor_id: str, conversation_id: str) -> int:
    return _delete_partition_items(_conversation_storage_key(actor_id, conversation_id))


def _list_actor_conversations(actor_id: str) -> list[str]:
    table = _chat_memory_table()
    if not table:
        return []

    client = _dynamodb_client()
    seen: set[str] = set()
    ordered: list[str] = []
    try:
        resp = client.query(
            TableName=table,
            KeyConditionExpression="conversation_id = :cid",
            ExpressionAttributeValues={":cid": {"S": f"conv_index#{actor_id}"}},
            ScanIndexForward=False,
            Limit=200,
        )
        for item in (resp.get("Items") or []):
            conv_id = str((item.get("content") or {}).get("S") or "").strip()
            if conv_id and conv_id not in seen:
                seen.add(conv_id)
                ordered.append(conv_id)
    except Exception:
        logger.warning("chat_memory_index_read_failed", extra={"extra": {"actor_id": actor_id}})

    return ordered


def _clear_all_memory_for_actor(actor_id: str) -> int:
    deleted = 0
    for conv_id in _list_actor_conversations(actor_id):
        deleted += _clear_conversation_memory(actor_id, conv_id)
    deleted += _delete_partition_items(f"conv_index#{actor_id}")
    return deleted


def _format_history_for_prompt(history: list[dict[str, str]]) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for item in history:
        role = "User" if item.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {item.get('content', '')}")
    return "\n".join(lines)


def _chunk_text(value: str, chunk_chars: int) -> list[str]:
    size = max(20, min(chunk_chars, 1000))
    if not value:
        return []
    return [value[i : i + size] for i in range(0, len(value), size)]


def _extract_image_b64_payloads(payload: Any) -> list[str]:
    if isinstance(payload, list):
        out: list[str] = []
        for item in payload:
            out.extend(_extract_image_b64_payloads(item))
        return out

    if isinstance(payload, dict):
        out: list[str] = []
        for key in ("images", "artifacts", "output", "results", "result"):
            if key in payload:
                out.extend(_extract_image_b64_payloads(payload.get(key)))
        for key in ("base64", "b64", "image", "imageBase64", "bytes"):
            raw = payload.get(key)
            if isinstance(raw, str) and raw.strip():
                out.append(raw.strip())
        return out

    if isinstance(payload, str) and payload.strip():
        return [payload.strip()]

    return []


def _generate_image(prompt: str, model_id: str | None = None, size: str | None = None) -> dict[str, Any]:
    chosen_model = (model_id or "").strip() or os.getenv("CHATBOT_IMAGE_MODEL_ID", "amazon.nova-canvas-v1:0")

    chosen_size = (size or os.getenv("CHATBOT_IMAGE_SIZE", "1024x1024")).strip().lower()
    width = 1024
    height = 1024
    if "x" in chosen_size:
        try:
            raw_w, raw_h = chosen_size.split("x", 1)
            width = max(256, min(int(raw_w), 2048))
            height = max(256, min(int(raw_h), 2048))
        except Exception:
            width, height = 1024, 1024

    runtime = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", DEFAULT_REGION))
    payload = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": prompt},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "quality": "standard",
            "width": width,
            "height": height,
        },
    }
    resp = runtime.invoke_model(
        modelId=chosen_model,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(payload).encode("utf-8"),
    )

    raw_body = resp.get("body")
    decoded = raw_body.read() if hasattr(raw_body, "read") else raw_body
    body = json.loads(decoded or "{}")
    images = _extract_image_b64_payloads(body)
    if not images:
        raise ValueError("image_generation_failed")

    return {
        "images": images,
        "count": len(images),
        "model_id": chosen_model,
        "size": f"{width}x{height}",
    }


def _answer_with_provider(
    provider: str,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    stream_callback: Callable[[str], None] | None = None,
    telemetry: dict[str, Any] | None = None,
) -> str:
    _validate_model_policy(provider, model_id)
    if telemetry is not None:
        telemetry["provider"] = provider
        telemetry["model_id"] = model_id

    if provider == "anthropic_direct":
        enabled = os.getenv("CHATBOT_ENABLE_ANTHROPIC_DIRECT", "false").strip().lower() == "true"
        if not enabled:
            raise ValueError("anthropic_direct_disabled")

        api_key = _load_anthropic_api_key()
        if not api_key:
            raise ValueError("anthropic_api_key_missing")

        client = AnthropicChatClient(
            api_key=api_key,
            model_id=model_id,
            api_base=os.getenv("CHATBOT_ANTHROPIC_API_BASE", "https://api.anthropic.com"),
            max_tokens=int(os.getenv("CHATBOT_MAX_TOKENS", "1200")),
        )
        if telemetry is not None:
            telemetry["guardrail_configured"] = False
        if stream_callback is None:
            return client.answer(system_prompt=system_prompt, user_prompt=user_prompt)
        return client.stream_answer(system_prompt=system_prompt, user_prompt=user_prompt, on_delta=stream_callback)

    guardrail_identifier = (os.getenv("CHATBOT_GUARDRAIL_ID") or os.getenv("BEDROCK_GUARDRAIL_ID") or "").strip()
    guardrail_version = (os.getenv("CHATBOT_GUARDRAIL_VERSION") or os.getenv("BEDROCK_GUARDRAIL_VERSION") or "").strip()
    guardrail_trace = (os.getenv("CHATBOT_GUARDRAIL_TRACE") or "").strip()
    guardrail_configured = bool(guardrail_identifier and guardrail_version)
    if telemetry is not None:
        telemetry["guardrail_configured"] = guardrail_configured
    client = BedrockChatClient(
        region=os.getenv("AWS_REGION", DEFAULT_REGION),
        model_id=model_id,
        guardrail_identifier=guardrail_identifier or None,
        guardrail_version=guardrail_version or None,
        guardrail_trace=guardrail_trace or None,
    )
    if stream_callback is None:
        return client.answer(system_prompt=system_prompt, user_prompt=user_prompt, telemetry=telemetry)
    return client.stream_answer(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        on_delta=stream_callback,
        telemetry=telemetry,
    )


def _request_path(event: dict[str, Any]) -> str:
    return (
        str(event.get("rawPath") or "").strip()
        or str(event.get("requestContext", {}).get("http", {}).get("path") or "").strip()
    )


def _list_bedrock_models(region: str) -> list[dict[str, Any]]:
    control = boto3.client("bedrock", region_name=region)
    resp = control.list_foundation_models(byOutputModality="TEXT")
    summaries = resp.get("modelSummaries") or []

    allowlist = _allowed_bedrock_model_ids()
    models: list[dict[str, Any]] = []
    for item in summaries:
        model_id = str(item.get("modelId") or "").strip()
        if not model_id:
            continue

        if allowlist and model_id not in allowlist:
            continue

        lifecycle = item.get("modelLifecycle") or {}
        if str(lifecycle.get("status") or "").upper() != "ACTIVE":
            continue

        models.append(
            {
                "model_id": model_id,
                "name": str(item.get("modelName") or model_id),
                "provider": str(item.get("providerName") or "unknown"),
                "inference_types": [str(x) for x in (item.get("inferenceTypesSupported") or [])],
                "output_modalities": [str(x) for x in (item.get("outputModalities") or [])],
            }
        )

    models.sort(key=lambda m: (m["provider"].lower(), m["name"].lower(), m["model_id"].lower()))
    return models


def _truncate_for_budget(value: str, max_chars: int) -> str:
    text = str(value or "")
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _apply_context_budget(context_blob: dict[str, str]) -> tuple[dict[str, str], dict[str, Any]]:
    per_source_limit = _context_max_chars_per_source()
    total_limit = _context_max_total_chars()
    ordered_sources = ("knowledge_base", "jira", "confluence", "github")

    trimmed: dict[str, str] = {}
    trimmed_chars_by_source: dict[str, int] = {}
    total_used = 0

    for source in ordered_sources:
        original = str(context_blob.get(source) or "")
        step = _truncate_for_budget(original, per_source_limit)
        remaining = max(0, total_limit - total_used)
        final = _truncate_for_budget(step, remaining) if remaining else ""
        trimmed[source] = final
        trimmed_chars_by_source[source] = max(0, len(original) - len(final))
        total_used += len(final)

    metadata = {
        "per_source_limit": per_source_limit,
        "total_limit": total_limit,
        "total_used_chars": total_used,
        "total_trimmed_chars": sum(trimmed_chars_by_source.values()),
        "trimmed_chars_by_source": trimmed_chars_by_source,
    }
    return trimmed, metadata


def _format_jira(issues: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for issue in issues:
        key = issue.get("key", "UNKNOWN")
        fields = issue.get("fields", {})
        summary = fields.get("summary", "")
        status = (fields.get("status") or {}).get("name", "")
        rows.append(f"- {key}: {summary} (status={status})")
    return "\n".join(rows) if rows else "No Jira issues found."


def _format_confluence(results: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in results:
        title = item.get("title") or (item.get("content") or {}).get("title") or "Untitled"
        url = (item.get("url") or item.get("_links", {}).get("webui") or "")
        rows.append(f"- {title} {url}".strip())
    return "\n".join(rows) if rows else "No Confluence pages found."


def _format_kb(results: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in results:
        title = item.get("title") or "Untitled"
        uri = item.get("uri") or ""
        text = str(item.get("text") or "").strip()
        snippet = text[:400] + ("..." if len(text) > 400 else "")
        rows.append(f"- {title} {uri}\n  {snippet}".strip())
    return "\n".join(rows) if rows else "No Knowledge Base passages found."


def _normalize_retrieval_mode(value: str | None) -> str:
    mode = (value or "hybrid").strip().lower()
    if mode not in ALLOWED_RETRIEVAL_MODES:
        return "hybrid"
    return mode


def _parse_repo_slug(value: str) -> tuple[str, str] | None:
    owner_repo = [part.strip() for part in value.split("/", 1)]
    if len(owner_repo) != 2 or not owner_repo[0] or not owner_repo[1]:
        return None
    return owner_repo[0], owner_repo[1]


def _format_github(results: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in results:
        repo = str(item.get("repo") or "")
        path = str(item.get("path") or "")
        url = str(item.get("url") or "")
        text = str(item.get("text") or "").strip()
        snippet = text[:400] + ("..." if len(text) > 400 else "")
        title = Path(path).name if path else "file"
        rows.append(f"- {repo}:{path} ({title}) {url}\n  {snippet}".strip())
    return "\n".join(rows) if rows else "No GitHub code/doc snippets found."


def _github_live_enabled() -> bool:
    return os.getenv("GITHUB_CHAT_LIVE_ENABLED", "false").strip().lower() == "true"


def _load_github_context(query: str, local_logger: Any) -> list[dict[str, Any]]:
    if not _github_live_enabled():
        return []

    repos_raw = os.getenv("GITHUB_CHAT_REPOS", "")
    repos = [slug.strip() for slug in repos_raw.split(",") if slug.strip()]
    if not repos:
        return []

    app_ids_secret = os.getenv("GITHUB_APP_IDS_SECRET_ARN", "").strip()
    key_secret = os.getenv("GITHUB_APP_PRIVATE_KEY_SECRET_ARN", "").strip()
    if not app_ids_secret or not key_secret:
        local_logger.warning("github_live_missing_secrets")
        return []

    max_results = max(1, int(os.getenv("GITHUB_CHAT_MAX_RESULTS", "3")))
    api_base = os.getenv("GITHUB_API_BASE", "https://api.github.com")

    auth = GitHubAppAuth(
        app_ids_secret_arn=app_ids_secret,
        private_key_secret_arn=key_secret,
        api_base=api_base,
    )
    gh = GitHubClient(token_provider=auth.get_installation_token, api_base=api_base)

    collected: list[dict[str, Any]] = []
    for slug in repos:
        parsed = _parse_repo_slug(slug)
        if not parsed:
            continue
        owner, repo = parsed
        try:
            items = gh.search_code(f"{query} repo:{owner}/{repo}", per_page=max_results)
            for item in items:
                path = str(item.get("path") or "").strip()
                if not path:
                    continue
                repo_obj = item.get("repository") or {}
                default_ref = str(repo_obj.get("default_branch") or "main")
                full_name = str(repo_obj.get("full_name") or f"{owner}/{repo}")

                text, _sha = gh.get_file_contents(owner, repo, path, default_ref)
                collected.append(
                    {
                        "repo": full_name,
                        "path": path,
                        "url": str(item.get("html_url") or ""),
                        "text": text,
                    }
                )
                if len(collected) >= max_results:
                    return collected
        except Exception:
            local_logger.warning("github_live_lookup_failed", extra={"extra": {"repo": slug}})

    return collected


def _citation_max_items() -> int:
    return max(1, min(12, int(os.getenv("CHATBOT_CITATION_MAX_ITEMS", "6"))))


def _append_citations_to_answer() -> bool:
    return os.getenv("CHATBOT_APPEND_CITATIONS", "true").strip().lower() == "true"


def _build_citations(
    jira_items: list[dict[str, Any]],
    conf_items: list[dict[str, Any]],
    kb_items: list[dict[str, Any]],
    github_items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(source: str, title: str, locator: str) -> None:
        normalized_title = str(title or "").strip() or "Untitled"
        normalized_locator = str(locator or "").strip()
        key = (source, normalized_title, normalized_locator)
        if key in seen:
            return
        seen.add(key)
        item: dict[str, str] = {
            "source": source,
            "title": normalized_title,
        }
        if normalized_locator:
            item["locator"] = normalized_locator
        citations.append(item)

    for issue in jira_items:
        key = str(issue.get("key") or "UNKNOWN")
        summary = str((issue.get("fields") or {}).get("summary") or "").strip()
        add("jira", f"{key}: {summary}" if summary else key, str(issue.get("self") or ""))

    for page in conf_items:
        title = str(page.get("title") or (page.get("content") or {}).get("title") or "Untitled")
        locator = str(page.get("url") or page.get("_links", {}).get("webui") or "")
        add("confluence", title, locator)

    for doc in kb_items:
        add("knowledge_base", str(doc.get("title") or "Untitled"), str(doc.get("uri") or ""))

    for result in github_items:
        repo = str(result.get("repo") or "").strip()
        path = str(result.get("path") or "").strip()
        title = f"{repo}:{path}" if repo and path else path or repo or "GitHub context"
        add("github", title, str(result.get("url") or ""))

    return citations


def _append_citation_footer(answer: str, citations: list[dict[str, str]]) -> str:
    if not citations or not _append_citations_to_answer():
        return answer

    lines = ["Sources:"]
    for idx, citation in enumerate(citations[: _citation_max_items()], start=1):
        title = str(citation.get("title") or "Untitled")
        locator = str(citation.get("locator") or "").strip()
        source = str(citation.get("source") or "source")
        suffix = f" ({locator})" if locator else ""
        lines.append(f"[{idx}] {source}: {title}{suffix}")

    return f"{answer.rstrip()}\n\n" + "\n".join(lines)


def _guardrail_outcome(telemetry: dict[str, Any]) -> dict[str, Any]:
    stop_reason = str(telemetry.get("stop_reason") or "").strip()
    configured = bool(telemetry.get("guardrail_configured"))
    intervened = bool(telemetry.get("guardrail_intervened")) or "guardrail" in stop_reason.lower()
    return {
        "configured": configured,
        "intervened": intervened,
        "stop_reason": stop_reason,
    }


def _emit_guardrail_telemetry(provider: str, outcome: dict[str, Any]) -> None:
    configured = bool(outcome.get("configured"))
    intervened = bool(outcome.get("intervened"))
    if intervened:
        state = "intervened"
    elif configured:
        state = "configured_no_intervention"
    else:
        state = "not_configured"

    _emit_metric(
        "ChatbotGuardrailOutcomeCount",
        1,
        dimensions={
            "Route": "query",
            "Method": "POST",
            "Provider": provider,
            "Outcome": state,
        },
    )


def _feedback_table() -> str:
    explicit = os.getenv("CHATBOT_FEEDBACK_TABLE", "").strip()
    if explicit:
        return explicit
    return _chat_memory_table()


def _normalize_feedback_sentiment(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    aliases = {
        "up": "positive",
        "thumbs_up": "positive",
        "down": "negative",
        "thumbs_down": "negative",
    }
    mapped = aliases.get(normalized, normalized)
    if mapped in _VALID_FEEDBACK_SENTIMENTS:
        return mapped
    return None


def _parse_feedback_rating(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        rating = int(value)
    else:
        raw = str(value).strip()
        if not raw or not raw.isdigit():
            return None
        rating = int(raw)
    if 1 <= rating <= 5:
        return rating
    return None


def _feedback_sentiment_from_rating(rating: int | None) -> str | None:
    if rating is None:
        return None
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "neutral"


def _store_feedback(actor_id: str, feedback: dict[str, Any]) -> bool:
    table = _feedback_table()
    if not table:
        return False

    now_ms = int(time.time() * 1000)
    ttl_days = max(1, int(os.getenv("CHATBOT_FEEDBACK_TTL_DAYS", "90")))
    expires_at = int(time.time()) + (ttl_days * 24 * 60 * 60)
    feedback_id = str(feedback.get("feedback_id") or uuid.uuid4())
    client = _dynamodb_client()

    item = {
        "conversation_id": {"S": f"feedback#{actor_id}"},
        "timestamp_ms": {"N": str(now_ms)},
        "role": {"S": "feedback"},
        "content": {
            "S": json.dumps(
                {
                    "feedback_id": feedback_id,
                    "conversation_id": feedback.get("conversation_id"),
                    "rating": feedback.get("rating"),
                    "sentiment": feedback.get("sentiment"),
                    "comment": feedback.get("comment"),
                    "query": feedback.get("query"),
                    "answer": feedback.get("answer"),
                },
                ensure_ascii=True,
            )
        },
        "expires_at": {"N": str(expires_at)},
    }
    client.put_item(TableName=table, Item=item)
    return True


def _parse_feedback_payload(body: dict[str, Any]) -> dict[str, Any]:
    rating = _parse_feedback_rating(body.get("rating"))
    sentiment = _normalize_feedback_sentiment(body.get("sentiment")) or _feedback_sentiment_from_rating(rating)
    if rating is None and sentiment is None:
        raise ValueError("feedback_rating_or_sentiment_required")

    comment = str(body.get("comment") or "").strip()
    if len(comment) > 2000:
        raise ValueError("feedback_comment_too_long")

    query = str(body.get("query") or "").strip()
    answer = str(body.get("answer") or "").strip()
    conversation_id = _normalize_conversation_id(str(body.get("conversation_id") or "").strip() or None)

    return {
        "feedback_id": str(body.get("feedback_id") or uuid.uuid4()),
        "conversation_id": conversation_id,
        "rating": rating,
        "sentiment": sentiment,
        "comment": comment or None,
        "query": query[:4000] if query else None,
        "answer": answer[:6000] if answer else None,
    }


def handle_query(
    query: str,
    jira_jql: str,
    confluence_cql: str,
    correlation_id: str,
    retrieval_mode: str | None = None,
    assistant_mode: str | None = None,
    llm_provider: str | None = None,
    model_id: str | None = None,
    conversation_id: str | None = None,
    actor_id: str = "anonymous",
    stream: bool = False,
    stream_chunk_chars: int = 120,
    stream_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    local_logger = get_logger("jira_confluence_chatbot", correlation_id=correlation_id)

    resolved_assistant_mode = _normalize_assistant_mode(assistant_mode)
    # Normalize once — callers may pass None for env-var fallback.
    mode = _normalize_retrieval_mode(retrieval_mode or os.getenv("CHATBOT_RETRIEVAL_MODE", "hybrid"))
    resolved_llm_provider = _normalize_llm_provider(llm_provider)
    resolved_model_id = _resolve_model_id(resolved_llm_provider, model_id)
    _validate_model_policy(resolved_llm_provider, resolved_model_id)
    resolved_conversation_id = _normalize_conversation_id(conversation_id)
    _enforce_prompt_safety(query, local_logger)
    _enforce_rate_quotas(actor_id, resolved_conversation_id)
    history = _load_conversation_history(actor_id, resolved_conversation_id)
    history_text = _format_history_for_prompt(history)
    stream_enabled = bool(stream or stream_callback is not None)
    provider_telemetry: dict[str, Any] = {}

    cache_enabled = _response_cache_enabled()
    cache_eligible = cache_enabled and len(query.strip()) >= _response_cache_min_query_length()
    cache_mode = mode if resolved_assistant_mode == "contextual" else "none"
    cache_exact_key: str | None = None
    cache_faq_key: str | None = None
    cached_response: dict[str, Any] | None = None
    cache_tier = "none"

    if cache_eligible:
        cache_exact_key = _response_cache_key(
            query=query,
            assistant_mode=resolved_assistant_mode,
            retrieval_mode=cache_mode,
            provider=resolved_llm_provider,
            model_id=resolved_model_id,
            conversation_id=resolved_conversation_id,
            history_text=history_text,
            jira_jql=jira_jql,
            confluence_cql=confluence_cql,
        )
        cache_faq_key = _response_cache_key(
            query=query,
            assistant_mode=resolved_assistant_mode,
            retrieval_mode=cache_mode,
            provider=resolved_llm_provider,
            model_id=resolved_model_id,
            conversation_id=None,
            history_text="",
            jira_jql=jira_jql,
            confluence_cql=confluence_cql,
        )
        if cache_faq_key == cache_exact_key:
            cache_faq_key = None

        cached_response = _load_cached_response(actor_id, cache_exact_key)
        if cached_response:
            cache_tier = "exact"
        elif cache_faq_key:
            cached_response = _load_cached_response(actor_id, cache_faq_key)
            if cached_response:
                cache_tier = "faq"

        _emit_metric(
            "ChatbotCacheHitCount" if cached_response else "ChatbotCacheMissCount",
            1,
            dimensions={"Route": "query", "Method": "POST", "Tier": cache_tier},
        )

    if cached_response:
        answer = str(cached_response.get("answer") or "").strip()
        if stream_callback is not None and answer:
            stream_callback(answer)
        _append_conversation_turn(actor_id, resolved_conversation_id, query, answer)
        chunks = _chunk_text(answer, stream_chunk_chars) if (stream and stream_callback is None) else []
        cached_citations_raw = cached_response.get("citations")
        cached_citations = list(cached_citations_raw) if isinstance(cached_citations_raw, list) else []
        cached_sources_raw = cached_response.get("sources")
        cached_sources = dict(cached_sources_raw) if isinstance(cached_sources_raw, dict) else {}
        cached_sources.setdefault("assistant_mode", resolved_assistant_mode)
        cached_sources.setdefault("provider", resolved_llm_provider)
        cached_sources.setdefault("model_id", resolved_model_id)
        cached_sources.setdefault("memory_enabled", _chat_memory_enabled())
        cached_sources.setdefault("memory_turns", len(history))
        cached_sources.setdefault("mode", "none" if resolved_assistant_mode == "general" else mode)
        cached_sources["response_cache"] = {
            "enabled": cache_enabled,
            "eligible": cache_eligible,
            "hit": True,
            "tier": cache_tier,
            "stored_at_ms": int(cached_response.get("stored_at_ms") or 0),
        }

        return {
            "answer": answer,
            "conversation_id": resolved_conversation_id,
            "citations": cached_citations[: _citation_max_items()],
            "stream": {"enabled": stream_enabled, "chunk_count": len(chunks), "chunks": chunks},
            "sources": cached_sources,
        }

    cache_lock_key: str | None = None
    cache_lock_acquired = False
    cache_store_keys: list[str] = []
    if cache_eligible and cache_exact_key:
        cache_store_keys = [cache_exact_key]
        if cache_faq_key:
            cache_store_keys.append(cache_faq_key)
        cache_lock_key = cache_faq_key or cache_exact_key
        cache_lock_acquired = _acquire_response_cache_lock(actor_id, cache_lock_key)

        if not cache_lock_acquired:
            wait_seconds = _response_cache_lock_wait_ms() / 1000.0
            for _ in range(_response_cache_lock_wait_attempts()):
                time.sleep(wait_seconds)
                cached_response = _load_cached_response(actor_id, cache_exact_key)
                cache_tier = "exact"
                if not cached_response and cache_faq_key:
                    cached_response = _load_cached_response(actor_id, cache_faq_key)
                    cache_tier = "faq" if cached_response else "none"
                if not cached_response:
                    continue

                _emit_metric(
                    "ChatbotCacheHitCount",
                    1,
                    dimensions={"Route": "query", "Method": "POST", "Tier": f"{cache_tier}_wait"},
                )
                answer = str(cached_response.get("answer") or "").strip()
                if stream_callback is not None and answer:
                    stream_callback(answer)
                _append_conversation_turn(actor_id, resolved_conversation_id, query, answer)
                chunks = _chunk_text(answer, stream_chunk_chars) if (stream and stream_callback is None) else []
                cached_citations_raw = cached_response.get("citations")
                cached_citations = list(cached_citations_raw) if isinstance(cached_citations_raw, list) else []
                cached_sources_raw = cached_response.get("sources")
                cached_sources = dict(cached_sources_raw) if isinstance(cached_sources_raw, dict) else {}
                cached_sources.setdefault("assistant_mode", resolved_assistant_mode)
                cached_sources.setdefault("provider", resolved_llm_provider)
                cached_sources.setdefault("model_id", resolved_model_id)
                cached_sources.setdefault("memory_enabled", _chat_memory_enabled())
                cached_sources.setdefault("memory_turns", len(history))
                cached_sources.setdefault("mode", "none" if resolved_assistant_mode == "general" else mode)
                cached_sources["response_cache"] = {
                    "enabled": cache_enabled,
                    "eligible": cache_eligible,
                    "hit": True,
                    "tier": cache_tier,
                    "stored_at_ms": int(cached_response.get("stored_at_ms") or 0),
                }
                return {
                    "answer": answer,
                    "conversation_id": resolved_conversation_id,
                    "citations": cached_citations[: _citation_max_items()],
                    "stream": {"enabled": stream_enabled, "chunk_count": len(chunks), "chunks": chunks},
                    "sources": cached_sources,
                }

            # Another invocation likely has this key in-flight; avoid duplicate cache writes.
            cache_store_keys = []

    routed_model_id, budget = _route_model_with_budget(
        provider=resolved_llm_provider,
        initial_model_id=resolved_model_id,
        query=query,
        actor_id=actor_id,
        conversation_id=resolved_conversation_id,
    )

    try:
        if resolved_assistant_mode == "general":
            system_prompt = (
                "You are a helpful enterprise AI assistant. Provide clear, practical answers. "
                "If policies or environment constraints are unknown, state assumptions explicitly."
            )
            general_user_prompt = (
                f"Conversation history:\n{history_text}\n\nLatest user question:\n{query}"
                if history_text
                else query
            )
            answer = _answer_with_provider(
                provider=resolved_llm_provider,
                model_id=routed_model_id,
                system_prompt=system_prompt,
                user_prompt=general_user_prompt,
                stream_callback=stream_callback,
                telemetry=provider_telemetry,
            )
            guardrail = _guardrail_outcome(provider_telemetry)
            _emit_guardrail_telemetry(resolved_llm_provider, guardrail)
            prompt_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(general_user_prompt)
            completion_tokens = _estimate_tokens(answer)
            estimated_cost_usd = _estimate_cost_usd(routed_model_id, prompt_tokens, completion_tokens)
            _record_budget_usage(
                actor_id=actor_id,
                conversation_id=resolved_conversation_id,
                model_id=routed_model_id,
                routing_reason=str(budget.get("route_reason") or "default"),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=estimated_cost_usd,
            )

            budget_details = {
                **budget,
                "last_prompt_tokens": prompt_tokens,
                "last_completion_tokens": completion_tokens,
                "last_estimated_cost_usd": round(estimated_cost_usd, 8),
            }
            _append_conversation_turn(actor_id, resolved_conversation_id, query, answer)

            chunks = _chunk_text(answer, stream_chunk_chars) if (stream and stream_callback is None) else []
            response_sources = {
                "assistant_mode": resolved_assistant_mode,
                "provider": resolved_llm_provider,
                "model_id": routed_model_id,
                "memory_enabled": _chat_memory_enabled(),
                "memory_turns": len(history),
                "guardrail": guardrail,
                "model_routing": {
                    "requested_model_id": resolved_model_id,
                    "effective_model_id": routed_model_id,
                    "reason": budget_details.get("route_reason"),
                    "complexity": budget_details.get("complexity"),
                },
                "budget": budget_details,
                "rerank": {
                    "enabled": False,
                    "top_k_per_source": 0,
                    "counts": {},
                },
                "safety": {
                    "enabled": _prompt_safety_enabled(),
                    "context_items_blocked": 0,
                },
                "response_cache": {
                    "enabled": cache_enabled,
                    "eligible": cache_eligible,
                    "hit": False,
                    "tier": "none",
                },
                "mode": "none",
                "context_source": "none",
                "kb_count": 0,
                "jira_count": 0,
                "confluence_count": 0,
                "github_count": 0,
                "context_items_blocked": 0,
            }
            for cache_store_key in cache_store_keys:
                _store_cached_response(
                    actor_id,
                    cache_store_key,
                    {"answer": answer, "sources": response_sources, "citations": []},
                )

            return {
                "answer": answer,
                "conversation_id": resolved_conversation_id,
                "citations": [],
                "stream": {"enabled": stream_enabled, "chunk_count": len(chunks), "chunks": chunks},
                "sources": response_sources,
            }

        jira_items: list[dict[str, Any]] = []
        conf_items: list[dict[str, Any]] = []
        kb_items: list[dict[str, Any]] = []
        github_items: list[dict[str, Any]] = []
        context_source = "live"
        context_items_blocked = 0

        if mode in {"kb", "hybrid"} and os.getenv("BEDROCK_KNOWLEDGE_BASE_ID", "").strip():
            kb_client = BedrockKnowledgeBaseClient(
                region=os.getenv("AWS_REGION", DEFAULT_REGION),
                knowledge_base_id=os.environ["BEDROCK_KNOWLEDGE_BASE_ID"],
                top_k=int(os.getenv("BEDROCK_KB_TOP_K", "5")),
            )
            # Circuit breaker: gracefully fall back to live if KB retrieval fails.
            try:
                kb_items = kb_client.retrieve(query)
            except Exception:
                local_logger.warning("kb_retrieval_failed_falling_back", extra={"extra": {"mode": mode}})
                kb_items = []
            if kb_items:
                context_source = "kb"

        use_live = mode == "live" or (mode == "hybrid" and not kb_items)
        if use_live:
            atlassian = AtlassianClient(credentials_secret_arn=os.environ["ATLASSIAN_CREDENTIALS_SECRET_ARN"])
            with ThreadPoolExecutor(max_workers=3) as pool:
                jira_future = pool.submit(atlassian.search_jira, jira_jql, 5)
                confluence_future = pool.submit(atlassian.search_confluence, confluence_cql, 5)
                github_future = pool.submit(_load_github_context, query, local_logger)
                jira_items = jira_future.result()
                conf_items = confluence_future.result()
                github_items = github_future.result()
            context_source = "live" if mode == "live" else "hybrid_fallback"

        jira_items, blocked = _sanitize_context_items("jira", jira_items, local_logger)
        context_items_blocked += blocked
        conf_items, blocked = _sanitize_context_items("confluence", conf_items, local_logger)
        context_items_blocked += blocked
        kb_items, blocked = _sanitize_context_items("knowledge_base", kb_items, local_logger)
        context_items_blocked += blocked
        github_items, blocked = _sanitize_context_items("github", github_items, local_logger)
        context_items_blocked += blocked

        rerank_counts = {
            "jira_before": len(jira_items),
            "confluence_before": len(conf_items),
            "kb_before": len(kb_items),
            "github_before": len(github_items),
        }
        jira_items = _rerank_context_items(query, "jira", jira_items)
        conf_items = _rerank_context_items(query, "confluence", conf_items)
        kb_items = _rerank_context_items(query, "knowledge_base", kb_items)
        github_items = _rerank_context_items(query, "github", github_items)
        rerank_counts.update(
            {
                "jira_after": len(jira_items),
                "confluence_after": len(conf_items),
                "kb_after": len(kb_items),
                "github_after": len(github_items),
            }
        )

        context_blob = {
            "jira": _format_jira(jira_items),
            "confluence": _format_confluence(conf_items),
            "knowledge_base": _format_kb(kb_items),
            "github": _format_github(github_items),
        }
        context_blob, context_budget = _apply_context_budget(context_blob)
        if int(context_budget.get("total_trimmed_chars") or 0) > 0:
            _emit_metric(
                "ChatbotContextTrimCount",
                1,
                dimensions={"Route": "query", "Method": "POST"},
            )

        system_prompt = (
            "You are an enterprise engineering assistant. Use only the provided Knowledge Base, Jira, and "
            "Confluence and GitHub context. "
            "If information is missing, state assumptions explicitly."
        )
        user_prompt = (
            f"User question:\n{query}\n\n"
            f"Conversation history:\n{history_text or 'None'}\n\n"
            f"Knowledge Base context:\n{context_blob['knowledge_base']}\n\n"
            f"Jira context:\n{context_blob['jira']}\n\n"
            f"Confluence context:\n{context_blob['confluence']}\n"
            f"GitHub context:\n{context_blob['github']}\n"
        )

        answer = _answer_with_provider(
            provider=resolved_llm_provider,
            model_id=routed_model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            stream_callback=stream_callback,
            telemetry=provider_telemetry,
        )
        guardrail = _guardrail_outcome(provider_telemetry)
        _emit_guardrail_telemetry(resolved_llm_provider, guardrail)
        citations = _build_citations(jira_items, conf_items, kb_items, github_items)
        answer_with_citations = _append_citation_footer(answer, citations)
        prompt_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
        completion_tokens = _estimate_tokens(answer_with_citations)
        estimated_cost_usd = _estimate_cost_usd(routed_model_id, prompt_tokens, completion_tokens)
        _record_budget_usage(
            actor_id=actor_id,
            conversation_id=resolved_conversation_id,
            model_id=routed_model_id,
            routing_reason=str(budget.get("route_reason") or "default"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )

        budget_details = {
            **budget,
            "last_prompt_tokens": prompt_tokens,
            "last_completion_tokens": completion_tokens,
            "last_estimated_cost_usd": round(estimated_cost_usd, 8),
        }
        _append_conversation_turn(actor_id, resolved_conversation_id, query, answer_with_citations)

        chunks = _chunk_text(answer_with_citations, stream_chunk_chars) if (stream and stream_callback is None) else []
        response_sources = {
            "assistant_mode": resolved_assistant_mode,
            "provider": resolved_llm_provider,
            "model_id": routed_model_id,
            "memory_enabled": _chat_memory_enabled(),
            "memory_turns": len(history),
            "guardrail": guardrail,
            "model_routing": {
                "requested_model_id": resolved_model_id,
                "effective_model_id": routed_model_id,
                "reason": budget_details.get("route_reason"),
                "complexity": budget_details.get("complexity"),
            },
            "budget": budget_details,
            "rerank": {
                "enabled": _rerank_enabled(),
                "top_k_per_source": _rerank_top_k_per_source(),
                "counts": rerank_counts,
            },
            "safety": {
                "enabled": _prompt_safety_enabled(),
                "context_items_blocked": context_items_blocked,
            },
            "response_cache": {
                "enabled": cache_enabled,
                "eligible": cache_eligible,
                "hit": False,
                "tier": "none",
            },
            "context_budget": context_budget,
            "mode": mode,
            "context_source": context_source,
            "kb_count": len(kb_items),
            "jira_count": len(jira_items),
            "confluence_count": len(conf_items),
            "github_count": len(github_items),
            "context_items_blocked": context_items_blocked,
        }
        citations_out = citations[: _citation_max_items()]
        for cache_store_key in cache_store_keys:
            _store_cached_response(
                actor_id,
                cache_store_key,
                {"answer": answer_with_citations, "sources": response_sources, "citations": citations_out},
            )

        local_logger.info(
            "chatbot_answered",
            extra={
                "extra": {
                    "assistant_mode": resolved_assistant_mode,
                    "provider": resolved_llm_provider,
                    "model_id": routed_model_id,
                    "retrieval_mode": mode,
                    "context_source": context_source,
                    "jira_items": len(jira_items),
                    "confluence_items": len(conf_items),
                    "kb_items": len(kb_items),
                    "github_items": len(github_items),
                    "context_items_blocked": context_items_blocked,
                    "rerank_enabled": _rerank_enabled(),
                    "rerank_counts": rerank_counts,
                    "citation_items": len(citations),
                    "guardrail_intervened": bool(guardrail.get("intervened")),
                    "guardrail_stop_reason": guardrail.get("stop_reason") or "",
                    "route_reason": budget_details.get("route_reason") or "",
                    "estimated_cost_usd": budget_details.get("last_estimated_cost_usd") or 0.0,
                }
            },
        )

        return {
            "answer": answer_with_citations,
            "conversation_id": resolved_conversation_id,
            "citations": citations_out,
            "stream": {"enabled": stream_enabled, "chunk_count": len(chunks), "chunks": chunks},
            "sources": response_sources,
        }
    finally:
        if cache_lock_acquired and cache_lock_key:
            _release_response_cache_lock(actor_id, cache_lock_key)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    request_context = event.get("requestContext") or {}
    if request_context.get("routeKey") is not None:
        route_key = str(request_context.get("routeKey") or "")
        connection_id = str(request_context.get("connectionId") or "")

        expected_token = _load_api_token()
        if expected_token and route_key != "$disconnect":
            headers = event.get("headers") or {}
            provided = ""
            for k, v in headers.items():
                if str(k).lower() == "x-api-token":
                    provided = str(v or "")
                    break
            if not hmac.compare_digest(provided, expected_token):
                if route_key == "$connect":
                    return {"statusCode": 401, "body": "unauthorized"}
                if connection_id:
                    _ws_send(event, connection_id, {"type": "error", "error": "unauthorized"})
                return {"statusCode": 200}

        if route_key in {"$connect", "$disconnect"}:
            return {"statusCode": 200}

        if route_key != "query":
            return {"statusCode": 400, "body": json.dumps({"error": "unsupported_route"})}

        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return {"statusCode": 400, "body": json.dumps({"error": "invalid_json"})}

        query = str(body.get("query") or "").strip()
        if not query:
            _ws_send(event, connection_id, {"type": "error", "error": "query_required"})
            return {"statusCode": 200}

        actor_id = _actor_id(event)
        jira_jql = str(body.get("jira_jql") or "").strip() or "order by updated DESC"
        confluence_cql = str(body.get("confluence_cql") or "").strip() or "type=page order by lastmodified desc"
        assistant_mode = _normalize_assistant_mode(body.get("assistant_mode"))
        llm_provider = _normalize_llm_provider(body.get("llm_provider"))
        model_id = str(body.get("model_id") or "").strip() or None
        conversation_id = str(body.get("conversation_id") or "").strip() or None
        retrieval_mode = _normalize_retrieval_mode(body.get("retrieval_mode"))
        chunk_chars = max(20, min(int(body.get("stream_chunk_chars") or _websocket_default_chunk_chars()), 1000))

        if assistant_mode == "contextual":
            if not _validate_query_filter(jira_jql) or not _validate_query_filter(confluence_cql):
                _ws_send(event, connection_id, {"type": "error", "error": "invalid_query_filter"})
                return {"statusCode": 200}

        chunk_index = 0
        buffered = ""

        def emit_chunk(content: str) -> None:
            nonlocal chunk_index
            if not content:
                return
            _ws_send(
                event,
                connection_id,
                {
                    "type": "chunk",
                    "index": chunk_index,
                    "content": content,
                    "conversation_id": conversation_id,
                },
            )
            chunk_index += 1

        def on_stream_delta(delta: str) -> None:
            nonlocal buffered
            if not delta:
                return
            buffered += delta
            while len(buffered) >= chunk_chars:
                emit_chunk(buffered[:chunk_chars])
                buffered = buffered[chunk_chars:]

        try:
            response_body = handle_query(
                query,
                jira_jql,
                confluence_cql,
                str(request_context.get("requestId") or "unknown"),
                retrieval_mode=retrieval_mode,
                assistant_mode=assistant_mode,
                llm_provider=llm_provider,
                model_id=model_id,
                conversation_id=conversation_id,
                actor_id=actor_id,
                stream=False,
                stream_callback=on_stream_delta,
            )
        except ValueError as exc:
            error_code = str(exc)
            _ws_send(
                event,
                connection_id,
                {"type": "error", "error": error_code, "status_code": _error_status_code(error_code)},
            )
            return {"statusCode": 200}
        except Exception:
            logger.exception("chatbot_websocket_internal_error")
            _ws_send(event, connection_id, {"type": "error", "error": "internal_error"})
            return {"statusCode": 200}

        if buffered:
            emit_chunk(buffered)
            buffered = ""

        if chunk_index == 0:
            for chunk in ((response_body.get("stream") or {}).get("chunks") or []):
                emit_chunk(str(chunk))

        _ws_send(
            event,
            connection_id,
            {
                "type": "done",
                "conversation_id": response_body.get("conversation_id"),
                "sources": response_body.get("sources") or {},
                "citations": response_body.get("citations") or [],
                "chunk_count": chunk_index,
            },
        )
        return {"statusCode": 200}

    method = str(event.get("requestContext", {}).get("http", {}).get("method") or "").upper()
    path = _request_path(event)
    started_at = time.time()
    if method not in {"POST", "GET"}:
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=405,
            payload={"error": "method_not_allowed"},
        )

    # H4: API token auth
    expected_token = _load_api_token()
    if expected_token:
        headers = event.get("headers") or {}
        provided = ""
        for k, v in headers.items():
            if k.lower() == "x-api-token":
                provided = v
                break
        if not hmac.compare_digest(provided, expected_token):
            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=401,
                payload={"error": "unauthorized"},
            )

    if method == "GET":
        if path.endswith("/chatbot/models"):
            try:
                models = _list_bedrock_models(region=os.getenv("AWS_REGION", DEFAULT_REGION))
            except Exception:
                logger.exception("chatbot_model_list_error")
                return _respond(
                    method=method,
                    path=path,
                    started_at=started_at,
                    status_code=500,
                    payload={"error": "model_list_failed"},
                )

            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=200,
                headers={"Content-Type": "application/json"},
                payload={
                    "models": models,
                    "count": len(models),
                    "region": os.getenv("AWS_REGION", DEFAULT_REGION),
                },
            )

        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=405,
            payload={"error": "method_not_allowed"},
        )

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=400,
            payload={"error": "invalid_json"},
        )

    query = str(body.get("query") or "").strip()
    actor_id = _actor_id(event)
    is_image_route = path.endswith("/chatbot/image")
    if is_image_route:
        if not query:
            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=400,
                payload={"error": "query_required"},
            )
        image_conversation_id = _normalize_conversation_id(str(body.get("conversation_id") or "").strip() or None)
        try:
            _enforce_image_rate_quotas(actor_id, image_conversation_id)
            _enforce_image_prompt_policy(query)
            image_payload = _generate_image(
                prompt=query,
                model_id=str(body.get("model_id") or "").strip() or None,
                size=str(body.get("size") or "").strip() or None,
            )
            _emit_metric(
                "ChatbotImageGeneratedCount",
                float(image_payload.get("count") or 0),
                dimensions={"Route": "image", "Method": method},
            )
        except ValueError as exc:
            error_code = str(exc)
            status_code = _error_status_code(error_code)
            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=status_code,
                payload={"error": error_code},
            )
        except Exception:
            logger.exception("chatbot_image_generation_error")
            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=500,
                payload={"error": "image_generation_failed"},
            )

        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=200,
            headers={"Content-Type": "application/json"},
            payload=image_payload,
        )

    if path.endswith("/chatbot/memory/clear"):
        conversation_id = _normalize_conversation_id(str(body.get("conversation_id") or "").strip() or None)
        if not conversation_id:
            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=400,
                payload={"error": "conversation_id_required"},
            )

        deleted = _clear_conversation_memory(actor_id, conversation_id)
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=200,
            headers={"Content-Type": "application/json"},
            payload={"cleared": True, "deleted_items": deleted, "conversation_id": conversation_id},
        )

    if path.endswith("/chatbot/memory/clear-all"):
        deleted = _clear_all_memory_for_actor(actor_id)
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=200,
            headers={"Content-Type": "application/json"},
            payload={"cleared": True, "deleted_items": deleted, "scope": "actor"},
        )

    if path.endswith("/chatbot/feedback"):
        try:
            feedback_payload = _parse_feedback_payload(body)
            stored = _store_feedback(actor_id, feedback_payload)
        except ValueError as exc:
            error_code = str(exc)
            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=_error_status_code(error_code),
                payload={"error": error_code},
            )
        except Exception:
            logger.exception("chatbot_feedback_store_failed")
            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=500,
                payload={"error": "feedback_store_failed"},
            )

        sentiment = str(feedback_payload.get("sentiment") or "neutral")
        _emit_metric(
            "ChatbotFeedbackCount",
            1,
            dimensions={"Route": "feedback", "Method": method, "Sentiment": sentiment},
        )
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=200,
            headers={"Content-Type": "application/json"},
            payload={
                "accepted": True,
                "stored": stored,
                "feedback_id": feedback_payload["feedback_id"],
                "sentiment": sentiment,
                "rating": feedback_payload.get("rating"),
                "conversation_id": feedback_payload.get("conversation_id"),
            },
        )

    if not query:
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=400,
            payload={"error": "query_required"},
        )

    # H5: Query length limit
    if len(query) > MAX_QUERY_LENGTH:
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=400,
            payload={"error": "query_too_long"},
        )

    jira_jql = str(body.get("jira_jql") or "").strip() or "order by updated DESC"
    confluence_cql = str(body.get("confluence_cql") or "").strip() or "type=page order by lastmodified desc"

    assistant_mode = _normalize_assistant_mode(body.get("assistant_mode"))
    llm_provider = _normalize_llm_provider(body.get("llm_provider"))
    model_id = str(body.get("model_id") or "").strip() or None
    conversation_id = str(body.get("conversation_id") or "").strip() or None
    retrieval_mode = _normalize_retrieval_mode(body.get("retrieval_mode"))
    stream = bool(body.get("stream") is True)
    stream_chunk_chars = int(body.get("stream_chunk_chars") or 120)

    # CQL/JQL validation is only required for contextual mode
    if assistant_mode == "contextual":
        if not _validate_query_filter(jira_jql) or not _validate_query_filter(confluence_cql):
            return _respond(
                method=method,
                path=path,
                started_at=started_at,
                status_code=400,
                payload={"error": "invalid_query_filter"},
            )

    correlation_id = event.get("requestContext", {}).get("requestId", "unknown")

    # M5: Structured error handling
    try:
        response_body = handle_query(
            query,
            jira_jql,
            confluence_cql,
            correlation_id,
            retrieval_mode=retrieval_mode,
            assistant_mode=assistant_mode,
            llm_provider=llm_provider,
            model_id=model_id,
            conversation_id=conversation_id,
            actor_id=actor_id,
            stream=stream,
            stream_chunk_chars=stream_chunk_chars,
        )
    except ValueError as exc:
        error_code = str(exc)
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=_error_status_code(error_code),
            payload={"error": error_code},
        )
    except Exception:
        logger.exception("chatbot_internal_error", extra={"extra": {"correlation_id": correlation_id}})
        return _respond(
            method=method,
            path=path,
            started_at=started_at,
            status_code=500,
            payload={"error": "internal_error", "correlation_id": correlation_id},
        )

    return _respond(
        method=method,
        path=path,
        started_at=started_at,
        status_code=200,
        headers={"Content-Type": "application/json"},
        payload=response_body,
    )
