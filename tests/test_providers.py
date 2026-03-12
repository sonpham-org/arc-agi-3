"""Test all LLM providers with a single cheap call each.

Usage:
    python test_providers.py              # test all configured providers
    python test_providers.py groq         # test single provider
    python test_providers.py groq gemini  # test multiple providers
    python test_providers.py --list       # list available providers and their status
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from agent import call_model, load_config, _parse_json
from models import MODELS

# One cheap model per provider to test the call path
PROVIDER_TEST_MODELS = {
    "groq":       "groq/llama-3.3-70b-versatile",
    "mistral":    "mistral/mistral-small-latest",
    "gemini":     "gemini-2.5-flash",
    "anthropic":  "claude-haiku-4-5",
    "cloudflare": "cloudflare/llama-3.3-70b",
    "huggingface": "hf/meta-llama-3.3-70b",
    "ollama":     "ollama/qwen3.5",
}

# Simple prompt that should produce parseable JSON — minimal tokens
TEST_PROMPT = (
    'You are a test. Respond with EXACTLY this JSON and nothing else: '
    '{"status": "ok", "action": 1, "data": {}}'
)

# Minimal config for testing
TEST_CFG = load_config()
TEST_CFG["reasoning"]["temperature"] = 0.0
TEST_CFG["reasoning"]["max_tokens"] = 100


def check_env_key(provider: str) -> tuple[bool, str]:
    """Check if the required env key is set for a provider."""
    model_key = PROVIDER_TEST_MODELS.get(provider)
    if not model_key:
        return False, f"No test model defined for provider '{provider}'"
    info = MODELS.get(model_key)
    if not info:
        return False, f"Model '{model_key}' not in MODELS registry"
    env_key = info.get("env_key", "")
    if not env_key:
        # Ollama/Copilot don't need env keys
        if provider == "ollama":
            return True, "Local (no key needed)"
        return True, "No key needed"
    if os.environ.get(env_key):
        return True, f"{env_key} is set"
    return False, f"{env_key} NOT SET"


def test_provider(provider: str) -> dict:
    """Test a single provider. Returns result dict."""
    model_key = PROVIDER_TEST_MODELS.get(provider)
    if not model_key:
        return {"provider": provider, "status": "SKIP", "reason": "No test model defined"}

    info = MODELS.get(model_key)
    if not info:
        return {"provider": provider, "status": "SKIP", "reason": f"Model {model_key} not in registry"}

    # Check env key
    env_key = info.get("env_key", "")
    if env_key and not os.environ.get(env_key):
        return {"provider": provider, "model": model_key, "status": "SKIP",
                "reason": f"{env_key} not set"}

    # Special check for Ollama — needs localhost running
    if provider == "ollama":
        try:
            import httpx
            r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
            if r.status_code != 200:
                return {"provider": provider, "model": model_key, "status": "SKIP",
                        "reason": "Ollama not running"}
        except Exception:
            return {"provider": provider, "model": model_key, "status": "SKIP",
                    "reason": "Ollama not running (localhost:11434 unreachable)"}

    # Make the call
    t0 = time.time()
    try:
        raw = call_model(model_key, TEST_PROMPT, TEST_CFG, role="executor")
        elapsed = time.time() - t0
    except Exception as e:
        elapsed = time.time() - t0
        return {"provider": provider, "model": model_key, "status": "FAIL",
                "error": str(e), "elapsed": round(elapsed, 2)}

    # Validate response
    if not isinstance(raw, str):
        # Some providers may return non-string (e.g., dict from tool calls)
        raw = json.dumps(raw) if raw else ""
    parsed = _parse_json(raw)
    if parsed is None:
        return {"provider": provider, "model": model_key, "status": "WARN",
                "reason": "Response not valid JSON", "raw": raw[:200],
                "elapsed": round(elapsed, 2)}

    return {"provider": provider, "model": model_key, "status": "PASS",
            "elapsed": round(elapsed, 2), "response": parsed}


def list_providers():
    """List all providers and their configuration status."""
    print(f"\n{'Provider':<14} {'Test Model':<35} {'Env Key Status'}")
    print(f"{'─' * 14} {'─' * 35} {'─' * 30}")
    for provider in sorted(PROVIDER_TEST_MODELS.keys()):
        model = PROVIDER_TEST_MODELS[provider]
        ready, status = check_env_key(provider)
        marker = "✓" if ready else "✗"
        print(f"{provider:<14} {model:<35} {marker} {status}")
    print()


def main():
    if "--list" in sys.argv:
        list_providers()
        return

    # Determine which providers to test
    providers_to_test = sys.argv[1:]
    if not providers_to_test:
        # Test all configured providers (skip those without env keys)
        providers_to_test = []
        for provider in sorted(PROVIDER_TEST_MODELS.keys()):
            ready, _ = check_env_key(provider)
            if ready:
                providers_to_test.append(provider)

    if not providers_to_test:
        print("No providers configured. Run with --list to see status.")
        return

    print(f"\n{'=' * 65}")
    print(f"  PROVIDER TESTS — {len(providers_to_test)} provider(s)")
    print(f"{'=' * 65}\n")

    results = []
    passed = 0
    failed = 0
    skipped = 0

    for provider in providers_to_test:
        print(f"  Testing {provider:<14} ({PROVIDER_TEST_MODELS.get(provider, '?')})...", end=" ", flush=True)
        result = test_provider(provider)
        results.append(result)

        if result["status"] == "PASS":
            print(f"PASS  ({result['elapsed']}s)")
            passed += 1
        elif result["status"] == "SKIP":
            print(f"SKIP  ({result.get('reason', '')})")
            skipped += 1
        elif result["status"] == "WARN":
            print(f"WARN  ({result.get('reason', '')})")
            passed += 1  # count as pass since the API call worked
        else:
            print(f"FAIL  ({result.get('error', '')[:80]})")
            failed += 1

    print(f"\n{'─' * 65}")
    print(f"  Results: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"{'─' * 65}\n")

    # Write detailed results
    report_path = Path(__file__).parent / "data" / "provider_test_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2))
    print(f"  Detailed results: {report_path}")

    if failed > 0:
        print("\n  FAILURES:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    {r['provider']}: {r.get('error', 'unknown')[:100]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
