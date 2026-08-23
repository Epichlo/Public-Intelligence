#!/usr/bin/env python3
"""A stand-in Ollama server for environments that have neither Ollama nor a GPU.

The Node treats Ollama as an external HTTP dependency: it lists models from
`/api/tags`, asks for context lengths from `/api/show`, and generates from
`/api/generate`. This script serves exactly those endpoints -- and nothing else --
with one deterministic model, so a topology without a model daemon (CI, or a
container stack) can still exercise everything between the gateway and the model.

It exists because the model daemon is out of scope for the topology under test,
NOT because any part of the stack under test is fake: the node, scheduler, mesh
transport, gateway and credential path it serves are all the real system.

Used by the `fake-ollama` profile in docker-compose.test.yml:

    docker compose -f docker-compose.test.yml --profile fake-ollama up
    # with NODE_OLLAMA_HOST=http://ollama-spoof:11434 on the workers

Stdlib only, so the image that ships it needs no pip install at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The one model this server hosts. docker-compose.test.yml's end-to-end job
# requests it by name; the matchmaker filters nodes on advertised model names, so
# the name must match what the requester asks for.
MODEL_NAME = "ci-test-model"

# A digest is required for the node's context-length resolution path; it keys the
# cache in node/clients/ollama.py. Content never changes, so the digest never does.
MODEL_DIGEST = "sha256:" + hashlib.sha256(MODEL_NAME.encode("utf-8")).hexdigest()


def generated_text(model: str, prompt: str) -> str:
    """Deterministic completion body.

    Embeds a prompt digest so a green assertion proves the request travelled the
    whole path -- the gateway's prompt is what comes back -- rather than merely
    that SOME 200 arrived.
    """
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    return f"[spoof-ollama:{model}:{digest}] echo of {len(prompt)} chars"


class Handler(BaseHTTPRequestHandler):
    """The three Ollama endpoints the Node reads, and nothing else."""

    server_version = "spoof-ollama/1.0"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:
        if self.path == "/":
            self._send_json({"status": "ok", "spoof": True})
        elif self.path == "/api/tags":
            self._send_json(
                {
                    "models": [
                        {
                            "name": MODEL_NAME,
                            "model": MODEL_NAME,
                            "size": 2048,
                            "digest": MODEL_DIGEST,
                            "details": {"family": "spoof", "parameter_size": "0B"},
                        }
                    ]
                }
            )
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/api/show":
            # Empty model_info sends the node down its documented fallback (2048);
            # the real endpoint is only consulted to resolve a context length.
            self._send_json({"model_info": {}})
        elif self.path == "/api/generate":
            body = self._read_json()
            model = str(body.get("model") or MODEL_NAME)
            prompt = str(body.get("prompt") or "")
            text = generated_text(model, prompt)
            if body.get("stream"):
                # NDJSON lines -- the framing node/clients/ollama.py iterates. No
                # chunked encoding: the handler speaks HTTP/1.0 by default, where
                # the connection close is what ends the body.
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                halves = (text[: len(text) // 2], text[len(text) // 2 :])
                for chunk in halves:
                    line = json.dumps({"model": model, "response": chunk, "done": False}).encode(
                        "utf-8"
                    )
                    self.wfile.write(line + b"\n")
                    self.wfile.flush()
                final = json.dumps({"model": model, "response": "", "done": True})
                self.wfile.write(final.encode("utf-8") + b"\n")
                self.wfile.flush()
            else:
                self._send_json({"model": model, "response": text, "done": True})
        else:
            self._send_json({"error": "not found"}, status=404)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        print(f"[spoof-ollama] {self.address_string()} {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11434)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[spoof-ollama] serving model {MODEL_NAME!r} on {args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
