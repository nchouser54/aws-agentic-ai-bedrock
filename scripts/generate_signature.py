#!/usr/bin/env python3
import hashlib
import hmac
import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: generate_signature.py <webhook_secret> <payload_file>")
        return 1

    secret = sys.argv[1].encode("utf-8")
    payload_file = pathlib.Path(sys.argv[2])
    body = payload_file.read_bytes()

    signature = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    print(signature)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
