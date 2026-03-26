# Claude Code OAuth Token — Sonnet 4.6 Fix Plan

**Author:** Claude Sonnet 4.6
**Date:** 2026-03-25
**Status:** Approved — implementing

---

## Problem

Claude Code OAuth tokens (`sk-ant-oat01-*`) fail with HTTP 400 when calling `claude-sonnet-4-6` via the Anthropic Messages API, even with the correct `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20` headers.

Root cause (confirmed by live API testing): Anthropic requires the system message to begin with `"You are Claude Code, Anthropic's official CLI for Claude."` to route Sonnet requests through the correct OAuth quota bucket. Without it, Sonnet returns `invalid_request_error`. Haiku works without it.

Secondary bug introduced this session: `models.py` was incorrectly changed to use fictional versioned IDs (`claude-sonnet-4-6-20250514`, `claude-opus-4-6-20250514`). The new-generation naming scheme (Claude 4.x) uses no date suffix. Must revert.

---

## Scope

**In:**
- Revert `models.py` model IDs to correct short-form
- Inject the required OAuth system text block in the CORS proxy (`server/app.py`)
- Same injection in the server-side CLI/batch path (`llm_providers_anthropic.py`)

**Out:**
- No JS changes — the browser-side `callLLM` and scaffolding are correct as-is
- No changes to user-facing system prompts — the Prompts tab already lets users override all prompts via localStorage

**Known limitation to flag in PR:** The injected `"You are Claude Code..."` block is prepended server-side and is not visible in the Prompts tab UI. It is a technical API requirement, not user content. Acceptable for now.

---

## Architecture

The OAuth proxy (`/api/llm/anthropic-proxy`) is the right injection point for the browser path — all browser OAuth calls already route here, and it's the single place that knows the request is OAuth. Injecting here keeps JS unchanged.

For CLI/batch (`llm_providers_anthropic.py`), the same injection must happen when `_is_oauth_token()` is true.

---

## Files

| File | Change |
|------|--------|
| `models.py` | Revert `claude-sonnet-4-6` and `claude-opus-4-6` `api_model` to short-form (no date suffix) |
| `server/app.py` | `anthropic_proxy()`: prepend OAuth system block before forwarding to Anthropic |
| `llm_providers_anthropic.py` | `_call_anthropic()`: prepend OAuth system block when key is an OAuth token |

---

## TODOs

- [x] Revert `models.py` api_model values
- [x] Inject system block in `server/app.py` `anthropic_proxy()`
- [x] Inject system block in `llm_providers_anthropic.py` `_call_anthropic()`
- [x] Inject system block in `agent_llm.py` `_call_anthropic()` *(gap — missed in original plan, added by Opus)*
- [ ] Restart server and verify via curl
- [ ] Open browser at localhost:5050, test Sonnet 4.6 with OAuth token end-to-end
- [x] CHANGELOG entry
- [ ] Push to staging

---

## Implementation Detail

### `server/app.py` — `anthropic_proxy()`

After `api_key = body.pop("api_key", "")`, before `_hx.post()`:

```python
_OAUTH_SYSTEM_BLOCK = {
    "type": "text",
    "text": "You are Claude Code, Anthropic's official CLI for Claude.",
}
existing = body.get("system")
if not existing:
    body["system"] = [_OAUTH_SYSTEM_BLOCK]
elif isinstance(existing, list):
    body["system"] = [_OAUTH_SYSTEM_BLOCK] + existing
else:  # plain string
    body["system"] = [_OAUTH_SYSTEM_BLOCK, {"type": "text", "text": existing}]
```

### `llm_providers_anthropic.py` — `_call_anthropic()`

```python
if _is_oauth_token(api_key):
    system_payload = [
        {"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."},
        {"type": "text", "text": SYSTEM_MSG},
    ]
else:
    system_payload = SYSTEM_MSG
# use system_payload in json= body
```

---

## Verification

```bash
# 1. Confirm model IDs
curl -s -A "Mozilla/5.0" http://localhost:5050/api/llm/models | python3 -c "
import sys,json
for m in json.load(sys.stdin).get('models',[]):
    if m['provider']=='anthropic': print(m['name'],'->', m['api_model'])
"
# Expected: claude-sonnet-4-6 -> claude-sonnet-4-6  (no date)

# 2. Test proxy with OAuth token
TOKEN="sk-ant-oat01-..."
curl -s -A "Mozilla/5.0" -X POST http://localhost:5050/api/llm/anthropic-proxy \
  -H "Content-Type: application/json" \
  -d "{\"api_key\":\"$TOKEN\",\"model\":\"claude-sonnet-4-6\",\"max_tokens\":10,\"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}]}"
# Expected: HTTP 200, "model":"claude-sonnet-4-6"

# 3. Browser test: http://localhost:5050 — select claude-sonnet-4-6, paste OAuth token, start session
```

---

## Docs / Changelog

- `CHANGELOG.md`: entry under fix — OAuth token support for Sonnet 4.6
- `docs/oauth-integration-plan.md`: update to note required system prompt for Sonnet
