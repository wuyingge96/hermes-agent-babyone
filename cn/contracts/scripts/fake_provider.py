"""Small local OpenAI-compatible provider used by the frozen-runtime contracts.

The server deliberately has no model dependency.  It records request bodies and
returns a deterministic streaming completion so the contract can prove that a
prompt reached the configured provider and that the gateway forwarded deltas.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _sse_chunk(model: str, delta: dict[str, Any], finish: str | None = None) -> bytes:
    body = {
        "id": "cn-contract",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    chunk = f"data: {json.dumps(body, ensure_ascii=False)}\n\n".encode("utf-8")
    if finish:
        chunk += b"data: [DONE]\n\n"
    return chunk


class FakeProvider:
    """Threaded provider with a stable response and request recorder."""

    def __init__(
        self,
        response_text: str = "CN fake provider response",
        *,
        approval_command: str | None = None,
    ) -> None:
        self.response_text = response_text
        self.approval_command = approval_command
        self.requests: list[dict[str, Any]] = []
        self.request_headers: list[dict[str, str]] = []
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _json(self, status: int, body: dict[str, Any]) -> None:
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if self.path.startswith("/v1/models"):
                    self._json(200, {
                        "object": "list",
                        "data": [{"id": "mock-model", "object": "model", "created": 0}],
                    })
                    return
                self._json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                if not self.path.startswith("/v1/chat/completions"):
                    self._json(404, {"error": "not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length) or b"{}")
                except (ValueError, json.JSONDecodeError):
                    self._json(400, {"error": "invalid JSON"})
                    return
                with owner._lock:
                    owner.requests.append(body)
                    owner.request_headers.append(dict(self.headers.items()))
                model = str(body.get("model") or "mock-model")
                messages = body.get("messages") or []
                approval_prompt = any(
                    message.get("role") == "user"
                    and "CN-APPROVAL-PROMPT" in str(message.get("content") or "")
                    for message in messages
                    if isinstance(message, dict)
                )
                has_tool_result = any(
                    message.get("role") == "tool"
                    for message in messages
                    if isinstance(message, dict)
                )
                emit_approval_call = bool(owner.approval_command and approval_prompt and not has_tool_result)
                tool_call = {
                    "id": "call_cn_approval",
                    "type": "function",
                    "function": {
                        "name": "terminal",
                        "arguments": json.dumps({"command": owner.approval_command}),
                    },
                }
                if body.get("stream") is not True:
                    if emit_approval_call:
                        self._json(200, {
                            "id": "cn-contract", "object": "chat.completion", "created": 0,
                            "model": model,
                            "choices": [{"index": 0, "message": {
                                "role": "assistant", "content": None, "tool_calls": [tool_call],
                            }, "finish_reason": "tool_calls"}],
                        })
                        return
                    self._json(200, {
                        "id": "cn-contract", "object": "chat.completion", "created": 0,
                        "model": model,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": owner.response_text},
                                     "finish_reason": "stop"}],
                    })
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                if emit_approval_call:
                    self.wfile.write(_sse_chunk(model, {"role": "assistant", "content": ""}))
                    self.wfile.write(_sse_chunk(model, {"tool_calls": [{
                        "index": 0,
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {"name": "terminal", "arguments": ""},
                    }]}))
                    self.wfile.write(_sse_chunk(model, {"tool_calls": [{
                        "index": 0,
                        "function": {"arguments": tool_call["function"]["arguments"]},
                    }]}))
                    self.wfile.write(_sse_chunk(model, {}, "tool_calls"))
                    self.wfile.flush()
                    return
                pieces = [owner.response_text[: max(1, len(owner.response_text) // 2)],
                          owner.response_text[max(1, len(owner.response_text) // 2):]]
                for piece in pieces:
                    self.wfile.write(_sse_chunk(model, {"content": piece}))
                    self.wfile.flush()
                self.wfile.write(_sse_chunk(model, {}, "stop"))
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def start(self) -> "FakeProvider":
        self._thread.start()
        return self

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)

