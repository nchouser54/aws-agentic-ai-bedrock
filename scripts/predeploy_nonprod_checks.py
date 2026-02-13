#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def _parse_tfvars(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def _terraform_version_ok(min_major: int, min_minor: int) -> tuple[bool, str]:
    try:
        output = subprocess.check_output(["terraform", "version"], text=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"terraform not available ({exc})"

    match = re.search(r"Terraform v(\d+)\.(\d+)\.(\d+)", output)
    if not match:
        return False, "unable to parse terraform version"

    major, minor, patch = map(int, match.groups())
    if (major, minor) < (min_major, min_minor):
        return False, f"found {major}.{minor}.{patch}, requires >= {min_major}.{min_minor}.0"

    return True, f"found {major}.{minor}.{patch}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-deploy checks for non-prod Terraform rollout")
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

    if not tfvars_path.exists():
        failures.append(f"tfvars file missing: {tfvars_path}")
    if not versions_path.exists():
        failures.append("missing infra/terraform/versions.tf")

    ok, tf_msg = _terraform_version_ok(1, 6)
    if not ok:
        failures.append(f"terraform version check failed: {tf_msg}")
    else:
        print(f"[OK] terraform version: {tf_msg}")

    if failures:
        for msg in failures:
            print(f"[FAIL] {msg}")
        return 1

    tfvars = _parse_tfvars(tfvars_path)

    required_values = ["bedrock_knowledge_base_id", "bedrock_kb_data_source_id"]
    placeholder_markers = {"<SET_KB_ID>", "<SET_KB_DATA_SOURCE_ID>", "<set-me>", ""}

    for key in required_values:
        val = tfvars.get(key, "")
        if val in placeholder_markers:
            failures.append(f"{key} is not set (current: {val or '<empty>'})")

    if tfvars.get("environment") != "nonprod":
        warnings.append(f"environment is '{tfvars.get('environment', '<missing>')}', expected 'nonprod'")

    if tfvars.get("chatbot_retrieval_mode") != "hybrid":
        warnings.append(
            f"chatbot_retrieval_mode is '{tfvars.get('chatbot_retrieval_mode', '<missing>')}', recommended 'hybrid'"
        )

    if tfvars.get("kb_sync_enabled", "").lower() != "true":
        warnings.append("kb_sync_enabled is not true (scheduled sync disabled)")

    if tfvars.get("dry_run", "").lower() != "true":
        warnings.append("dry_run is not true; first non-prod rollout is safer with dry_run=true")

    if tfvars.get("teams_adapter_enabled", "").lower() == "true":
        warnings.append("teams_adapter_enabled=true (ensure this is intentional for non-prod)")

    if failures:
        for msg in failures:
            print(f"[FAIL] {msg}")
    else:
        print("[OK] required KB values are set")

    for msg in warnings:
        print(f"[WARN] {msg}")

    if failures:
        print("\nResult: NOT READY for apply")
        return 2

    print("\nResult: READY for terraform plan/apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
