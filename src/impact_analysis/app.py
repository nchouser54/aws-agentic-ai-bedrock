"""Impact analysis Lambda.

Given a set of changed files (from a PR or commit), queries the Bedrock
Knowledge Base to identify:

- Which symbols were changed (based on KB metadata)
- Which callers / dependents reference those symbols
- Which of those tests are already covered vs. uncovered
- A risk score summarising the blast-radius

API
---
``POST /impact-analysis``

Request body (JSON):

.. code-block:: json

    {
        "repo":          "owner/repo",
        "ref":           "main",
        "files_changed": ["src/auth.py", "src/models/user.py"],
        "pr_number":     42           // optional — adds PR comment
    }

Response body (JSON):

.. code-block:: json

    {
        "status":           "ok",
        "changed_files":    ["src/auth.py"],
        "changed_symbols":  [{"file": "src/auth.py", "symbol": "verify_token", ...}],
        "impacted_callers": [{"file": "src/api.py",  "symbol": "login_view",  ...}],
        "recommended_tests":["tests/test_auth.py", "tests/test_api.py"],
        "coverage_gaps":    [{"file": "src/auth.py", "coverage_pct": 45.0, ...}],
        "risk_score":       "high"    // low / medium / high
    }
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from shared.bedrock_chat import BedrockChatClient
from shared.bedrock_kb import BedrockKnowledgeBaseClient
from shared.constants import DEFAULT_REGION
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger

logger = get_logger("impact_analysis")

_IMPACT_KB_TOP_K = int(os.getenv("IMPACT_ANALYSIS_KB_TOP_K", "8"))


# ---------------------------------------------------------------------------
# KB Retrieval helpers
# ---------------------------------------------------------------------------


def _retrieve_symbols_for_file(
    kb: BedrockKnowledgeBaseClient, repo: str, path: str
) -> list[dict[str, Any]]:
    """Retrieve symbol docs (functions/classes) from KB that belong to *path*."""
    results = kb.retrieve(f"functions classes symbols in file {path} repo:{repo}")
    out = []
    for r in results:
        text = r.get("text") or ""
        uri = r.get("uri") or ""
        title = r.get("title") or ""
        # Filter to results that mention the specific path
        if path in text or path in uri or path in title:
            out.append(r)
    return out


def _retrieve_callers(
    kb: BedrockKnowledgeBaseClient, repo: str, symbol_name: str, path: str
) -> list[dict[str, Any]]:
    """Retrieve KB docs that reference *symbol_name* as a caller/dependent."""
    return kb.retrieve(
        f"calls uses imports {symbol_name} in repo:{repo} related to {path}"
    )


def _retrieve_coverage_for_file(
    kb: BedrockKnowledgeBaseClient, repo: str, path: str
) -> dict[str, Any] | None:
    """Retrieve the most recent coverage doc for *path* from the KB."""
    results = kb.retrieve(f"coverage line_rate uncovered lines file:{path} repo:{repo}")
    for r in results:
        text = r.get("text") or ""
        if "coverage" in text.lower() and (path in text or path in (r.get("uri") or "")):
            # Parse coverage_pct from text "Line coverage: 45.2% ..."
            m = re.search(r"Line coverage:\s*([\d.]+)%", text)
            pct = float(m.group(1)) if m else None
            uncov_m = re.search(r"Untested functions:\s*(.+)", text)
            uncov_funcs = [f.strip() for f in uncov_m.group(1).split(",")] if uncov_m else []
            return {
                "file": path,
                "coverage_pct": pct,
                "uncovered_functions": uncov_funcs,
                "raw_text": text,
            }
    return None


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------


def _compute_risk_score(
    impacted_count: int,
    coverage_gaps: list[dict[str, Any]],
) -> str:
    """Return ``low`` / ``medium`` / ``high`` based on blast-radius + coverage."""
    low_coverage = sum(
        1 for g in coverage_gaps if (g.get("coverage_pct") or 100.0) < 60.0
    )
    if impacted_count >= 5 or low_coverage >= 2:
        return "high"
    if impacted_count >= 2 or low_coverage >= 1:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# LLM-based recommended test list
# ---------------------------------------------------------------------------

_RECOMMEND_SYSTEM = """\
You are a senior software engineer doing impact analysis. Given a list of \
changed symbols and their known callers/dependents (from a knowledge base), \
produce a JSON array of test file paths that MUST be run or updated. Only \
include real paths that appear in the context. Output ONLY valid JSON — a \
single JSON array of strings. No explanation.
"""


def _llm_recommend_tests(
    changed: list[dict[str, Any]],
    callers: list[dict[str, Any]],
    model_id: str,
    region: str,
) -> list[str]:
    """Ask the LLM to recommend test files based on change + caller context."""
    if not changed and not callers:
        return []

    context_lines = ["Changed symbols:"]
    for sym in changed[:10]:
        context_lines.append(f"  - {sym.get('title') or sym.get('text') or ''}")

    context_lines.append("\nKnown callers / dependents:")
    for cal in callers[:10]:
        context_lines.append(f"  - {cal.get('title') or cal.get('text') or ''}")

    user_prompt = "\n".join(context_lines)
    try:
        chat = BedrockChatClient(region=region, model_id=model_id, max_tokens=512)
        raw = chat.answer(_RECOMMEND_SYSTEM, user_prompt)
        # Extract JSON array
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            candidates = json.loads(m.group(0))
            if isinstance(candidates, list):
                return [str(p) for p in candidates if isinstance(p, str) and p.strip()]
    except Exception:  # noqa: BLE001
        logger.warning("llm_recommend_tests_failed")
    return []


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------


def run_impact_analysis(
    repo: str,
    ref: str,
    files_changed: list[str],
    model_id: str,
    region: str,
    kb: BedrockKnowledgeBaseClient,
) -> dict[str, Any]:
    """Run impact analysis for a set of changed files.

    Returns the full structured result dict ready for the API response.
    """
    all_changed_symbols: list[dict[str, Any]] = []
    all_callers: list[dict[str, Any]] = []
    coverage_gaps: list[dict[str, Any]] = []
    seen_caller_uris: set[str] = set()

    for path in files_changed[:20]:  # cap at 20 files for latency
        # 1. Get symbols in changed file
        changed_syms = _retrieve_symbols_for_file(kb, repo, path)
        all_changed_symbols.extend(changed_syms)

        # 2. Coverage gap for this file
        cov = _retrieve_coverage_for_file(kb, repo, path)
        if cov:
            coverage_gaps.append(cov)

        # 3. Callers for each symbol
        for sym in changed_syms[:5]:  # limit per-file symbol lookups
            sym_name = sym.get("title") or ""
            if sym_name:
                callers = _retrieve_callers(kb, repo, sym_name, path)
                for c in callers:
                    uri = c.get("uri") or c.get("title") or id(c)
                    if uri not in seen_caller_uris:
                        seen_caller_uris.add(str(uri))
                        all_callers.append(c)

    # 4. LLM-recommended tests
    recommended_tests = _llm_recommend_tests(
        all_changed_symbols, all_callers, model_id, region
    )

    # Fallback: extract test paths from caller URIs / text
    if not recommended_tests:
        for c in all_callers:
            for text_field in (c.get("uri") or "", c.get("title") or "", c.get("text") or ""):
                m = re.search(r"(tests?/[^\s\"']+\.(?:py|ts|js|go|java))", text_field)
                if m:
                    p = m.group(1)
                    if p not in recommended_tests:
                        recommended_tests.append(p)

    risk_score = _compute_risk_score(len(all_callers), coverage_gaps)

    return {
        "status": "ok",
        "repo": repo,
        "ref": ref,
        "changed_files": files_changed,
        "changed_symbols": [
            {
                "title": s.get("title") or "",
                "uri": s.get("uri") or "",
                "score": s.get("score"),
            }
            for s in all_changed_symbols
        ],
        "impacted_callers": [
            {
                "title": c.get("title") or "",
                "uri": c.get("uri") or "",
                "score": c.get("score"),
            }
            for c in all_callers
        ],
        "recommended_tests": recommended_tests,
        "coverage_gaps": coverage_gaps,
        "risk_score": risk_score,
    }


# ---------------------------------------------------------------------------
# PR comment
# ---------------------------------------------------------------------------


def _format_pr_comment(result: dict[str, Any]) -> str:
    risk = result.get("risk_score", "unknown")
    risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")

    callers = result.get("impacted_callers") or []
    tests = result.get("recommended_tests") or []
    gaps = result.get("coverage_gaps") or []

    lines = [
        f"## {risk_icon} Impact Analysis — Risk: **{risk.upper()}**",
        "",
        f"**Changed files:** {', '.join(f'`{f}`' for f in result.get('changed_files') or [])}",
        f"**Impacted callers found:** {len(callers)}",
        "",
    ]

    if callers:
        lines.append("<details><summary>Impacted callers</summary>\n")
        for c in callers[:15]:
            lines.append(f"- {c.get('title') or c.get('uri') or '(unknown)'}")
        lines.append("\n</details>\n")

    if tests:
        lines.append("### Recommended tests to run / update\n")
        for t in tests[:10]:
            lines.append(f"- `{t}`")
        lines.append("")

    if gaps:
        lines.append("### Coverage gaps in changed files\n")
        for g in gaps:
            pct = g.get("coverage_pct")
            pct_str = f"{pct:.1f}%" if pct is not None else "unknown"
            funcs = ", ".join(g.get("uncovered_functions") or [])
            lines.append(f"- `{g['file']}` — {pct_str} line coverage" + (f" | untested: {funcs}" if funcs else ""))
        lines.append("")

    lines.append("_Generated by AI Impact Analysis. Review before acting._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Handle ``POST /impact-analysis``."""
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    method = http.get("method", "").upper()

    if method != "POST":
        return {"statusCode": 405, "body": json.dumps({"error": "method_not_allowed"})}

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": json.dumps({"error": "invalid_json"})}

    repo_full = (body.get("repo") or "").strip()
    ref = (body.get("ref") or "main").strip()
    files_changed: list[str] = [f for f in (body.get("files_changed") or []) if isinstance(f, str) and f.strip()]
    pr_number = body.get("pr_number")

    if not repo_full or "/" not in repo_full:
        return {"statusCode": 400, "body": json.dumps({"error": "repo (owner/repo) is required"})}
    if not files_changed:
        return {"statusCode": 400, "body": json.dumps({"error": "files_changed must be a non-empty list"})}

    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    model_id = os.environ.get("IMPACT_ANALYSIS_MODEL_ID") or os.environ.get("BEDROCK_MODEL_ID", "")
    kb_id = os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "").strip()

    if not kb_id:
        return {"statusCode": 503, "body": json.dumps({"error": "knowledge_base_not_configured"})}

    kb = BedrockKnowledgeBaseClient(region=region, knowledge_base_id=kb_id, top_k=_IMPACT_KB_TOP_K)

    try:
        result = run_impact_analysis(
            repo=repo_full,
            ref=ref,
            files_changed=files_changed,
            model_id=model_id,
            region=region,
            kb=kb,
        )
    except Exception:
        logger.exception("impact_analysis_failed")
        return {"statusCode": 500, "body": json.dumps({"error": "analysis_failed"})}

    # Optionally post as PR comment
    if pr_number:
        try:
            owner, repo = repo_full.split("/", maxsplit=1)
            auth = GitHubAppAuth(
                app_ids_secret_arn=os.environ["GITHUB_APP_IDS_SECRET_ARN"],
                private_key_secret_arn=os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"],
                api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
            )
            token = auth.get_installation_token()
            gh = GitHubClient(
                token_provider=lambda: token,
                api_base=os.getenv("GITHUB_API_BASE", "https://api.github.com"),
            )
            comment = _format_pr_comment(result)
            gh.create_issue_comment(owner, repo, int(pr_number), comment)
        except Exception:  # noqa: BLE001
            logger.warning("impact_analysis_pr_comment_failed")

    logger.info(
        "impact_analysis_completed",
        extra={
            "extra": {
                "repo": repo_full,
                "files": len(files_changed),
                "callers": len(result.get("impacted_callers") or []),
                "risk": result.get("risk_score"),
            }
        },
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result),
    }
