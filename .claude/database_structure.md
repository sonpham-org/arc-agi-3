# Database Structure

Single SQLite database on Railway Volume (`/data/sessions.db` via `DB_DATA_DIR` env var).
Locally defaults to `./data/sessions.db`.

## Tables

### `sessions` — Session metadata

Each game session (human or AI) gets one row. Loaded per-user for session browsing.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Session UUID |
| `game_id` | TEXT NOT NULL | Which game was played |
| `created_at` | REAL NOT NULL | Unix timestamp |
| `user_id` | TEXT | Author (FK to users) |
| `player_type` | TEXT | `'human'` or `'agent'` |
| `scaffolding_json` | TEXT | If agent: full scaffolding config (type, models, params) |
| `model` | TEXT | Primary model used |
| `result` | TEXT | `'WIN'`, `'LOSE'`, `'NOT_FINISHED'` |
| `steps` | INTEGER | Total steps taken |
| `levels` | INTEGER | Levels reached |
| `steps_per_level_json` | TEXT | JSON array of step counts per level, e.g. `[12, 8, 15]` |
| `total_cost` | REAL | Total LLM cost in USD |
| `duration_seconds` | REAL | Wall-clock duration |
| `parent_session_id` | TEXT | If branched: parent session |
| `branch_at_step` | INTEGER | If branched: step number where branch occurred |
| `live_mode` | INTEGER | `1` if human session was played in live mode (auto-tick ACT7), `0` otherwise |
| `live_fps` | INTEGER | FPS used during live mode (null if not live mode) |

### `session_actions` — Game actions

Every action taken in a session. One action can produce multiple state transitions (e.g., player moves → enemy moves → level complete).

| Column | Type | Description |
|--------|------|-------------|
| `session_id` | TEXT NOT NULL | FK to sessions |
| `step_num` | INTEGER NOT NULL | Sequential action number |
| `action` | INTEGER NOT NULL | Action enum (1-4 = d-pad, 6 = click) |
| `row` | INTEGER | Grid row (for click actions) |
| `col` | INTEGER | Grid col (for click actions) |
| `author_id` | TEXT | Who performed this action |
| `author_type` | TEXT | `'human'` or `'agent'` |
| `call_id` | INTEGER | FK to llm_calls (if AI-initiated) |
| `states_json` | TEXT | JSON array of game states resulting from this action |
| `timestamp` | REAL NOT NULL | When the action was executed |
| PK | | `(session_id, step_num)` |

### `llm_calls` — LLM invocations

Every individual LLM API call, tagged by which agent made it.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | TEXT NOT NULL | FK to sessions |
| `agent_type` | TEXT NOT NULL | Agent role (e.g., `'planner'`, `'executor'`, `'monitor'`, `'world_model'`, `'single'`) |
| `agent_id` | TEXT | Instance ID within session (e.g., `'executor-1'`, `'executor-2'`) |
| `step_num` | INTEGER | Which game step this call relates to |
| `turn_num` | INTEGER | Which planning turn |
| `parent_call_id` | INTEGER | For sub-calls (e.g., monitor triggered by planner) |
| `model` | TEXT NOT NULL | Model used |
| `input_json` | TEXT | Full prompt/messages sent |
| `input_tokens` | INTEGER | Token count |
| `output_json` | TEXT | Full response received |
| `output_tokens` | INTEGER | Token count (response text only, excludes thinking) |
| `thinking_tokens` | INTEGER | Thinking/reasoning token count (Gemini thinking, Claude extended thinking) |
| `thinking_json` | TEXT | Thinking/reasoning text content (truncated to 5000 chars) |
| `cost` | REAL | USD cost of this call (input + output + thinking tokens) |
| `duration_ms` | INTEGER | Latency |
| `error` | TEXT | Error message if failed |
| `timestamp` | REAL NOT NULL | When the call was made |

### `tool_executions` — REPL code & tool calls

Every piece of code the agent wrote and ran, plus tool invocations. Enables full reconstruction of agent reasoning.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `session_id` | TEXT NOT NULL | FK to sessions |
| `call_id` | INTEGER | FK to llm_calls (which LLM call triggered this) |
| `agent_id` | TEXT | Which agent ran it |
| `tool_name` | TEXT NOT NULL | `'repl'`, `'memory_read'`, `'memory_write'`, etc. |
| `code` | TEXT | Full Python source (for REPL) or tool arguments |
| `output` | TEXT | Execution result / stdout |
| `error` | TEXT | Error message if failed |
| `variables_snapshot_json` | TEXT | REPL namespace dump (only at checkpoints) |
| `is_checkpoint` | INTEGER | `1` at turn boundaries, `0` otherwise |
| `timestamp` | REAL NOT NULL | When executed |

### `comments` — User feedback

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment |
| `user_id` | TEXT NOT NULL | FK to users |
| `author_name` | TEXT NOT NULL | Display name |
| `body` | TEXT NOT NULL | Comment text |
| `upvotes` | INTEGER | Upvote count |
| `downvotes` | INTEGER | Downvote count |
| `location` | TEXT NOT NULL | `'feedback'` or a game_id |
| `created_at` | REAL NOT NULL | When posted |

### `comment_votes` — Vote tracking

| Column | Type | Description |
|--------|------|-------------|
| `comment_id` | INTEGER NOT NULL | FK to comments |
| `voter_id` | TEXT NOT NULL | FK to users |
| `vote` | INTEGER NOT NULL | `+1` or `-1` |
| PK | | `(comment_id, voter_id)` |

### `users` — Auth

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | User UUID |
| `email` | TEXT UNIQUE | Login email |
| `display_name` | TEXT | Shown in UI |
| `google_id` | TEXT | Google OAuth ID |
| `created_at` | REAL | When registered |
| `last_login_at` | REAL | Last login time |

### `auth_tokens` — Session tokens

| Column | Type | Description |
|--------|------|-------------|
| `token` | TEXT PK | Token string |
| `user_id` | TEXT NOT NULL | FK to users |
| `created_at` | REAL | When issued |
| `expires_at` | REAL | Expiry time |
| `last_used_at` | REAL | Last use time |

### `magic_links` — Passwordless login

| Column | Type | Description |
|--------|------|-------------|
| `code` | TEXT PK | Magic link code |
| `email` | TEXT NOT NULL | Target email |
| `created_at` | REAL | When created |
| `expires_at` | REAL | Expiry time |
| `used` | INTEGER | `0` or `1` |

## Tables Removed

These old tables are replaced by the schema above:

- `session_steps` → replaced by `session_actions` (adds author, explicit row/col, multi-state)
- `session_turns` → removed; agent hierarchy captured by `agent_type` + `agent_id` in `llm_calls`
- `session_events` → removed; events captured by `tool_executions` and action log
- `obs_events` → removed; observability data lives in `session_actions` + `llm_calls`
- `batch_runs` / `batch_games` → kept for CLI batch runner (unchanged)

## Reconstruction

To reconstruct a full agent session:

1. Load `sessions` row for metadata + scaffolding config
2. Load `session_actions` ordered by `step_num` for game state timeline
3. Load `llm_calls` ordered by `id` for the reasoning chain
4. Load `tool_executions` ordered by `id` for code that was written/run
5. At any checkpoint (`is_checkpoint=1`), `variables_snapshot_json` gives the full REPL state

This lets you replay: LLM thought → code written → code result → next LLM thought → game action → state change.
