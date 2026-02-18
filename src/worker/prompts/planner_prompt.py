"""Stage-1 planner prompt.

The planner model (BEDROCK_MODEL_LIGHT) reads the raw PR context and produces
a structured triage plan. Its only job is to:
  - Rank files by risk
  - Identify hotspot areas
  - Assign token budget per file cluster

Output must be strict JSON matching planner.schema.json — no prose.
"""
from __future__ import annotations

import json
from typing import Any

PLANNER_SYSTEM = """\
You are a senior software engineer performing a focused triage of a pull request.
Your ONLY output must be a single valid JSON object — no prose, no markdown, no explanation.
The JSON must match this exact schema:
{
  "risk_ranking": ["filename ordered highest→lowest risk"],
  "hotspots": [{"file": "...", "reason": "one sentence, cite code evidence"}],
  "file_clusters": [{"cluster_label": "...", "files": ["..."], "token_budget": 500}],
  "skip_files": ["filename — reason: ..."],
  "overall_risk_estimate": "low|medium|high"
}

Hard rules:
- Every hotspot reason MUST cite a specific function name, line range, or code pattern.
- Never include secrets, credentials, or key material in output.
- Do not make claims you cannot support from the diff alone.
"""

PLANNER_USER_TMPL = """\
Pull request context:
{context_json}

Produce the triage plan JSON now.
"""


def build_planner_messages(context: dict[str, Any]) -> list[dict]:
    """Return the messages list for Bedrock Anthropic API invocation."""
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": PLANNER_USER_TMPL.format(context_json=json.dumps(context, indent=2)),
                }
            ],
        }
    ]
