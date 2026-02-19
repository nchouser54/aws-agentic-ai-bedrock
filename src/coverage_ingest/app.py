"""Coverage ingestion Lambda.

Accepts CI-generated coverage reports and stores per-file coverage metadata
in the Knowledge Base so test-gen and impact-analysis can reason about what
is and is not tested.

Supported formats
-----------------
- **Cobertura XML** (``pytest --cov --cov-report=xml``, Maven, Gradle)
- **LCOV** (``jest --coverage --coverageReporters=lcov``, Go)

API
---
``POST /coverage/ingest``

Request body (JSON):

.. code-block:: json

    {
        "repo": "owner/repo",
        "ref":  "main",
        "format": "cobertura",      // or "lcov"
        "coverage_data": "<xml or lcov text>"
    }

The Lambda:

1. Parses the report into per-file :class:`FileCoverage` records.
2. Writes each record as a JSON doc to S3 (under the KB sync bucket).
3. Starts a Bedrock KB ingestion job so the data is immediately searchable.

Response body (JSON):

.. code-block:: json

    {
        "status": "ingested",
        "files_processed": 12,
        "ingestion_job_id": "..."
    }
"""

from __future__ import annotations

import base64
import json
import os
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3

from shared.constants import DEFAULT_REGION
from shared.logging import get_logger

logger = get_logger("coverage_ingest")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FileCoverage:
    """Coverage summary for a single source file."""

    path: str
    line_rate: float  # 0.0 – 1.0
    branch_rate: float  # 0.0 – 1.0
    lines_valid: int
    lines_covered: int
    branches_valid: int
    branches_covered: int
    uncovered_lines: list[int] = field(default_factory=list)
    uncovered_functions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cobertura parser
# ---------------------------------------------------------------------------


def _safe_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (ValueError, TypeError):
        return default


def _safe_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except (ValueError, TypeError):
        return default


def parse_cobertura(xml_text: str) -> list[FileCoverage]:
    """Parse a Cobertura XML coverage report into :class:`FileCoverage` records."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid Cobertura XML: {exc}") from exc

    results: list[FileCoverage] = []
    for cls in root.iter("class"):
        path = cls.get("filename") or cls.get("name") or ""
        if not path:
            continue

        line_rate = _safe_float(cls.get("line-rate"))
        branch_rate = _safe_float(cls.get("branch-rate"))
        lines_valid = _safe_int(cls.get("lines-valid") or cls.get("line-count"))
        lines_covered = _safe_int(cls.get("lines-covered"))

        uncovered_lines: list[int] = []
        uncovered_funcs: list[str] = []

        for line in cls.iter("line"):
            hits = _safe_int(line.get("hits"))
            lineno = _safe_int(line.get("number"))
            if hits == 0 and lineno > 0:
                uncovered_lines.append(lineno)

        for method in cls.iter("method"):
            hits = _safe_int(method.get("hits"))
            if hits == 0:
                name = method.get("name") or ""
                if name:
                    uncovered_funcs.append(name)

        # Fall back: derive lines_covered if not in attributes
        if lines_valid > 0 and lines_covered == 0:
            total_lines = sum(1 for _ in cls.iter("line"))
            hit_lines = sum(1 for ln in cls.iter("line") if _safe_int(ln.get("hits")) > 0)
            lines_valid = total_lines
            lines_covered = hit_lines
            if total_lines > 0:
                line_rate = hit_lines / total_lines

        results.append(
            FileCoverage(
                path=path,
                line_rate=line_rate,
                branch_rate=branch_rate,
                lines_valid=lines_valid,
                lines_covered=lines_covered,
                branches_valid=_safe_int(cls.get("branches-valid") or cls.get("branches-covered")),
                branches_covered=_safe_int(cls.get("branches-covered")),
                uncovered_lines=sorted(set(uncovered_lines)),
                uncovered_functions=uncovered_funcs,
            )
        )
    return results


# ---------------------------------------------------------------------------
# LCOV parser
# ---------------------------------------------------------------------------

def parse_lcov(lcov_text: str) -> list[FileCoverage]:
    """Parse an LCOV coverage report into :class:`FileCoverage` records."""
    results: list[FileCoverage] = []
    current_path = ""
    lines_found = 0
    lines_hit = 0
    uncovered_lines: list[int] = []
    uncovered_funcs: list[str] = []
    func_hits: dict[str, int] = {}

    for raw_line in lcov_text.splitlines():
        line = raw_line.strip()
        if line.startswith("SF:"):
            current_path = line[3:].strip()
            lines_found = 0
            lines_hit = 0
            uncovered_lines = []
            uncovered_funcs = []
            func_hits = {}
        elif line.startswith("DA:"):
            parts = line[3:].split(",")
            if len(parts) >= 2:
                try:
                    lineno = int(parts[0])
                    hits = int(parts[1])
                    lines_found += 1
                    if hits > 0:
                        lines_hit += 1
                    else:
                        uncovered_lines.append(lineno)
                except ValueError:
                    pass
        elif line.startswith("FNDA:"):
            parts = line[5:].split(",", 1)
            if len(parts) == 2:
                try:
                    hits = int(parts[0])
                    fname = parts[1].strip()
                    func_hits[fname] = func_hits.get(fname, 0) + hits
                except ValueError:
                    pass
        elif line == "end_of_record":
            if current_path:
                uncovered_funcs = [f for f, h in func_hits.items() if h == 0]
                rate = lines_hit / lines_found if lines_found > 0 else 0.0
                results.append(
                    FileCoverage(
                        path=current_path,
                        line_rate=rate,
                        branch_rate=0.0,
                        lines_valid=lines_found,
                        lines_covered=lines_hit,
                        branches_valid=0,
                        branches_covered=0,
                        uncovered_lines=sorted(set(uncovered_lines)),
                        uncovered_functions=uncovered_funcs,
                    )
                )
    return results


# ---------------------------------------------------------------------------
# S3 document builder
# ---------------------------------------------------------------------------

_COVERAGE_TIER_THRESHOLDS = (0.8, 0.5)  # >= 80 % → high, >= 50 % → medium, else low


def _coverage_tier(rate: float) -> str:
    if rate >= _COVERAGE_TIER_THRESHOLDS[0]:
        return "high"
    if rate >= _COVERAGE_TIER_THRESHOLDS[1]:
        return "medium"
    return "low"


def _build_coverage_doc(
    fc: FileCoverage, repo: str, ref: str, web_base: str
) -> dict[str, Any]:
    from pathlib import Path  # noqa: PLC0415

    pct = round(fc.line_rate * 100, 1)
    tier = _coverage_tier(fc.line_rate)
    title = Path(fc.path).name or fc.path

    text_parts = [
        f"File: {fc.path}",
        f"Repository: {repo}",
        f"Ref: {ref}",
        f"Line coverage: {pct}% ({fc.lines_covered}/{fc.lines_valid} lines) — {tier}",
        f"Branch coverage: {round(fc.branch_rate * 100, 1)}% ({fc.branches_covered}/{fc.branches_valid} branches)",
    ]
    if fc.uncovered_functions:
        text_parts.append(f"Untested functions: {', '.join(fc.uncovered_functions)}")
    if fc.uncovered_lines:
        # Summarise long lists
        shown = fc.uncovered_lines[:20]
        tail = f" … ({len(fc.uncovered_lines) - 20} more)" if len(fc.uncovered_lines) > 20 else ""
        text_parts.append(f"Uncovered lines: {', '.join(str(l) for l in shown)}{tail}")

    return {
        "id": f"coverage:{repo}:{ref}:{fc.path}",
        "title": f"Coverage: {title}",
        "repo": repo,
        "path": fc.path,
        "ref": ref,
        "url": f"{web_base}/{repo}/blob/{ref}/{fc.path}",
        "source": "coverage",
        "coverage_pct": pct,
        "coverage_tier": tier,
        "lines_valid": fc.lines_valid,
        "lines_covered": fc.lines_covered,
        "branch_rate": fc.branch_rate,
        "uncovered_lines": fc.uncovered_lines,
        "uncovered_functions": fc.uncovered_functions,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "text": "\n".join(text_parts),
    }


def _s3_coverage_key(prefix: str, repo: str, ref: str, path: str) -> str:
    safe_path = path.strip("/")
    return f"{prefix.rstrip('/')}/coverage/{repo}/{ref}/{safe_path}.json"


# ---------------------------------------------------------------------------
# Core ingest function
# ---------------------------------------------------------------------------


def ingest_coverage(
    coverage_data: str,
    fmt: str,
    repo: str,
    ref: str,
    bucket: str,
    knowledge_base_id: str,
    data_source_id: str,
    prefix: str,
    web_base: str,
    s3_client: Any,
    bedrock_agent: Any,
) -> tuple[int, str]:
    """Parse and upload coverage docs, then start KB ingestion.

    Returns ``(files_processed, ingestion_job_id)``.
    """
    fmt_lower = (fmt or "cobertura").lower()
    if fmt_lower == "lcov":
        records = parse_lcov(coverage_data)
    else:
        records = parse_cobertura(coverage_data)

    if not records:
        return 0, ""

    for fc in records:
        doc = _build_coverage_doc(fc, repo, ref, web_base)
        key = _s3_coverage_key(prefix, repo, ref, fc.path)
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(doc).encode("utf-8"),
            ContentType="application/json",
        )

    response = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        clientToken=str(uuid.uuid4()),
        description=f"Coverage ingest for {repo}@{ref}",
    )
    job_id = str((response.get("ingestionJob") or {}).get("ingestionJobId") or "")
    return len(records), job_id


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Handle ``POST /coverage/ingest``."""
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    method = http.get("method", "").upper()

    if method != "POST":
        return {"statusCode": 405, "body": json.dumps({"error": "method_not_allowed"})}

    try:
        raw_body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        body = json.loads(raw_body)
    except (json.JSONDecodeError, Exception):  # noqa: BLE001
        return {"statusCode": 400, "body": json.dumps({"error": "invalid_json"})}

    repo_full = (body.get("repo") or "").strip()
    ref = (body.get("ref") or "main").strip()
    fmt = (body.get("format") or "cobertura").strip().lower()
    coverage_data = (body.get("coverage_data") or "").strip()

    if not repo_full or "/" not in repo_full:
        return {"statusCode": 400, "body": json.dumps({"error": "repo (owner/repo) is required"})}
    if not coverage_data:
        return {"statusCode": 400, "body": json.dumps({"error": "coverage_data is required"})}
    if fmt not in ("cobertura", "lcov"):
        return {"statusCode": 400, "body": json.dumps({"error": "format must be cobertura or lcov"})}

    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    bucket = os.environ["KB_SYNC_BUCKET"]
    knowledge_base_id = os.environ["BEDROCK_KNOWLEDGE_BASE_ID"]
    data_source_id = os.environ.get("GITHUB_KB_DATA_SOURCE_ID") or os.environ["BEDROCK_KB_DATA_SOURCE_ID"]
    prefix = os.getenv("GITHUB_KB_SYNC_PREFIX", "github")
    github_api_base = os.getenv("GITHUB_API_BASE", "https://api.github.com")

    # Derive web_base same way as github_kb_sync
    api_base = github_api_base.rstrip("/")
    if api_base == "https://api.github.com":
        web_base = "https://github.com"
    elif api_base.endswith("/api/v3"):
        web_base = api_base[: -len("/api/v3")]
    else:
        web_base = api_base

    s3_client = boto3.client("s3", region_name=region)
    bedrock_agent = boto3.client("bedrock-agent", region_name=region)

    try:
        files_processed, job_id = ingest_coverage(
            coverage_data=coverage_data,
            fmt=fmt,
            repo=repo_full,
            ref=ref,
            bucket=bucket,
            knowledge_base_id=knowledge_base_id,
            data_source_id=data_source_id,
            prefix=prefix,
            web_base=web_base,
            s3_client=s3_client,
            bedrock_agent=bedrock_agent,
        )
    except ValueError as exc:
        return {"statusCode": 422, "body": json.dumps({"error": str(exc)})}
    except Exception:  # noqa: BLE001
        logger.exception("coverage_ingest_failed")
        return {"statusCode": 500, "body": json.dumps({"error": "ingest_failed"})}

    logger.info(
        "coverage_ingest_completed",
        extra={"extra": {"repo": repo_full, "ref": ref, "files": files_processed, "job_id": job_id}},
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "status": "ingested",
                "files_processed": files_processed,
                "ingestion_job_id": job_id,
            }
        ),
    }
