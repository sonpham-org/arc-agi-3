# Agent Profile Tabs — Plan

**Date**: 2026-03-18
**Goal**: Transform the agent profile view (shown when clicking an agent in the leaderboard) from a flat game-replay layout into a tabbed view with: Recent Games, Code, Program.md, and Evolution Log.

## Current State

- **Agent view** (`arRenderAgentView` in arena.js:5980) shows a header (name, ELO, W/L/D) and game replays partitioned by opponent ELO. Code/Program are shown in separate modals.
- **Evolution log**: `_run_evolution()` in `arena_heartbeat.py` generates a `conversation_log` via `run_tool_loop()` but **discards it** after logging stats. The `arena_evolution_cycles` table exists in the schema with a `conversation` TEXT column but is **never written to**.
- **Agent → cycle link**: No FK from `arena_agents` to `arena_evolution_cycles`.

## Scope

**In scope:**
- Store evolution conversation log in `arena_evolution_cycles` (already has the table)
- Add `evolution_cycle_id` FK on `arena_agents`
- New API endpoint: `GET /api/arena/agents/<game_id>/<agent_id>/profile` (returns all tab data in one call)
- Tabbed agent view UI with 4 tabs: Recent Games, Code, Program.md, Evolution Log
- Graceful handling when data is missing (e.g., seed agents have no evolution log)

**Out of scope:**
- Editing code/program from the profile view
- Evolution log for client-side (local) evolved agents

## Database Changes

### 1. Add column to `arena_agents`

```sql
ALTER TABLE arena_agents ADD COLUMN evolution_cycle_id INTEGER DEFAULT NULL;
```

This links each agent to the evolution cycle that created it.

### 2. Write to `arena_evolution_cycles` during evolution

The table already exists:
```sql
arena_evolution_cycles (
    id, game_id, generation, worker_label,
    agents_created, agents_passed,
    conversation TEXT DEFAULT '[]',  -- JSON conversation log
    started_at, finished_at
)
```

In `_run_evolution()`, after the tool loop completes:
1. Insert a row with the conversation log (capped at 100KB)
2. Pass the cycle ID back so `_tool_create_agent` can set `evolution_cycle_id` on the agent

### 3. No new tables needed

All data already exists somewhere:
- **Recent games**: `arena_games` (existing query)
- **Code**: `arena_agents.code` (existing)
- **Program.md**: `arena_agents.program_file` + `arena_program_versions` (existing)
- **Evolution log**: `arena_evolution_cycles.conversation` (unused, will populate)

## API Design

### `GET /api/arena/agents/<game_id>/<agent_id>/profile`

Returns all data needed for all 4 tabs in one call (cheap — single round-trip):

```json
{
  "agent": { "id", "name", "elo", "wins", "losses", "draws", "games_played", "generation", "contributor", "is_human", "created_at" },
  "code": "function getMove(state) { ... }",
  "program_file": "# Strategy\n...",
  "program_version": { "id", "version", "content", "change_summary" },
  "evolution_log": [
    {"type": "assistant", "content": "I'll analyze the leaderboard..."},
    {"type": "tool_call", "name": "create_agent", "args": {"name": "gen5_flood", "code": "..."}},
    {"type": "tool_result", "name": "create_agent", "result": "Agent created (ELO: 1000)"}
  ],
  "evolution_meta": { "generation", "model", "cost_usd", "started_at", "finished_at" },
  "games": [ ... same as current /games endpoint ... ]
}
```

**Why one endpoint**: Avoids 4 separate fetches. The data is small (evolution log capped at 100KB, code typically <10KB, program <5KB). Lazy-loading individual tabs would add latency for negligible savings.

## Frontend Changes

### Tabbed UI in `arRenderAgentView`

```
┌──────────────────────────────────────────┐
│ AgentName    ELO: 1245   W/L/D: 28/10/4 │
│ By: Claude Sonnet · Gen 5                │
│ [Play ▶]                                 │
├──────────────────────────────────────────┤
│ [Games] [Code] [Program] [Evolution Log] │
├──────────────────────────────────────────┤
│                                          │
│  (Tab content here)                      │
│                                          │
└──────────────────────────────────────────┘
```

- **Games tab**: Same as current view (replay canvases, vs Higher/Lower ELO sections)
- **Code tab**: Syntax-highlighted agent code (inline, not modal). Read-only.
- **Program tab**: Program.md content rendered as preformatted text. Shows "No program" if null.
- **Evolution Log tab**: Scrollable conversation view. Assistant text in white, tool calls in cyan, tool results in dim. Shows "No evolution log (seed agent)" if missing.

## TODOs

1. **DB migration**: Add `evolution_cycle_id` column to `arena_agents` (ALTER TABLE)
2. **Backend — save evolution log**: In `_run_evolution()`, insert into `arena_evolution_cycles` and pass cycle ID to agent creation
3. **Backend — new DB function**: `arena_get_agent_profile()` that joins agent + cycle + program version
4. **Backend — new API route**: `/api/arena/agents/<game_id>/<agent_id>/profile`
5. **Frontend — refactor `arRenderAgentView`**: Split into tabbed layout
6. **Frontend — tab renderers**: Games (existing), Code, Program, Evolution Log
7. **CSS**: Tab styling (reuse existing `.ar-btn` patterns)
8. **Verify**: Test with seed agents (no log), evolved agents (has log), and offline agents

## Docs / Changelog

- Update `.claude/database_structure.md` with new column and usage notes
- Add CHANGELOG entry for agent profile tabs feature
