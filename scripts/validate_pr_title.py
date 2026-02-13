#!/usr/bin/env python3
"""Validate PR titles against repository convention.

This script is intentionally lightweight and stdlib-only so it can run in CI
without additional dependencies.
"""

from __future__ import annotations

import re
import sys

PATTERN = re.compile(r"^(feat|fix|chore)\([a-z0-9_-]+\): .+")


def main() -> int:
    if len(sys.argv) < 2:
        print("::warning::No PR title provided; skipping convention check.")
        return 0

    title = sys.argv[1].strip()
    if PATTERN.match(title):
        print(f"PR title matches convention: {title}")
        return 0

    print("::warning::PR title does not match optional convention.")
    print("Expected format: feat(scope): short outcome")
    print("Also allowed: fix(scope): ..., chore(scope): ...")
    print(f"Received: {title}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())