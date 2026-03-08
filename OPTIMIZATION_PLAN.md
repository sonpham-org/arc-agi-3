# ARC-AGI-3 Optimization Plan

## Current State (March 2026)

- **Hosting**: Railway (~$10/mo), serves everything (static + API)
- **DB**: Local SQLite
- **Traffic target**: ~100 visitors/day by late March
- **Static assets**: ~2MB total (HTML/CSS/JS/game data)
- **Architecture**: All game logic + LLM calls run client-side; server is mostly static file serving + session CRUD + game step proxy

## Phase 1: Cloudflare Pages for Static Assets (DO FIRST)

Move static file serving off Railway to Cloudflare Pages (free, unlimited bandwidth).

**What moves to Cloudflare Pages:**
- `templates/index.html`, `templates/share.html`
- `static/css/`, `static/js/`
- `environment_files/` (game data)

**What stays on Railway (API only):**
- `/api/*` endpoints (session CRUD, game step proxy, auth, batch)
- `/share/<id>` server-side rendering (or convert to client-side fetch)

**Changes needed:**
- Frontend JS must call Railway API via absolute URL (e.g. `api.arc3.sonpham.net`) instead of relative paths
- Add CORS headers on Railway for the Cloudflare Pages origin
- Set up Cloudflare Pages deploy from GitHub (master branch)
- DNS: `arc3.sonpham.net` -> Cloudflare Pages, `api.arc3.sonpham.net` -> Railway

**Cost impact:** Railway bill drops significantly since it no longer serves static traffic.

## Phase 2: Quick Wins on Railway

Things to do regardless of hosting changes:

- [ ] Add `Cache-Control` headers for static assets (if any remain on Railway)
- [ ] Enable gzip/brotli compression for responses
- [ ] Default Pyodide to ON in prod (reduces `/api/step` calls to server)
- [ ] Compress session payloads (already using zlib in places, extend to all)
- [ ] Prune old sessions from SQLite after N months

## Phase 3: Google Cloud Run (IF Railway costs become a problem)

Replace Railway with Cloud Run for the API backend.

**Why:**
- Pay-per-request ($0 when idle, Railway charges 24/7)
- Free tier: 2M requests/mo, 360K vCPU-seconds/mo
- $300 Google credit available
- 100 visitors/day x ~50 API calls = ~150K requests/mo (well within free tier)

**What's needed:**
- Dockerfile for the Flask app
- `gcloud run deploy` setup
- GitHub Actions for CI/CD (replaces Railway's auto-deploy)
- Env vars migration (Resend, Turnstile keys)

**Cost projection:**
| Traffic | Cloud Run | Railway (current) |
|---------|-----------|-------------------|
| 100/day | $0 | ~$10-15/mo |
| 500/day | ~$2/mo | ~$20-30/mo |

**Downsides:**
- Worse DX than Railway (Dockerfile, gcloud CLI, IAM)
- Cold starts on scale-to-zero (mitigated with min instances = 1, but costs more)
- Lose Railway's nice deploy logs and rollback UI

**Decision:** Only do this if Railway costs exceed ~$20/mo. The $300 Google credit is a safety net.

## Phase 4: Edge Optimization (Future)

- Cloudflare Workers for lightweight API endpoints (session browse, share metadata)
- Edge caching for `/api/games` and game source responses (rarely change)
- WebSocket connection for observatory live updates instead of polling

## Architecture Diagram

```
Current:
  Browser --> Railway (static + API + game proxy + SQLite)

Phase 1:
  Browser --> Cloudflare Pages (static, FREE)
      |
      +-----> Railway (API only, reduced cost, SQLite)

Phase 3 (if needed):
  Browser --> Cloudflare Pages (static, FREE)
      |
      +-----> Cloud Run (API, FREE/$300 credit, SQLite)
```
