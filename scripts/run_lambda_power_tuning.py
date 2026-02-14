#!/usr/bin/env python3
"""Run AWS Lambda Power Tuning against a target function and emit JSON results."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import boto3

TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}
DEFAULT_POWER_VALUES = [128, 256, 512, 768, 1024, 1536, 2048, 2560, 3008]


def _parse_power_values(raw: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        value = int(candidate)
        if value < 128:
            raise ValueError("Power values must be >= 128 MB")
        values.append(value)
    if not values:
        raise ValueError("At least one power value is required")
    return values


def _load_payload(payload_file: str, payload_json: str) -> dict[str, Any]:
    if payload_file:
        return json.loads(Path(payload_file).read_text())
    if payload_json:
        return json.loads(payload_json)
    return {}


def _wait_for_execution(
    sf_client: Any,
    execution_arn: str,
    poll_interval_seconds: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.time()
    while True:
        result = sf_client.describe_execution(executionArn=execution_arn)
        status = result.get("status", "UNKNOWN")
        if status in TERMINAL_STATUSES:
            return result
        if (time.time() - started) > timeout_seconds:
            raise TimeoutError(
                f"Timed out waiting for Step Functions execution after {timeout_seconds} seconds"
            )
        time.sleep(max(1, poll_interval_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AWS Lambda Power Tuning execution and capture output JSON.")
    parser.add_argument("--state-machine-arn", required=True, help="Lambda Power Tuning Step Functions state machine ARN")
    parser.add_argument("--function-name", required=True, help="Lambda function name, full ARN, or alias-qualified ARN")
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "us-gov-west-1"), help="AWS region")
    parser.add_argument(
        "--strategy",
        default="balanced",
        choices=["cost", "speed", "balanced"],
        help="Optimization strategy",
    )
    parser.add_argument("--num", type=int, default=25, help="Invocations per memory value")
    parser.add_argument(
        "--power-values",
        default=",".join(str(v) for v in DEFAULT_POWER_VALUES),
        help="Comma-separated memory values in MB (for example: 128,256,512,1024)",
    )
    parser.add_argument("--parallel-invocations", action="store_true", help="Enable parallel invocations in tuning")
    parser.add_argument("--balanced-weight", type=float, default=0.5, help="Balanced strategy weight (0.0-1.0)")
    parser.add_argument("--payload-file", default="", help="Path to JSON payload file sent to target Lambda")
    parser.add_argument("--payload-json", default="", help="Inline JSON payload string sent to target Lambda")
    parser.add_argument("--poll-interval-seconds", type=int, default=10, help="Polling interval")
    parser.add_argument("--timeout-seconds", type=int, default=1800, help="Execution timeout")
    parser.add_argument(
        "--output-file",
        default="lambda-power-tuning-result.json",
        help="Where to write execution metadata + parsed tuning output JSON",
    )
    args = parser.parse_args()

    if args.payload_file and args.payload_json:
        raise SystemExit("Use either --payload-file or --payload-json, not both.")

    power_values = _parse_power_values(args.power_values)
    payload = _load_payload(args.payload_file, args.payload_json)

    tuning_input: dict[str, Any] = {
        "lambdaARN": args.function_name,
        "powerValues": power_values,
        "num": max(1, args.num),
        "parallelInvocation": bool(args.parallel_invocations),
        "strategy": args.strategy,
        "payload": payload,
        "autoOptimize": False,
        "balancedWeight": min(max(args.balanced_weight, 0.0), 1.0),
    }

    stepfunctions = boto3.client("stepfunctions", region_name=args.region)
    started = stepfunctions.start_execution(
        stateMachineArn=args.state_machine_arn,
        input=json.dumps(tuning_input),
    )
    execution_arn = started["executionArn"]
    print(f"Started power tuning execution: {execution_arn}")

    execution = _wait_for_execution(
        stepfunctions,
        execution_arn=execution_arn,
        poll_interval_seconds=args.poll_interval_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    status = execution.get("status", "UNKNOWN")
    print(f"Execution status: {status}")

    output_obj: Any = None
    if execution.get("output"):
        try:
            output_obj = json.loads(execution["output"])
        except json.JSONDecodeError:
            output_obj = execution["output"]

    result = {
        "execution_arn": execution_arn,
        "status": status,
        "start_date": str(execution.get("startDate", "")),
        "stop_date": str(execution.get("stopDate", "")),
        "tuning_input": tuning_input,
        "tuning_output": output_obj,
    }
    output_path = Path(args.output_file)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"Wrote results to {output_path}")

    if status == "SUCCEEDED" and isinstance(output_obj, dict):
        recommended_power = output_obj.get("power")
        if recommended_power is not None:
            print(f"Recommended memory: {recommended_power} MB")
        if output_obj.get("cost") is not None:
            print(f"Estimated relative cost: {output_obj.get('cost')}")
        if output_obj.get("duration") is not None:
            print(f"Estimated duration: {output_obj.get('duration')} ms")
        if output_obj.get("stateMachine"):
            print(f"Visualization URL: {output_obj.get('stateMachine')}")

    return 0 if status == "SUCCEEDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
