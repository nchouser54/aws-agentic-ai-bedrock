#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys

import requests


def _call_chatbot(url: str, query: str, retrieval_mode: str, timeout: int) -> dict:
    payload = {
        "query": query,
        "retrieval_mode": retrieval_mode,
    }
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test chatbot retrieval modes")
    parser.add_argument("--url", required=True, help="Chatbot endpoint URL (/chatbot/query)")
    parser.add_argument("--query", default="Summarize current release blockers.", help="Query used for all modes")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    args = parser.parse_args()

    modes = ["live", "kb", "hybrid"]
    summary: dict[str, dict] = {}

    for mode in modes:
        try:
            payload = _call_chatbot(args.url, args.query, mode, args.timeout)
            sources = payload.get("sources") or {}
            summary[mode] = {
                "mode": sources.get("mode"),
                "context_source": sources.get("context_source"),
                "kb_count": sources.get("kb_count"),
                "jira_count": sources.get("jira_count"),
                "confluence_count": sources.get("confluence_count"),
            }
        except requests.RequestException as exc:
            summary[mode] = {"error": str(exc)}

    print(json.dumps(summary, indent=2))

    failed_modes = [mode for mode, data in summary.items() if "error" in data]
    if failed_modes:
        print(f"Failed modes: {', '.join(failed_modes)}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
