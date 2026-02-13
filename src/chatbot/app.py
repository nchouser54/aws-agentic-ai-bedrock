from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Any

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

_cached_api_token: str | None = None
_cached_anthropic_api_key: str | None = None


def _load_api_token() -> str:
    """Load chatbot API token from Secrets Manager or env var, with caching."""
    global _cached_api_token  # noqa: PLW0603
    if _cached_api_token is not None:
        return _cached_api_token

    secret_arn = os.getenv("CHATBOT_API_TOKEN_SECRET_ARN", "").strip()
    if secret_arn:
        client = boto3.client("secretsmanager")
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


def _allowed_bedrock_model_ids() -> set[str]:
    raw = os.getenv("CHATBOT_ALLOWED_MODEL_IDS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _validate_bedrock_model_id(model_id: str) -> None:
    if not model_id:
        raise ValueError("model_id_required")
    allowlist = _allowed_bedrock_model_ids()
    if allowlist and model_id not in allowlist:
        raise ValueError("model_not_allowed")


def _load_anthropic_api_key() -> str:
    global _cached_anthropic_api_key  # noqa: PLW0603
    if _cached_anthropic_api_key is not None:
        return _cached_anthropic_api_key

    secret_arn = os.getenv("CHATBOT_ANTHROPIC_API_KEY_SECRET_ARN", "").strip()
    if secret_arn:
        client = boto3.client("secretsmanager")
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


def _answer_with_provider(
    provider: str,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
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
        return client.answer(system_prompt=system_prompt, user_prompt=user_prompt)

    _validate_bedrock_model_id(model_id)
    client = BedrockChatClient(
        region=os.getenv("AWS_REGION", DEFAULT_REGION),
        model_id=model_id,
    )
    return client.answer(system_prompt=system_prompt, user_prompt=user_prompt)


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


def handle_query(
    query: str,
    jira_jql: str,
    confluence_cql: str,
    correlation_id: str,
    retrieval_mode: str | None = None,
    assistant_mode: str | None = None,
    llm_provider: str | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    local_logger = get_logger("jira_confluence_chatbot", correlation_id=correlation_id)

    resolved_assistant_mode = _normalize_assistant_mode(assistant_mode)
    resolved_llm_provider = _normalize_llm_provider(llm_provider)
    resolved_model_id = _resolve_model_id(resolved_llm_provider, model_id)

    if resolved_assistant_mode == "general":
        system_prompt = (
            "You are a helpful enterprise AI assistant. Provide clear, practical answers. "
            "If policies or environment constraints are unknown, state assumptions explicitly."
        )
        answer = _answer_with_provider(
            provider=resolved_llm_provider,
            model_id=resolved_model_id,
            system_prompt=system_prompt,
            user_prompt=query,
        )

        return {
            "answer": answer,
            "sources": {
                "assistant_mode": resolved_assistant_mode,
                "provider": resolved_llm_provider,
                "model_id": resolved_model_id,
                "mode": "none",
                "context_source": "none",
                "kb_count": 0,
                "jira_count": 0,
                "confluence_count": 0,
                "github_count": 0,
            },
        }

    # M6: Normalize once — callers may pass None for env-var fallback
    mode = _normalize_retrieval_mode(retrieval_mode or os.getenv("CHATBOT_RETRIEVAL_MODE", "hybrid"))
    jira_items: list[dict[str, Any]] = []
    conf_items: list[dict[str, Any]] = []
    kb_items: list[dict[str, Any]] = []
    github_items: list[dict[str, Any]] = []
    context_source = "live"

    if mode in {"kb", "hybrid"} and os.getenv("BEDROCK_KNOWLEDGE_BASE_ID", "").strip():
        kb_client = BedrockKnowledgeBaseClient(
            region=os.getenv("AWS_REGION", DEFAULT_REGION),
            knowledge_base_id=os.environ["BEDROCK_KNOWLEDGE_BASE_ID"],
            top_k=int(os.getenv("BEDROCK_KB_TOP_K", "5")),
        )
        # Circuit breaker: gracefully fall back to live if KB retrieval fails
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
        jira_items = atlassian.search_jira(jira_jql, max_results=5)
        conf_items = atlassian.search_confluence(confluence_cql, limit=5)
        github_items = _load_github_context(query, local_logger)
        context_source = "live" if mode == "live" else "hybrid_fallback"

    context_blob = {
        "jira": _format_jira(jira_items),
        "confluence": _format_confluence(conf_items),
        "knowledge_base": _format_kb(kb_items),
        "github": _format_github(github_items),
    }

    system_prompt = (
        "You are an enterprise engineering assistant. Use only the provided Knowledge Base, Jira, and "
        "Confluence and GitHub context. "
        "If information is missing, state assumptions explicitly."
    )
    user_prompt = (
        f"User question:\n{query}\n\n"
        f"Knowledge Base context:\n{context_blob['knowledge_base']}\n\n"
        f"Jira context:\n{context_blob['jira']}\n\n"
        f"Confluence context:\n{context_blob['confluence']}\n"
        f"GitHub context:\n{context_blob['github']}\n"
    )

    answer = _answer_with_provider(
        provider=resolved_llm_provider,
        model_id=resolved_model_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    local_logger.info(
        "chatbot_answered",
        extra={
            "extra": {
                "assistant_mode": resolved_assistant_mode,
                "provider": resolved_llm_provider,
                "model_id": resolved_model_id,
                "retrieval_mode": mode,
                "context_source": context_source,
                "jira_items": len(jira_items),
                "confluence_items": len(conf_items),
                "kb_items": len(kb_items),
                "github_items": len(github_items),
            }
        },
    )

    return {
        "answer": answer,
        "sources": {
            "assistant_mode": resolved_assistant_mode,
            "provider": resolved_llm_provider,
            "model_id": resolved_model_id,
            "mode": mode,
            "context_source": context_source,
            "kb_count": len(kb_items),
            "jira_count": len(jira_items),
            "confluence_count": len(conf_items),
            "github_count": len(github_items),
        },
    }


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    method = str(event.get("requestContext", {}).get("http", {}).get("method") or "").upper()
    path = _request_path(event)
    if method not in {"POST", "GET"}:
        return {"statusCode": 405, "body": json.dumps({"error": "method_not_allowed"})}

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
            return {"statusCode": 401, "body": json.dumps({"error": "unauthorized"})}

    if method == "GET":
        if path.endswith("/chatbot/models"):
            try:
                models = _list_bedrock_models(region=os.getenv("AWS_REGION", DEFAULT_REGION))
            except Exception:
                logger.exception("chatbot_model_list_error")
                return {"statusCode": 500, "body": json.dumps({"error": "model_list_failed"})}

            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(
                    {
                        "models": models,
                        "count": len(models),
                        "region": os.getenv("AWS_REGION", DEFAULT_REGION),
                    }
                ),
            }

        return {"statusCode": 405, "body": json.dumps({"error": "method_not_allowed"})}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "invalid_json"})}

    query = str(body.get("query") or "").strip()
    if not query:
        return {"statusCode": 400, "body": json.dumps({"error": "query_required"})}

    # H5: Query length limit
    if len(query) > MAX_QUERY_LENGTH:
        return {"statusCode": 400, "body": json.dumps({"error": "query_too_long"})}

    jira_jql = str(body.get("jira_jql") or "").strip() or "order by updated DESC"
    confluence_cql = str(body.get("confluence_cql") or "").strip() or "type=page order by lastmodified desc"

    assistant_mode = _normalize_assistant_mode(body.get("assistant_mode"))
    llm_provider = _normalize_llm_provider(body.get("llm_provider"))
    model_id = str(body.get("model_id") or "").strip() or None
    retrieval_mode = _normalize_retrieval_mode(body.get("retrieval_mode"))

    # CQL/JQL validation is only required for contextual mode
    if assistant_mode == "contextual":
        if not _validate_query_filter(jira_jql) or not _validate_query_filter(confluence_cql):
            return {"statusCode": 400, "body": json.dumps({"error": "invalid_query_filter"})}

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
        )
    except ValueError as exc:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": str(exc)}),
        }
    except Exception:
        logger.exception("chatbot_internal_error", extra={"extra": {"correlation_id": correlation_id}})
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "internal_error", "correlation_id": correlation_id}),
        }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(response_body),
    }
