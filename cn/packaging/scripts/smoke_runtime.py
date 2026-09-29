#!/usr/bin/env python3
"""Launch a runtime artifact and verify the client's initial HTTP probes."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def get_json(url: str, token: str, timeout: float) -> tuple[int, object]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--token", default="cn-smoke-token")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()

    args.home.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "HERMES_HOME": str(args.home),
        "HERMES_DASHBOARD_SESSION_TOKEN": args.token,
        "HERMES_DISABLE_LAZY_INSTALLS": "1",
    }
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            [str(args.executable), "serve", "--host", args.host, "--port", str(args.port)],
            cwd=args.executable.parent,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )
        base = f"http://{args.host}:{args.port}"
        deadline = time.monotonic() + args.timeout
        try:
            status: tuple[int, object] | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stderr.seek(0)
                    detail = stderr.read()[-4000:].decode("utf-8", errors="replace").strip()
                    raise RuntimeError(
                        f"runtime exited before readiness: {process.returncode}\n{detail}"
                    )
                try:
                    status = get_json(f"{base}/api/status", args.token, 2)
                    if status[0] == 200:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.5)
            if not status or status[0] != 200:
                stderr.seek(0)
                detail = stderr.read()[-4000:].decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"/api/status did not become ready: {status}\n{detail}")
            openapi_status, openapi = get_json(f"{base}/openapi.json", args.token, 5)
            if openapi_status != 200 or not isinstance(openapi, dict):
                raise RuntimeError(f"/openapi.json probe failed: {openapi_status}")
            print(json.dumps({"ok": True, "status": status[1], "openapi": openapi_status}, indent=2))
            return 0
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
