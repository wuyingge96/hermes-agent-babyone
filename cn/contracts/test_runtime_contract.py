"""Real-process contract test for a built CN runtime.

The test is opt-in because freezing and starting an executable is expensive.
Set ``CN_RUNTIME_EXECUTABLE`` to run it against a local artifact; the normal
packaging unit tests remain dependency-free.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "cn/contracts/scripts/probe_runtime.py"


class RuntimeContractTests(unittest.TestCase):
    def test_frozen_runtime_contract(self) -> None:
        executable_value = os.environ.get("CN_RUNTIME_EXECUTABLE")
        if not executable_value:
            self.skipTest("set CN_RUNTIME_EXECUTABLE to run the frozen runtime contract")
        executable = Path(executable_value).resolve()
        self.assertTrue(executable.is_file(), executable)
        probe_python = Path(os.environ.get("CN_CONTRACT_PYTHON", sys.executable)).resolve()
        token = os.environ.get("CN_CONTRACT_TOKEN", "cn-contract-token")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="hermes-cn-contract-") as home_dir, tempfile.TemporaryFile() as stderr:
            env = {
                **os.environ,
                "HERMES_HOME": home_dir,
                "HERMES_DASHBOARD_SESSION_TOKEN": token,
                "HERMES_DISABLE_LAZY_INSTALLS": "1",
            }
            process = subprocess.Popen(
                [str(executable), "serve", "--host", "127.0.0.1", "--port", str(port)],
                cwd=executable.parent,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
            )
            base_url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 90
            try:
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

                completed = subprocess.run(
                    [str(probe_python), str(PROBE), "--base-url", base_url, "--token", token],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    env=env,
                )
                if completed.returncode != 0:
                    stderr.seek(0)
                    detail = stderr.read()[-4000:].decode("utf-8", errors="replace")
                    self.fail(f"runtime contract probe failed:\n{completed.stdout}\n{completed.stderr}\n{detail}")
                report = json.loads(completed.stdout)
                self.assertTrue(report["skillhub_config_round_trip"])
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    unittest.main()
