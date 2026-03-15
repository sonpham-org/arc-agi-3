# Arena Auto Research — Plan Doc

**Date:** 2026-03-15
**Author:** Claude Opus 4.6
**Status:** APPROVED

---

## Goal

Add an **Auto Research** tab to the ARC Arena where:
1. Users can run **Local Auto Research** per-game using their own resources (BYOK + local compute)
2. A **Community Auto Research** mode lets everyone contribute agents to a shared genome pool with ELO-rated tournaments run on our server
3. Users can **play against AI agents** from the leaderboard with configurable time delays, tracked as `human-{delay}ms` in ELO

---

## Scope

### In Scope
- New "Auto Research" tab in Arena UI (alongside existing Match/Setup views)
- Per-game auto research (each game gets its own leaderboard, agent pool, program.md)
- Local Auto Research: config dialog → evolution workers → tournament → leaderboard (modeled on snake_autoresearch)
- Community Auto Research: shared genome pool, strategy discussion, program.md voting, server-side tournaments
- Human vs AI play with delay settings (250ms, 500ms, 1000ms, 2000ms, ∞)
- Human ELO entries as `human-{delay}ms` pseudo-agents
- Server: save comments, save ~10 games/pair, skip games when ELO gap too large (unless upset), efficient agent storage
- New DB tables for arena auto research
- New server API endpoints

### Out of Scope
- New game engines (we use existing Arena games)
- Full Python port of all 9 game engines (deferred — see Architecture section)
- Custom game creation tool

---

## Architecture

### Agent Format: JavaScript

Agents are **JS code strings** with a standard interface per game:

```javascript
// Snake/Tron agent
function getMove(state) {
    // state: { grid, mySnake, enemySnake, food, turn, memory }
    // memory: mutable object persisted across turns
    return 'UP'; // UP, DOWN, LEFT, RIGHT
}

// Board game agent (Connect4, Othello, Gomoku, Go)
function getMove(state) {
    // state: { board, myColor, validMoves, turn, memory }
    return { col: 3 }; // or { row: 5, col: 3 }
}

// Chess960 agent
function getMove(state) {
    // state: { board, myColor, validMoves, turn, castling, memory }
    return { from: 'e2', to: 'e4' };
}
```

**Why JS?**
- Game engines already exist in JS (arena.js, ~4200 lines)
- Human play must run in browser — agents must run client-side too
- Local auto research runs entirely in-browser (no server dependency)
- Agents can be `eval()`'d safely in a Web Worker sandbox

### Dual Execution: Client + Server

| Component | Local Auto Research | Community Auto Research |
|-----------|-------------------|----------------------|
| **Game engine** | JS in browser | Node.js subprocess on server |
| **LLM evolution** | Browser → BYOK provider | Server → managed API keys |
| **Tournament** | Web Worker in browser | Python orchestrator + Node.js game runner |
| **Agent storage** | localStorage / IndexedDB | SQLite on Railway volume |
| **Leaderboard** | Local (in-memory) | Server DB, shared by all users |

### Server-Side Game Runner

A small Node.js script (`arena_game_runner.js`) that:
1. Receives: game_id, agent1_code, agent2_code, config (seed, maxTurns)
2. Loads the game engine (extracted from arena.js into reusable modules)
3. Runs the match (both agents in isolated `vm` contexts with timeout)
4. Returns: `{ winner, scores, turns, history }`

Called from Python via `subprocess.run(['node', 'arena_game_runner.js'], input=json_payload)`.

**Alternative considered**: Porting game engines to Python. Rejected because:
- 9 game engines × ~200 lines each = significant effort
- Must be kept in sync with JS versions
- Node.js is already commonly available on servers

### Data Flow

```
Local Auto Research:
  Browser ──LLM call──→ Provider (BYOK)
  Browser ──game run──→ Web Worker (JS engine)
  Browser ──submit agent──→ Server (community pool)

Community Auto Research:
  Server ──LLM call──→ Claude OAuth (4 cores, no API cost)
  Server ──game run──→ Node.js subprocess (10 cores)
  Server ──ELO update──→ SQLite
  Browser ←──poll──→ Server (leaderboard, games, discussion)
```

---

## Database Schema (new tables)

```sql
-- Per-game auto research context
CREATE TABLE arena_research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,          -- 'snake', 'tron', 'connect4', etc.
    program_md TEXT DEFAULT '',     -- current steering doc
    program_version INTEGER DEFAULT 0,
    generation INTEGER DEFAULT 0,
    status TEXT DEFAULT 'stopped',  -- running, stopped, error
    created_at REAL DEFAULT (unixepoch('now')),
    updated_at REAL DEFAULT (unixepoch('now'))
);
CREATE UNIQUE INDEX idx_ar_game ON arena_research(game_id);

-- Agents (shared genome pool per game)
CREATE TABLE arena_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    name TEXT NOT NULL,
    code TEXT NOT NULL,             -- JS source code
    generation INTEGER DEFAULT 0,
    elo REAL DEFAULT 1000.0,
    games_played INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    draws INTEGER DEFAULT 0,
    contributor TEXT,               -- user_id or 'server' or 'human-250ms'
    is_human INTEGER DEFAULT 0,     -- 1 for human-delay pseudo-agents
    active INTEGER DEFAULT 1,
    created_at REAL DEFAULT (unixepoch('now')),
    UNIQUE(game_id, name)
);
CREATE INDEX idx_aa_game_elo ON arena_agents(game_id, elo DESC);

-- Games (matches between agents)
CREATE TABLE arena_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    agent1_id INTEGER REFERENCES arena_agents(id),
    agent2_id INTEGER REFERENCES arena_agents(id),
    winner_id INTEGER REFERENCES arena_agents(id),
    agent1_score INTEGER DEFAULT 0,
    agent2_score INTEGER DEFAULT 0,
    turns INTEGER DEFAULT 0,
    history TEXT DEFAULT '[]',      -- JSON turn-by-turn replay (only stored for ~10/pair)
    is_upset INTEGER DEFAULT 0,     -- 1 if lower-ELO agent won by large margin
    created_at REAL DEFAULT (unixepoch('now'))
);
CREATE INDEX idx_ag_game ON arena_games(game_id);
CREATE INDEX idx_ag_agents ON arena_games(agent1_id, agent2_id);

-- Evolution cycles (LLM conversations that produced agents)
CREATE TABLE arena_evolution_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    generation INTEGER,
    worker_label TEXT,              -- 'server-0', 'user-abc123', etc.
    agents_created INTEGER DEFAULT 0,
    agents_passed INTEGER DEFAULT 0,
    conversation TEXT DEFAULT '[]', -- JSON log of LLM tool calls
    started_at REAL,
    finished_at REAL
);

-- Community discussion (strategy comments + votes)
CREATE TABLE arena_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    user_id TEXT,                   -- authenticated user or anonymous hash
    username TEXT DEFAULT 'Anon',
    content TEXT NOT NULL,          -- markdown
    comment_type TEXT DEFAULT 'strategy', -- 'strategy', 'program_vote', 'general'
    parent_id INTEGER REFERENCES arena_comments(id),  -- for threading
    upvotes INTEGER DEFAULT 0,
    downvotes INTEGER DEFAULT 0,
    created_at REAL DEFAULT (unixepoch('now'))
);
CREATE INDEX idx_ac_game ON arena_comments(game_id, created_at DESC);

-- Program.md version history (for voting)
CREATE TABLE arena_program_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    author TEXT,                    -- 'double_agent', 'community_vote', user_id
    change_summary TEXT,
    votes_for INTEGER DEFAULT 0,
    votes_against INTEGER DEFAULT 0,
    created_at REAL DEFAULT (unixepoch('now'))
);

-- Vote tracking (prevent double-voting)
CREATE TABLE arena_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    version_id INTEGER REFERENCES arena_program_versions(id),
    user_id TEXT NOT NULL,
    vote INTEGER NOT NULL,          -- +1 or -1
    created_at REAL DEFAULT (unixepoch('now')),
    UNIQUE(version_id, user_id)
);

-- Human play sessions (for ELO tracking)
CREATE TABLE arena_human_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    human_agent_id INTEGER REFERENCES arena_agents(id), -- the human-Xms pseudo-agent
    opponent_id INTEGER REFERENCES arena_agents(id),
    delay_ms INTEGER NOT NULL,      -- 250, 500, 1000, 2000, 0 (infinite)
    winner TEXT,                    -- 'human', 'ai', 'draw'
    turns INTEGER DEFAULT 0,
    created_at REAL DEFAULT (unixepoch('now'))
);
```

### Game Storage Rules

1. **~10 games per agent pair**: `MAX_STORED_GAMES_PER_PAIR = 10`. After 10, new games for that pair store scores/ELO but empty history `[]`.
2. **Skip games when ELO gap too large**: If `abs(elo1 - elo2) > 400`, don't run the match. Exception: run anyway if we detect an upset potential (agent with < 20 games played).
3. **Upset detection**: If lower-ELO agent wins when `abs(elo_gap) > 200`, mark `is_upset = 1` and always store full history.
4. **Agent code storage**: Agents stored in DB `code` column (TEXT). No filesystem storage needed — keeps it portable and Railway-volume-friendly.

### Sustainability Limits

#### Active Agent Cap — 200 per game

| Rule | Detail |
|------|--------|
| Hard cap | 200 active agents per game |
| Overflow pruning | When cap is hit, **randomly deactivate agents with ELO < 1000** until under cap. Random selection prevents gaming the system by sitting just above the cut line. |
| Probation | New agents play 20 "placement matches" with higher K-factor (K=64 vs K=32) to converge ELO quickly |
| Hall of Fame | Top 10 all-time peak ELO preserved permanently (code + stats, not in active tournament) |

With 200 agents max, pairs = ~20K. At 10 games/pair, max ~200K game records per game. Manageable.

#### Game History TTL — 48 hours

- Full replay history (JSON) kept for **48 hours** only
- After 48h, history column set to `'[]'` (scores, ELO, winner preserved)
- Exception: **upsets always keep history** (capped at 500 upset records per game)
- Caps history storage at ~50-100MB per game

#### Game Record TTL — 90 days

- Game records older than 90 days deleted entirely (ELO already baked into agent stats)

#### Evolution Rate Limits

| Source | Limit |
|--------|-------|
| Server evolution (OAuth) | 4 workers, 1 agent per 3-min cycle ≈ 80/day |
| Community user submission | 10 agents/user/day |
| Global daily cap | 500 new agents/day per game. After cap, new agents must beat median ELO in a test match to be admitted |

#### Minimum ELO Gate (Anti-Flood)

Once a game has **100+ active agents**, new submissions must win a test match against the current **median-ELO agent** before being admitted to the pool.

#### Matchmaking Optimization

At N > 100 agents, **disable UCB and round-robin** (both O(N²)). Use only Swiss (90%) + Random (10%).

#### ELO Anchoring

ELO drifts over time as agents churn. Weekly **anchoring job**:
1. Select the 3 longest-lived seed/baseline agents as anchors (fixed at ELO 1000)
2. Re-run Glicko-2 rating from the last 30 days of game results, anchored to those baselines
3. Update all active agent ELOs to the re-anchored values
4. Log the drift magnitude for monitoring

This prevents the scenario where a pool of mediocre agents all inflate each other to 1500+ because the truly strong agents were pruned.

#### Storage Budget Per Game

| Component | Target | Cap |
|-----------|--------|-----|
| Agent code | 200 × 3KB = 600KB | ~1MB |
| Game records (scores only) | 200K × 100B = 20MB | 50MB |
| Game histories (live 48h) | ~50MB | 100MB |
| Upset archive | 500 × 20KB = 10MB | 20MB |
| Evolution conversations (30-day) | ~50MB | 100MB |
| Comments | Tiny | 10MB |
| **Total per game** | **~130MB** | **280MB** |
| **Total 9 games** | **~1.2GB** | **2.5GB** |

#### Cleanup Cron (daily)

1. Strip history from game records older than 48h
2. Delete game records older than 90 days
3. If active agents > 200: randomly deactivate agents with ELO < 1000
4. Delete evolution conversation logs older than 30 days
5. Run weekly ELO anchoring (on Sundays)
6. `VACUUM` the database

### LLM Provider for Server-Side Evolution

Server-side evolution uses **Claude OAuth** (same scheme as snake_autoresearch) — no API key cost. Users contributing from browser use their own BYOK keys.

---

## UI Design

### Tab Structure

The Arena page gets a **top-level mode switcher** (not traditional tabs — matches existing Arena pattern):

```
[ Match Mode ]  [ Auto Research ]
```

When "Auto Research" is selected, the 3-column layout transforms:

### Auto Research Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [ Match Mode ]  [ Auto Research ]                                      │
├───────────────┬──────────────────────────────────────┬──────────────────┤
│               │                                      │                  │
│  GAME LIST    │   RESEARCH VIEW                      │  LIVE GAMES     │
│  (left col)   │   (center, large)                    │  (right col)    │
│               │                                      │                  │
│  ┌──────────┐ │   ┌────────────────────────────────┐ │  ┌────────────┐ │
│  │Category  │ │   │ program.md viewer/editor        │ │  │ 2x2 game  │ │
│  │  Game 1  │ │   │ (rendered / raw / edit modes)   │ │  │ canvases   │ │
│  │   [C][L] │ │   │                                 │ │  │            │ │
│  │  Game 2  │ │   │ Strategy chat panel              │ │  │ Live       │ │
│  │   [C][L] │ │   └────────────────────────────────┘ │  │ tournament │ │
│  │          │ │   ┌────────────────────────────────┐ │  │ matches    │ │
│  │Category  │ │   │ Observatory / Evolution log     │ │  │            │ │
│  │  Game 3  │ │   │ (LLM tool calls, worker logs)  │ │  │            │ │
│  │   [C][L] │ │   └────────────────────────────────┘ │  └────────────┘ │
│  │  Game 4  │ │                                      │  ┌────────────┐ │
│  │   [C][L] │ │   ┌─────────┬──────────────────────┐ │  │ Leaderboard│ │
│  └──────────┘ │   │ Leader- │  Discussion /        │ │  │ table      │ │
│               │   │ board   │  Strategy comments   │ │  │            │ │
│               │   │ (ELO)   │  + Vote on program   │ │  │ [Play ▶]  │ │
│               │   │         │  + Model/Key config   │ │  │ buttons   │ │
│               │   └─────────┴──────────────────────┘ │  └────────────┘ │
├───────────────┴──────────────────────────────────────┴──────────────────┤
│ Status: Gen 42 | 156 agents | 8,420 games | Best: flood_master (1847) │
└─────────────────────────────────────────────────────────────────────────┘
```

**[C] = Community Auto Research** button
**[L] = Local Auto Research** button

### Game List (Left Column)

- Same game categories as current Arena (ARC-style, Board Games, Action, etc.)
- Each game shows:
  - Game name + small preview
  - Two action buttons:
    - **Community** — opens shared community research view
    - **Local** — opens local research config dialog, then local research view
  - Indicator: agents count, top ELO

### Local Auto Research Config Dialog

Modeled on snake_autoresearch's "New Run" dialog:

```
┌─ Local Auto Research: Snake Battle ──────────┐
│                                               │
│  Evolving Model                               │
│  [Gemini 2.5 Flash ▼]                        │
│  API Key: [••••••••••]  (in-memory only)      │
│                                               │
│  Workers: [3 ▼]   Max Tokens: [16k ▼]        │
│                                               │
│  Matchmaking                                  │
│  Swiss: [90] UCB: [10] RR: [0] Random: [0]   │
│                                               │
│  [Cancel]  [Start Local Research]             │
└───────────────────────────────────────────────┘
```

### Community Research View (Center)

When viewing Community Auto Research for a game:
- **Top half**: program.md viewer (rendered markdown) with version selector
- **Middle**: Leaderboard table (Rank | Agent | ELO | W/L | Gen | Contributor | Actions)
  - Click agent name → view code modal
  - **[Play Against ▶]** button next to each agent
- **Bottom half**: Discussion panel
  - Strategy comments (threaded, upvote/downvote)
  - "Suggest Program Change" → opens editor, submits for 10-second community vote
  - Model + API key selector for contributing evolution cycles from browser

### Human vs AI Play

When clicking **[Play Against ▶]** on a leaderboard agent:

```
┌─ Play Against: flood_master (ELO 1847) ──────┐
│                                                │
│  Your Time Per Move:                           │
│  ○ Fast (250ms)     — reflex mode              │
│  ○ Normal (500ms)   — competitive              │
│  ● Relaxed (1000ms) — strategic                │
│  ○ Slow (2000ms)    — careful analysis          │
│  ○ Infinite         — unlimited thinking time   │
│                                                │
│  You will appear on the leaderboard as:        │
│  human-1000ms                                  │
│                                                │
│  [Cancel]  [Start Game]                        │
└────────────────────────────────────────────────┘
```

- Game runs in browser: human uses keyboard/mouse, AI agent code eval'd in Web Worker
- After game ends, result submitted to server for ELO update
- `human-{delay}ms` gets its own ELO entry in the leaderboard
- Multiple humans with same delay share the same `human-{delay}ms` pseudo-agent

---

## Server API Endpoints

### Research Management
- `GET /api/arena/research/<game_id>` — Get research state (generation, status, program.md, stats)
- `POST /api/arena/research/<game_id>/start` — Start server-side community tournament
- `POST /api/arena/research/<game_id>/stop` — Stop server-side tournament

### Agents
- `GET /api/arena/agents/<game_id>` — Get leaderboard (all active agents, sorted by ELO)
- `GET /api/arena/agents/<game_id>/<agent_id>` — Get agent details + code
- `POST /api/arena/agents/<game_id>` — Submit agent (from local research or community evolution)
  - Body: `{ name, code, contributor }`
  - Server validates (syntax check, safety check, test match vs baseline)
- `DELETE /api/arena/agents/<game_id>/<agent_id>` — Deactivate agent (admin only)

### Games
- `GET /api/arena/games/<game_id>?limit=50` — Recent games
- `GET /api/arena/games/<game_id>/<match_id>` — Single game + replay history
- `POST /api/arena/games/<game_id>` — Submit game result (from local research or human play)
  - Body: `{ agent1_id, agent2_id, winner_id, scores, turns, history? }`
  - Server verifies and updates ELO

### Discussion
- `GET /api/arena/comments/<game_id>` — Get strategy comments
- `POST /api/arena/comments/<game_id>` — Post a comment
- `POST /api/arena/comments/<game_id>/<comment_id>/vote` — Upvote/downvote

### Program.md
- `GET /api/arena/program/<game_id>` — Get current program + version history
- `POST /api/arena/program/<game_id>/propose` — Propose a change (starts 10s vote)
- `POST /api/arena/program/<game_id>/vote` — Vote on proposed change (+1/-1)

### Human Play
- `POST /api/arena/human-play/<game_id>` — Submit human play result
  - Body: `{ opponent_agent_id, delay_ms, winner, turns }`
  - Server creates/updates `human-{delay}ms` pseudo-agent ELO

---

## Implementation Phases

### Phase 1: Database + Server APIs + UI Shell
**Files touched:** `db.py`, `server/app.py`, `server/services/arena_research_service.py` (new), `templates/arena.html`, `static/js/arena.js`, `static/css/arena.css`

1. Add new DB tables (arena_research, arena_agents, arena_games, arena_comments, arena_program_versions, arena_votes, arena_human_sessions)
2. Create `server/services/arena_research_service.py` — all business logic
3. Add API routes to `app.py`
4. Add "Auto Research" mode toggle to Arena UI
5. Build game list with [C] and [L] buttons per game
6. Build leaderboard component

**Verify:** API endpoints return correct data, UI mode toggle works

### Phase 2: Local Auto Research (In-Browser)
**Files:** `static/js/arena-autoresearch.js` (new), `static/js/arena-evolution.js` (new)

1. Config dialog (model, API key, workers, matchmaking)
2. In-browser evolution worker:
   - Reads leaderboard + top agent code
   - Calls LLM (BYOK) with tool-calling interface
   - Tools: query_leaderboard, read_agent, create_agent, test_match
   - Agent validation (syntax check via `new Function()`, timeout test)
3. In-browser tournament:
   - Web Worker runs game matches
   - Swiss/UCB/round-robin matchmaking
   - Local ELO tracking
4. Auto Research dashboard view:
   - program.md viewer
   - Observatory (LLM conversation log)
   - Local leaderboard
   - 2x2 live game canvases
5. "Submit to Community" button — uploads best agents to server

**Verify:** Full local evolution cycle for Snake Battle, agents compete, leaderboard updates

### Phase 3: Community Auto Research (Server-Side)
**Files:** `server/arena_tournament.py` (new), `server/arena_evolution.py` (new), `arena_game_runner.js` (new)

1. Node.js game runner (`arena_game_runner.js`):
   - Extracts game engines from arena.js into reusable modules
   - Runs matches in isolated `vm` contexts with timeout
   - Called from Python via subprocess
2. Server-side tournament thread:
   - 10 parallel game workers (Node.js subprocesses)
   - Swiss matchmaking with ELO-gap filtering
   - ~10 games stored per pair, upset detection
3. Server-side evolution workers:
   - 4 LLM workers generating agents
   - Tool-calling loop (same tools as local, but server-side)
   - Uses Claude OAuth (no API cost)
4. Community discussion UI:
   - Strategy comment thread with upvote/downvote
   - Program.md proposal + 10-second voting mechanism
   - Model + API key input for user-contributed evolution cycles

**Verify:** Server tournament runs, community agents compete, discussion works

### Phase 4: Human vs AI Play
**Files:** `static/js/arena-human-play.js` (new), arena.html additions

1. "Play Against" button on leaderboard agents
2. Delay selector dialog
3. Human play mode:
   - Game engine runs in browser
   - AI agent code eval'd in Web Worker with `setTimeout` for delay enforcement
   - Human input via keyboard (d-pad games) or mouse (click games / board games)
   - Timer display showing remaining time per move
4. Result submission to server
5. `human-{delay}ms` pseudo-agent in leaderboard

**Verify:** Human can play against snake agent, result updates ELO, leaderboard shows human entries

---

## Modules Touched / Created

### New Files
| File | Purpose |
|------|---------|
| `server/services/arena_research_service.py` | Business logic for all auto research features |
| `server/arena_tournament.py` | Server-side tournament runner |
| `server/arena_evolution.py` | Server-side LLM evolution workers |
| `arena_game_runner.js` | Node.js game execution subprocess |
| `static/js/arena-autoresearch.js` | Client-side auto research UI + local evolution |
| `static/js/arena-evolution.js` | In-browser LLM evolution worker |
| `static/js/arena-human-play.js` | Human vs AI play mode |

### Modified Files
| File | Changes |
|------|---------|
| `db.py` | New tables, migrations |
| `server/app.py` | ~15 new API routes |
| `templates/arena.html` | Auto Research mode UI, human play UI |
| `static/js/arena.js` | Mode toggle, game list refactor, agent interface extraction |
| `static/css/arena.css` | Auto research layout styles |
| `CHANGELOG.md` | New entry |

---

## Docs / Changelog

- `CHANGELOG.md`: New `[1.3.6]` entry for Arena Auto Research
- This plan doc: `docs/15-Mar-2026-arena-autoresearch-plan.md`
- No new README changes needed (internal feature)

---

## Open Questions

1. **Node.js on Railway**: Is Node.js available in the Railway deployment? If not, we'll need to add it to the Dockerfile or port game engines to Python.
2. **Agent safety**: JS `eval()` is dangerous. Web Workers provide some isolation, but server-side needs `vm2` or similar sandbox. Should we add a safety whitelist (no `fetch`, `import`, `require`)?
3. **Seed agents**: Each game needs 2-3 baseline agents to bootstrap the leaderboard + serve as ELO anchors. Should these be handwritten or generated?
4. **Program.md voting window**: You said "10 seconds" — is that literally 10 seconds, or a different interval? That's very fast for async community.
