# LM Studio Integration — Developer Notes

Added in `feature/lmstudio-support`. This doc captures every gotcha hit during implementation so the next developer doesn't repeat them.

## Architecture

LM Studio LLM calls are **pure client-side** — the browser calls `localhost:1234/v1/chat/completions` directly. Discovery uses a **hybrid strategy** because of CORS limitations (see pitfall #8).

### Discovery flow (hybrid)
1. `loadModels()` in `scaffolding.js` fetches `/api/llm/models` from the server
2. **Staging mode**: the server probes `localhost:1234/v1/models` directly (server-to-server HTTP, no CORS). LM Studio models are returned with capabilities from `LMSTUDIO_CAPABILITIES` in `models.py`. Embedding models filtered out.
3. **Production mode (Railway)**: server can't reach user's localhost:1234. Returns zero LM Studio models.
4. `loadModels()` then attempts browser-side discovery: fetches `{baseUrl}/v1/models` directly (default `http://localhost:1234`, 1.5s timeout). This only works if LM Studio has CORS enabled.
5. Client-side dedup: models already returned by the server (step 2) are skipped to prevent doubles.
6. If both paths fail, no LM Studio group appears in the dropdown — no error.

### LLM call flow
The browser calls `localhost:1234/v1/chat/completions` directly via `_callLLMInner()`. The Railway server is **never** in the LLM call path.

### Why hybrid?
- **Staging**: server is local, so server-to-server HTTP always works (no CORS needed). This is the reliable path.
- **Production (Railway)**: server can't reach user's localhost:1234, so the browser must do it. But LM Studio does NOT send CORS headers by default (see pitfall #8). Users must enable CORS in LM Studio settings for production discovery to work.

### Key constraints
- LLM calls always go browser → LM Studio directly (no server proxy)
- Discovery has two paths: server-side (staging, always works) and client-side (production, needs CORS)
- User must have LM Studio running locally (or via Cloudflare Tunnel)
- `LMSTUDIO_CAPABILITIES` is intentionally duplicated in `scaffolding.js` (browser) and `models.py` (server/CLI) — update both when adding models

## Pitfalls (all real, all hit)

### 1. `reasoning_content` vs `content` — GLM models
GLM 4.7 Flash returns thinking tokens in `reasoning_content`. The `content` field comes back `null` or empty. Any code that reads `choices[0].message.content` gets nothing.

**Fix (scaffolding.js):**
```js
const text = data.choices?.[0]?.message?.content
           || data.choices?.[0]?.message?.reasoning_content
           || '';
```

### 2. Provider must be in `byokProviderOrder`
If `'lmstudio'` is not in the provider order array, all discovered LM Studio models are silently dropped on the floor — they exist in the registry but never appear in the UI dropdown.

**Fix (scaffolding.js):** Add `'Lmstudio'` to `providerOrder` (the available/free group, not `byokProviderOrder`) and add a display label in `providerLabels`.

### 3. Context window defaults to 3900 — silent truncation
LM Studio's default context window is 3900 tokens. llama_index (and similar wrappers) use this value to truncate prompts *before* sending them — no error is thrown, the model just receives a mangled half-prompt.

**Fix (scaffolding.js):** Hardcode `context_window: 8192` in the client-side discovery block inside `loadModels()`. Every model discovered from LM Studio gets this override applied before it enters `modelsData`.

### 4. `finish_reason: 'length'` is your only truncation signal
When the model hits the context limit on the API side, the response silently truncates. No error. The only indicator is `finish_reason === 'length'`.

**Fix (scaffolding.js):**
```js
if (data.choices?.[0]?.finish_reason === 'length') return { text, truncated: true };
```

### 5. Thinking mode is set at model load, not per-request
Unlike Anthropic's `budget_tokens` parameter, LM Studio thinking mode is a preset baked in when the model loads. You cannot toggle it per-request via the API.

**Impact:** All requests in a session use the same thinking config. Can't mix thinking/non-thinking calls.

### 6. Reasoning model detection — no API indicator
There's no standard API field to detect if a model supports reasoning. The `/v1/models` endpoint doesn't expose this.

**Fix:** Hardcode a known-good capability lookup in `LMSTUDIO_CAPABILITIES` — exists in **two** files:
- `scaffolding.js` (browser discovery path)
- `models.py` (CLI agent path)

Both must be kept in sync. Unknown models default to `{ reasoning: false, image: false }`.

Known reasoning-capable models (confirmed as of Mar 2026):
- `zai-org/glm-4.7-flash` — reasoning only
- `zai-org/glm-4.6v-flash` — reasoning + vision
- `qwen/qwen3.5-35b-a3b` — reasoning + vision (confirmed from LM Studio load logs)
- `qwen/qwen3.5-9b` — reasoning only

### 7. Vision/image capability — check load logs
`qwen3.5-35b-a3b` has a vision encoder (confirmed from LM Studio load logs) but the model ID doesn't make this obvious. Image capability is set in `LMSTUDIO_CAPABILITIES` (both `scaffolding.js` and `models.py`). When confirming a new vision model, add it to both files.

### 8. CORS headers missing — browser discovery fails silently
LM Studio does **NOT** send `Access-Control-Allow-Origin` headers by default (confirmed Mar 2026, Express-based server). When the browser fetches `http://localhost:1234/v1/models` from a page served on a different origin (e.g. `localhost:5050` or `https://your-app.railway.app`), the browser blocks the response. The `catch` block swallows the error, and no LM Studio models appear in the dropdown.

**Fix:** Hybrid discovery strategy:
- **Staging mode**: server probes `localhost:1234` directly in `/api/llm/models` (server-to-server HTTP, no CORS needed). This always works when server and LM Studio are on the same machine.
- **Production mode (Railway)**: server can't reach user's localhost:1234, so the browser must do it. User **must enable CORS** in LM Studio → Settings → Server → Enable CORS.
- **Client-side dedup**: `loadModels()` in `scaffolding.js` builds a `Set` of `api_model` IDs already returned by the server, skips any model the server already discovered.
- **Console warning**: non-timeout fetch failures log `[LM Studio discovery] client-side fetch failed:` to browser console for debugging.

**If a user reports "LM Studio models don't appear"**: check (1) LM Studio is running with at least one model loaded, (2) CORS is enabled in LM Studio settings if accessing from a different origin.

### 9. MLX Outlines + Pydantic enums = broken JSON schema
Pydantic enums (`Enum(str)`) generate `$defs/$ref` in their JSON schema. MLX Outlines can't handle `$ref` and returns empty content.

**Fix:** Use `Literal["a", "b", "c"]` instead of `Enum` for any field used in structured output.

## Configuration

Users configure LM Studio via the BYOK panel:
- **No API key required** — `lmstudio` is in `_BYOK_FREE_PROVIDERS`
- **Base URL field** — defaults to `http://localhost:1234`, overridable for Cloudflare Tunnel users

## Testing

LM Studio discovery is **client-side only** — you cannot test it via `curl` against the server. The server's `/api/llm/models` endpoint will never return LM Studio models.

### Browser verification
1. Start the server: `python server.py --mode staging --port-staging 5050`
2. Open `http://localhost:5050` in a browser
3. With LM Studio running (at least one model loaded), open the model dropdown — LM Studio models should appear under "LM Studio (free, local)"
4. With LM Studio stopped, reload — no LM Studio group should appear, no errors in console

### Console verification
Open browser DevTools console and run:
```js
fetch('http://localhost:1234/v1/models').then(r => r.json()).then(d => console.log(d.data.map(m => m.id)));
```
This confirms what the discovery code sees. Models with `embedding` in the ID are filtered out.

### Verification checklist
- [ ] LM Studio running → models appear in dropdown under "LM Studio (free, local)"
- [ ] LM Studio stopped → no LM Studio group, no console errors
- [ ] Custom base URL (Cloudflare Tunnel) → discovery uses that URL
- [ ] Known capability models show correct RSN/IMG tags
- [ ] `text-embedding-*` models are not shown

LM Studio must be running with at least one model loaded for discovery to work.

## Client↔Server Communication Analysis

The current architecture has an important nuance: **LM Studio models exist only in the browser's memory** after discovery. The server never knows about them. This means:

### What works today
- **Discovery**: browser → LM Studio `/v1/models` → merged into `modelsData` in JS
- **LLM calls**: browser → LM Studio `/v1/chat/completions` → response parsed in JS
- **Session save/resume**: the *model name* is persisted in session metadata, so resumed sessions know which model was used

### What the server does NOT know
- Which LM Studio models the user has loaded
- Whether a specific session used an LM Studio model (it only sees the model name string)
- LM Studio token usage or costs (all tracked client-side in `callLLM._lastUsage`)

### When this matters
- **Observatory/replay**: LLM call logs stored in `llm_calls` table include model name — replays can show "this step used qwen3.5-35b-a3b" but can't verify the model is still available
- **Batch runner / CLI agent**: uses `models.py` LMSTUDIO_CAPABILITIES, NOT the browser discovery path. CLI LM Studio support is a separate concern (out of scope for this feature)
- **Analytics**: if you ever need server-side LM Studio usage stats, the model name in `llm_calls` is the only signal

### Future considerations
If you need the server to know about LM Studio models (e.g. for admin dashboards, model usage analytics, or coordinating multiple users), the browser would need to POST discovered models back to a server endpoint. This is NOT implemented today and is not needed for the current single-user architecture.

## Next Developer Notes

### Adding a new LM Studio model to the capability list
1. Load the model in LM Studio and check its capabilities (reasoning: test with a thinking prompt; vision: check load logs for mmproj)
2. Add the entry to `LMSTUDIO_CAPABILITIES` in **both**:
   - `static/js/scaffolding.js` (browser path)
   - `models.py` (CLI agent path)
3. Update this doc's pitfall #6 known models list

### Changing the discovery timeout
The 1.5s timeout in `scaffolding.js` `loadModels()` (`AbortSignal.timeout(1500)`) balances UX speed vs. slow network/tunnel latency. If users report models not appearing, increase this — but it delays the entire model dropdown load.

### If LM Studio changes its API
LM Studio uses the OpenAI-compatible `/v1/models` and `/v1/chat/completions` endpoints. If these change, update:
- Discovery: `loadModels()` in `scaffolding.js`
- LLM calls: `_callLLMInner()` lmstudio branch in `scaffolding.js`
- CORS: LM Studio 0.3+ has CORS on by default. If a future version changes this, users will see a CORS error in console — the error message in `_callLLMInner` already directs them to check model load state.

### CLI agent LM Studio support
The CLI agent (`agent.py` / `batch_runner.py`) can use LM Studio models if running on the same machine, since `localhost:1234` resolves correctly in that context. This uses `models.py` LMSTUDIO_CAPABILITIES for capability metadata. This is a separate concern from web UI discovery and is not addressed in the `feature/lmstudio-support` branch.

## Production Readiness Assessment

### Will this break on Railway? No.

The changes are **safe for production deployment** because:

1. **Server-side removal is additive, not breaking.** We removed code that *never worked on Railway anyway* — probing `localhost:1234` on Railway hits Railway's own host, which doesn't run LM Studio. The server was returning zero LM Studio models in production mode already.
2. **Client-side discovery is fail-safe.** If the browser can't reach `localhost:1234` (which it can't if the user doesn't run LM Studio), the `fetch` throws, the `catch` swallows it silently, and the model dropdown shows no LM Studio group. No error, no console noise.
3. **No server API contract changes.** `/api/llm/models` still returns the same structure — it just no longer includes `provider: 'lmstudio'` entries. The client adds them itself from the browser-side discovery.
4. **Session persistence is unaffected.** Model names are stored as opaque strings in `sessions.model` and `llm_calls.model`. Whether the model came from server discovery or client discovery doesn't matter.
5. **All 46 existing tests pass.** Import tests, JSON parse tests, config tests, fallback action tests — none touch LM Studio discovery, and none are broken by the changes.

### What the test suite does NOT cover (gaps)

The existing test suite tests server-side concerns only:
- `test_imports.py` — verifies `db`, `server`, `agent`, `batch_runner` import without errors
- `test_parse.py` — tests `_extract_json` and `_parse_llm_response` (server-side JSON parsing)
- `test_config.py` — tests `load_config` and `_deep_merge` (CLI agent config)
- `test_fallback.py` — tests `_fallback_action` (CLI agent fallback)
- `test_providers.py` — live LLM call test per provider (requires API keys)
- `test_scaffolds.py` — end-to-end game scaffold test with real LLM (requires API keys)
- `test_gemini_live.py` — Gemini-specific live test

**There are NO browser-side tests.** No Playwright, Selenium, Cypress, or equivalent. This means:
- LM Studio client-side discovery is tested **manually only** (see Testing section above)
- The BYOK panel, model dropdown, and provider wiring have no automated verification
- Any future regression in `loadModels()` or `_callLLMInner()` will only be caught by a human

**Recommendation for next developer:** Add a Playwright or Puppeteer test that:
1. Starts the server in staging mode
2. Opens the browser
3. Mocks `localhost:1234/v1/models` with a fake response
4. Verifies the LM Studio group appears in the dropdown
5. Verifies embedding models are filtered out
6. Verifies the group disappears when LM Studio is not running

### What could go wrong in production (honest assessment)

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LM Studio changes `/v1/models` response format | Low | Models don't appear | User reports it; update `loadModels()` parsing |
| LM Studio disables CORS by default | Low | Discovery fails silently | Error message in `_callLLMInner` already directs user to check CORS |
| Browser blocks `localhost` fetch from HTTPS page | Medium | Discovery fails on Railway prod (HTTPS) | **This is the #1 risk.** Mixed content: HTTPS page fetching HTTP localhost. Most browsers allow this for `localhost` specifically, but it's not guaranteed. Test on Railway prod URL. |
| `AbortSignal.timeout` not supported in older browsers | Low | Discovery hangs or fails | Safari 16+, Chrome 103+, Firefox 100+ all support it. Only affects very old browsers. |
| `LMSTUDIO_CAPABILITIES` gets out of sync between `scaffolding.js` and `models.py` | Medium | Wrong RSN/IMG tags | Comments in both files cross-reference each other. No automated check exists. |

### The HTTPS mixed content risk (important)

When deployed on Railway at `https://your-app.railway.app`, the browser will make a fetch to `http://localhost:1234/v1/models`. This is **mixed content** (HTTPS page → HTTP resource). Most modern browsers have a `localhost` exemption for this, but:
- Chrome: allows it (explicit localhost exemption)
- Firefox: allows it (explicit localhost exemption)
- Safari: allows it as of Safari 15+
- Edge: same as Chrome

**If a user reports "LM Studio models don't appear in production but work in staging"**, the first thing to check is mixed content blocking in their browser's console.
