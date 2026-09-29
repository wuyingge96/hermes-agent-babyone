"""Source-level contract for the approval queue used by the desktop gateway."""

from __future__ import annotations

import os
import queue
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch


class ApprovalFifoContractTests(unittest.TestCase):
    def test_unaddressed_responses_resolve_oldest_request_first(self) -> None:
        from tools import approval

        session_key = f"cn-fifo-{uuid.uuid4().hex}"
        notifications: queue.Queue[dict] = queue.Queue()
        results: list[dict | None] = [None, None]
        commands = ("rm -rf first", "rm -rf second")
        threads: list[threading.Thread] = []

        def wait_for_approval(index: int) -> None:
            results[index] = approval._await_gateway_decision(
                session_key,
                notifications.put,
                {
                    "command": commands[index],
                    "description": "CN FIFO contract",
                    "pattern_key": commands[index],
                    "pattern_keys": [commands[index]],
                },
            )

        with tempfile.TemporaryDirectory(prefix="hermes-cn-fifo-") as home:
            with patch.dict(os.environ, {"HERMES_HOME": home}), patch(
                "tools.approval_context._get_approval_timeout", return_value=30
            ):
                try:
                    for index in range(2):
                        thread = threading.Thread(target=wait_for_approval, args=(index,))
                        threads.append(thread)
                        thread.start()
                        self.assertEqual(notifications.get(timeout=10)["command"], commands[index])

                    pending = approval.list_gateway_approvals(session_key)
                    self.assertEqual([item["command"] for item in pending], list(commands))
                    self.assertEqual(approval.resolve_gateway_approval(session_key, "deny"), 1)
                    threads[0].join(timeout=10)
                    self.assertFalse(threads[0].is_alive())
                    self.assertEqual(results[0]["choice"], "deny")
                    self.assertEqual(results[0]["resolved"], True)
                    self.assertEqual(
                        [item["command"] for item in approval.list_gateway_approvals(session_key)],
                        [commands[1]],
                    )
                    self.assertTrue(threads[1].is_alive())

                    self.assertEqual(approval.resolve_gateway_approval(session_key, "session"), 1)
                    threads[1].join(timeout=10)
                    self.assertFalse(threads[1].is_alive())
                    self.assertEqual(results[1]["choice"], "session")
                    self.assertEqual(results[1]["resolved"], True)
                    self.assertEqual(approval.list_gateway_approvals(session_key), [])
                finally:
                    approval.resolve_gateway_approval(session_key, "deny", resolve_all=True)
                    approval.unregister_gateway_notify(session_key)
                    for thread in threads:
                        thread.join(timeout=10)


if __name__ == "__main__":
    unittest.main()
