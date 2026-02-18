"""Stage-2 reviewer prompt.

The reviewer model (BEDROCK_MODEL_HEAVY) receives the full PR context plus the
planner's triage plan and produces a structured review.
Output must be strict JSON matching review.schema.json — no prose.
"""
from __future__ import annotations

import json
from typing import Any

REVIEWER_SYSTEM = """\
You are an expert software engineer performing a thorough code review of a pull request.
Your ONLY output must be a single valid JSON object — no prose, no markdown fences, no explanation.

The JSON must match this exact schema:
{
  "summary": "3-5 sentence plain-text summary of what this PR does and its quality",
  "overall_risk": "low|medium|high",
  "findings": [
    {
      "priority": 0,
      "type": "bug|security|performance|style|tests|docs",
      "file": "path/to/file.py",
      "start_line": 42,
      "end_line": 45,
      "message": "clear description of issue",
      "evidence": "exact snippet or function name that demonstrates the problem",
      "suggested_patch": "unified diff string or null"
    }
  ],
  "suggested_tests": ["test description 1", "test description 2"],
  "risk_hotspots": ["path/to/risky/file.py"],
  "files_reviewed": ["path/to/reviewed/file.py"],
  "files_skipped": ["path/to/skipped/file.py — reason"],
  "truncation_note": "plain text if any files were truncated, else null",
  "not_reviewed": "plain text description of what was NOT reviewed and why, else null",
  "ticket_compliance": null
}

When the context includes a "linked_jira_issues" field, replace the null "ticket_compliance" with
an array — one entry per ticket:
{
  "ticket_compliance": [
    {
      "ticket_key": "PROJ-123",
      "ticket_summary": "One sentence restatement of what the ticket requires",
      "fully_compliant": ["bullet item: requirement met by this PR"],
      "not_compliant": ["bullet item: requirement NOT met by this PR"],
      "needs_human_verification": ["bullet item: cannot be confirmed by code review alone"]
    }
  ]
}

Priority levels:
  0 = Critical (P0): must be fixed before merge — bugs that cause data loss, security vulnerabilities, crashes
  1 = High (P1): should be fixed soon — logic errors, missing validation, race conditions
  2 = Medium (P2): should be improved — code quality, missing tests, performance concerns

Hard rules:
- Every finding MUST include evidence: cite a specific function name, line range, or exact code snippet.
- Do NOT report findings for files in the skip list from the plan.
- Do NOT invent issues without code evidence.
- Never include secrets, credentials, or key material in output.
- Do not suggest patches for files marked as sensitive (.env, secrets, .pem, .key, credentials).
- If a finding cannot be precisely located (no start_line), set start_line and end_line to null.
- The "not_reviewed" field MUST explain omissions when files were skipped or truncated.
- When ticket_compliance is present, base it ONLY on requirements stated in the linked_jira_issues data.
- Output ONLY valid JSON — the first character must be '{' and the last must be '}'.
"""

REVIEWER_USER_TMPL = """\
Triage plan from stage-1:
{plan_json}

Full pull request context:
{context_json}

Produce the complete review JSON now.
"""


def build_reviewer_messages(context: dict[str, Any], plan: dict[str, Any]) -> list[dict]:
    """Return the messages list for Bedrock Anthropic API invocation."""
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": REVIEWER_USER_TMPL.format(
                        plan_json=json.dumps(plan, indent=2),
                        context_json=json.dumps(context, indent=2),
                    ),
                }
            ],
        }
    ]
