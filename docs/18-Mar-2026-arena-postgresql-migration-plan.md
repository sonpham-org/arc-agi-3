# Arena PostgreSQL Migration

**Date**: 2026-03-18
**Author**: Claude Opus 4.6
**Status**: DRAFT — awaiting approval

## Problem

The arena leaderboard query takes **8.5 seconds** on prod. Root cause: SQLite single-writer lock contention. The heartbeat tournament thread writes games constantly via `BEGIN IMMEDIATE`, blocking all web reads with `busy_timeout = 30000ms`. This makes the entire arena page feel slow.

## Approach: Arena-Only PostgreSQL

Migrate **only the arena tables** to PostgreSQL. Keep everything else (sessions, auth, LLM calls, game-playing) on SQLite — they don't have the contention problem.

This is the lowest-risk approach:
- Only `db_arena.py` changes (46 functions, 1 file)
- All other `db_*.py` files untouched
- No risk to Observatory/game-playing
- Arena gets full concurrent reads + writes

### Why not migrate everything?

- Session/Observatory tables work fine on SQLite (no background writers)
- Per-session SQLite exports (`db_exports.py`) are a key feature for sharing/replay
- Full migration touches 9 files + 82 functions — high risk for low gain
- Can always do Phase 2 later if needed

## Architecture

```
Before:
  SQLite (sessions.db)
  ├── sessions, session_actions, llm_calls, ...  (web + CLI)
  └── arena_agents, arena_games, arena_research, ...  (web + heartbeat)
       ^ CONTENTION: heartbeat writes block web reads

After:
  SQLite (sessions.db)
  ├── sessions, session_actions, llm_calls, ...  (unchanged)
  └── (arena tables removed)

  PostgreSQL (Railway)
  └── arena_agents, arena_games, arena_research, ...  (no contention)
```

### Connection Layer

```python
# db_arena.py — new PostgreSQL connection pool
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

_pg_pool = None  # initialized on first use

def _pg():
    """PostgreSQL context manager for arena tables."""
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = ThreadedConnectionPool(1, 10, os.environ['DATABASE_URL'])
    conn = _pg_pool.getconn()
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except:
        conn.rollback()
        raise
    finally:
        _pg_pool.putconn(conn)
```

All `with _db() as conn:` in db_arena.py becomes `with _pg() as conn:`.

## SQL Syntax Changes

| SQLite | PostgreSQL | Occurrences |
|--------|-----------|------------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` | 11 tables |
| `unixepoch('now')` | `EXTRACT(EPOCH FROM NOW())` | 11 defaults |
| `?` parameter | `%s` parameter | ~120 queries |
| `PRAGMA table_info(...)` | `information_schema.columns` | 3 calls |
| `conn.execute(sql, (params,))` | `cur.execute(sql, (params,))` | All queries |
| `row["field"]` (sqlite3.Row) | `row["field"]` (RealDictCursor) | No change needed |
| `last_insert_rowid()` | `RETURNING id` | ~5 INSERT calls |

## Scope

### In Scope
- 11 arena tables migrated to PostgreSQL
- `db_arena.py` — all 46 functions updated
- `db.py` — remove arena CREATE TABLE / migration statements
- `server/arena_heartbeat.py` — imports from db_arena (no change needed, same API)
- `requirements.txt` — add `psycopg2-binary`
- Railway — provision PostgreSQL instance
- Data migration script (one-time)

### Out of Scope
- Session tables (stay on SQLite)
- Auth tables (stay on SQLite)
- LLM call tables (stay on SQLite)
- Per-session exports (`db_exports.py`)
- `obs_server.py`
- CLI agent/batch runner DB access

## Tables to Migrate (11)

| Table | Rows (est.) | Purpose |
|-------|-------------|---------|
| `arena_research` | 6 | Per-game research state |
| `arena_agents` | 273 | Agent code + ELO + stats |
| `arena_games` | 7,500 | Match results + histories |
| `arena_evolution_cycles` | ~200 | LLM conversation logs |
| `arena_comments` | ~100 | Community discussion |
| `arena_program_versions` | ~20 | Program.md history |
| `arena_votes` | ~10 | Program voting |
| `arena_human_sessions` | ~50 | Human vs AI matches |
| `arena_evolution_sessions` | ~200 | Evolution cycle stats |
| `arena_llm_calls` | ~500 | API call monitoring |
| `arena_library_requests` | ~20 | Import request logs |

Total: ~9,000 rows. Small dataset — migration will be fast.

## TODOs

### Phase 1: PostgreSQL Setup
- [ ] Add `psycopg2-binary` to requirements.txt
- [ ] Provision PostgreSQL on Railway (free tier)
- [ ] Add `DATABASE_URL` env var to Railway
- [ ] Create PostgreSQL schema (converted DDL)
- [ ] **Verify**: Can connect from Railway app to PG instance

### Phase 2: db_arena.py Migration
- [ ] Add `_pg()` connection pool context manager
- [ ] Convert all 46 functions: `_db()` → `_pg()`, `?` → `%s`, `RETURNING id`
- [ ] Replace `PRAGMA table_info` with `information_schema.columns` query
- [ ] Remove `_apv_has_evo_cols()` defensive check (PG schema is authoritative)
- [ ] **Verify**: All 46 functions work with PostgreSQL locally

### Phase 3: db.py Cleanup
- [ ] Remove arena CREATE TABLE statements from `_init_db()`
- [ ] Remove arena migration ALTER TABLE statements from `_migrate_schema()`
- [ ] Keep arena table removal code (drop from SQLite if they exist)
- [ ] **Verify**: `_init_db()` still works for session/auth tables

### Phase 4: Data Migration
- [ ] Write one-time migration script: SQLite → PostgreSQL
- [ ] Export arena tables from prod SQLite
- [ ] Import into PostgreSQL
- [ ] **Verify**: Row counts match, leaderboard correct

### Phase 5: Testing
- [ ] Local smoke test with PostgreSQL (Docker)
- [ ] Batch runner test (uses agent.py which uses db.py, not db_arena.py — should be unaffected)
- [ ] Import check: `from server.app import app; import db; import db_arena`
- [ ] API tests: `/api/arena/research/snake`, `/api/arena/agents/snake`
- [ ] **Verify**: Heartbeat tournament runs without errors

### Phase 6: Deploy
- [ ] Push to staging, test on staging-arena.sonpham.net
- [ ] Run data migration on prod
- [ ] Push to master
- [ ] **Verify**: Leaderboard loads in < 500ms (not 8.5s)

## Fallback Plan

If PostgreSQL causes issues:
1. `DATABASE_URL` env var is optional — if unset, `db_arena.py` falls back to SQLite
2. This means the migration is **opt-in per environment**
3. Local dev continues to use SQLite (no PG required)

```python
def _pg():
    if os.environ.get('DATABASE_URL'):
        # PostgreSQL path
    else:
        # Fallback to SQLite (_db())
        yield from _db()
```

## Expected Performance Impact

| Query | SQLite (current) | PostgreSQL (expected) |
|-------|-----------------|----------------------|
| Leaderboard (20 agents) | 8,500ms | < 50ms |
| Research stats | 11,000ms | < 100ms |
| Record game | 200ms (blocked by lock) | < 10ms |
| Comments | 2,500ms | < 50ms |
| Agent profile | 450ms | < 50ms |

## Docs / Changelog Touchpoints

- `CHANGELOG.md` — new entry for PostgreSQL migration
- `CLAUDE.md` — update Database section
- `.claude/database_structure.md` — note arena tables now on PostgreSQL
- This plan doc
