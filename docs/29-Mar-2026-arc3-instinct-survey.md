# ARC3 Agent Instinct Survey

**Date:** 29-March-2026
**Goal:** Run the existing agent across all ARC-AGI-3 games, capture agent instincts, classify behavior patterns, write results to Railway Postgres for shared analysis.

**Repo:** `sonpham-org/arc-agi-3` — all work happens here, not in autoresearch-arena.

---

## Background

This repo has a working agent (`agent.py`) with config-driven LLM integration, grid analysis, prompt building, memory, and a batch runner. The agent uses `arc_agi.Arcade` in Local Toolkit mode.

The agent currently scores 0 on all tested games. It takes actions but never completes a level — it can't hatch. Before we can evolve harnesses or refine prompts, we need to understand what the agent naturally does across the full game catalog.

**Questions to answer:**
1. What does the agent naturally do when it sees each game?
2. Are there games where it gets close to hatching?
3. Where do its instincts (from training data) help vs hurt?

---

## Environment Setup

### `.env` File

A `.env` file should exist at repo root (excluded from git via `.gitignore`). On the Mac Mini it's already created. Contains:

```
ANTHROPIC_API_KEY=<sk-ant-oat...>   # OAuth token, agent_llm.py auto-detects prefix
GEMINI_API_KEY=<key>
ARC_AGI_3_API_KEY=<key>             # Required by arc_agi.Arcade
DATABASE_PUBLIC_URL=<postgres url>  # Railway Postgres public proxy
```

All values come from `~/.zshrc` on the Mac Mini. Run `source ~/.zshrc` before any work.

### Python Dependencies
Everything in `requirements.txt`. Key ones for the survey:
- `arc-agi==0.9.6`, `arcengine>=0.9` — game environment
- `httpx>=0.28` — LLM API calls
- `psycopg2-binary>=2.9` — Postgres writes (already in requirements, not yet used in code)
- `pyyaml>=6.0` — config

**Note:** `zstandard` is NOT needed — this repo uses `zlib` (stdlib) for compression in `db.py`, not `zstandard`.

### Sonnet 4.6 OAuth — How It Works in This Repo

`agent_llm.py` line 66-77 handles OAuth correctly:
- Detects `sk-ant-oat` prefix on `ANTHROPIC_API_KEY`
- Adds `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20` headers
- Sends system prompt as two content blocks: `[{preamble: "You are Claude Code..."}, {actual system}]`
- This two-block approach works — verified 29-March-2026
- `temperature=0.0` also works with this approach (unlike single-string system prompt)

No changes needed to `agent_llm.py` for the survey.

---

## Existing Codebase

### Key Files (all in repo root)
```
agent.py                  — Main agent: config, memory, prompt building, game loop
agent_llm.py              — LLM provider calls (Anthropic, Gemini, OpenAI, local)
agent_response_parsing.py — Parse LLM JSON → actions
agent_history.py          — History condensation, memory reflection
prompt_builder.py         — _build_prompt / _build_prompt_parts (grid RLE, change maps)
grid_analysis.py          — compress_row, compute_change_map, color_histogram, region_map
batch_runner.py           — Run multiple games via ThreadPoolExecutor
db.py                     — SQLite persistence (sessions, session_actions, llm_calls)
constants.py              — COLOR_NAMES, ACTION_NAMES, ARC_AGI3_DESCRIPTION, SYSTEM_MSG
models.py                 — Model registry, cost computation
```

### Local DB Schema

SQLite at `data/sessions.db`. Full schema in `.claude/database_structure.md`.

**`sessions`:** id (TEXT PK), game_id, created_at, player_type, model, result (`WIN`/`LOSE`/`NOT_FINISHED`), steps, levels, total_cost, duration_seconds, scaffolding_json

**`session_actions`:** session_id + step_num (PK), action (1-4=dpad, 6=click), row, col, call_id (FK→llm_calls), states_json, timestamp

**`llm_calls`:** id (INT PK), session_id, agent_type, step_num, model, prompt, response, input_tokens, output_tokens, cost, latency_ms

### Running Games
```bash
# Single game
python3 agent.py --game cn04 --model anthropic --max-actions 30

# Batch (concurrent)
python3 batch_runner.py --games cn04,ls20,vc33 --model anthropic --max-actions 30
```

---

## Game Catalog (46 unique games)

Pinned from `environment_files/` on 29-March-2026. The API returns 80 environments (some games have multiple variants).

```
ab   ac   ar   ar25 bp35 cd82 cn04 cr   dc22 fd
fr   ft09 fy   g50t gh   ka59 lb   lf52 lp85 ls20
m0r0 mr   mw   pc   pi   pt   px   r11l re86 s5i5
sb26 sc25 sh   sk48 sn   sp80 su15 td   tn36 tr87
ts   tu93 vc33 wa30 ws03 ws04
```

**Step 1 of execution:** Run `arcade.get_environments()` and record the full list (game_id + variant hash) as the first line of the output JSON. This pins the exact set for reproducibility.

---

## The Experiment

### Parameters
- **Model:** claude-sonnet-4-6 (OAuth, subscription — not per-token)
- **Steps per game:** 30
- **Games:** All unique environments from `arcade.get_environments()` (~80 variants across 46 game prefixes). Deduplicate by game prefix — run one variant per game.
- **Execution:** Sequential (`--workers 1`) to avoid OAuth rate limits
- **Per-game timeout:** 10 minutes — implemented via `threading.Timer` in the survey runner (NOT `signal.alarm`, which is unreliable in threaded Python on macOS). On timeout: save all completed actions to SQLite, mark session `result='TIMEOUT'`, continue to next game.

### Error Handling
- **Game won't load:** Log error, record `result='LOAD_FAILED'`, continue.
- **5 consecutive LLM 4xx/5xx errors:** Abort game, mark `result='FAILED'`, continue.
- **429 rate limit:** Retry with exponential backoff (2s, 4s, 8s, 16s, 32s — 5 retries max). If all 5 fail, pause the entire survey for 60 seconds, then retry once more. If that fails, abort game, mark `FAILED`, continue. OAuth Sonnet rate limits are generous but undocumented.
- **Game environment crash:** Catch exception, mark `FAILED`, continue.

### Resume Logic
Before running a game, check SQLite for an existing session matching `(game_id, model='claude-sonnet-4-6', steps >= 30 OR result IN ('WIN','LOSE','TIMEOUT'))`. If found, skip. This makes the survey idempotent — safe to restart after crashes.

### Cost Tracking
OAuth runs have no per-token billing. `total_cost` and per-call `cost` fields will contain **estimated costs** computed by `models.py` (based on public token pricing). These are useful for comparing relative expense across games/models, not for actual billing. This is called out explicitly so nobody mistakes them for real charges.

---

## Instinct Classification

After all games complete, classify each game's agent behavior. Classification runs on the collected data (no additional LLM calls).

| Category | Description | Primary Signal |
|----------|-------------|----------------|
| `random_clicker` | Clicks (ACTION6) on random positions. Mentions colors but no hypotheses. | ACTION6 > 60% of actions |
| `systematic_explorer` | Methodically tries actions, references changes, forms hypotheses. | ≥ 4 distinct action types used AND change references > 30% of steps |
| `directional_mover` | Defaults to movement (ACTION1-4). Thinks it's controlling a character. | ACTION1-4 collectively > 70% |
| `action5_spammer` | Repeats ACTION5 without understanding. | ACTION5 > 50% |
| `hypothesis_driven` | Explicitly states and tests hypotheses about game rules. | ≥ 3 steps with hypothesis language ("I think", "let me test", "this suggests", "my theory", "if I try") |
| `frozen` | Picks one action and repeats every step. No adaptation. | Single action > 80%, entropy < 0.5 |
| `partial_solver` | Completes at least one level. | `levels >= 1` |

### Classification Rules
1. Check `partial_solver` first — if `levels >= 1`, that's the classification regardless.
2. Check `frozen` next — single dominant action + low entropy overrides everything.
3. Then check `hypothesis_driven` — ≥ 3 hypothesis statements across all LLM responses.
4. Then check remaining categories by action distribution thresholds.
5. **Tiebreaker:** If multiple categories match after `partial_solver`/`frozen`/`hypothesis_driven`, pick the one with the strongest signal (highest percentage). Record secondary classification in `instinct_secondary` field.

### Where Classification Data Comes From
- Action distribution: `session_actions` table → count by `action` column
- LLM reasoning: `llm_calls` table → `response` column (contains JSON with `"reasoning"` and `"action"` fields as formatted by `agent_response_parsing.py`)
- Change awareness: count steps where the LLM response text references prior grid changes

### Strategy Phases
`strategy_phases` in the output JSON are generated by a simple segmentation:
1. Divide the 30 steps into windows of 5
2. For each window, compute the dominant action type
3. Merge adjacent windows with the same dominant action
4. Label each phase by its dominant behavior (e.g., `"exploration"` if ≥ 3 distinct actions, `"clicking"` if ACTION6 dominant, `"movement"` if ACTION1-4 dominant)

This is approximate — useful for quick visual scan, not rigorous analysis.

---

## Railway Postgres Integration

### New Table: `arc3_survey_results`

No existing Postgres write code exists in this repo. The survey runner creates this table on first run.

```sql
CREATE TABLE IF NOT EXISTS arc3_survey_results (
    id              SERIAL PRIMARY KEY,
    survey_run_id   TEXT NOT NULL,           -- UUID for this survey execution
    game_id         TEXT NOT NULL,           -- e.g. 'cn04-65d47d14'
    game_prefix     TEXT NOT NULL,           -- e.g. 'cn04'
    model           TEXT NOT NULL,           -- 'claude-sonnet-4-6'
    steps_taken     INTEGER NOT NULL,
    levels_completed INTEGER NOT NULL DEFAULT 0,
    result          TEXT NOT NULL,           -- WIN/LOSE/NOT_FINISHED/TIMEOUT/FAILED/LOAD_FAILED
    estimated_cost_usd REAL,                -- Estimated, not real billing (OAuth)
    duration_seconds REAL,
    action_distribution JSONB,              -- {"ACTION1": 3, "ACTION5": 8, "ACTION6": 19}
    instinct_class  TEXT,                   -- Primary classification
    instinct_secondary TEXT,                -- Secondary if tiebreaker needed
    hypothesis_count INTEGER DEFAULT 0,
    change_awareness_ratio REAL,            -- Steps referencing changes / total steps
    strategy_phases JSONB,                  -- [{"steps": "0-4", "label": "exploration"}, ...]
    first_impression TEXT,                  -- First LLM reasoning output (truncated to 500 chars)
    session_id_local TEXT,                  -- FK to local SQLite session
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arc3_survey_game ON arc3_survey_results(game_prefix);
CREATE INDEX IF NOT EXISTS idx_arc3_survey_run ON arc3_survey_results(survey_run_id);
```

### Postgres Write Path
```python
import psycopg2, os, json

def write_survey_result(result: dict):
    conn = psycopg2.connect(os.environ['DATABASE_PUBLIC_URL'])
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO arc3_survey_results
        (survey_run_id, game_id, game_prefix, model, steps_taken, levels_completed,
         result, estimated_cost_usd, duration_seconds, action_distribution,
         instinct_class, instinct_secondary, hypothesis_count,
         change_awareness_ratio, strategy_phases, first_impression, session_id_local)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        result['survey_run_id'], result['game_id'], result['game_prefix'],
        result['model'], result['steps_taken'], result['levels_completed'],
        result['result'], result.get('estimated_cost_usd'),
        result.get('duration_seconds'),
        json.dumps(result.get('action_distribution', {})),
        result.get('instinct_class'), result.get('instinct_secondary'),
        result.get('hypothesis_count', 0),
        result.get('change_awareness_ratio'),
        json.dumps(result.get('strategy_phases', [])),
        result.get('first_impression', '')[:500],
        result.get('session_id_local'),
    ))
    conn.commit()
    conn.close()
```

---

## Output

### Per-Game JSON
```json
{
  "game_id": "cn04-65d47d14",
  "game_prefix": "cn04",
  "model": "claude-sonnet-4-6",
  "steps_taken": 30,
  "levels_completed": 0,
  "result": "NOT_FINISHED",
  "estimated_cost_usd": 0.12,
  "action_distribution": {"ACTION1": 1, "ACTION5": 3, "ACTION6": 20, "ACTION2": 6},
  "first_impression": "Agent described grid as colored blocks on light blue background...",
  "strategy_phases": [
    {"steps": "0-4", "label": "exploration", "summary": "Tried varied actions"},
    {"steps": "5-29", "label": "clicking", "summary": "Focused on ACTION6 on colored regions"}
  ],
  "change_awareness_ratio": 0.27,
  "hypothesis_count": 2,
  "instinct_class": "random_clicker",
  "instinct_secondary": null,
  "session_id_local": "abc123..."
}
```

### Deliverables
1. **`docs/reports/instinct-survey.json`** — full per-game data array + metadata header (game list, model, date)
2. **`docs/reports/instinct-survey.md`** — human-readable summary
3. **Railway Postgres `arc3_survey_results`** — same data, queryable
4. Committed and pushed to this repo

### Summary Report Structure
- Survey metadata (date, model, game count, total time, total estimated cost)
- Games ranked by levels_completed (best first)
- Instinct distribution breakdown (pie chart data)
- Top 5 most promising games (signs of understanding, highest change_awareness)
- Bottom 5 (completely lost)
- Common failure patterns across all games

---

## Implementation

### Preferred: Wrap `batch_runner.py`

`batch_runner.py` already handles the game loop, model calls, and SQLite writes. The survey adds:
1. Sequential execution (`--workers 1`)
2. Per-game timeout via `threading.Timer`
3. Resume logic (skip completed games)
4. Post-run: read SQLite sessions, classify instincts, write to Postgres + JSON + Markdown

### New Files
```
survey/
├── run_survey.py          — Orchestrator: sequential game loop, timeout, resume, progress
└── report_generator.py    — Read SQLite → classify → write Postgres + JSON + Markdown
```

`run_survey.py` calls into `batch_runner.py` or `agent.py` internals directly (import `play_game`, `load_config`, etc.). Does NOT shell out.

`report_generator.py` reads from local SQLite only. Writes to:
- `docs/reports/instinct-survey.json`
- `docs/reports/instinct-survey.md`
- Railway Postgres `arc3_survey_results` table

---

## Estimated Cost & Time

- ~46 games × 30 steps × ~$0.004/step ≈ $5.50 estimated (OAuth, not real billing)
- ~46 games × 30 steps × ~10s/step ≈ 230 minutes (~4 hours)
- Report generation: ~5 minutes
- **Total: ~4 hours**

---

## What This Gives Us

1. **For prompt work:** Where words fail the agent. Which instincts help, which hurt. Where better framing could help it hatch.
2. **For evolution:** Which games to target first. Which baseline behaviors to evolve from. Can't evolve an organism that can't survive.
3. **For everyone:** Shared artifact in repo + Railway DB documenting baseline agent behavior.

---

## Not In Scope

- Reading game source code (agent must discover mechanics)
- Evolution worker (needs viable baseline first)
- Hand-tuning prompts per game (evolution's job)
- Dashboard UI changes (build after we have data)
