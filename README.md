# ARC-AGI-3

A web platform for playing [ARC-AGI-3](https://arcprize.org/) games — interactive reasoning puzzles on a 64×64 pixel grid with 16 colours. No instructions are given; players (human or AI) must discover the rules, controls, and goals by experimenting.

**Live at [arc3.sonpham.net](https://arc3.sonpham.net)**

---

## Quick start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # fill in API keys you want to use
python server/app.py           # local dev server
```

Open `http://localhost:5000` in your browser to play.

### CLI agent

```bash
python agent.py --game ls20                        # play one game
python agent.py --model gemini-2.5-flash --game ft09  # override model
python agent.py --max-steps 400                    # custom step limit
python agent.py --list-models                      # check available models
python agent.py --show-config                      # print resolved config
```

### Batch runner

```bash
python batch_runner.py --games ls20 --concurrency 1 --max-steps 10   # smoke test
python batch_runner.py --games all --concurrency 4                   # all games
python batch_runner.py --games fd01,ft09 --repeat 3 --concurrency 4  # specific games
python batch_runner.py --resume <batch_id>                           # resume interrupted
```

---

## Architecture

### Client-side game logic

All game-playing logic runs **in the browser**: game environment execution (Pyodide or server-proxied), LLM calls (BYOK / Puter.js / Copilot), REPL / code execution, agent memory, and scaffolding logic. The server is stateless except for auth and session persistence.

### Python backend

**Entry points:**
- `server/app.py` — Flask application (63 routes)
- `agent.py` — Autonomous CLI agent
- `batch_runner.py` — Batch game runner

**Service layer** (`server/services/`):
- `auth_service.py` — Magic link, Google OAuth, Copilot auth, API keys
- `session_service.py` — Session resume, branch, import, OBS events
- `game_service.py` — Game start, step, reset, undo
- `social_service.py` — Comments, leaderboard, contributors
- `llm_admin_service.py` — Model listing, BYOK key management

**Database layer:**
- `db.py` — Connection pooling, schema init, migrations
- `db_sessions.py` — Session CRUD
- `db_auth.py` — Users, tokens, magic links
- `db_llm.py` — LLM call logging
- `db_tools.py` — Tool execution logging
- `db_exports.py` — File export/import

**LLM providers:**
- `llm_providers.py` — Router: model ID → provider call
- `llm_providers_openai.py` — OpenAI + LM Studio (OpenAI-compatible)
- `llm_providers_anthropic.py` — Anthropic Claude
- `llm_providers_google.py` — Google Gemini
- `llm_providers_copilot.py` — GitHub Copilot (device flow)

**Agent modules:**
- `agent.py` — Game-playing orchestrator
- `agent_llm.py` — LLM decision logic
- `agent_response_parsing.py` — Parse LLM responses → actions
- `agent_history.py` — Action history management

**Infrastructure:**
- `models.py` — Model registry (42 models across 10 providers)
- `constants.py` — Shared constants
- `exceptions.py` — Structured error classes

### JavaScript frontend (`static/js/`)

Global-scope scripts loaded via `<script>` tags. Load order matters.

**Core:** `state.js`, `engine.js`, `reasoning.js`

**UI:** `ui.js`, `ui-grid.js`, `ui-models.js`, `ui-tabs.js`, `ui-tokens.js`

**LLM:** `llm.js`, `llm-config.js`, `llm-controls.js`, `llm-executor.js`, `llm-reasoning.js`, `llm-timeline.js`

**Scaffolding:** `scaffolding.js`, `scaffolding-linear.js`, `scaffolding-rlm.js`, `scaffolding-three-system.js`, `scaffolding-agent-spawn.js`, `scaffolding-world-model.js`

**Session:** `session.js`, `session-storage.js`, `session-persistence.js`, `session-replay.js`, `session-views.js`, `session-views-grid.js`, `session-views-history.js`

**Observatory:** `observatory.js`, `obs-page.js`, `obs-scrubber.js`, `obs-session-loader.js`, `obs-swimlane.js`

**Human play:** `human.js`, `human-game.js`, `human-input.js`, `human-render.js`, `human-session.js`, `human-social.js`

**Other:** `arena.js`, `leaderboard.js`, `memory-inspector.js`, `share-page.js`, `draw-page.js`, `dev.js`

### HTML pages

- `templates/index.html` — Main SPA (game player + agent UI)
- `templates/obs.html` — Observatory (session replay viewer)
- `templates/share.html` — Public share/replay page
- `templates/arena.html` — Game arena
- `templates/draw.html` — Grid drawing tool
- `templates/ab01.html` — Antibody standalone page

---

## Configuration

The CLI agent is configured via `config.yaml` with four blocks:

### Context block — what the agent sees

| Setting | Default | Effect |
|---------|---------|--------|
| `full_grid` | `true` | Full RLE-compressed 64×64 grid |
| `change_map` | `true` | Cells changed since last action |
| `color_histogram` | `false` | Count of each colour |
| `region_map` | `false` | Connected-component regions (BFS flood-fill) |
| `history_length` | `0` | Recent moves in prompt (0 = all) |
| `reasoning_trace` | `false` | Include LLM reasoning in history |
| `max_context_tokens` | `100000` | Token budget for context |
| `memory_injection` | `true` | Inject hard-memory facts |
| `memory_injection_max_chars` | `1500` | Max chars of memory to inject |

### Reasoning block — which models think

| Setting | Default | Effect |
|---------|---------|--------|
| `executor_model` | `gemini-2.5-flash` | Main action model |
| `condenser_model` | `null` | History condensation model (null = reuse executor) |
| `reflector_model` | `null` | Post-game reflection model (null = reuse executor) |
| `temperature` | `0.3` | Sampling temperature |
| `max_tokens` | `2048` | Max output tokens |
| `planning_horizon` | `5` | Max actions per LLM call |
| `reflection_max_tokens` | `1024` | Max tokens for reflection passes |
| `planner_model` | `null` | Scaffolding planner model |
| `monitor_model` | `null` | Scaffolding monitor model |
| `world_model_model` | `null` | Scaffolding world model |

### Memory block — what the agent remembers

| Setting | Default | Effect |
|---------|---------|--------|
| `hard_memory_file` | `memory/MEMORY.md` | Cross-session persistent facts |
| `session_log_file` | `memory/sessions.json` | Structured session log |
| `allow_inline_memory_writes` | `true` | Agent can save facts mid-game |
| `reflect_after_game` | `true` | Reflection pass after each game |
| `condense_every` | `0` | Summarise history every N steps (0 = off) |
| `condense_threshold` | `0` | Force condensation above N entries (0 = off) |

### Scaffolding block — multi-system agent architecture

| Setting | Default | Effect |
|---------|---------|--------|
| `mode` | `single` | `single` or `three_system` |
| `planner_max_turns` | `10` | Max REPL iterations for planner |
| `world_model_max_turns` | `5` | Max REPL iterations for world model |
| `world_model_update_every` | `5` | Steps between world model updates |
| `max_plan_length` | `15` | Maximum plan steps |
| `min_plan_length` | `3` | Minimum plan steps |

---

## Supported providers

| Provider | Example model | Env key | Cost |
|----------|--------------|---------|------|
| **Anthropic** | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | Paid |
| **Gemini** | `gemini-2.5-flash` | `GEMINI_API_KEY` | ~Free |
| **OpenAI** | `openai/o4-mini` | `OPENAI_API_KEY` | Paid |
| **Groq** | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` | Free |
| **Mistral** | `mistral/mistral-small-latest` | `MISTRAL_API_KEY` | Free |
| **Cloudflare** | `cf/llama-3.3-70b-instruct` | `CLOUDFLARE_API_KEY` + `CLOUDFLARE_ACCOUNT_ID` | Free |
| **HuggingFace** | `hf/qwen2.5-72b-instruct` | `HUGGINGFACE_API_KEY` | Free |
| **Copilot** | `copilot/gpt-4.1` | None (OAuth) | Free w/ subscription |
| **Puter** | `puter/gpt-4o` | None (client-side) | Free |
| **LM Studio** | `lmstudio/qwen3.5-35b` | None (local) | Free |
| **Ollama** | `ollama/llama3.1` | None (local) | Free |

Full model list: see `models.py` `MODEL_REGISTRY` or run `python agent.py --list-models`.

---

## Session Streaming API

External harnesses can stream game sessions to `arc3.sonpham.net` in real-time. Live sessions appear in **Browse Sessions → AI Sessions** with a 🔴 Live badge.

### Quick start

```python
import requests, websockets, json, asyncio

# 1. Register a session
resp = requests.post("https://arc3.sonpham.net/api/sessions/stream/register", json={
    "game_id": "ls20",
    "harness": "my-harness",
    "agents": [{"id": "main", "model": "gemini-2.5-flash", "role": "executor"}]
})
data = resp.json()
ws_url = data["ws_url"]          # wss://arc3.sonpham.net/ws/stream/{id}?token=...
view_url = data["view_url"]      # share this link — anyone can watch live

# 2. Stream events over WebSocket
async def run():
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"v":1, "event":"session_start", "game_id":"ls20", ...}))
        # After each LLM call:
        await ws.send(json.dumps({"v":1, "event":"llm_call", "agent_id":"main", ...}))
        # After each game action (grid state is required):
        await ws.send(json.dumps({"v":1, "event":"act", "action":"UP", "grid":[[...]], ...}))
        # When done:
        await ws.send(json.dumps({"v":1, "event":"session_end", "result":"WIN", ...}))

asyncio.run(run())
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sessions/stream/register` | Register a new live session. Returns `session_id`, `stream_token`, `ws_url`, `view_url`. |
| `WS` | `/ws/stream/{session_id}?token={stream_token}` | Push events as JSON messages. One event per message. |
| `GET` | `/api/sessions/live` | List all currently streaming sessions (game, model, steps, viewers). |
| `GET` | `/api/sessions/{id}/obs-events?live=true` | SSE stream for viewers — replays history then tails live events. |
| `POST` | `/api/sessions/upload` | Upload a completed `.arc3log` (JSONL) file for post-hoc replay. |

### Event types

All events share an envelope: `{"v": 1, "t": "<ISO-8601>", "elapsed_s": <float>, "session_id": "...", "game_id": "...", "event": "<type>"}`.

| Event | Required fields | Purpose |
|-------|----------------|---------|
| `session_start` | `harness`, `agents[]` | Harness metadata — emitted once at start |
| `llm_call` | `agent_id`, `model`, `response` | One per LLM API call. Optional: `coordinates_mentioned[]` for hover highlight |
| `act` | `action`, `grid[][]`, `step_num` | One per game action. `grid` = full 64×64 state after action |
| `memory_write` | `file`, `content` | Full memory file content at time of write |
| `tool_call` | `tool`, `code`, `output` | REPL / tool executions |
| `agent_message` | `from_agent`, `to_agent`, `content` | Inter-agent communication |
| `session_end` | `result`, `total_steps`, `total_cost` | Final summary — emitted once at end |

Full specification with examples: [`docs/SESSION-LOG-API.md`](docs/SESSION-LOG-API.md)

---

## Deployment

- **Railway**: auto-deploys from `master` branch
- **Procfile**: `gunicorn server.app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8`
- **Railway Volume**: persistent disk at `/data` for SQLite
- **Env vars**: `SERVER_MODE=prod`, `DB_DATA_DIR=/data`
- **Staging**: push to `staging` branch first, never directly to `master`

---

## Testing

```bash
python tests/test_providers.py              # all provider API paths
python tests/test_providers.py groq         # single provider
python -c "from server.app import app; import db; import agent; import batch_runner; print('OK')"
python batch_runner.py --games ls20 --concurrency 1 --max-steps 5   # smoke test
```

---

## License

Uses [arc-agi](https://pypi.org/project/arc-agi/) and [arcengine](https://pypi.org/project/arcengine/) from ARC Prize.
