# Arena Repository Split Plan

**Date:** 2026-03-21
**Goal:** Extract AutoResearch Arena into a standalone repository (`autoresearch-arena`) that shares the same PostgreSQL database with ARC Observatory.

---

## Scope

### In Scope
- Create new repo `autoresearch-arena` with Arena-only Flask app
- Extract all Arena backend (heartbeat, engines, db_arena, tool runner, research service)
- Extract all Arena frontend (arena.html, arena_monitor.html, arena.css, arena.js, arena-autoresearch.js, code-arena.js)
- Copy shared frontend dependencies Arena needs (callLLM from scaffolding.js, auth.js, main.css)
- Copy minimal shared backend (Anthropic auth helpers)
- Deploy as separate Railway service, same `DATABASE_URL`
- Migrate domain (`arc3.sonpham.net` → Arena service)
- Remove Arena files from this repo after split is confirmed working

### Out of Scope
- Migrating Observatory's SQLite tables to PG (stays as-is)
- Shared package/library extraction (overkill for now — just copy)
- Auth unification (Arena will implement its own lightweight auth against PG)

---

## Architecture

### New Repo Structure

```
autoresearch-arena/
├── app.py                        # Flask app — Arena routes only
├── db_arena.py                   # PG database layer (drop SQLite fallback)
├── llm_auth.py                   # Extracted: _anthropic_auth_headers, _is_oauth_token
├── arena_heartbeat.py            # Tournament engine (from server/)
├── arena_tool_runner.py          # LLM tool-calling loop (from server/)
├── arena_research_service.py     # Business logic (from server/services/)
├── engines/
│   ├── snake_engine.py
│   ├── chess960_engine.py
│   └── othello_engine.py
├── arena_seeds/                  # Program.md templates (from server/)
├── templates/
│   ├── arena.html                # Entry point (updated asset paths)
│   └── arena_monitor.html        # Self-contained monitor page
├── static/
│   ├── css/
│   │   ├── main.css              # Copy of shared base styles
│   │   └── arena.css             # Arena-specific styles
│   └── js/
│       ├── arena.js              # Main Arena module
│       ├── arena-autoresearch.js # Auto-research + evolution
│       ├── code-arena.js         # Code challenges
│       ├── arena-llm.js          # Extracted callLLM() + provider routing from scaffolding.js
│       ├── arena-auth.js         # Extracted auth UI from auth.js
│       └── config/
│           └── scaffolding-schemas.js  # Game definitions (Arena uses these)
├── requirements.txt              # Trimmed: flask, httpx, psycopg2-binary, gunicorn, google-genai
├── Procfile                      # gunicorn app:app
└── CLAUDE.md                     # Arena-specific instructions
```

### What Each Piece Needs

| Arena File | Current Imports From Shared | Resolution |
|---|---|---|
| `arena_tool_runner.py` | `llm_providers_anthropic._anthropic_auth_headers`, `_is_oauth_token` | Extract into `llm_auth.py` (~30 lines) |
| `arena_heartbeat.py` | `db_arena` only | Direct — no changes needed |
| `arena_research_service.py` | `db_arena` only | Direct — no changes needed |
| `db_arena.py` | stdlib + psycopg2 | Drop SQLite fallback code, PG-only |
| Arena routes (in app.py) | `get_current_user()` → `db.verify_auth_token` (SQLite!) | New: verify against PG `users` table directly |
| `arena.html` | `main.css`, `scaffolding.js`, `scaffolding-schemas.js`, `auth.js` | Copy main.css. Extract `callLLM()` into `arena-llm.js`. Extract auth UI into `arena-auth.js`. |

### Auth Strategy

Current auth flow: `arc_auth` cookie → `verify_auth_token()` in `db.py` (SQLite).

For Arena standalone:
- Add `auth_tokens` and `users` tables to PG (Arena needs these)
- `db_arena.py` gets `arena_verify_auth_token()` and `arena_get_user()` against PG
- Same cookie name (`arc_auth`) so users logged into Observatory are logged into Arena (shared domain cookies won't work cross-domain, but the auth UI handles re-login)
- Google OAuth + magic link endpoints duplicated in Arena's app.py

**OR simpler:** Arena only needs auth for comment attribution and agent submission. We can make auth optional — anonymous submissions with optional login. This avoids duplicating the full auth stack.

### Domain Migration

- `arc3.sonpham.net` → Arena (Railway CNAME update on Hostgator)
- Observatory gets a new subdomain (e.g., `obs.sonpham.net` or `play.sonpham.net`)
- Or vice versa — user decides

---

## TODOs

### Phase 1: Create New Repo (local)

1. [ ] Create `autoresearch-arena/` directory at `~/Desktop/GitHub/autoresearch-arena`
2. [ ] `git init` + create initial structure
3. [ ] Copy Arena backend files, flatten `server/` nesting:
   - `db_arena.py` → `db_arena.py` (drop SQLite fallback)
   - `server/arena_heartbeat.py` → `arena_heartbeat.py` (update imports)
   - `server/arena_tool_runner.py` → `arena_tool_runner.py` (update imports)
   - `server/services/arena_research_service.py` → `arena_research_service.py`
   - `server/snake_engine.py` → `engines/snake_engine.py`
   - `server/chess960_engine.py` → `engines/chess960_engine.py`
   - `server/othello_engine.py` → `engines/othello_engine.py`
   - `server/arena_seeds/` → `arena_seeds/`
4. [ ] Create `llm_auth.py` — extract `_anthropic_auth_headers()` and `_is_oauth_token()` from `llm_providers_anthropic.py`
5. [ ] Create `app.py` — new Flask app with all 33 Arena routes extracted from `server/app.py`
6. [ ] Add auth helpers: `get_current_user()` backed by PG (or make auth optional for v1)
7. [ ] Copy Arena frontend files:
   - `templates/arena.html` → update script/CSS paths
   - `templates/arena_monitor.html` → as-is (self-contained)
   - `static/css/arena.css`
   - `static/css/main.css` (full copy for now)
   - `static/js/arena.js`
   - `static/js/arena-autoresearch.js`
   - `static/js/code-arena.js`
8. [ ] Extract `arena-llm.js` from `scaffolding.js` — just `callLLM()`, provider routing, BYOK key management
9. [ ] Extract `arena-auth.js` from `auth.js` — login modal, Google OAuth, magic link, user badge
10. [ ] Copy `config/scaffolding-schemas.js` (Arena references game definitions)
11. [ ] Create `requirements.txt` (trimmed)
12. [ ] Create `Procfile`

### Phase 2: Verify Locally

13. [ ] Run Arena Flask app locally, verify all routes respond
14. [ ] Test arena.html loads and renders games
15. [ ] Test arena_monitor.html loads
16. [ ] Test callLLM() works from Arena frontend
17. [ ] Test heartbeat starts and runs matches

### Phase 3: Deploy

18. [ ] Create GitHub repo `sonpham-org/autoresearch-arena`
19. [ ] Push code
20. [ ] Create Railway service, set `DATABASE_URL` to same PG instance
21. [ ] Set env vars: `ARENA_ADMIN_KEY`, `ARENA_CLAUDE_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`
22. [ ] Verify deployment works
23. [ ] Update DNS: domain → Arena Railway service

### Phase 4: Cleanup (after confirmed working)

24. [ ] Remove Arena files from `arc-agi-3` repo
25. [ ] Remove Arena routes from `server/app.py`
26. [ ] Remove Arena imports from `server/app.py`
27. [ ] Remove `db_arena.py` from Observatory repo
28. [ ] Remove `arena_exports/` from Observatory repo
29. [ ] Update `CLAUDE.md` in both repos

---

## Docs / Changelog

- `CHANGELOG.md` in `arc-agi-3`: entry for Arena extraction
- `CHANGELOG.md` in `autoresearch-arena`: initial entry
- `CLAUDE.md` in `autoresearch-arena`: Arena-specific instructions
- Memory update: new repo location, deployment info

---

## Decision Points for User

1. **Domain assignment:** Which gets `arc3.sonpham.net` — Arena or Observatory?
2. **Auth strategy:** Full auth duplication in Arena, or anonymous-first with optional login?
3. **main.css:** Full copy, or trim to only what Arena uses?
