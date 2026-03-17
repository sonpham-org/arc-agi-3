# Author: Claude Opus 4.6
# Date: 2026-03-15 00:00
# PURPOSE: LLM provider routing tests — verifies dispatch dict routes models
#   to correct providers, unknown models fall back to Ollama, and throttling works.
# SRP/DRY check: Pass — focused on provider routing only
"""Provider routing tests — dispatch correctness, fallback, throttling."""

import sys
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import MODEL_REGISTRY
from llm_providers import _route_model_call, _throttle_provider, PROVIDER_MIN_DELAY


class TestProviderDispatch(unittest.TestCase):
    """Tests for _route_model_call dispatch to correct providers."""

    @patch("llm_providers_google._call_gemini")
    def test_gemini_model_routes_to_gemini(self, mock_gemini):
        """Gemini models should route to _call_gemini."""
        mock_gemini.return_value = '{"action": 1}'
        # Find a gemini model in registry
        gemini_key = None
        for key, info in MODEL_REGISTRY.items():
            if info["provider"] == "gemini":
                gemini_key = key
                break
        if not gemini_key:
            self.skipTest("No Gemini model in registry")

        _route_model_call(gemini_key, "test prompt")
        mock_gemini.assert_called_once()

    @patch("llm_providers_anthropic._call_anthropic")
    def test_anthropic_model_routes_to_anthropic(self, mock_anthropic):
        """Anthropic models should route to _call_anthropic."""
        mock_anthropic.return_value = '{"action": 1}'
        anthropic_key = None
        for key, info in MODEL_REGISTRY.items():
            if info["provider"] == "anthropic":
                anthropic_key = key
                break
        if not anthropic_key:
            self.skipTest("No Anthropic model in registry")

        _route_model_call(anthropic_key, "test prompt")
        mock_anthropic.assert_called_once()

    @patch("llm_providers_openai._call_openai")
    def test_openai_model_routes_to_openai(self, mock_openai):
        """OpenAI models should route to _call_openai."""
        mock_openai.return_value = '{"action": 1}'
        openai_key = None
        for key, info in MODEL_REGISTRY.items():
            if info["provider"] == "openai":
                openai_key = key
                break
        if not openai_key:
            self.skipTest("No OpenAI model in registry")

        _route_model_call(openai_key, "test prompt")
        mock_openai.assert_called_once()

    @patch("llm_providers_openai._call_openai_compatible")
    def test_groq_model_routes_to_compatible(self, mock_compatible):
        """Groq models should route to _call_openai_compatible."""
        mock_compatible.return_value = '{"action": 1}'
        groq_key = None
        for key, info in MODEL_REGISTRY.items():
            if info["provider"] == "groq":
                groq_key = key
                break
        if not groq_key:
            self.skipTest("No Groq model in registry")

        _route_model_call(groq_key, "test prompt")
        mock_compatible.assert_called_once()

    @patch("llm_providers_openai._call_openai_compatible")
    def test_lmstudio_model_routes_to_compatible(self, mock_compatible):
        """LM Studio models should route to _call_openai_compatible with localhost:1234."""
        mock_compatible.return_value = '{"action": 1}'
        lmstudio_key = None
        for key, info in MODEL_REGISTRY.items():
            if info["provider"] == "lmstudio":
                lmstudio_key = key
                break
        if not lmstudio_key:
            self.skipTest("No LM Studio model in registry")

        _route_model_call(lmstudio_key, "test prompt")
        mock_compatible.assert_called_once()
        # Verify the URL contains localhost:1234
        call_args = mock_compatible.call_args
        self.assertIn("1234", call_args[0][0])

    @patch("llm_providers_copilot._call_copilot")
    def test_copilot_model_routes_to_copilot(self, mock_copilot):
        """Copilot models should route to _call_copilot."""
        mock_copilot.return_value = '{"action": 1}'
        copilot_key = None
        for key, info in MODEL_REGISTRY.items():
            if info["provider"] == "copilot":
                copilot_key = key
                break
        if not copilot_key:
            self.skipTest("No Copilot model in registry")

        _route_model_call(copilot_key, "test prompt")
        mock_copilot.assert_called_once()


class TestUnknownModelFallback(unittest.TestCase):
    """Tests for fallback behavior with unknown model keys."""

    @patch("llm_providers_openai._call_ollama")
    def test_unknown_model_falls_back_to_ollama(self, mock_ollama):
        """Unknown model key should fall back to _call_ollama."""
        mock_ollama.return_value = '{"action": 1}'
        _route_model_call("totally-unknown-model-xyz", "test prompt")
        mock_ollama.assert_called_once()
        # First arg should be the model key itself
        self.assertEqual(mock_ollama.call_args[0][0], "totally-unknown-model-xyz")

    @patch("llm_providers_openai._call_openai_compatible")
    def test_discovered_local_model_routes_to_compatible(self, mock_compatible):
        """Discovered local models should route to _call_openai_compatible."""
        from models import _discovered_local_models
        mock_compatible.return_value = '{"action": 1}'

        # Temporarily add a local model
        _discovered_local_models["test-local-model"] = {
            "local_port": 9999,
            "api_model": "test-model",
        }
        try:
            _route_model_call("test-local-model", "test prompt")
            mock_compatible.assert_called_once()
            call_args = mock_compatible.call_args
            self.assertIn("9999", call_args[0][0])
        finally:
            del _discovered_local_models["test-local-model"]


class TestProviderThrottling(unittest.TestCase):
    """Tests for per-provider throttle enforcement."""

    def test_all_standard_providers_have_delay(self):
        """Standard providers in MODEL_REGISTRY should have a throttle delay defined."""
        # Providers that go through _route_model_call dispatch or OpenAI-compatible fallback
        standard_providers = {
            "gemini", "anthropic", "openai", "groq", "mistral",
            "huggingface", "cloudflare", "copilot", "ollama", "lmstudio",
        }
        providers_in_registry = {info["provider"] for info in MODEL_REGISTRY.values()}
        for provider in providers_in_registry & standard_providers:
            self.assertIn(provider, PROVIDER_MIN_DELAY,
                          f"Provider '{provider}' missing from PROVIDER_MIN_DELAY")

    def test_throttle_respects_min_delay(self):
        """Throttle should enforce minimum delay between calls."""
        # Use a provider with known delay
        provider = "anthropic"
        min_delay = PROVIDER_MIN_DELAY[provider]

        # First call should not wait
        start = time.time()
        _throttle_provider(provider)
        first_duration = time.time() - start
        self.assertLess(first_duration, min_delay,
                        "First call should not wait")

        # Second call should wait (approximately min_delay)
        start = time.time()
        _throttle_provider(provider)
        second_duration = time.time() - start
        # Allow 0.1s tolerance
        self.assertGreater(second_duration, min_delay - 0.2,
                           "Second call should enforce delay")

    def test_ollama_no_throttle(self):
        """Ollama should have 0 delay (local model)."""
        self.assertEqual(PROVIDER_MIN_DELAY.get("ollama", -1), 0.0)


class TestRegistryCompleteness(unittest.TestCase):
    """Tests for MODEL_REGISTRY data integrity."""

    def test_all_models_have_required_fields(self):
        """Every model entry should have provider, api_model, capabilities."""
        required_fields = {"provider", "api_model", "capabilities"}
        for key, info in MODEL_REGISTRY.items():
            for field in required_fields:
                self.assertIn(field, info,
                              f"Model '{key}' missing required field '{field}'")

    def test_capabilities_have_image_key(self):
        """Every model capabilities dict should have 'image' key."""
        for key, info in MODEL_REGISTRY.items():
            caps = info.get("capabilities", {})
            self.assertIn("image", caps,
                          f"Model '{key}' capabilities missing 'image' key")

    def test_no_empty_provider(self):
        """No model should have empty string as provider."""
        for key, info in MODEL_REGISTRY.items():
            self.assertTrue(info.get("provider"),
                            f"Model '{key}' has empty provider")


if __name__ == "__main__":
    unittest.main()
