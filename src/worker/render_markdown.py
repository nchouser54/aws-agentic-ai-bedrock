"""Render a validated review dict into a GitHub Check Run markdown body.

Format (Check Run output.text / PR review body):
  ## Summary
  ## Top Findings  (P0 / P1 / P2)
  ## Suggested Tests
  ## Risk Hotspots
  ## Files Reviewed / Skipped
  ## Truncation Note   (only when present)
"""
from __future__ import annotations

from typing import Any

_SEVERITY_LABEL = {
    0: "🔴 P0 — Critical",
    1: "🟠 P1 — High",
    2: "🟡 P2 — Medium",
}

_RISK_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴"}


def render_check_run_body(review: dict[str, Any], verdict: str | None = None) -> str:
    """Convert validated ``review.schema.json`` dict to markdown for Check Run output.

    Returns a string that fits within GitHub's 65 535-byte ``output.text`` limit.
    We truncate gracefully at section boundaries when needed.
    """
    parts: list[str] = []

    # ---- Verdict headline (P3: structured verdict) ---------------------------
    if verdict:
        parts.append(f"**{verdict}**\n\n")

    # ---- Summary ----------------------------------------------------------------
    summary = (review.get("summary") or "").strip()
    overall_risk = (review.get("overall_risk") or "unknown").lower()
    parts.append("## Summary\n")
    if summary:
        parts.append(summary + "\n")
    risk_display = f"{_RISK_EMOJI.get(overall_risk, '⚪')} Overall risk: **{overall_risk.upper()}**"
    parts.append(f"\n{risk_display}\n")

    # ---- Top Findings -----------------------------------------------------------
    findings: list[dict[str, Any]] = review.get("findings") or []
    if findings:
        parts.append("\n## Top Findings\n")
        for finding in findings:
            priority = int(finding.get("priority", 2))
            label = _SEVERITY_LABEL.get(priority, f"P{priority}")
            f_type = finding.get("type", "general")
            f_file = finding.get("file", "")
            start = finding.get("start_line")
            end = finding.get("end_line")
            message = finding.get("message", "").strip()
            evidence = finding.get("evidence", "").strip()

            location = f_file
            if start is not None:
                location = f"{f_file}:{start}" if (end is None or end == start) else f"{f_file}:{start}-{end}"

            heading = f"### {label} · `{f_type}` · `{location}`"
            parts.append(f"\n{heading}\n{message}\n")
            if evidence:
                parts.append(f"\n**Evidence:** {evidence}\n")

    # ---- Suggested Tests --------------------------------------------------------
    suggested_tests: list[str] = review.get("suggested_tests") or []
    if suggested_tests:
        parts.append("\n## Suggested Tests\n")
        for test in suggested_tests:
            parts.append(f"- {test.strip()}\n")

    # ---- Risk Hotspots ----------------------------------------------------------
    hotspots: list[str] = review.get("risk_hotspots") or []
    if hotspots:
        parts.append("\n## Risk Hotspots\n")
        for spot in hotspots:
            parts.append(f"- `{spot.strip()}`\n")

    # ---- Files Reviewed / Skipped -----------------------------------------------
    reviewed: list[str] = review.get("files_reviewed") or []
    skipped: list[str] = review.get("files_skipped") or []
    parts.append("\n## Files\n")
    if reviewed:
        parts.append(f"**Reviewed ({len(reviewed)}):** " + ", ".join(f"`{f}`" for f in reviewed) + "\n")
    if skipped:
        parts.append(f"**Skipped ({len(skipped)}):** " + ", ".join(f"`{f}`" for f in skipped) + "\n")

    # ---- Truncation Note --------------------------------------------------------
    truncation_note = (review.get("truncation_note") or "").strip()
    if truncation_note:
        parts.append(f"\n## ⚠️ Truncation Note\n{truncation_note}\n")

    # ---- What was not reviewed --------------------------------------------------
    not_reviewed = (review.get("not_reviewed") or "").strip()
    if not_reviewed:
        parts.append(f"\n## What Was Not Reviewed\n{not_reviewed}\n")

    # ---- Ticket Compliance ------------------------------------------------------
    ticket_compliance: list[dict[str, Any]] = review.get("ticket_compliance") or []
    if ticket_compliance:
        parts.append("\n## Jira Ticket Compliance\n")
        for tc in ticket_compliance:
            key = tc.get("ticket_key", "")
            summary = tc.get("ticket_summary", "").strip()
            parts.append(f"\n### {key}" + (f" — {summary}" if summary else "") + "\n")

            fully = tc.get("fully_compliant") or []
            not_comp = tc.get("not_compliant") or []
            needs_human = tc.get("needs_human_verification") or []

            if fully:
                parts.append("**✅ Compliant:**\n")
                for item in fully:
                    parts.append(f"- {item.strip()}\n")
            if not_comp:
                parts.append("**❌ Not compliant:**\n")
                for item in not_comp:
                    parts.append(f"- {item.strip()}\n")
            if needs_human:
                parts.append("**🔍 Needs human verification:**\n")
                for item in needs_human:
                    parts.append(f"- {item.strip()}\n")

    body = "".join(parts)

    # GitHub Check Run output.text limit is 65 535 bytes
    limit = 65_000
    if len(body.encode("utf-8")) > limit:
        truncated = body.encode("utf-8")[:limit].decode("utf-8", errors="ignore")
        body = truncated + "\n\n*[Output truncated due to size limits]*"

    return body


def render_pr_review_body(review: dict[str, Any]) -> str:
    """Render a shorter PR review comment body (no strict size limit, but keep concise)."""
    return render_check_run_body(review)
