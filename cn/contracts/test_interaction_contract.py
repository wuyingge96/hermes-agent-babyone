"""Frozen-runtime contracts for provider streaming and client attachments."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from typing import Any

from cn.contracts.scripts.fake_provider import FakeProvider


REPO = Path(__file__).resolve().parents[2]
CLIENT_PLUGIN = REPO.parent / "erp-assistant-electron" / "resources" / "hermes-plugins" / "babybus-skillhub-session-header"
SKILLHUB_URL = "https://skillhub-api.icloud.babybus.com/sb-api/openai/v1"
PNG = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\x0dIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")


class RpcClient:
    def __init__(self, websocket: Any, timeout: float = 60) -> None:
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
            frame = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=self.timeout))
            if frame.get("method") == "event":
                self.events.append(frame)
                continue
            if str(frame.get("id")) != request_id:
                continue
            if "error" in frame:
                raise AssertionError(f"RPC {method} failed: {frame['error']!r}")
            result = frame.get("result")
            if not isinstance(result, dict):
                raise AssertionError(f"RPC {method} returned {result!r}")
            return result
        raise AssertionError(f"timed out waiting for {method}")

    async def next_event(self, event_type: str, session_id: str | None, timeout: float = 90) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = json.loads(await asyncio.wait_for(self.websocket.recv(), timeout=timeout))
            if frame.get("method") != "event":
                continue
            self.events.append(frame)
            params = frame.get("params") or {}
            if params.get("type") == event_type and (session_id is None or params.get("session_id") == session_id):
                return params
        raise AssertionError(f"timed out waiting for event {event_type}")


class InteractionContractTests(unittest.TestCase):
    def test_prompt_stream_and_attachments(self) -> None:
        executable_value = os.environ.get("CN_RUNTIME_EXECUTABLE")
        if not executable_value:
            self.skipTest("set CN_RUNTIME_EXECUTABLE to run the frozen runtime interaction contract")
        executable = Path(executable_value).resolve()
        self.assertTrue(executable.is_file(), executable)
        if not (CLIENT_PLUGIN / "plugin.yaml").is_file():
            self.skipTest("the separate Electron client plugin is not available")
        token = os.environ.get("CN_CONTRACT_TOKEN", "cn-contract-token")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        provider = FakeProvider("CN fake provider response\nMEDIA:C:\\contract\\media.png").start()
        try:
            with tempfile.TemporaryDirectory(prefix="hermes-cn-interaction-") as home_dir:
                home = Path(home_dir)
                provider.approval_command = f"rm -rf {home / 'approval-victim'}"
                plugin_dir = home / "plugins" / CLIENT_PLUGIN.name
                shutil.copytree(CLIENT_PLUGIN, plugin_dir, ignore=shutil.ignore_patterns("request-audit.jsonl"))
                plugin_file = plugin_dir / "__init__.py"
                plugin_source = plugin_file.read_text(encoding="utf-8")
                self.assertEqual(plugin_source.count(f'SKILLHUB_BASE_URL = "{SKILLHUB_URL}"'), 1)
                self.assertEqual(plugin_source.count('{"custom", "custom:skillhub"}'), 1)
                plugin_file.write_text(
                    plugin_source.replace(f'SKILLHUB_BASE_URL = "{SKILLHUB_URL}"',
                                          f'SKILLHUB_BASE_URL = "{provider.url}/v1"')
                    .replace('{"custom", "custom:skillhub"}', '{"custom", "custom:skillhub", "mock"}'),
                    encoding="utf-8",
                )
                (home / ".env").write_text("MOCK_API_KEY=cn-contract-key\n", encoding="utf-8")
                (home / "config.yaml").write_text(
                    f"""model:\n  default: mock-model\n  provider: mock\nproviders:\n  mock:\n    api: {provider.url}/v1\n    name: Mock\n    api_mode: chat_completions\n    key_env: MOCK_API_KEY\n    models:\n      mock-model: {{}}\n    context_length: 64000\nplugins:\n  enabled:\n    - babybus-skillhub-session-header\nauxiliary:\n  title_generation:\n    enabled: false\nsecurity:\n  tirith_enabled: false\nterminal:\n  backend: local\napprovals:\n  mode: manual\n""",
                    encoding="utf-8",
                )
                env = {
                    **os.environ,
                    "HERMES_HOME": str(home),
                    "HERMES_DASHBOARD_SESSION_TOKEN": token,
                    "HERMES_DISABLE_LAZY_INSTALLS": "1",
                }
                process = subprocess.Popen(
                    [str(executable), "serve", "--host", "127.0.0.1", "--port", str(port)],
                    cwd=executable.parent, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                try:
                    base_url = f"http://127.0.0.1:{port}"
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            break
                        try:
                            with urllib.request.urlopen(f"{base_url}/api/status", timeout=2) as response:
                                if response.status == 200:
                                    break
                        except OSError:
                            time.sleep(0.5)
                    else:
                        self.fail("frozen runtime did not become ready")
                    asyncio.run(self._exercise(base_url, token, home, provider))
                finally:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    if process.stderr is not None:
                        process.stderr.close()
        finally:
            provider.close()

    async def _exercise(self, base_url: str, token: str, home: Path, provider: FakeProvider) -> None:
        import websockets

        ws_url = f"{base_url.replace('http://', 'ws://')}/api/ws?token={token}"
        async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as websocket:
            client = RpcClient(websocket)
            ready = await client.next_event("gateway.ready", None)
            self.assertIn("skin", ready["payload"])
            capabilities = await client.call("client.capabilities", {"server_requests": True})
            self.assertIn("approval", capabilities.get("server_requests", []))
            session = await client.call("session.create", {"source": "desktop", "title": "CN interaction"})
            sid = session["session_id"]
            stored_sid = session["stored_session_id"]
            self.assertNotEqual(sid, stored_sid)

            file_result = await client.call("file.attach", {
                "session_id": sid,
                "data_url": "data:text/plain;base64," + base64.b64encode(b"contract file").decode(),
                "name": "contract.txt",
            })
            self.assertTrue(file_result["attached"])
            self.assertEqual(file_result["name"], "contract.txt")
            self.assertTrue(file_result["ref_text"].startswith("@file:"))

            # The gateway-visible path must exist; use a temp image in the profile home.
            image_path = home / "contract.png"
            image_path.write_bytes(base64.b64decode(PNG))
            image_result = await client.call("image.attach", {"session_id": sid, "path": str(image_path)})
            self.assertTrue(image_result["attached"])
            bytes_result = await client.call("image.attach_bytes", {
                "session_id": sid, "content_base64": PNG, "filename": "uploaded.png",
            })
            self.assertTrue(bytes_result["attached"])
            self.assertGreaterEqual(bytes_result["count"], 2)

            submit = await client.call("prompt.submit", {"session_id": sid, "text": "CN-CONTRACT-PROMPT"})
            self.assertEqual(submit["status"], "streaming")
            deltas: list[str] = []
            complete: dict[str, Any] | None = None
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                frame = json.loads(await asyncio.wait_for(websocket.recv(), timeout=90))
                if frame.get("method") != "event":
                    continue
                params = frame.get("params") or {}
                if params.get("session_id") != sid:
                    continue
                if params.get("type") == "message.delta":
                    deltas.append(str((params.get("payload") or {}).get("text") or ""))
                elif params.get("type") == "message.complete":
                    complete = params.get("payload") or {}
                    break
            self.assertIsNotNone(complete)
            self.assertTrue(deltas)
            self.assertIn("CN fake provider response", "".join(deltas))
            self.assertIn("CN fake provider response", str(complete.get("text")))
            self.assertEqual(complete.get("status"), "complete")
            self.assertTrue(any(
                any("CN-CONTRACT-PROMPT" in str(message.get("content", "")) for message in request.get("messages", []))
                for request in provider.requests
            ))
            prompt_request_indexes = [
                index for index, request in enumerate(provider.requests)
                if any(
                    isinstance(message, dict)
                    and message.get("role") == "user"
                    and "CN-CONTRACT-PROMPT" in str(message.get("content") or "")
                    for message in request.get("messages", [])
                )
            ]
            self.assertTrue(prompt_request_indexes, provider.requests)
            self.assertTrue(all(
                provider.request_headers[index].get("X-Session-ID") == stored_sid
                for index in prompt_request_indexes
            ), provider.request_headers)

            await self._exercise_approval(websocket, client, sid, home, provider)

    async def _exercise_approval(
        self,
        websocket: Any,
        client: RpcClient,
        session_id: str,
        home: Path,
        provider: FakeProvider,
    ) -> None:
        approval_session = await client.call("session.create", {
            "source": "desktop",
            "title": "CN approval",
        })
        session_id = approval_session["session_id"]
        victim = home / "approval-victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("must survive denial", encoding="utf-8")
        submit = await client.call("prompt.submit", {
            "session_id": session_id,
            "text": "CN-APPROVAL-PROMPT",
        })
        self.assertIn(submit["status"], {"streaming", "queued"})

        approval: dict[str, Any] | None = None
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                frame = json.loads(await asyncio.wait_for(
                    websocket.recv(), timeout=max(0.1, min(5, deadline - time.monotonic()))
                ))
            except asyncio.TimeoutError:
                continue
            if frame.get("method") == "approval":
                params = frame.get("params") or {}
                if params.get("session_id") == session_id:
                    approval = frame
                    break
            elif frame.get("method") == "event":
                client.events.append(frame)
                event = frame.get("params") or {}
                if event.get("type") == "message.complete" and event.get("session_id") == session_id:
                    self.fail(
                        "approval prompt completed without an approval request; "
                        f"payload={event.get('payload')!r}, provider_requests={provider.requests!r}"
                    )
        self.assertIsNotNone(approval)
        params = (approval or {}).get("params") or {}
        request_id = params.get("request_id")
        self.assertTrue(isinstance(request_id, str) and request_id)
        self.assertIn("rm -rf", str(params.get("command")))
        self.assertIn(str(victim), str(params.get("command")))
        self.assertEqual(params.get("choices"), ["once", "session", "always", "deny"])
        self.assertTrue(victim.exists(), "dangerous command ran before approval was answered")

        resolved = await client.call("approval.respond", {
            "session_id": session_id,
            "request_id": request_id,
            "choice": "deny",
            "all": False,
        })
        self.assertGreaterEqual(resolved.get("resolved", 0), 1)

        pending = await client.call("approval.pending", {"session_id": session_id})
        self.assertEqual(pending.get("approvals"), [])
        self.assertTrue(victim.exists())
        self.assertTrue((victim / "keep.txt").exists())

        complete: dict[str, Any] | None = next(
            (
                (frame.get("params") or {}).get("payload") or {}
                for frame in client.events
                if frame.get("method") == "event"
                and (frame.get("params") or {}).get("type") == "message.complete"
                and (frame.get("params") or {}).get("session_id") == session_id
            ),
            None,
        )
        while complete is None and time.monotonic() < deadline:
            try:
                frame = json.loads(await asyncio.wait_for(
                    websocket.recv(), timeout=max(0.1, min(5, deadline - time.monotonic()))
                ))
            except asyncio.TimeoutError:
                continue
            if frame.get("method") != "event":
                continue
            client.events.append(frame)
            event = frame.get("params") or {}
            if event.get("type") == "message.complete" and event.get("session_id") == session_id:
                complete = event.get("payload") or {}
        self.assertIsNotNone(complete)
        self.assertEqual((complete or {}).get("status"), "complete")

        tool_results = [
            message
            for request in provider.requests
            for message in request.get("messages", [])
            if isinstance(message, dict) and message.get("role") == "tool"
        ]
        self.assertTrue(tool_results, "provider never received the denied terminal tool result")
        self.assertIn("denied", str(tool_results[-1].get("content", "")).lower())

if __name__ == "__main__":
    unittest.main()
