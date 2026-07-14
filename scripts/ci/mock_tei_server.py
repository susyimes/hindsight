#!/usr/bin/env python3
"""Small deterministic TEI-compatible embeddings server for CI smoke tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_DIMENSION = 32
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def embed_text(text: str) -> list[float]:
    vector = [0.0] * _DIMENSION
    for token in _TOKEN_PATTERN.findall(text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % _DIMENSION
        vector[index] += 1.0 if digest[2] & 1 else -1.0

    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        vector[0] = 1.0
        return vector
    return [value / magnitude for value in vector]


class MockTEIHandler(BaseHTTPRequestHandler):
    server_version = "HindsightMockTEI/1.0"

    def _write_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/health":
            self._write_json(200, {"status": "ok"})
        elif self.path == "/info":
            self._write_json(200, {"model_id": "hindsight-ci-deterministic", "dimension": _DIMENSION})
        else:
            self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/embed":
            self._write_json(404, {"error": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(content_length))
            inputs = request["inputs"]
            if isinstance(inputs, str):
                inputs = [inputs]
            if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs):
                raise ValueError("inputs must be a string or list of strings")
        except (ValueError, KeyError, json.JSONDecodeError) as error:
            self._write_json(400, {"error": str(error)})
            return

        self._write_json(200, [embed_text(item) for item in inputs])

    def log_message(self, format_string: str, *args: Any) -> None:
        # Request bodies may contain retained text; CI only needs endpoint-level logs.
        print(f"mock-tei {self.command} {self.path} {args[1]}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockTEIHandler)
    print(f"mock-tei listening on {args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
