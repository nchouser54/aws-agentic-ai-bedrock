from __future__ import annotations

import json
import os
from typing import Any

import requests

from shared.logging import get_logger

logger = get_logger("chatbot_github_oauth_authorizer")


def _parse_bearer_token(headers: dict[str, str] | None) -> str:
    if not headers:
        return ""

    auth_header = ""
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth_header = value
            break

    if not auth_header:
        return ""

    parts = auth_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""

    return parts[1].strip()


def _allowed_orgs() -> set[str]:
    raw = os.getenv("GITHUB_OAUTH_ALLOWED_ORGS", "")
    return {org.strip().lower() for org in raw.split(",") if org.strip()}


def _github_get(api_base: str, token: str, path: str) -> requests.Response:
    return requests.get(
        f"{api_base.rstrip('/')}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=10,
    )


def _authorize(token: str) -> tuple[bool, dict[str, str]]:
    api_base = os.getenv("GITHUB_API_BASE", "https://api.github.com").strip().rstrip("/")
    user_resp = _github_get(api_base, token, "/user")
    if user_resp.status_code != 200:
        logger.warning("github_oauth_user_lookup_failed", extra={"extra": {"status": user_resp.status_code}})
        return False, {}

    user = user_resp.json()
    login = str(user.get("login") or "")
    if not login:
        return False, {}

    allowlist = _allowed_orgs()
    if not allowlist:
        return True, {"github_login": login, "auth_provider": "github_oauth"}

    org_resp = _github_get(api_base, token, "/user/orgs")
    if org_resp.status_code != 200:
        logger.warning("github_oauth_org_lookup_failed", extra={"extra": {"status": org_resp.status_code}})
        return False, {}

    orgs = {str(org.get("login") or "").lower() for org in org_resp.json()}
    if not orgs.intersection(allowlist):
        logger.info(
            "github_oauth_org_membership_denied",
            extra={"extra": {"github_login": login, "required_orgs": sorted(allowlist)}},
        )
        return False, {}

    return True, {"github_login": login, "auth_provider": "github_oauth"}


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    headers = event.get("headers") or {}
    token = _parse_bearer_token(headers)
    if not token:
        return {"isAuthorized": False}

    request_id = event.get("requestContext", {}).get("requestId", "unknown")
    try:
        authorized, context = _authorize(token)
    except (requests.RequestException, json.JSONDecodeError):
        logger.exception(
            "github_oauth_authorizer_error",
            extra={"extra": {"request_id": request_id}},
        )
        return {"isAuthorized": False}

    if not authorized:
        return {"isAuthorized": False}

    return {
        "isAuthorized": True,
        "context": context,
    }
