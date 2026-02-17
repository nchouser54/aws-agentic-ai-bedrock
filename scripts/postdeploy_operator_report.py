#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

import requests


def _detect_infra_cli() -> str | None:
    for cli in ("tofu", "terraform"):
        try:
            subprocess.check_output([cli, "version"], text=True)
            return cli
        except Exception:  # noqa: BLE001
            continue
    return None


def _run_infra_output(cli: str, terraform_dir: str) -> dict[str, Any]:
    output = subprocess.check_output([cli, f"-chdir={terraform_dir}", "output", "-json"], text=True)
    data = json.loads(output)
    if not isinstance(data, dict):
        return {}
    return data


def _extract_output(outputs: dict[str, Any], key: str) -> str:
    raw = outputs.get(key)
    if not isinstance(raw, dict):
        return ""
    value = raw.get("value")
    if isinstance(value, str):
        return value.strip()
    return ""


def _derive_models_url(chatbot_url: str) -> str:
    if not chatbot_url:
        return ""
    return re.sub(r"/chatbot/query$", "/chatbot/models", chatbot_url)


def _headers(auth_mode: str, auth_value: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not auth_value or auth_mode == "none":
        return headers
    if auth_mode == "token":
        headers["X-Api-Token"] = auth_value
    elif auth_mode == "bearer":
        headers["Authorization"] = f"Bearer {auth_value}"
    return headers


def _request(method: str, url: str, timeout: int, headers: dict[str, str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = requests.request(method=method, url=url, headers=headers, json=payload, timeout=timeout)
        return {
            "reachable": True,
            "status_code": response.status_code,
            "ok": response.ok,
            "body_snippet": (response.text or "")[:300],
        }
    except requests.RequestException as exc:
        return {
            "reachable": False,
            "error": str(exc),
        }


def _status_from_result(result: dict[str, Any], *, allow_auth_fail: bool = False) -> str:
    if not result.get("reachable"):
        return "fail"
    status_code = int(result.get("status_code") or 0)
    if 200 <= status_code < 300:
        return "ok"
    if allow_auth_fail and status_code in {401, 403}:
        return "warn"
    return "warn"


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-deploy operator report for webhook/chatbot/webapp health")
    parser.add_argument("--terraform-dir", default="infra/terraform", help="Terraform/OpenTofu directory")
    parser.add_argument("--auth-mode", default="none", choices=["none", "token", "bearer"], help="Auth mode for chatbot endpoint checks")
    parser.add_argument("--auth-value", default="", help="Token or bearer value for chatbot checks")
    parser.add_argument("--query", default="Summarize release blockers for this week.", help="Chatbot query for functional check")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout seconds")
    args = parser.parse_args()

    cli = _detect_infra_cli()
    if not cli:
        print("[FAIL] neither tofu nor terraform is available in PATH")
        return 2

    try:
        outputs = _run_infra_output(cli, args.terraform_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] unable to read {cli} outputs: {exc}")
        return 2

    webhook_url = _extract_output(outputs, "webhook_url")
    chatbot_url = _extract_output(outputs, "chatbot_url")
    webapp_https_url = _extract_output(outputs, "webapp_https_url")
    webapp_url = _extract_output(outputs, "webapp_url")
    webapp_target = webapp_https_url or webapp_url

    report: dict[str, Any] = {
        "cli": cli,
        "terraform_dir": args.terraform_dir,
        "checks": {},
    }

    failures = 0

    if webhook_url:
        webhook_result = _request(
            method="POST",
            url=webhook_url,
            timeout=args.timeout,
            headers={"Content-Type": "application/json"},
            payload={"health": "probe"},
        )
        webhook_status = _status_from_result(webhook_result, allow_auth_fail=True)
        report["checks"]["webhook"] = {
            "url": webhook_url,
            "status": webhook_status,
            **webhook_result,
        }
        if webhook_status == "fail":
            failures += 1
    else:
        report["checks"]["webhook"] = {
            "status": "warn",
            "reason": "terraform output webhook_url missing",
        }

    chatbot_headers = _headers(args.auth_mode, args.auth_value)
    if chatbot_url:
        chatbot_result = _request(
            method="POST",
            url=chatbot_url,
            timeout=args.timeout,
            headers=chatbot_headers,
            payload={"query": args.query, "retrieval_mode": "hybrid"},
        )
        chatbot_status = _status_from_result(chatbot_result, allow_auth_fail=True)
        report["checks"]["chatbot_query"] = {
            "url": chatbot_url,
            "status": chatbot_status,
            **chatbot_result,
        }
        if chatbot_status == "fail":
            failures += 1

        models_url = _derive_models_url(chatbot_url)
        if models_url:
            models_result = _request(
                method="GET",
                url=models_url,
                timeout=args.timeout,
                headers=chatbot_headers,
                payload=None,
            )
            models_status = _status_from_result(models_result, allow_auth_fail=True)
            report["checks"]["chatbot_models"] = {
                "url": models_url,
                "status": models_status,
                **models_result,
            }
            if models_status == "fail":
                failures += 1
    else:
        report["checks"]["chatbot_query"] = {
            "status": "warn",
            "reason": "terraform output chatbot_url missing",
        }

    if webapp_target:
        webapp_result = _request(
            method="GET",
            url=webapp_target,
            timeout=args.timeout,
            headers={},
            payload=None,
        )
        webapp_status = _status_from_result(webapp_result, allow_auth_fail=True)
        report["checks"]["webapp"] = {
            "url": webapp_target,
            "status": webapp_status,
            **webapp_result,
        }
        if webapp_status == "fail":
            failures += 1
    else:
        report["checks"]["webapp"] = {
            "status": "warn",
            "reason": "terraform outputs webapp_url/webapp_https_url missing (web hosting may be disabled)",
        }

    print(json.dumps(report, indent=2))

    if failures > 0:
        print("\nResult: NOT READY (one or more checks failed)", file=sys.stderr)
        return 1

    print("\nResult: READY (no hard failures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
