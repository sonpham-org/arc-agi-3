# Plan: APP_MODE Split — Observatory & Arena as Separate Services

**Author:** Claude Opus 4.6 | 2026-03-16
**Status:** Phase 1 complete — Phase 2 (Railway setup) is manual

---

## Goal

Run Observatory and Arena as **two separate Railway services** from the same repo, each with its own custom domain and root `/` landing page. Eventually remove the `/obs` and `/arena` path prefixes entirely.

| Service | Domain | `APP_MODE` | `/` serves |
|---------|--------|-----------|------------|
| Observatory | `arc3.sonpham.net` | `observatory` | Observatory (currently `index.html` at `/obs`) |
| Arena | `arena.sonpham.net` | `arena` | Arena (currently `arena.html` at `/arena`) |

Both services share the **same SQLite database** on a shared Railway volume.

---

## Scope

### In scope
- New `APP_MODE` env var (`observatory` | `arena`) controlling which page `/` serves
- Root `/` route serves the mode's primary page directly (no redirect)
- Keep `/obs` and `/arena` as temporary aliases (302 → `/`) during transition so old bookmarks don't break
- Cross-links between Observatory ↔ Arena use full domain URLs instead of relative paths
- Arena heartbeat only starts when `APP_MODE=arena`
- Arena Monitor (`/arena/monitor` → `/monitor`) only accessible on arena service
- Shared DB via Railway volume mount (same `DB_DATA_DIR=/data`)

### Out of scope (future)
- Removing `/obs` and `/arena` aliases (do after transition period)
- Splitting API namespaces (`/api/arena/*` stays as-is on both services)
- Separate Procfiles or Dockerfiles (same Procfile, behavior differs by env var)
- Moving to separate repos

---

## Architecture

### Railway Setup

```
Railway Project: arc-agi-3
├── Service: observatory
│   ├── Source: same GitHub repo (master branch)
│   ├── Env: APP_MODE=observatory, SERVER_MODE=prod
│   ├── Domain: arc3.sonpham.net
│   └── Volume: /data (shared)
│
├── Service: arena
│   ├── Source: same GitHub repo (master branch)
│   ├── Env: APP_MODE=arena, SERVER_MODE=prod
│   ├── Domain: arena.sonpham.net
│   └── Volume: /data (shared)  ← SAME volume as observatory
│
└── Volume: sessions-data
    └── Mounted at /data on BOTH services
```

**Key constraint:** Railway allows mounting the same volume on multiple services in the same project. SQLite WAL mode supports concurrent readers + single writer. Current Procfile uses `--workers 1 --threads 8`, so each service has one writer — two total across both services, which WAL handles safely.

### Code Changes

**Single decision point:** `APP_MODE` env var read once at startup.

```python
# server/app.py (near top, after app creation)
APP_MODE = os.environ.get("APP_MODE", "observatory")  # default to observatory for backward compat
```

### Route Changes

| Current route | Observatory service | Arena service |
|---------------|-------------------|---------------|
| `/` | Serves `index.html` directly | Serves `arena.html` directly |
| `/obs` | 302 → `/` (temporary alias) | 302 → `https://arc3.sonpham.net/` |
| `/arena` | 302 → `https://arena.sonpham.net/` | 302 → `/` (temporary alias) |
| `/arena/monitor` | 302 → `https://arena.sonpham.net/monitor` | Serves `arena_monitor.html` at `/monitor` |
| `/api/arena/*` | Passes through (shared DB) | Passes through (shared DB) |
| `/api/*` (non-arena) | Passes through | Passes through |
| `/share/<id>` | Passes through | Passes through |

### Template Changes

**`templates/index.html`** — Observatory cross-links:
- `href="/arena"` → `href="https://arena.sonpham.net"` (2 places: lines 27, 35)

**`templates/arena.html`** — Arena cross-links:
- `href="/obs"` → `href="https://arc3.sonpham.net"` (2 places: lines 48, 53)

These should be template variables (`{{ observatory_url }}` / `{{ arena_url }}`) so they work in both staging and prod:
```python
CROSS_LINKS = {
    "observatory": os.environ.get("OBSERVATORY_URL", "/obs"),
    "arena": os.environ.get("ARENA_URL", "/arena"),
}
```

### Heartbeat Safety

The arena heartbeat background thread must **only run on the arena service**:

```python
# Only start heartbeat on the arena service
if APP_MODE == "arena":
    try:
        from server.arena_heartbeat import start_arena_heartbeat
        start_arena_heartbeat()
    except Exception as e:
        print(f"[arena] Heartbeat start failed (non-fatal): {e}")
```

This prevents duplicate evolution cycles, duplicate games, and ELO race conditions.

### Database

**No changes.** Both services read `DB_DATA_DIR` (defaults to `/data` on Railway) and open the same `sessions.db`. SQLite WAL mode handles concurrent access. All arena tables (`arena_agents`, `arena_games`, `arena_research`, etc.) and observatory tables (`sessions`, `session_actions`, `llm_calls`, etc.) live in the same DB file.

### Static Assets

**No changes.** Both services serve the full `/static/` directory. Arena pages load arena JS/CSS, observatory pages load observatory JS/CSS. No need to strip assets per mode — the unused files are just never requested.

---

## TODOs

### Phase 1: APP_MODE routing (code changes)

- [ ] **1.1** Add `APP_MODE` env var read at top of `server/app.py`
- [ ] **1.2** Add `OBSERVATORY_URL` and `ARENA_URL` env var reads with sensible defaults
- [ ] **1.3** Rewrite root `/` route to serve the correct template based on `APP_MODE`
- [ ] **1.4** Add temporary alias routes: `/obs` and `/arena` redirect appropriately based on `APP_MODE`
- [ ] **1.5** Move `/arena/monitor` → `/monitor` on arena service (keep `/arena/monitor` as alias)
- [ ] **1.6** Update `templates/index.html` cross-links to use `{{ arena_url }}` template var
- [ ] **1.7** Update `templates/arena.html` cross-links to use `{{ observatory_url }}` template var
- [ ] **1.8** Gate heartbeat start behind `APP_MODE == "arena"`
- [ ] **1.9** Remove the `before_request` subdomain routing hook added earlier (no longer needed)
- [ ] **Verify:** Local smoke test — run with `APP_MODE=observatory` and `APP_MODE=arena`, confirm `/` serves correct page, cross-links work, API calls work

### Phase 2: Railway deployment

- [ ] **2.1** Create second Railway service in the same project, pointing to same repo
- [ ] **2.2** Mount the existing volume on the new service at `/data`
- [ ] **2.3** Set env vars: `APP_MODE=arena`, `SERVER_MODE=prod`, `ARENA_URL=https://arena.sonpham.net`, `OBSERVATORY_URL=https://arc3.sonpham.net`
- [ ] **2.4** Set env vars on existing service: `APP_MODE=observatory`, `ARENA_URL=https://arena.sonpham.net`, `OBSERVATORY_URL=https://arc3.sonpham.net`
- [ ] **2.5** Add custom domain `arena.sonpham.net` to arena service in Railway
- [ ] **2.6** Add DNS CNAME record: `arena.sonpham.net` → Railway arena service domain
- [ ] **2.7** Deploy both services, verify TLS and routing
- [ ] **Verify:** Hit both domains, confirm correct landing pages, API calls, auth, shared data

### Phase 3: Cleanup (after transition period)

- [ ] **3.1** Remove `/obs` and `/arena` alias routes
- [ ] **3.2** Update any remaining hardcoded `/obs` or `/arena` references in JS
- [ ] **3.3** Update CLAUDE.md and docs to reflect new architecture
- [ ] **3.4** Update CHANGELOG.md

---

## Docs / Changelog Touchpoints

- `CHANGELOG.md` — New entry for APP_MODE split
- `CLAUDE.md` — Update "Environments" section to document APP_MODE
- This plan doc — Update status after each phase

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Two services writing to same SQLite | Potential write contention | WAL mode + single worker per service handles this; monitor for `SQLITE_BUSY` errors |
| Heartbeat running on both services | Duplicate agents, ELO races | Gate behind `APP_MODE == "arena"` |
| Railway shared volume latency | Stale reads across services | SQLite WAL provides read consistency; not an issue for this workload |
| Old bookmarks to `/obs` and `/arena` break | Users get 404 | Phase 1 adds temporary 302 redirects; remove in Phase 3 after sufficient time |
| OAuth callback URLs | Google OAuth redirect_uri mismatch | Both services use `/api/auth/google/callback` — add both domains to Google OAuth console authorized redirect URIs |
| Umami analytics | Separate page views per domain | Same website ID tracks both; verify in Umami dashboard that both domains report |
