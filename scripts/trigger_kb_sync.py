#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

import boto3


def main() -> int:
    parser = argparse.ArgumentParser(description="Invoke Confluence->KB sync Lambda and print response")
    parser.add_argument("--function-name", required=True, help="KB sync Lambda function name")
    parser.add_argument("--region", default="us-gov-west-1", help="AWS region")
    parser.add_argument("--qualifier", default="", help="Optional Lambda version or alias")
    args = parser.parse_args()

    client = boto3.client("lambda", region_name=args.region)
    invoke_args = {
        "FunctionName": args.function_name,
        "InvocationType": "RequestResponse",
        "Payload": b"{}",
    }
    if args.qualifier:
        invoke_args["Qualifier"] = args.qualifier

    response = client.invoke(**invoke_args)
    payload_bytes = response["Payload"].read()
    payload = json.loads(payload_bytes.decode("utf-8") or "{}")

    print(json.dumps(payload, indent=2))
    status = int(response.get("StatusCode", 500))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
