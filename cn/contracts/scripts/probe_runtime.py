#!/usr/bin/env python3
"""Probe the standalone runtime through the same HTTP/JSON-RPC boundary as Electron.

The probe deliberately avoids model calls.  It verifies that a frozen runtime is
reachable, authenticated, and able to serve the desktop session metadata paths.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def http_json(
    base_url: str, path: str, token: str | None, timeout: float,
    *, method: str = "GET", payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, raw


def require_status(base_url: str, path: str, token: str | None, expected: set[int], timeout: float) -> Any:
    status, body = http_json(base_url, path, token, timeout)
    if status not in expected:
        raise RuntimeError(f"{path} returned HTTP {status}, expected {sorted(expected)}: {body!r}")
    return body


def as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class RpcClient:
    def __init__(self, websocket: Any, timeout: float) -> None:
        self.websocket = websocket
        self.timeout = timeout
        self.next_id = 1
        self.events: list[dict[str, Any]] = []

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = str(self.next_id)
        self.next_id += 1
        await self.websocket.send(json.dumps({
            "jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {},
        }))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            frame = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=remaining))
            if frame.get("method") == "event":
                self.events.append(frame)
                continue
            if str(frame.get("id")) != request_id:
                continue
            if "error" in frame:
                raise RuntimeError(f"RPC {method} failed: {frame['error']!r}")
            result = frame.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"RPC {method} returned a non-object result: {result!r}")
            return result
        raise TimeoutError(f"timed out waiting for RPC {method}")


async def probe_websocket(base_url: str, token: str, timeout: float) -> dict[str, Any]:
    try:
        import websockets
    except ImportError as error:  # pragma: no cover - build dependency validation catches this earlier
        raise RuntimeError("the probe requires the websockets package") from error

    ws_url = base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
    ws_url = f"{ws_url}/api/ws?token={urllib.parse.quote(token)}"

    unauthenticated_rejected = False
    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(f"{base_url.replace('http://', 'ws://', 1)}/api/ws"):
                pass
    except Exception:
        unauthenticated_rejected = True
    if not unauthenticated_rejected:
        raise RuntimeError("/api/ws accepted a connection without a token")

    async with asyncio.timeout(timeout):
        async with websockets.connect(ws_url) as websocket:
            client = RpcClient(websocket, timeout)
            ready = None
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                frame = json.loads(await asyncio.wait_for(websocket.recv(), timeout=timeout))
                if frame.get("method") == "event":
                    client.events.append(frame)
                    params = frame.get("params")
                    if isinstance(params, dict) and params.get("type") == "gateway.ready":
                        ready = params
                        break
            if ready is None:
                raise RuntimeError("/api/ws did not emit gateway.ready")

            # Empty drafts are intentionally kept in memory until the first prompt.  Seed one
            # transcript row so the REST history route observes the same durable session that
            # the desktop can resume without invoking a model provider.
            created = await client.call("session.create", {
                "source": "desktop",
                "title": "CN contract probe",
                "messages": [{"role": "user", "content": "CN contract probe seed"}],
            })
            for field in ("session_id", "stored_session_id", "messages", "info"):
                if field not in created:
                    raise RuntimeError(f"session.create result is missing {field!r}: {created!r}")
            stored_id = created["stored_session_id"]
            if not isinstance(stored_id, str) or not stored_id:
                raise RuntimeError(f"session.create returned an invalid stored_session_id: {created!r}")

            resumed = await client.call("session.resume", {"session_id": stored_id})
            if resumed.get("session_id") in (None, ""):
                raise RuntimeError(f"session.resume returned no runtime session_id: {resumed!r}")

            catalog = await client.call("commands.catalog")
            for field in ("pairs", "sub", "canon", "commands", "categories", "skills", "skill_count"):
                if field not in catalog:
                    raise RuntimeError(f"commands.catalog result is missing {field!r}: {catalog!r}")

            reloaded = await client.call("skills.reload")
            diff = reloaded.get("result")
            if not isinstance(diff, dict) or "total" not in diff:
                raise RuntimeError(f"skills.reload result has no diff total: {reloaded!r}")

            return {
                "gateway_ready": True,
                "session_create": True,
                "session_resume": True,
                "commands_catalog": True,
                "skills_reload": True,
                "stored_session_id": stored_id,
                "event_count": len(client.events),
            }


def probe(base_url: str, token: str, timeout: float) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    status = require_status(base_url, "/api/status", None, {200}, timeout)
    openapi = require_status(base_url, "/openapi.json", None, {200}, timeout)
    if not isinstance(status, dict) or not isinstance(openapi, dict):
        raise RuntimeError("public health routes did not return JSON objects")

    private_paths = ("/api/config", "/api/sessions", "/api/tools/toolsets")
    unauthenticated = {
        path: http_json(base_url, path, None, timeout)[0]
        for path in private_paths
    }
    if any(code not in {401, 403} for code in unauthenticated.values()):
        raise RuntimeError(f"private REST routes did not reject missing auth: {unauthenticated}")

    authenticated: dict[str, int] = {}
    authenticated_bodies: dict[str, Any] = {}
    for path in private_paths:
        code, body = http_json(base_url, path, token, timeout)
        authenticated[path] = code
        authenticated_bodies[path] = body
        if code != 200:
            raise RuntimeError(f"authenticated {path} returned HTTP {code}")

    config = authenticated_bodies["/api/config"]
    if not isinstance(config, dict):
        raise RuntimeError(f"authenticated /api/config returned a non-object: {config!r}")
    provider_id = "custom:skillhub"
    provider_url = "https://skillhub-api.icloud.babybus.com/sb-api/openai/v1"
    model_name = "cn-contract-model"
    provider = {
        "name": "BabyBus SkillHub",
        "base_url": provider_url,
        "api_mode": "chat_completions",
        "transport": "openai_chat",
        "model": model_name,
        "models": {model_name: {}},
        "api_key": "cn-contract-placeholder-token",
    }
    next_config = {
        **config,
        "providers": {**as_record(config.get("providers")), provider_id: provider},
        "model": {
            **as_record(config.get("model")),
            "provider": provider_id,
            "default": model_name,
            "name": provider["name"],
            "base_url": provider_url,
            "api_mode": provider["api_mode"],
            "transport": provider["transport"],
            "api_key": provider["api_key"],
        },
    }
    saved_status, saved = http_json(
        base_url, "/api/config", token, timeout,
        method="PUT", payload={"config": next_config},
    )
    if saved_status != 200 or not isinstance(saved, dict) or saved.get("ok") is not True:
        raise RuntimeError(f"SkillHub config PUT failed with HTTP {saved_status}: {saved!r}")
    config_status, reloaded = http_json(base_url, "/api/config", token, timeout)
    if config_status != 200 or not isinstance(reloaded, dict):
        raise RuntimeError(f"SkillHub config re-read failed with HTTP {config_status}")
    actual_provider = as_record(as_record(reloaded.get("providers")).get(provider_id))
    if any(actual_provider.get(key) != provider[key] for key in provider):
        raise RuntimeError("SkillHub provider fields did not survive the config round trip")
    if reloaded.get("model") != model_name:
        raise RuntimeError("SkillHub model name did not survive the config round trip")
    sessions = authenticated_bodies["/api/sessions"]
    if not isinstance(sessions, (dict, list)):
        raise RuntimeError(f"authenticated /api/sessions returned an invalid JSON value: {sessions!r}")
    legacy_toolsets = authenticated_bodies["/api/tools/toolsets"]
    if not isinstance(legacy_toolsets, (dict, list)):
        raise RuntimeError(
            "authenticated /api/tools/toolsets returned an invalid JSON value: "
            f"{legacy_toolsets!r}"
        )

    # Older client revisions probe /api/tools first and fall back to the
    # current toolset catalog route. Preserve that compatibility contract.
    legacy_tools_status, tools_body = http_json(base_url, "/api/tools", token, timeout)
    if legacy_tools_status not in {200, 404}:
        raise RuntimeError(f"authenticated /api/tools returned unexpected HTTP {legacy_tools_status}")
    if legacy_tools_status == 200 and not isinstance(tools_body, dict):
        raise RuntimeError(f"authenticated /api/tools returned a non-object: {tools_body!r}")

    websocket = asyncio.run(probe_websocket(base_url, token, timeout))
    stored_session_id = websocket["stored_session_id"]
    messages_path = f"/api/sessions/{urllib.parse.quote(stored_session_id, safe='')}/messages"
    messages_status, messages = http_json(base_url, messages_path, token, timeout)
    if messages_status != 200:
        raise RuntimeError(f"authenticated {messages_path} returned HTTP {messages_status}: {messages!r}")
    if not isinstance(messages, (dict, list)):
        raise RuntimeError(f"authenticated {messages_path} returned an invalid JSON value: {messages!r}")
    message_rows = messages.get("messages", []) if isinstance(messages, dict) else messages
    if not isinstance(message_rows, list) or not any(
        isinstance(row, dict) and row.get("role") == "user"
        and row.get("content") == "CN contract probe seed"
        for row in message_rows
    ):
        raise RuntimeError("session history did not contain the seeded user message")
    sessions_status, sessions_body = http_json(base_url, "/api/sessions?limit=100&offset=0", token, timeout)
    session_rows = sessions_body.get("sessions", []) if isinstance(sessions_body, dict) else []
    if sessions_status != 200 or not any(
        isinstance(row, dict) and row.get("id") == stored_session_id for row in session_rows
    ):
        raise RuntimeError("session listing did not contain the created session")
    delete_path = f"/api/sessions/{urllib.parse.quote(stored_session_id, safe='')}"
    delete_status, deleted = http_json(base_url, delete_path, token, timeout, method="DELETE")
    if delete_status != 200 or not isinstance(deleted, dict) or deleted.get("ok") is not True:
        raise RuntimeError(f"session deletion failed with HTTP {delete_status}: {deleted!r}")
    missing_status, _ = http_json(base_url, messages_path, token, timeout)
    if missing_status != 404:
        raise RuntimeError(f"deleted session history remained accessible: HTTP {missing_status}")
    return {
        "ok": True,
        "status": 200,
        "openapi": 200,
        "unauthenticated": unauthenticated,
        "authenticated": authenticated,
        "skillhub_config_round_trip": True,
        "legacy_tools_status": legacy_tools_status,
        "session_messages": 200,
        "session_rest_round_trip": True,
        "websocket": websocket,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", default="cn-contract-token")
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    print(json.dumps(probe(args.base_url, args.token, args.timeout), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
