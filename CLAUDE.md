# ARC-AGI-3 Project Instructions

## Terminology

- **"Replay"** = the share page (`share.html` / `/share/<id>` endpoint), NOT the in-app replay in `index.html`
- **"Step"** = a single game step (one action executed in the environment via `env.step()`). Stored in `session_steps`.
- **"Turn"** = one complete planning cycle. In scaffold mode: planner REPL → execute plan steps → monitor checks → world model update. In single-agent mode: one LLM call → one step. Each turn gets a unique `turnId`. Undo reverts an entire turn, not individual steps. Stored in `session_turns`.
- **"Call"** = one individual LLM invocation. A single turn may contain many calls (planner REPL iterations, monitor checks, world model queries). In single-agent mode, one turn = one call. Stored in `llm_calls`. Compact context triggers after N Calls, not Steps.

## UI Views (index.html)

The web UI has two main views that replace each other in the main content area:

1. **Settings View** (default) — Game sidebar (list of games) on the left, game canvas with human controls (d-pad, intervene button) and transport bar (Autoplay, Undo, Restart) in the center, and the right panel with Agent Settings / Prompts / Graphics tabs. No scrubber in this view.
2. **Observatory View** — Replaces the entire settings view during autoplay or when resumed. Left side has status bar, swimlane timeline, and event log table. Right side has the game canvas, step scrubber, reasoning log (mirrored from the Reasoning tab), and transport (Pause / Back to Settings). A "Back to Observatory" button appears in the settings transport bar after exiting obs mode.

When modifying either view, do NOT mix up their elements — they have separate DOM structures. The observatory has its own scrubber (`obsScrubBar`), its own reasoning mirror (`obsReasoningContent`), and its own canvas host (`obsCanvasHost`). The settings view's live scrubber (`liveScrubberBar`) is kept hidden.

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
python tests/test_providers.py          # test all configured providers
python tests/test_providers.py groq     # test single provider
```

Each test sends one short prompt and validates the response parses as JSON. Total cost: <$0.01 for all paid providers combined.

## Default Test Game

Use **LS20** (`ls20`) as the default game for all smoke tests and manual testing.

## Batch Runner

```bash
# Single game smoke test
python batch_runner.py --games ls20 --concurrency 1 --max-steps 10

# All games, 4 workers
python batch_runner.py --games all --concurrency 4

# Specific games with repeats
python batch_runner.py --games fd01,ft09 --repeat 3 --concurrency 4

# Resume interrupted batch
python batch_runner.py --resume <batch_id>

```

## Environments (Staging vs Prod)

Only two environments — no separate "local" mode:
- **Staging** (`SERVER_MODE=staging` or unset) — all features, all games visible. Used for both local dev and Railway staging deployment.
- **Prod** (`SERVER_MODE=prod`) — same features, but games in `HIDDEN_GAMES` list are hidden from `/api/games` unless `?show_all=1` is passed.

The `HIDDEN_GAMES` list is a hardcoded Python list in `server.py`. `SERVER_MODE` env var controls which mode is active.

## Client-Side Architecture (CRITICAL)

**All game-playing logic runs CLIENT-SIDE in the browser.** This includes:
- Game environment execution (Pyodide or server-proxied game steps)
- LLM calls (BYOK / Puter.js / Copilot — keys stored in browser)
- REPL / code execution (Pyodide sandbox in browser)
- Agent memory / variables (in-memory JS, persisted to session state)
- Scaffolding logic (RLM iterations, planning, compaction)

The server's role is LIMITED to:
- Serving static files (`index.html`, game data)
- Session persistence (save/resume via SQLite)
- Proxying game steps when Pyodide isn't available
- Model registry / capabilities metadata

**Never add server-side LLM orchestration for scaffoldings.** All scaffolding types (Linear, RLM, Three-System) must run their iteration loops, REPL execution, and sub-calls client-side. The server-side `scaffoldings/` Python handlers exist only for the CLI `agent.py` / `batch_runner.py` path, not the web UI.

When a session is saved/resumed, all necessary state (REPL variables, memory, compact summaries) must be serialized into the session record so the session can be accurately restored.

## Model Select Checklist (recurring bug)

Every `{ type: 'model-select', id: '...' }` field in `SCAFFOLDING_SCHEMAS` **must** be wired up in three places:

1. **`loadModels()`** — populate the `<select>` with model options via `_populateSubModelSelect()`. Without this, the select stays at "Loading..." forever.
2. **`loadModels()` restore block** — after populating, restore saved value from `localStorage.getItem('arc_scaffolding_<type>')`. Without this, model choices reset when switching scaffoldings.
3. **`attachSettingsListeners()`** — add a `change` listener to trigger BYOK key prompt updates (if the scaffold has a Model Keys section).

This has been missed repeatedly (Three-System selects, REPL selects, etc.). When adding a new `model-select` to any scaffold, always update all three places.

## Building New Games

When creating a new ARC-AGI-3 game, follow this checklist:

### Game Versioning

Every time a game's code is updated (bug fix, level change, balance tweak, new levels, etc.), the **version directory number must be incremented**. The version directory is the 8-digit folder under the game ID:

```
environment_files/<game_id>/<version>/
```

- `00000001` → initial version
- `00000002` → first update
- `00000003` → second update, etc.

The `metadata.json` must also be updated with the current `date_downloaded` (use the date of the change, format `YYYY-MM-DD`). This ensures:
- Old sessions replay correctly against the version they were recorded on
- We can track when each change was made
- Breaking changes don't silently corrupt existing data

**Never edit a game file in-place without bumping the version.** If the change is purely cosmetic (comments, whitespace), a version bump is not required.

### File Structure
- Directory: `environment_files/<game_id>/<version>/` (version = zero-padded 8-digit number, e.g., `00000001`)
- Game file: `<game_id>.py` with class named in PascalCase from the ID (e.g., `mk01` → `Mk01`)
- Metadata: `metadata.json` with `game_id`, `title`, `default_fps`, `baseline_actions`, `tags`, `local_dir`, `date_downloaded` (date of this version)

### Game Class Requirements
- Extend `ARCBaseGame` from `arcengine`
- Class name MUST match the game ID in PascalCase (e.g., `Mk01`, `Ls20`) — Pyodide loads it by this name
- Override `step()` and call `self.complete_action()` at the end of every code path
- Override `on_set_level()` for level-specific setup
- Use `self.next_level()` for win, `self.lose()` for game over
- `available_actions` in constructor: `[1,2,3,4]` for d-pad, `[6]` for click-only, `[1,2,3,4,6]` for both

### Mandatory Smoke Test
After building or modifying any game, run this automated playthrough that **wins every level** using the game's actual movement system:

```bash
source venv/bin/activate && python -c "
import sys; sys.path.insert(0, 'environment_files/<game_id>/00000001')
import <game_id>
g = <game_id>.<ClassName>()
from arcengine.enums import ActionInput, GameAction

# For click games (ACTION6):
def click(gx, gy):
    ox, oy = g.current_level.get_data('ox'), g.current_level.get_data('oy')
    CELL = 5  # or whatever cell size the game uses
    return g.perform_action(ActionInput(id=GameAction.ACTION6, data={'x': ox+gx*CELL+2, 'y': oy+gy*CELL+2}))

# For d-pad games (ACTION1-4):
UP, DOWN, LEFT, RIGHT = GameAction.ACTION1, GameAction.ACTION2, GameAction.ACTION3, GameAction.ACTION4
A = lambda a: g.perform_action(ActionInput(id=a))

# ... solve every level ...
# Final check must show GameState.WIN
"
```

This test must:
1. Solve **every single level** in sequence
2. End with `GameState.WIN`
3. Use the actual movement system (clicks for click games, d-pad for d-pad games)

### Design Rules (reiterated)
- Fully deterministic — no RNG
- All state defined as constants
- Sprites: use `tags=[]` in constructor (tags property has no setter)
- For click games: store valid moves dict, validate clicks against it
- Guards/moving enemies: move AFTER player, check collision after guard movement, check win BEFORE guard movement

## After Every Fix

After completing any fix or feature, **always**:
1. Push to `staging`
2. Run all non-LLM tests (import check + any unit/integration tests that don't require API keys)
3. After any refactor, clean up dead code: remove old functions, aliases, unused HTML IDs, and dangling references that are no longer called

## Pre-Push QC

Before every push to staging, run:

```bash
python tests/test_providers.py          # all provider API paths work
python -c "import db; import server; import agent; import batch_runner; print('OK')"  # import check
python batch_runner.py --games ls20 --concurrency 1 --max-steps 5  # smoke test
```
