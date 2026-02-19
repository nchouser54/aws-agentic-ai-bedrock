from __future__ import annotations

import fnmatch
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3

from shared.ast_parser import build_symbol_text, parse_file, symbol_doc_id
from shared.constants import DEFAULT_REGION
from shared.github_app_auth import GitHubAppAuth
from shared.github_client import GitHubClient
from shared.logging import get_logger

logger = get_logger("github_kb_sync")


def _parse_csv_list(value: str, default: list[str] | None = None) -> list[str]:
    items = [item.strip() for item in (value or "").split(",") if item.strip()]
    if items:
        return items
    return list(default or [])


def _parse_repo(value: str) -> tuple[str, str] | None:
    parts = [p.strip() for p in value.split("/", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _api_base_to_web_base(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base == "https://api.github.com":
        return "https://github.com"
    if base.endswith("/api/v3"):
        return base[: -len("/api/v3")]
    return base


def _matches(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
    return False


def _s3_key(prefix: str, owner: str, repo: str, ref: str, path: str, symbol: str = "") -> str:
    safe_path = path.strip("/")
    if symbol:
        safe_symbol = re.sub(r"[^\w.\-]", "_", symbol)
        return f"{prefix.rstrip('/')}/repos/{owner}/{repo}/{ref}/{safe_path}.{safe_symbol}.json"
    return f"{prefix.rstrip('/')}/repos/{owner}/{repo}/{ref}/{safe_path}.json"


def _build_doc(*, owner: str, repo: str, ref: str, path: str, text: str, web_base: str) -> dict[str, Any]:
    title = Path(path).name or path
    return {
        "id": f"{owner}/{repo}:{ref}:{path}",
        "title": title,
        "repo": f"{owner}/{repo}",
        "path": path,
        "ref": ref,
        "url": f"{web_base}/{owner}/{repo}/blob/{ref}/{path}",
        "source": "github",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "text": text,
    }


def lambda_handler(_event: dict[str, Any], _context: Any) -> dict[str, Any]:
    region = os.getenv("AWS_REGION", DEFAULT_REGION)
    api_base = os.getenv("GITHUB_API_BASE", "https://api.github.com")
    app_ids_secret_arn = os.environ["GITHUB_APP_IDS_SECRET_ARN"]
    private_key_secret_arn = os.environ["GITHUB_APP_PRIVATE_KEY_SECRET_ARN"]
    knowledge_base_id = os.environ["BEDROCK_KNOWLEDGE_BASE_ID"]
    data_source_id = os.getenv("GITHUB_KB_DATA_SOURCE_ID", "").strip() or os.environ["BEDROCK_KB_DATA_SOURCE_ID"]
    bucket = os.environ["KB_SYNC_BUCKET"]

    repos = _parse_csv_list(os.getenv("GITHUB_KB_REPOS", ""))
    include_patterns = _parse_csv_list(
        os.getenv("GITHUB_KB_INCLUDE_PATTERNS", ""),
        default=["README.md", "docs/**", "**/*.md"],
    )
    # Source-code patterns to parse at symbol level (functions/classes)
    source_patterns = _parse_csv_list(os.getenv("GITHUB_KB_SOURCE_PATTERNS", ""))
    symbol_ingestion_enabled = bool(source_patterns)
    prefix = os.getenv("GITHUB_KB_SYNC_PREFIX", "github")
    max_files_per_repo = max(1, int(os.getenv("GITHUB_KB_MAX_FILES_PER_REPO", "200")))
    ref_override = os.getenv("GITHUB_KB_REF", "").strip()

    auth = GitHubAppAuth(
        app_ids_secret_arn=app_ids_secret_arn,
        private_key_secret_arn=private_key_secret_arn,
        api_base=api_base,
    )
    gh = GitHubClient(token_provider=auth.get_installation_token, api_base=api_base)

    s3 = boto3.client("s3", region_name=region)
    bedrock_agent = boto3.client("bedrock-agent", region_name=region)
    web_base = _api_base_to_web_base(api_base)

    uploaded = 0
    failed = 0
    skipped = 0
    repos_processed = 0

    for repo_slug in repos:
        parsed = _parse_repo(repo_slug)
        if not parsed:
            logger.warning("invalid_repo_slug", extra={"extra": {"repo": repo_slug}})
            failed += 1
            continue

        owner, repo = parsed
        repos_processed += 1

        try:
            effective_ref = ref_override
            if not effective_ref:
                metadata = gh.get_repository(owner, repo)
                effective_ref = str(metadata.get("default_branch") or "main")

            files = gh.list_repository_files(owner, repo, effective_ref)
            matches = [path for path in files if _matches(path, include_patterns)]
            if symbol_ingestion_enabled:
                source_matches = [path for path in files if _matches(path, source_patterns)]
                # merge without duplicates, source-code files first
                all_paths = list(dict.fromkeys(source_matches + matches))
            else:
                all_paths = matches
            matches = all_paths[:max_files_per_repo]

            for path in matches:
                try:
                    text, _sha = gh.get_file_contents(owner, repo, path, effective_ref)
                    text = (text or "").strip()
                    if not text:
                        skipped += 1
                        continue

                    # Always emit a file-level doc
                    doc = _build_doc(
                        owner=owner,
                        repo=repo,
                        ref=effective_ref,
                        path=path,
                        text=text,
                        web_base=web_base,
                    )
                    s3.put_object(
                        Bucket=bucket,
                        Key=_s3_key(prefix, owner, repo, effective_ref, path),
                        Body=json.dumps(doc).encode("utf-8"),
                        ContentType="application/json",
                    )
                    uploaded += 1

                    # Emit per-symbol docs when source_patterns matched
                    if symbol_ingestion_enabled and _matches(path, source_patterns):
                        parsed = parse_file(path, text)
                        for sym in parsed.symbols:
                            sym_text = build_symbol_text(sym, path)
                            sym_doc = {
                                "id": symbol_doc_id(f"{owner}/{repo}", path, sym.symbol_name, effective_ref),
                                "title": f"{sym.symbol_name} ({sym.symbol_type})",
                                "repo": f"{owner}/{repo}",
                                "path": path,
                                "ref": effective_ref,
                                "url": f"{web_base}/{owner}/{repo}/blob/{effective_ref}/{path}#L{sym.line_start}",
                                "source": "github",
                                "symbol_type": sym.symbol_type,
                                "symbol_name": sym.symbol_name,
                                "signature": sym.signature,
                                "language": sym.language,
                                "line_start": sym.line_start,
                                "line_end": sym.line_end,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                                "text": sym_text,
                            }
                            s3.put_object(
                                Bucket=bucket,
                                Key=_s3_key(prefix, owner, repo, effective_ref, path, sym.symbol_name),
                                Body=json.dumps(sym_doc).encode("utf-8"),
                                ContentType="application/json",
                            )
                            uploaded += 1
                except Exception:
                    logger.exception("github_doc_sync_failed", extra={"extra": {"repo": repo_slug, "path": path}})
                    failed += 1
        except Exception:
            logger.exception("github_repo_sync_failed", extra={"extra": {"repo": repo_slug}})
            failed += 1

    ingestion_job_id = ""
    if uploaded > 0:
        response = bedrock_agent.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
            clientToken=str(uuid.uuid4()),
            description="GitHub docs sync from chatbot platform",
        )
        ingestion_job_id = str((response.get("ingestionJob") or {}).get("ingestionJobId") or "")

    logger.info(
        "github_kb_sync_completed",
        extra={
            "extra": {
                "repos_processed": repos_processed,
                "uploaded": uploaded,
                "failed": failed,
                "skipped": skipped,
                "ingestion_job_id": ingestion_job_id,
                "knowledge_base_id": knowledge_base_id,
            }
        },
    )

    return {
        "repos_processed": repos_processed,
        "uploaded": uploaded,
        "failed": failed,
        "skipped": skipped,
        "ingestion_job_id": ingestion_job_id,
        "knowledge_base_id": knowledge_base_id,
    }
