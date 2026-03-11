# LM Studio Integration — Developer Notes

Added in `feature/lmstudio-support`. This doc captures every gotcha hit during implementation so the next developer doesn't repeat them.

## Architecture

LM Studio support is **pure client-side**. The browser calls `localhost:1234/v1/chat/completions` directly. The Railway server is never involved. This means:
- No server-side proxy needed
- User must have LM Studio running locally
- CORS works out of the box in LM Studio 0.3+ (no config required)

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

**Fix:** Hardcode `context_window: 8192` minimum in both:
- Static model registry entries (`models.py`)
- Dynamic discovery override (`server.py` — `LMSTUDIO_CONTEXT_WINDOW_OVERRIDE`)

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

**Fix:** Hardcode a known-good reasoning model list in `server.py` (`LMSTUDIO_REASONING_MODELS`). Anything not on the list gets `reasoning: false` in the registry.

Known reasoning-capable models (confirmed as of Mar 2026):
- `zai-org/glm-4.7-flash`
- `zai-org/glm-4.6v-flash`
- `qwen/qwen3.5-35b-a3b`
- `qwen/qwen3.5-9b`

### 7. Vision/image capability — check load logs
`qwen3.5-35b-a3b` has a vision encoder (confirmed from LM Studio load logs) but the model ID doesn't make this obvious. Use `LMSTUDIO_IMAGE_MODELS` set in `server.py` to override image capability for known vision models.

### 8. MLX Outlines + Pydantic enums = broken JSON schema
Pydantic enums (`Enum(str)`) generate `$defs/$ref` in their JSON schema. MLX Outlines can't handle `$ref` and returns empty content.

**Fix:** Use `Literal["a", "b", "c"]` instead of `Enum` for any field used in structured output.

## Configuration

Users configure LM Studio via the BYOK panel:
- **No API key required** — `lmstudio` is in `_BYOK_FREE_PROVIDERS`
- **Base URL field** — defaults to `http://localhost:1234`, overridable for Cloudflare Tunnel users

## Testing

Start the server in staging mode and hit the models endpoint:
```bash
python server.py --mode staging --port-staging 5050
curl http://localhost:5050/api/llm/models | python3 -c "
import sys,json
d=json.load(sys.stdin)
lm=[m for m in d['models'] if m.get('provider')=='lmstudio']
print(f'{len(lm)} LM Studio models found')
"
```

LM Studio must be running with at least one model loaded for dynamic discovery to work.
