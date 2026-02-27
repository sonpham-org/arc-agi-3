# ARC-AGI-3 Project Instructions

## Terminology

- **"Replay"** = the share page (`share.html` / `/share/<id>` endpoint), NOT the in-app replay in `index.html`
- **"Step"** = a single game step (one action executed in the environment)
- **"Turn"** = one complete agent invocation (an LLM call + all steps in its plan), or one human action. Each turn gets a unique `turnId`. Undo reverts an entire turn, not individual steps.
- **"Call"** = one LLM agent invocation (may produce a multi-step plan). Compact context triggers after N Calls, not Steps.

## Reasoning View Consistency

The Reasoning view must look the same across ALL viewing modes and pages:
- **`index.html`**: live agent session, resumed session, branched session, in-app replay (all use `renderRestoredReasoning()`)
- **`share.html`**: public share/replay page (has its own rendering but must match the same grouped format)

When updating reasoning rendering in one place, update ALL others to match. Key principles:
- Steps are grouped into plan groups (LLM call + its plan followers), not shown individually
- Plan steps show as numbered action buttons; green = completed/current, unlit = pending
- Scrubber progressively lights up plan steps as you advance
- Human actions show separately in yellow
- Both pages must use the same grouping logic (check `llm_response.parsed` for plan leader, absorb followers by plan capacity)
- Branched sessions must show parent reasoning up to the branch point (trace back via `parent_session_id` / `branch_at_step`)

## Git Workflow

- **Always push to the `staging` branch first.** Never push directly to `master`.
- Only switch to `master` or merge into `master` when explicitly told to by the user.

## Game Design Rules

All games must be **fully deterministic** — no random elements of any kind:
- No `random`, `np.random`, or any other RNG calls
- Enemy movement, spawn positions, map layout, treasure placement — all fixed and hardcoded
- Given the same sequence of player actions, the game must always produce the exact same outcome
- Maps, levels, and all initial state are defined as constants, not generated at runtime

## Turso (Remote DB) Upload

To upload local sessions to Turso, you must source `.env` first since `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are not set in the shell by default:

```bash
set -a && source .env && set +a
```

Then use `libsql_experimental` to connect and write directly. The server's `_turso_import_session()` won't work from a standalone script because env vars are read at module import time. Instead, connect directly:

```python
import libsql_experimental as libsql
conn = libsql.connect("turso_replica.db", sync_url=url, auth_token=token)
```

Upload sessions with >5 steps to avoid cluttering Turso with empty/trivial sessions.

## LLM Providers

There are two model registries — `agent.py:MODELS` (CLI agent) and `server.py:MODEL_REGISTRY` (web UI). The batch runner uses `agent.py:MODELS`.

### Provider Reference

| Provider | Call path | Env key(s) | Cheapest test model | Cost |
|----------|-----------|------------|---------------------|------|
| **Groq** | OpenAI-compatible (`_call_openai_compatible`) | `GROQ_API_KEY` | `groq/llama-3.3-70b-versatile` | Free |
| **Mistral** | OpenAI-compatible | `MISTRAL_API_KEY` | `mistral/mistral-small-latest` | Free |
| **Gemini** | Google GenAI SDK (`_call_gemini`) | `GEMINI_API_KEY` | `gemini-2.5-flash` | ~Free |
| **Anthropic** | Direct httpx (`_call_anthropic`) | `ANTHROPIC_API_KEY` | `claude-haiku-4-5` | $0.80/$4 per 1M tok |
| **Cloudflare** | OpenAI-compatible via Workers AI | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID` | `cloudflare/llama-3.3-70b` | Free (10k neurons/day) |
| **HuggingFace** | OpenAI-compatible | `HUGGINGFACE_API_KEY` | `hf/meta-llama-3.3-70b` | Free tier |
| **Ollama** | OpenAI-compatible (localhost:11434) | None (local) | `ollama/llama3.1` | Free (local GPU) |
| **Copilot** | GitHub Copilot OAuth (web UI only) | None (OAuth flow) | `copilot/gpt-4o` | Free (with Copilot sub) |

**Known issues found by test_providers.py (fixed):**
- `gemini-2.0-flash-lite` deprecated — use `gemini-2.5-flash` or `gemini-2.0-flash`
- HuggingFace URL was stale (`api-inference.huggingface.co` → `router.huggingface.co`)
- Ollama: must not send `Authorization: Bearer` header with empty key

### Testing all providers

```bash
python test_providers.py          # test all configured providers
python test_providers.py groq     # test single provider
```

Each test sends one short prompt and validates the response parses as JSON. Total cost: <$0.01 for all paid providers combined.

## Batch Runner

```bash
# Single game smoke test
python batch_runner.py --games fd01 --concurrency 1 --max-steps 10

# All games, 4 workers
python batch_runner.py --games all --concurrency 4

# Specific games with repeats
python batch_runner.py --games fd01,ft09 --repeat 3 --concurrency 4

# Resume interrupted batch
python batch_runner.py --resume <batch_id>

# Upload results to Turso
python batch_runner.py --games all --upload-turso
```

## Environments (Staging vs Prod)

Only two environments — no separate "local" mode:
- **Staging** (`SERVER_MODE=staging` or unset) — all features, all games visible. Used for both local dev and Railway staging deployment.
- **Prod** (`SERVER_MODE=prod`) — same features, but games in `HIDDEN_GAMES` list are hidden from `/api/games` unless `?show_all=1` is passed.

The `HIDDEN_GAMES` list is a hardcoded Python list in `server.py`. `SERVER_MODE` env var controls which mode is active.

## Pre-Push QC

Before every push to staging, run:

```bash
python test_providers.py          # all provider API paths work
python -c "import db; import server; import agent; import batch_runner; print('OK')"  # import check
python batch_runner.py --games fd01 --concurrency 1 --max-steps 5  # smoke test
```
