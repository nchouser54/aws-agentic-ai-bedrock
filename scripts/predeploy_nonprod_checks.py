#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def _detect_infra_cli() -> str | None:
    for cli in ("tofu", "terraform"):
        try:
            subprocess.check_output([cli, "version"], text=True)
            return cli
        except Exception:  # noqa: BLE001
            continue
    return None


def _parse_tfvars(path: Path) -> dict[str, str]:
    def _strip_inline_comment(value: str) -> str:
        in_quote = False
        escaped = False
        out: list[str] = []
        for ch in value:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_quote = not in_quote
                out.append(ch)
                continue
            if ch == "#" and not in_quote:
                break
            out.append(ch)
        return "".join(out).strip()

    data: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        cleaned_value = _strip_inline_comment(value)
        data[key.strip()] = cleaned_value.strip().strip('"')
    return data


def _infra_cli_version_ok(cli: str, min_major: int, min_minor: int) -> tuple[bool, str]:
    try:
        output = subprocess.check_output([cli, "version"], text=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"{cli} not available ({exc})"

    match = re.search(r"(?:Terraform|OpenTofu) v(\d+)\.(\d+)\.(\d+)", output)
    if not match:
        return False, f"unable to parse {cli} version"

    major, minor, patch = map(int, match.groups())
    if (major, minor) < (min_major, min_minor):
        return False, f"found {major}.{minor}.{patch}, requires >= {min_major}.{min_minor}.0"

    return True, f"found {major}.{minor}.{patch}"


def _read_required_terraform_version(versions_path: Path) -> tuple[int, int] | None:
    try:
        content = versions_path.read_text()
    except Exception:  # noqa: BLE001
        return None

    # Matches patterns like: required_version = ">= 1.6.0"
    match = re.search(r'required_version\s*=\s*"\s*>=\s*(\d+)\.(\d+)\.(\d+)\s*"', content)
    if not match:
        return None
    major, minor, _patch = map(int, match.groups())
    return major, minor


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-deploy checks for non-prod OpenTofu/Terraform rollout")
    parser.add_argument(
        "--tfvars",
        default="infra/terraform/terraform.nonprod.tfvars.example",
        help="Path to tfvars file to validate",
    )
    args = parser.parse_args()

    tfvars_path = Path(args.tfvars)
    versions_path = Path("infra/terraform/versions.tf")

    failures: list[str] = []
    warnings: list[str] = []

    infra_cli = _detect_infra_cli()
    if infra_cli is None:
        failures.append("neither tofu nor terraform is available in PATH")
        for msg in failures:
            print(f"[FAIL] {msg}")
        return 1

    cli_name = infra_cli

    if not tfvars_path.exists():
        failures.append(f"tfvars file missing: {tfvars_path}")
    if not versions_path.exists():
        failures.append("missing infra/terraform/versions.tf")

    required_tf = _read_required_terraform_version(versions_path)
    min_major, min_minor = required_tf if required_tf is not None else (1, 6)

    ok, tf_msg = _infra_cli_version_ok(cli_name, min_major, min_minor)
    if not ok:
        failures.append(
            f"{cli_name} version check failed: {tf_msg} (required by versions.tf: >= {min_major}.{min_minor}.0)"
        )
    else:
        print(f"[OK] {cli_name} version: {tf_msg}")

    if failures:
        for msg in failures:
            print(f"[FAIL] {msg}")
        return 1

    tfvars = _parse_tfvars(tfvars_path)

    placeholder_markers = {"<SET_KB_ID>", "<SET_KB_DATA_SOURCE_ID>", "<set-me>", ""}

    create_secrets_manager_secrets = tfvars.get("create_secrets_manager_secrets", "false").lower() == "true"
    chatbot_auth_mode = tfvars.get("chatbot_auth_mode", "token").strip().lower()
    webapp_default_auth_mode = tfvars.get("webapp_default_auth_mode", "token").strip().lower()
    environment = tfvars.get("environment", "").strip().lower()
    retrieval_mode = tfvars.get("chatbot_retrieval_mode", "hybrid").strip().lower()
    create_bedrock_kb_resources = tfvars.get("create_bedrock_kb_resources", "false").lower() == "true"
    create_managed_bedrock_kb_role = tfvars.get("create_managed_bedrock_kb_role", "false").lower() == "true"
    create_managed_bedrock_kb_opensearch_collection = (
        tfvars.get("create_managed_bedrock_kb_opensearch_collection", "false").lower() == "true"
    )
    managed_bedrock_kb_opensearch_allow_public = (
        tfvars.get("managed_bedrock_kb_opensearch_allow_public", "false").lower() == "true"
    )
    kb_id = tfvars.get("bedrock_knowledge_base_id", "")
    kb_data_source_id = tfvars.get("bedrock_kb_data_source_id", "")
    managed_kb_role_arn = tfvars.get("managed_bedrock_kb_role_arn", "")
    managed_kb_embedding_model_arn = tfvars.get("managed_bedrock_kb_embedding_model_arn", "")
    managed_kb_opensearch_collection_arn = tfvars.get("managed_bedrock_kb_opensearch_collection_arn", "")
    managed_kb_opensearch_vector_index_name = tfvars.get("managed_bedrock_kb_opensearch_vector_index_name", "")
    managed_kb_opensearch_collection_name = tfvars.get("managed_bedrock_kb_opensearch_collection_name", "")

    if environment == "prod" and chatbot_auth_mode == "token":
        failures.append("environment=prod with chatbot_auth_mode=token is not allowed (use jwt or github_oauth)")

    if chatbot_auth_mode == "token" and webapp_default_auth_mode != "token":
        warnings.append(
            "chatbot_auth_mode=token but webapp_default_auth_mode is not token; this often causes 401/403 in the web UI"
        )
    if chatbot_auth_mode in {"jwt", "github_oauth"} and webapp_default_auth_mode not in {"bearer", "none"}:
        warnings.append(
            "chatbot_auth_mode uses bearer auth but webapp_default_auth_mode is not bearer/none; bearer is usually required for browser calls"
        )

    if create_bedrock_kb_resources:
        missing_managed_inputs: list[str] = []
        if not create_managed_bedrock_kb_role and managed_kb_role_arn in placeholder_markers:
            missing_managed_inputs.append("managed_bedrock_kb_role_arn")
        if managed_kb_embedding_model_arn in placeholder_markers:
            missing_managed_inputs.append("managed_bedrock_kb_embedding_model_arn")
        if (
            not create_managed_bedrock_kb_opensearch_collection
            and managed_kb_opensearch_collection_arn in placeholder_markers
        ):
            missing_managed_inputs.append("managed_bedrock_kb_opensearch_collection_arn")
        if (
            create_managed_bedrock_kb_opensearch_collection
            and managed_kb_opensearch_collection_name in placeholder_markers
        ):
            missing_managed_inputs.append("managed_bedrock_kb_opensearch_collection_name")
        if managed_kb_opensearch_vector_index_name in placeholder_markers:
            missing_managed_inputs.append("managed_bedrock_kb_opensearch_vector_index_name")

        if missing_managed_inputs:
            failures.append(
                "create_bedrock_kb_resources=true is missing required values: " + ", ".join(missing_managed_inputs)
            )

    if environment == "prod" and create_managed_bedrock_kb_opensearch_collection and managed_bedrock_kb_opensearch_allow_public:
        failures.append(
            "In prod, managed_bedrock_kb_opensearch_allow_public must be false when create_managed_bedrock_kb_opensearch_collection=true"
        )

    if retrieval_mode == "kb" and not create_bedrock_kb_resources and kb_id in placeholder_markers:
        failures.append("chatbot_retrieval_mode=kb requires bedrock_knowledge_base_id to be set")
    elif retrieval_mode == "hybrid" and not create_bedrock_kb_resources and kb_id in placeholder_markers:
        warnings.append(
            "chatbot_retrieval_mode=hybrid without bedrock_knowledge_base_id will run in live fallback mode until KB ID is set"
        )

    if not create_secrets_manager_secrets:
        required_existing_secret_arns = [
            "existing_github_webhook_secret_arn",
            "existing_github_app_private_key_secret_arn",
            "existing_github_app_ids_secret_arn",
            "existing_atlassian_credentials_secret_arn",
        ]
        for key in required_existing_secret_arns:
            if tfvars.get(key, "") in placeholder_markers:
                failures.append(f"create_secrets_manager_secrets=false requires {key}")

        if chatbot_auth_mode == "token" and tfvars.get("existing_chatbot_api_token_secret_arn", "") in placeholder_markers:
            failures.append(
                "chatbot_auth_mode=token requires existing_chatbot_api_token_secret_arn when create_secrets_manager_secrets=false"
            )

        teams_adapter_enabled = tfvars.get("teams_adapter_enabled", "").lower() == "true"
        if teams_adapter_enabled and tfvars.get("existing_teams_adapter_token_secret_arn", "") in placeholder_markers:
            failures.append(
                "teams_adapter_enabled=true requires existing_teams_adapter_token_secret_arn when create_secrets_manager_secrets=false"
            )

    if tfvars.get("environment") != "nonprod":
        warnings.append(f"environment is '{tfvars.get('environment', '<missing>')}', expected 'nonprod'")

    if retrieval_mode != "hybrid":
        warnings.append(
            f"chatbot_retrieval_mode is '{tfvars.get('chatbot_retrieval_mode', '<missing>')}', recommended 'hybrid'"
        )

    kb_sync_enabled = tfvars.get("kb_sync_enabled", "").lower() == "true"
    if not kb_sync_enabled:
        warnings.append("kb_sync_enabled is not true (scheduled sync disabled)")
    else:
        if not create_bedrock_kb_resources and kb_id in placeholder_markers:
            failures.append("kb_sync_enabled=true requires bedrock_knowledge_base_id")
        if not create_bedrock_kb_resources and kb_data_source_id in placeholder_markers:
            failures.append("kb_sync_enabled=true requires bedrock_kb_data_source_id")

    github_kb_enabled = tfvars.get("github_kb_sync_enabled", "").lower() == "true"
    if github_kb_enabled:
        repos = tfvars.get("github_kb_repos", "")
        if repos in {"", "[]"}:
            failures.append("github_kb_sync_enabled=true but github_kb_repos is empty")

        gh_data_source = tfvars.get("github_kb_data_source_id", "")
        base_data_source = tfvars.get("bedrock_kb_data_source_id", "")
        if gh_data_source in placeholder_markers and base_data_source in placeholder_markers:
            failures.append(
                "github_kb_sync_enabled=true but neither github_kb_data_source_id nor bedrock_kb_data_source_id is set"
            )

    if tfvars.get("dry_run", "").lower() != "true":
        warnings.append("dry_run is not true; first non-prod rollout is safer with dry_run=true")

    if tfvars.get("teams_adapter_enabled", "").lower() == "true":
        warnings.append("teams_adapter_enabled=true (ensure this is intentional for non-prod)")

    if failures:
        for msg in failures:
            print(f"[FAIL] {msg}")
    else:
        print("[OK] mode-specific KB requirements are satisfied")

    for msg in warnings:
        print(f"[WARN] {msg}")

    if failures:
        print("\nResult: NOT READY for apply")
        return 2

    print(f"\nResult: READY for {cli_name} plan/apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
