"""Offline contract for the Desktop-managed SkillHub request middleware."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


CLIENT_PLUGIN = (
    Path(__file__).resolve().parents[3]
    / "erp-assistant-electron"
    / "resources"
    / "hermes-plugins"
    / "babybus-skillhub-session-header"
)
SKILLHUB_URL = "https://skillhub-api.icloud.babybus.com/sb-api/openai/v1"


class SessionHeaderContractTests(unittest.TestCase):
    def test_managed_plugin_rewrites_only_skillhub_requests(self) -> None:
        if not (CLIENT_PLUGIN / "plugin.yaml").is_file():
            self.skipTest("the separate Electron client plugin is not available")

        from hermes_cli.middleware import apply_llm_request_middleware
        from hermes_cli.plugins import _reset_plugin_managers_for_tests, get_plugin_manager

        with tempfile.TemporaryDirectory(prefix="hermes-cn-session-header-") as home_dir:
            home = Path(home_dir)
            shutil.copytree(CLIENT_PLUGIN, home / "plugins" / CLIENT_PLUGIN.name)
            (home / "config.yaml").write_text(
                "plugins:\n  enabled:\n    - babybus-skillhub-session-header\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"HERMES_HOME": str(home)}):
                try:
                    request = {"messages": [{"role": "user", "content": "contract"}]}
                    context = {
                        "session_id": "cn_contract_session",
                        "provider": "custom:skillhub",
                        "base_url": SKILLHUB_URL,
                        "api_mode": "chat_completions",
                        "model": "mock-model",
                    }
                    result = apply_llm_request_middleware(request, **context)
                    self.assertIn(CLIENT_PLUGIN.name, get_plugin_manager()._plugins)
                    self.assertTrue(result.changed)
                    self.assertEqual(result.payload["extra_headers"]["X-Session-ID"], context["session_id"])
                    self.assertNotIn("extra_headers", request)

                    other_url = apply_llm_request_middleware(
                        request, **{**context, "base_url": "http://127.0.0.1:1/v1"}
                    )
                    self.assertFalse(other_url.changed)
                    self.assertNotIn("extra_headers", other_url.payload)
                finally:
                    _reset_plugin_managers_for_tests()


if __name__ == "__main__":
    unittest.main()
