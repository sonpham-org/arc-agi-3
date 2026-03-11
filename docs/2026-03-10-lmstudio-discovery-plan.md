# Plan: LM Studio Client-Side Discovery
**Date:** 2026-03-10
**Author:** Claude Sonnet 4.6
**Branch:** feature/lmstudio-support

---

## Scope

**In:**
- Move LM Studio model discovery entirely to the browser
- Remove the server-side `localhost:1234` probe from `server.py`
- Add file headers to every file touched in this feature branch
- Create `CHANGELOG.md` entry for all changes in this branch

**Out:**
- CLI agent (`agent.py` / `batch_runner.py`) — LM Studio via CLI is a separate concern, not addressed here
- Any changes to LLM call routing — only discovery is broken, `callLLM` already runs client-side correctly

---

## Problem

The original implementation calls `http://localhost:1234/v1/models` from the **server** (Railway) to discover LM Studio models. On Railway, that port is dead — it resolves to Railway's own localhost, not the user's machine. Discovery silently returns nothing.

The LLM calls (`callLLM` in `scaffolding.js`) already run browser → `localhost:1234` directly and work correctly. Discovery must follow the same pattern.

---

## Architecture

### Responsibilities after this change

| Concern | Where it lives | Why |
|---|---|---|
| LM Studio discovery | Browser (`loadModels()` in `scaffolding.js`) | Browser IS the user's machine |
| LM Studio LLM calls | Browser (`_callLLMInner` in `scaffolding.js`) | Already correct, no change |
| Capability overrides | `LMSTUDIO_CAPABILITIES` const in `scaffolding.js` + `models.py` | Unavoidable client/server split; must be kept in sync |
| Server discovery | `server.py` — **removed for port 1234 only** | Wrong layer for this provider |

### `LMSTUDIO_CAPABILITIES` duplication
This dict exists in both `models.py` (for CLI agent path) and `scaffolding.js` (for browser path). This is an intentional and necessary split given the client-side architecture documented in `CLAUDE.md`. A comment in both files must point to the other.

### Discovery flow (after fix)
1. `loadModels()` fetches `/api/llm/models` from server — gets all cloud providers + Ollama
2. `loadModels()` then fetches `{baseUrl}/v1/models` directly from the browser (1.5s timeout, silent fail)
3. Returned models are annotated with capabilities from `LMSTUDIO_CAPABILITIES`, filtered for embedding models, and merged into `modelsData`
4. If LM Studio is not running, the fetch fails silently — no error, no LM Studio group in dropdown

---

## Coding standards violations (must be remediated)

The following violations of `coding-standards.md` were made during the initial implementation and must be fixed as part of completing this plan:

1. **No plan doc created before coding** — commits were made directly without a plan. This plan is retroactive.
2. **No file headers** — `scaffolding.js`, `ui.js`, `server.py`, and `models.py` were all edited without the required Author/Date/PURPOSE/SRP-DRY header block.
3. **No CHANGELOG.md** — behavior changes were made and committed with no changelog entry. `CHANGELOG.md` does not exist in the repo yet.
4. **Docs written incorrectly** — `docs/lmstudio-integration.md` pitfall #2 originally stated to add `lmstudio` to `byokProviderOrder` (for models needing API keys). The correct fix was `providerOrder` (free/available group). The doc has since been corrected.
5. **Implementation before approval** — browser-side discovery code was partially drafted in `scaffolding.js` before this plan was written. That change is currently unstaged and must not be committed until this plan is approved.

---

## TODOs (ordered)

- [ ] **1. Get plan approved**
- [ ] **2. Add file headers** to all files touched in this branch: `scaffolding.js`, `ui.js`, `server.py`, `models.py`
- [ ] **3. Remove server-side LM Studio discovery** from `server.py` — delete the `port == 1234` branch from the `LOCAL_PORTS` loop (keep port 8080/8000 for other local servers)
- [ ] **4. Add browser-side discovery** to `loadModels()` in `scaffolding.js` — fetch `{baseUrl}/v1/models` with 1.5s timeout, merge results (uncommitted edit already drafted, needs header + review)
- [ ] **5. Add `LMSTUDIO_CAPABILITIES` const** to `scaffolding.js` — mirrors `models.py`, comment must reference the other file
- [ ] **6. Update `docs/lmstudio-integration.md`** — replace server-side discovery description with client-side architecture; remove outdated pitfall #3 reference to `models.py` static entries (those are gone)
- [ ] **7. Create `CHANGELOG.md`** — document all changes in this branch under a new version entry
- [ ] **8. Commit and push** (after user approval and testing)

---

## Verification steps

1. Server running on Railway (or staging) with no LM Studio on its host → LM Studio group does not appear in dropdown
2. User's browser has LM Studio running on `localhost:1234` → models appear in dropdown under "LM Studio (free, local)"
3. User has custom base URL set (e.g. Cloudflare Tunnel) → discovery uses that URL, models still appear
4. LM Studio is running but has no models loaded → LM Studio group does not appear (empty)
5. Known capability models (`qwen3.5-35b-a3b`, `glm-4.7-flash`) show correct RSN/IMG tags
6. `text-embedding-*` models are not shown in dropdown

---

## Docs / Changelog touchpoints

- `docs/lmstudio-integration.md` — architecture section needs rewrite; pitfall #3 static entries note is outdated
- `CHANGELOG.md` — new file, needs full entry for this branch
- `README.md` — Supported Models table still has no LM Studio entry (out of scope for this plan but flagged)
