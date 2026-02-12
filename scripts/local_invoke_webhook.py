#!/usr/bin/env python3
import base64
import json
import os
import pathlib
import subprocess
import sys

sys.path.append("src")
from webhook_receiver.app import lambda_handler  # noqa: E402


def main() -> int:
    payload_path = pathlib.Path("scripts/sample_pull_request_opened.json")
    payload_bytes = payload_path.read_bytes()

    webhook_secret = os.getenv("WEBHOOK_SECRET", "local-dev-secret")
    signature = subprocess.check_output(
        [sys.executable, "scripts/generate_signature.py", webhook_secret, str(payload_path)],
        text=True,
    ).strip()

    event = {
        "headers": {
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "local-delivery-123",
            "X-Hub-Signature-256": signature,
        },
        "isBase64Encoded": True,
        "body": base64.b64encode(payload_bytes).decode("utf-8"),
    }

    out = lambda_handler(event, None)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
