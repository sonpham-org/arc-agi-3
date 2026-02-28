#!/usr/bin/env python3
"""
LLM Provider Benchmark — measures latency, throughput, and token accounting
across all configured providers. Designed for ARC-AGI-3 call scheduling.

Metrics:
  - TTFT  : Time to first token (streaming) or time to response (non-streaming)
  - TPS   : Output tokens per second
  - E2E   : End-to-end latency
  - Tokens: Input / output / thinking token counts

Usage:
  python benchmark_models.py                  # benchmark all available providers
  python benchmark_models.py groq gemini      # benchmark specific providers
  python benchmark_models.py --parallel       # test parallel call scheduling
  python benchmark_models.py --context-sweep  # test increasing context sizes
"""

import os, sys, time, json, httpx, statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Optional

# Load .env
from pathlib import Path
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# ── Benchmark models (one per provider, cheapest/fastest) ────────────────

BENCH_MODELS = {
    "groq": {
        "name": "groq/llama-3.3-70b-versatile",
        "provider": "groq",
        "api_model": "llama-3.3-70b-versatile",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "env_key": "GROQ_API_KEY",
        "type": "openai",
        "context_window": 128_000,
        "cost_per_1m_in": 0.59,
        "cost_per_1m_out": 0.79,
    },
    "mistral": {
        "name": "mistral/mistral-small-latest",
        "provider": "mistral",
        "api_model": "mistral-small-latest",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "env_key": "MISTRAL_API_KEY",
        "type": "openai",
        "context_window": 128_000,
        "cost_per_1m_in": 0.0,
        "cost_per_1m_out": 0.0,
    },
    "gemini-flash": {
        "name": "gemini-2.5-flash",
        "provider": "gemini",
        "api_model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
        "type": "gemini",
        "context_window": 1_048_576,
        "cost_per_1m_in": 0.30,
        "cost_per_1m_out": 2.50,
    },
    "gemini-flash-lite": {
        "name": "gemini-2.5-flash-lite",
        "provider": "gemini",
        "api_model": "gemini-2.5-flash-lite",
        "env_key": "GEMINI_API_KEY",
        "type": "gemini",
        "context_window": 1_048_576,
        "cost_per_1m_in": 0.10,
        "cost_per_1m_out": 0.40,
    },
    "gemini-pro": {
        "name": "gemini-2.5-pro",
        "provider": "gemini",
        "api_model": "gemini-2.5-pro",
        "env_key": "GEMINI_API_KEY",
        "type": "gemini",
        "context_window": 1_048_576,
        "cost_per_1m_in": 1.25,
        "cost_per_1m_out": 10.0,
    },
    "cloudflare": {
        "name": "cloudflare/llama-3.3-70b",
        "provider": "cloudflare",
        "api_model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "env_key": "CLOUDFLARE_API_KEY",
        "env_account": "CLOUDFLARE_ACCOUNT_ID",
        "type": "cloudflare",
        "context_window": 8_192,
        "cost_per_1m_in": 0.0,
        "cost_per_1m_out": 0.0,
    },
    "huggingface": {
        "name": "hf/meta-llama-3.3-70b",
        "provider": "huggingface",
        "api_model": "meta-llama/Llama-3.3-70B-Instruct",
        "url": "https://router.huggingface.co/v1/chat/completions",
        "env_key": "HUGGINGFACE_API_KEY",
        "type": "openai",
        "context_window": 128_000,
        "cost_per_1m_in": 0.0,
        "cost_per_1m_out": 0.0,
    },
}

# ── Test prompts at different context sizes ──────────────────────────────

SMALL_PROMPT = (
    "You are a puzzle-solving AI. Given this 3x3 grid:\n"
    "[[1,0,0],[0,1,0],[0,0,1]]\n"
    "Describe the pattern in exactly 2 sentences, then output JSON: "
    '{"pattern": "<description>", "confidence": <0-1>}'
)

MEDIUM_FILLER = (
    "Additional context for analysis:\n"
    + "\n".join(f"Row {i}: {[i % 10] * 20}" for i in range(100))
    + "\n\nNow analyze the original 3x3 grid pattern. "
    'Output JSON: {"pattern": "<description>", "confidence": <0-1>}'
)

LARGE_FILLER = (
    "Extended grid history for analysis:\n"
    + "\n".join(f"Grid {i}: {[[j % 10 for j in range(10)] for _ in range(10)]}" for i in range(50))
    + "\n\nNow analyze the original 3x3 grid pattern. "
    'Output JSON: {"pattern": "<description>", "confidence": <0-1>}'
)


@dataclass
class BenchResult:
    model: str
    provider: str
    prompt_size: str          # "small" / "medium" / "large"
    e2e_ms: float = 0.0      # end-to-end latency
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0  # reasoning/thinking tokens if available
    total_tokens: int = 0
    output_tps: float = 0.0   # output tokens per second
    input_tps: float = 0.0    # effective input processing speed
    cost_usd: float = 0.0
    error: str = ""
    response_preview: str = ""
    # Raw details for analysis
    prompt_chars: int = 0     # character length of prompt sent
    response_chars: int = 0   # character length of full response
    full_response: str = ""   # complete response text (for token analysis)
    raw_usage: dict = field(default_factory=dict)  # raw usage dict from API


# ── Provider call functions ──────────────────────────────────────────────

def _call_openai_compatible(model_cfg: dict, prompt: str) -> BenchResult:
    """Call OpenAI-compatible endpoint (Groq, Mistral, HuggingFace)."""
    result = BenchResult(model=model_cfg["name"], provider=model_cfg["provider"], prompt_size="")
    api_key = os.environ.get(model_cfg["env_key"], "")
    if not api_key:
        result.error = f"Missing {model_cfg['env_key']}"
        return result

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model_cfg["api_model"],
        "messages": [
            {"role": "system", "content": "You are an expert puzzle-solving AI."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
    }

    t0 = time.perf_counter()
    try:
        resp = httpx.post(model_cfg["url"], json=body, headers=headers, timeout=60)
        t1 = time.perf_counter()
        resp.raise_for_status()
        data = resp.json()

        result.e2e_ms = (t1 - t0) * 1000
        result.prompt_chars = len(prompt)
        usage = data.get("usage", {})
        result.raw_usage = usage
        result.input_tokens = usage.get("prompt_tokens", 0)
        result.output_tokens = usage.get("completion_tokens", 0)
        result.total_tokens = usage.get("total_tokens", result.input_tokens + result.output_tokens)
        full_text = data["choices"][0]["message"]["content"]
        result.full_response = full_text
        result.response_chars = len(full_text)
        result.response_preview = full_text[:200]

        # Check for reasoning tokens (some providers report this)
        if "completion_tokens_details" in usage:
            details = usage["completion_tokens_details"]
            result.thinking_tokens = details.get("reasoning_tokens", 0)

    except Exception as e:
        t1 = time.perf_counter()
        result.e2e_ms = (t1 - t0) * 1000
        result.error = str(e)[:200]

    return result


def _call_gemini(model_cfg: dict, prompt: str) -> BenchResult:
    """Call Gemini via google-genai SDK."""
    result = BenchResult(model=model_cfg["name"], provider=model_cfg["provider"], prompt_size="")
    api_key = os.environ.get(model_cfg["env_key"], "")
    if not api_key:
        result.error = f"Missing {model_cfg['env_key']}"
        return result

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # Enable thinking for models that support it
        thinking_config = None
        if "2.5" in model_cfg["api_model"] or "3" in model_cfg["api_model"]:
            thinking_config = types.ThinkingConfig(thinking_budget=4096)

        # Pro models need more output budget since thinking consumes tokens
        max_out = 2048 if "pro" in model_cfg["api_model"].lower() else 512
        config = types.GenerateContentConfig(
            system_instruction="You are an expert puzzle-solving AI.",
            temperature=0.3,
            max_output_tokens=max_out,
        )
        if thinking_config:
            config.thinking_config = thinking_config

        t0 = time.perf_counter()
        response = client.models.generate_content(
            model=model_cfg["api_model"],
            contents=prompt,
            config=config,
        )
        t1 = time.perf_counter()

        result.e2e_ms = (t1 - t0) * 1000
        result.prompt_chars = len(prompt)

        # Extract usage metadata
        if response.usage_metadata:
            um = response.usage_metadata
            result.input_tokens = getattr(um, "prompt_token_count", 0) or 0
            result.output_tokens = getattr(um, "candidates_token_count", 0) or 0
            result.total_tokens = getattr(um, "total_token_count", 0) or 0
            # Capture raw usage for analysis
            result.raw_usage = {
                "prompt_token_count": result.input_tokens,
                "candidates_token_count": result.output_tokens,
                "total_token_count": result.total_tokens,
            }
            # Thinking tokens
            thinking = getattr(um, "thoughts_token_count", 0)
            if thinking:
                result.thinking_tokens = thinking
                result.raw_usage["thoughts_token_count"] = thinking
            elif result.total_tokens > result.input_tokens + result.output_tokens:
                result.thinking_tokens = result.total_tokens - result.input_tokens - result.output_tokens
                result.raw_usage["thoughts_token_count_estimated"] = result.thinking_tokens

        # Extract text
        text_parts = []
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "thought") and part.thought:
                    continue  # skip thinking parts for preview
                if hasattr(part, "text") and part.text:
                    text_parts.append(part.text)
        full_text = " ".join(text_parts) if text_parts else "(thinking only, no text output)"
        result.full_response = full_text
        result.response_chars = len(full_text)
        result.response_preview = full_text[:200]

    except Exception as e:
        t1 = time.perf_counter()
        result.e2e_ms = (t1 - t0) * 1000 if 't0' in dir() else 0
        result.error = str(e)[:200]

    return result


def _call_cloudflare(model_cfg: dict, prompt: str) -> BenchResult:
    """Call Cloudflare Workers AI."""
    result = BenchResult(model=model_cfg["name"], provider=model_cfg["provider"], prompt_size="")
    api_key = os.environ.get(model_cfg["env_key"], "")
    account_id = os.environ.get(model_cfg.get("env_account", ""), "")
    if not api_key or not account_id:
        result.error = f"Missing {model_cfg['env_key']} or {model_cfg.get('env_account', '')}"
        return result

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_cfg['api_model']}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "messages": [
            {"role": "system", "content": "You are an expert puzzle-solving AI."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 512,
    }

    t0 = time.perf_counter()
    try:
        resp = httpx.post(url, json=body, headers=headers, timeout=60)
        t1 = time.perf_counter()
        resp.raise_for_status()
        data = resp.json()

        result.e2e_ms = (t1 - t0) * 1000
        result.prompt_chars = len(prompt)
        r = data.get("result", {})
        full_text = r.get("response", str(r))
        result.full_response = full_text
        result.response_chars = len(full_text)
        result.response_preview = full_text[:200]
        result.raw_usage = {"cloudflare_result_keys": list(r.keys()) if isinstance(r, dict) else "raw_string"}

        # CF doesn't return token counts — estimate from response length
        result.output_tokens = int(len(full_text.split()) * 1.3)  # rough estimate

    except Exception as e:
        t1 = time.perf_counter()
        result.e2e_ms = (t1 - t0) * 1000
        result.error = str(e)[:200]

    return result


# ── Dispatch ─────────────────────────────────────────────────────────────

CALLERS = {
    "openai": _call_openai_compatible,
    "gemini": _call_gemini,
    "cloudflare": _call_cloudflare,
}


def call_model(model_key: str, prompt: str, prompt_size: str) -> BenchResult:
    cfg = BENCH_MODELS[model_key]
    caller = CALLERS[cfg["type"]]
    result = caller(cfg, prompt)
    result.prompt_size = prompt_size

    # Compute derived metrics
    if result.e2e_ms > 0 and result.output_tokens > 0:
        result.output_tps = result.output_tokens / (result.e2e_ms / 1000)
    if result.e2e_ms > 0 and result.input_tokens > 0:
        result.input_tps = result.input_tokens / (result.e2e_ms / 1000)

    # Compute cost
    cost_in = cfg.get("cost_per_1m_in", 0)
    cost_out = cfg.get("cost_per_1m_out", 0)
    result.cost_usd = (result.input_tokens * cost_in + result.output_tokens * cost_out) / 1_000_000

    return result


# ── Parallel scheduling benchmark ───────────────────────────────────────

def benchmark_parallel(model_keys: list, n_calls: int = 3) -> dict:
    """Test parallel call throughput — simulates chaining N calls concurrently."""
    results = {}

    for concurrency in [1, 2, 4, len(model_keys)]:
        label = f"concurrency={concurrency}"
        t0 = time.perf_counter()

        tasks = []
        for i in range(n_calls):
            mk = model_keys[i % len(model_keys)]
            tasks.append((mk, SMALL_PROMPT, "small"))

        completed = []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(call_model, mk, p, ps): mk for mk, p, ps in tasks}
            for fut in as_completed(futures):
                completed.append(fut.result())

        wall_time = (time.perf_counter() - t0) * 1000
        total_e2e = sum(r.e2e_ms for r in completed)
        errors = sum(1 for r in completed if r.error)

        results[label] = {
            "wall_time_ms": round(wall_time, 1),
            "sum_e2e_ms": round(total_e2e, 1),
            "speedup": round(total_e2e / wall_time, 2) if wall_time > 0 else 0,
            "calls": n_calls,
            "errors": errors,
        }

    return results


# ── Main ─────────────────────────────────────────────────────────────────

def print_table(results: list[BenchResult]):
    """Pretty-print benchmark results."""
    print("\n" + "=" * 140)
    print(f"{'Model':<30} {'Size':<7} {'E2E(ms)':>8} {'In Tok':>7} {'Out Tok':>8} "
          f"{'Think':>6} {'Total':>7} {'Out TPS':>8} {'In TPS':>8} "
          f"{'Pmt Ch':>7} {'Rsp Ch':>7} {'Cost $':>8} {'Status':<10}")
    print("-" * 140)

    for r in results:
        status = "OK" if not r.error else f"ERR: {r.error[:30]}"
        print(f"{r.model:<30} {r.prompt_size:<7} {r.e2e_ms:>8.0f} {r.input_tokens:>7} "
              f"{r.output_tokens:>8} {r.thinking_tokens:>6} {r.total_tokens:>7} {r.output_tps:>8.1f} "
              f"{r.input_tps:>8.0f} {r.prompt_chars:>7} {r.response_chars:>7} "
              f"{r.cost_usd:>8.5f} {status:<10}")

    print("=" * 140)


def print_parallel_results(results: dict):
    """Pretty-print parallel scheduling results."""
    print("\n" + "=" * 80)
    print("PARALLEL CALL SCHEDULING BENCHMARK")
    print("-" * 80)
    print(f"{'Concurrency':<20} {'Wall(ms)':>10} {'Sum E2E(ms)':>12} {'Speedup':>8} {'Errors':>7}")
    print("-" * 80)
    for label, data in results.items():
        print(f"{label:<20} {data['wall_time_ms']:>10.0f} {data['sum_e2e_ms']:>12.0f} "
              f"{data['speedup']:>8.2f}x {data['errors']:>7}")
    print("=" * 80)


def main():
    args = sys.argv[1:]
    do_parallel = "--parallel" in args
    do_context_sweep = "--context-sweep" in args
    args = [a for a in args if not a.startswith("--")]

    # Filter to requested providers or all available
    available = {}
    for key, cfg in BENCH_MODELS.items():
        env_key = cfg["env_key"]
        if cfg["type"] == "cloudflare":
            if os.environ.get(env_key) and os.environ.get(cfg.get("env_account", "")):
                available[key] = cfg
        else:
            if os.environ.get(env_key):
                available[key] = cfg

    if args:
        available = {k: v for k, v in available.items()
                     if any(a.lower() in k.lower() or a.lower() in v["provider"].lower() for a in args)}

    if not available:
        print("No providers available. Check your .env file.")
        sys.exit(1)

    print(f"\nBenchmarking {len(available)} models: {', '.join(available.keys())}")
    print(f"Prompts: small (~{len(SMALL_PROMPT)} chars)")

    # ── Single-call benchmarks ───────────────────────────────────────────
    all_results = []

    prompts = [("small", SMALL_PROMPT)]
    if do_context_sweep:
        prompts.append(("medium", MEDIUM_FILLER))
        prompts.append(("large", LARGE_FILLER))

    for prompt_size, prompt in prompts:
        print(f"\n--- {prompt_size.upper()} prompt (~{len(prompt)} chars) ---")
        for model_key in available:
            print(f"  Testing {model_key}...", end=" ", flush=True)
            result = call_model(model_key, prompt, prompt_size)
            all_results.append(result)
            if result.error:
                print(f"ERROR: {result.error[:60]}")
            else:
                print(f"{result.e2e_ms:.0f}ms, {result.output_tokens} out tok, "
                      f"{result.thinking_tokens} think tok, {result.output_tps:.1f} out TPS")
            # Respect rate limits between calls
            time.sleep(1)

    print_table(all_results)

    # ── Parallel scheduling benchmark ────────────────────────────────────
    if do_parallel:
        model_keys = list(available.keys())
        n_calls = max(len(model_keys) * 2, 6)
        print(f"\nTesting parallel scheduling with {n_calls} calls across {len(model_keys)} models...")
        par_results = benchmark_parallel(model_keys, n_calls=n_calls)
        print_parallel_results(par_results)

    # ── Summary & recommendations ────────────────────────────────────────
    print("\n" + "=" * 80)
    print("SUMMARY & CALL SCHEDULING RECOMMENDATIONS")
    print("=" * 80)

    ok_results = [r for r in all_results if not r.error and r.prompt_size == "small"]
    if ok_results:
        fastest = min(ok_results, key=lambda r: r.e2e_ms)
        highest_tps = max(ok_results, key=lambda r: r.output_tps)
        cheapest = min(ok_results, key=lambda r: r.cost_usd)
        most_thinking = max(ok_results, key=lambda r: r.thinking_tokens)

        print(f"\n  Fastest E2E:      {fastest.model} ({fastest.e2e_ms:.0f}ms)")
        print(f"  Highest Out TPS:  {highest_tps.model} ({highest_tps.output_tps:.1f} tok/s)")
        print(f"  Cheapest:         {cheapest.model} (${cheapest.cost_usd:.6f})")
        if most_thinking.thinking_tokens > 0:
            print(f"  Most Thinking:    {most_thinking.model} ({most_thinking.thinking_tokens} tokens)")

        print("\n  Scheduling strategies for ARC-AGI-3:")
        print("  1. FAST-FIRST: Route to fastest model for initial analysis,")
        print("     escalate to reasoning model (Gemini Pro) only if needed")
        print("  2. PARALLEL FAN-OUT: Send same prompt to 2-3 models in parallel,")
        print("     take first valid response (latency hedge)")
        print("  3. PIPELINE: Fast model filters/classifies → reasoning model solves")
        print("  4. BUDGET-AWARE: Track cumulative cost, switch to free models when budget is tight")

    # Save raw results to test/ directory
    test_dir = Path(__file__).parent / "test"
    test_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = test_dir / f"benchmark_{ts}.json"
    # Also save a latest symlink-style copy
    latest_path = test_dir / "benchmark_latest.json"

    out_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": [asdict(r) for r in all_results],
    }
    if do_parallel:
        out_data["parallel"] = par_results
    out_json = json.dumps(out_data, indent=2)
    out_path.write_text(out_json)
    latest_path.write_text(out_json)
    print(f"\n  Raw results saved to: {out_path}")
    print(f"  Latest copy at:       {latest_path}")


if __name__ == "__main__":
    main()
