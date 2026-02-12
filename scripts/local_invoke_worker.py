#!/usr/bin/env python3
import json
import sys

sys.path.append("src")
from worker.app import lambda_handler  # noqa: E402


def main() -> int:
    message = {
        "delivery_id": "local-delivery-123",
        "repo_full_name": "example-org/example-repo",
        "pr_number": 42,
        "head_sha": "0123456789abcdef0123456789abcdef01234567",
        "installation_id": 12345678,
        "event_action": "opened",
    }

    event = {
        "Records": [
            {
                "messageId": "local-message-1",
                "body": json.dumps(message),
            }
        ]
    }

    out = lambda_handler(event, None)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
