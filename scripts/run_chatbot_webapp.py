#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.server
import socketserver
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local static webapp for chatbot UI")
    parser.add_argument("--port", type=int, default=8080, help="Local port to serve webapp")
    parser.add_argument(
        "--dir",
        default="webapp",
        help="Directory to serve (defaults to webapp)",
    )
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Directory not found: {root}")

    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", args.port), handler) as httpd:
        print(f"Serving {root.resolve()} on http://localhost:{args.port}")
        print("Press Ctrl+C to stop")
        try:
            import os

            os.chdir(root)
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
