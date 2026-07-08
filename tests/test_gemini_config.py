from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bibliometrics.gemini_config import GeminiConfig


class GeminiConfigDefaultsTests(unittest.TestCase):
    def test_default_api_url_is_official_endpoint(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            config = GeminiConfig()
        self.assertEqual(config.api_url, "https://generativelanguage.googleapis.com/v1beta")

    def test_env_overrides_apply(self) -> None:
        env = {
            "GEMINI_API_KEY": "test-key-123",
            "GEMINI_API_URL": "https://example.com/v1beta",
            "GEMINI_MODEL": "gemini-x",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = GeminiConfig()
        self.assertEqual(config.api_key, "test-key-123")
        self.assertEqual(config.api_url, "https://example.com/v1beta")
        self.assertEqual(config.model, "gemini-x")
        self.assertTrue(config.is_enabled())

    def test_placeholder_key_disables_api(self) -> None:
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "YOUR_API_KEY_HERE"}, clear=True):
            config = GeminiConfig()
        self.assertFalse(config.is_enabled())

    def test_missing_key_disables_api(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            config = GeminiConfig()
        self.assertFalse(config.is_enabled())
        self.assertFalse(config.validate())


if __name__ == "__main__":
    unittest.main()
