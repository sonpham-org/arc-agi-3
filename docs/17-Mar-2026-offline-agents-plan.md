# Offline Arena Agents — Plan

**Date**: 2026-03-17
**Author**: Claude Opus 4.6
**Status**: Draft — awaiting approval

## Goal

Enable local agent generation using any LLM provider (LM Studio, Anthropic, Google, OpenAI), then upload to the Arena for competitive play. These agents are called **offline agents** and are prefixed `offline_`.

## Problem

Currently, agent evolution only happens server-side via `arena_heartbeat.py` using Anthropic's Haiku. The user has local compute (LM Studio) and API keys for multiple providers, and wants to generate agents locally against the same Program.md, then upload them.

## Scope

### In Scope
1. **CLI tool** (`offline_agent_runner.py`) — local evolution loop that reads Program.md, calls any LLM, generates agents, validates them, and uploads to the server
2. **Upload API** (`POST /api/arena/agents/<game_id>/offline`) — dedicated endpoint for offline agent uploads with validation + testing
3. **Multi-provider LLM support** — Anthropic, Google (Gemini), OpenAI, and LM Studio (OpenAI-compatible)
4. **Agent naming** — all offline agents auto-prefixed `offline_` (e.g., `offline_gen3_flood_fill`)
5. **Validation** — same 12-scenario test suite as server-side evolution, run on the server after upload
6. **Program.md fetch** — CLI can fetch current Program.md from server or read from local seed file

### Out of Scope
- Client-side (browser) changes — this is CLI-only
- Changes to the existing server-side evolution loop
- New arena games
- UI for managing offline agents (they appear in the existing leaderboard)

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `offline_agent_runner.py` | CLI entry point — orchestrates the full loop |
| `offline_llm.py` | Multi-provider LLM caller (Anthropic, Gemini, OpenAI, LM Studio) with tool-calling support |

### Modified Files

| File | Change |
|------|--------|
| `server/app.py` | Add `POST /api/arena/agents/<game_id>/offline` route |
| `server/services/arena_research_service.py` | Add `submit_offline_agent()` with offline-specific validation |
| `db_arena.py` | Add `contributor_type` field support (distinguish `offline` vs `evolution` vs `human`) |

### Data Flow

```
CLI (local machine)
  │
  ├─ 1. Fetch Program.md from server (GET /api/arena/program/<game_id>)
  │     or read local seed file
  │
  ├─ 2. Fetch leaderboard (GET /api/arena/agents/<game_id>)
  │     + top agent code (GET /api/arena/agents/<game_id>/<id>)
  │
  ├─ 3. Build system prompt (Program.md + create instructions)
  │     Build user prompt (leaderboard + top agent code)
  │
  ├─ 4. Call LLM (any provider) with tool-calling loop
  │     Tools: create_agent, read_agent, run_test (local validation)
  │     LLM generates agent code via create_agent tool call
  │
  ├─ 5. Local validation (syntax, safety, timing, get_move exists)
  │
  └─ 6. Upload to server (POST /api/arena/agents/<game_id>/offline)
        Server re-validates + runs 12-scenario tests
        Agent enters tournament pool with offline_ prefix
```

### Multi-Provider LLM Architecture (`offline_llm.py`)

Reuses existing provider patterns from the codebase:

| Provider | Method | Auth | Notes |
|----------|--------|------|-------|
| **Anthropic** | Direct httpx (like `arena_tool_runner.py`) | `ANTHROPIC_API_KEY` env var or `--anthropic-key` flag | Native tool_use support |
| **OpenAI** | `openai` SDK or httpx | `OPENAI_API_KEY` env var or `--openai-key` flag | Native function calling |
| **Google Gemini** | `google.genai` SDK (like `llm_providers_google.py`) | `GEMINI_API_KEY` env var or `--gemini-key` flag | Native function calling |
| **LM Studio** | OpenAI-compatible endpoint | `--lmstudio-url` flag (default `http://localhost:1234/v1`) | Tool support depends on model |

All providers use the same tool schema (converted to each provider's format) and the same tool handler. The tool-calling loop is generic:

```
while rounds < max_rounds:
    response = call_llm(provider, messages, tools)
    if no tool calls: break
    for each tool call:
        result = handle_tool(name, args)
        append result to messages
```

### Upload API Design

```
POST /api/arena/agents/<game_id>/offline
Content-Type: application/json

{
  "name": "offline_gen3_flood_fill",     # must start with "offline_"
  "code": "def get_move(state): ...",     # full Python source
  "provider": "anthropic",                # which LLM created it
  "model": "claude-sonnet-4-6",           # model used
  "api_key_hash": "sha256:abc123..."      # optional — hash of API key for rate-limiting per key
}

Response 200:
{
  "id": 1234,
  "name": "offline_gen3_flood_fill",
  "elo": 1000,
  "test_results": {"passed": 12, "failed": 0, "details": "All 12 tests passed."}
}

Response 400:
{
  "error": "Validation failed: get_move returned invalid direction 'DIAGONAL'"
}
```

### Validation Pipeline (server-side)

1. **Name check** — must match `^offline_[a-zA-Z0-9_]{1,55}$`
2. **Code check** — reuse `validate_agent_code()` (50KB max, get_move exists, no dangerous patterns)
3. **Safety check** — reuse `_load_agent_fn()` sandboxed execution
4. **12-scenario test** — reuse `_validate_code()` from `arena_heartbeat.py` (all game-specific scenarios)
5. **Duplicate check** — reject if name already exists for this game
6. **Rate limit** — 20 offline agents per day per API key hash (more generous than web UI's 10)

### CLI Usage

```bash
# Basic: use Anthropic, target snake game
python offline_agent_runner.py --game snake --provider anthropic

# Use LM Studio local model
python offline_agent_runner.py --game snake --provider lmstudio --lmstudio-url http://localhost:1234/v1

# Use Gemini
python offline_agent_runner.py --game snake --provider gemini

# Use OpenAI
python offline_agent_runner.py --game snake --provider openai --model gpt-4o

# Override server URL (default: https://arc3.sonpham.net)
python offline_agent_runner.py --game snake --provider anthropic --server http://localhost:8000

# Multiple agents in one run
python offline_agent_runner.py --game snake --provider anthropic --count 3

# Use local seed file instead of fetching from server
python offline_agent_runner.py --game snake --provider lmstudio --program-file server/arena_seeds/default_program.md
```

### CLI Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--game` | `snake` | Arena game ID |
| `--provider` | (required) | `anthropic`, `openai`, `gemini`, `lmstudio` |
| `--model` | Provider default | Model ID override |
| `--server` | `https://arc3.sonpham.net` | Server URL for upload + data fetch |
| `--count` | `1` | Number of agents to generate |
| `--max-rounds` | `6` | Max tool-calling iterations per agent |
| `--max-tokens` | `8192` | Max tokens per LLM response |
| `--program-file` | (none) | Local Program.md path (skips server fetch) |
| `--lmstudio-url` | `http://localhost:1234/v1` | LM Studio endpoint |
| `--anthropic-key` | `$ANTHROPIC_API_KEY` | Anthropic API key |
| `--openai-key` | `$OPENAI_API_KEY` | OpenAI API key |
| `--gemini-key` | `$GEMINI_API_KEY` | Google API key |
| `--dry-run` | `false` | Validate locally but don't upload |
| `--verbose` | `false` | Print full LLM conversation |

## TODOs — Ordered Implementation Steps

### Phase 1: Upload API (server-side)

- [ ] Add `POST /api/arena/agents/<game_id>/offline` route to `server/app.py`
- [ ] Add `submit_offline_agent()` to `arena_research_service.py` with offline-specific validation
- [ ] Extract `_validate_code()` from `arena_heartbeat.py` into a shared utility (currently it's a private function — both heartbeat and offline upload need it)
- [ ] Add `contributor_type` column to `arena_agents` table (values: `evolution`, `offline`, `human`, `seed`)
  - Migration: default existing agents to `evolution` or `seed` based on `is_anchor`
- [ ] Verify: `curl -X POST .../api/arena/agents/snake/offline` with valid agent code → 200

### Phase 2: Multi-Provider LLM Module (`offline_llm.py`)

- [ ] Implement `call_anthropic_tools()` — direct httpx, reuse auth logic from `arena_tool_runner.py`
- [ ] Implement `call_openai_tools()` — openai SDK or httpx to OpenAI API
- [ ] Implement `call_gemini_tools()` — google.genai SDK, convert tool schemas
- [ ] Implement `call_lmstudio_tools()` — OpenAI-compatible endpoint, same as openai but custom base URL
- [ ] Implement `run_tool_loop()` — generic multi-turn loop that dispatches to any provider
- [ ] Verify: each provider can do a single tool call and return a result

### Phase 3: CLI Tool (`offline_agent_runner.py`)

- [ ] Implement Program.md fetcher (server API or local file)
- [ ] Implement leaderboard fetcher (server API)
- [ ] Implement tool handler (create_agent → local validation → upload)
- [ ] Implement `read_agent` tool (fetch from server API)
- [ ] Implement `run_test` tool (local _validate_code)
- [ ] Implement `test_match` tool (run local snake match)
- [ ] Wire up argument parser
- [ ] Wire up main loop: for each `--count`, run one evolution cycle
- [ ] Verify: `python offline_agent_runner.py --game snake --provider anthropic --dry-run` generates valid agent code

### Phase 4: Integration Testing

- [ ] End-to-end: generate with Anthropic → upload → appears on leaderboard
- [ ] End-to-end: generate with LM Studio → upload → appears on leaderboard
- [ ] Verify offline agents play in tournaments (no special treatment — just regular agents with `offline_` name)
- [ ] Verify rate limiting works (>20 uploads/day → rejected)

## Docs / Changelog Touchpoints

- `CHANGELOG.md` — new feature entry for offline agents
- No new docs needed — CLI `--help` is the documentation

## Design Decisions

1. **Dedicated `/offline` endpoint** rather than reusing `POST /api/arena/agents/<game_id>` — keeps validation separate and allows offline-specific rate limits + metadata.

2. **Name prefix `offline_`** enforced server-side — the upload API rejects names that don't start with `offline_`. This makes them instantly identifiable on the leaderboard.

3. **Server-side re-validation** — even though the CLI validates locally, the server runs the full 12-scenario test suite again. Defense in depth: never trust the client.

4. **Separate `offline_llm.py`** rather than extending `arena_tool_runner.py` — the tool runner is Anthropic-only and tightly coupled to httpx. The offline module needs to support 4 providers with different SDKs. No benefit to forcing them together.

5. **No auth required for upload** — same as existing `POST /api/arena/agents/<game_id>`. Rate-limited by API key hash instead. If we add auth later, the endpoint is ready (just add `@login_required`).

6. **`contributor_type` DB field** — distinguishes how an agent was created. Enables future filtering (e.g., "show only offline agents" or "only evolution agents").
