# RGB Local Sandbox — Plan Doc

**Date**: 2026-03-25
**Author**: Claude Sonnet 4.6
**Status**: Draft — awaiting approval

## Background

The RGB harness (`static/js/scaffolding-rgb.js`) executes `bash` tool calls through Pyodide (in-browser WASM Python). Pyodide has real limitations:

- No network access inside the sandbox
- Only a subset of Python packages available (numpy, pydantic, but not scipy, pandas, sklearn, etc.)
- Significant first-load latency (~5–15s to download and initialize the WASM runtime)
- WASM execution is slower than native CPython (matters for numeric-heavy analysis)
- Cannot call external processes or shell commands

A "Local Sandbox" mode lets the user run a small Python script on their own machine. The browser sends code execution requests to that local process via WebSocket, runs them in real CPython, and returns stdout/stderr. Pyodide stays as the automatic fallback if the local sandbox is not running.

## Scope

### In

- `local_sandbox.py` — a standalone Python script the user runs locally (`python local_sandbox.py`)
- A new "Local Sandbox" toggle + URL field in the RGB settings panel (schema + `getScaffoldingSettings`)
- A browser-side WebSocket client that routes `bash` tool calls to the local server when it is enabled and reachable
- Automatic fallback to Pyodide if the WebSocket is disconnected or the feature is off
- A one-time connection check on toggle-enable, with a visible status indicator (Connected / Disconnected)
- Session save/resume stores the `rgb_sandbox_mode` setting (just a flag; the URL defaults to `ws://localhost:8765`)

### Out

- Docker / container sandboxing (out of scope — local CPython is sufficient)
- Any server-side relay through the Railway backend (the local sandbox must connect browser → localhost directly, never through the Railway server)
- Authentication / API keys on the WebSocket (localhost only; no auth needed)
- Supporting remote (non-localhost) sandbox URLs in v1 (adds security surface; defer)
- Batch runner (`agent.py` / `batch_runner.py`) integration — CLI already uses real CPython
- Changing how `read` or `grep` tools work (they remain pure JavaScript, no change)

## Architecture

### Data Flow

```
Browser (scaffolding-rgb.js)
  │
  │  bash tool call arrives in rgbExecuteTool()
  │
  ├─► [local sandbox enabled AND ws connected?]
  │       │  YES
  │       └─► WebSocket → local_sandbox.py (localhost:8765)
  │                │  executes code in subprocess
  │                └─► stdout/stderr → WebSocket → browser → tool result
  │
  └─► [fallback: Pyodide]
          runPyodide(fullCode, grid, prevGrid, sessionId)
```

### local_sandbox.py

A single-file Python script (~120 lines). No external dependencies beyond the standard library (Python 3.8+).

```
python local_sandbox.py [--port 8765] [--timeout 15]
```

Responsibilities:
1. Start a WebSocket server on `ws://localhost:<port>` using `asyncio` + `websockets` (stdlib-adjacent, ships with most Python installs; if missing, `pip install websockets` — one line in the printed startup message)
2. Accept one connection at a time (the browser tab is the only client)
3. On each message: deserialize JSON `{ id, code }`, run code in a subprocess with `subprocess.run(['python3', '-c', code], capture_output=True, timeout=timeout, text=True)`, respond with JSON `{ id, stdout, stderr, error }`
4. The game log is embedded in the code string by the browser (same technique as the Pyodide path: prepend `os.makedirs` + file write). The subprocess gets a fresh environment each call.
5. Print a startup banner to the terminal: `Local sandbox ready on ws://localhost:8765 — open ARC-AGI-3 and enable Local Sandbox in RGB settings.`
6. On `Ctrl-C`: clean shutdown.

Security model: localhost-only, no auth. The user is explicitly running this on their own machine. The browser origin check (`Origin` header = `localhost` or `127.0.0.1`) is enforced by the websockets library's default behaviour. No cross-origin WebSocket connections are accepted.

### Browser WebSocket Client (in scaffolding-rgb.js)

A module-level singleton manages the WebSocket lifecycle:

```
_rgbLocalWs          — the WebSocket instance (null when not connected)
_rgbLocalWsReady     — boolean
_rgbLocalWsPending   — Map<id, {resolve, reject}>  (per-call promises)
_rgbLocalCallId      — monotonic counter
```

Key functions (all new, in `scaffolding-rgb.js`):

- `rgbLocalSandboxConnect(url)` — opens the WebSocket, wires `onopen` / `onmessage` / `onclose` / `onerror`, returns a Promise that resolves when connected or rejects on error. Called when the user enables the toggle.
- `rgbLocalSandboxDisconnect()` — closes the WebSocket cleanly, rejects all pending promises, resets `_rgbLocalWsReady`.
- `rgbLocalSandboxExec(code)` — sends `{ id, code }`, returns a Promise that resolves to `{ stdout, stderr }` or rejects on timeout (10s) / error.
- `rgbCheckLocalSandbox()` — sends a health-check (`print("ok")`), updates the status indicator DOM element.

The `bash` case in `rgbExecuteTool()` becomes:

```
if (settings.rgb_sandbox_mode === 'local' && _rgbLocalWsReady) {
    try {
        const { stdout, stderr } = await rgbLocalSandboxExec(fullCode);
        return (stdout + (stderr ? '\n[stderr]\n' + stderr : '')).trim() || '(no output)';
    } catch (e) {
        return `[Local sandbox error: ${e.message}] — falling back to Pyodide`;
        // then fall through to Pyodide
    }
}
// Pyodide path (unchanged)
```

### Settings Panel Changes

New fields added to the `rgb` section of `SCAFFOLDING_SCHEMAS` (in `scaffolding-schemas.js`):

```js
{ type: 'section-divider', label: 'Bash Sandbox' },
{ type: 'select', id: 'sf_rgb_sandboxMode', label: 'Sandbox',
  options: [
    { v: 'pyodide', l: 'Pyodide (in-browser)' },
    { v: 'local',   l: 'Local (ws://localhost)' },
  ], default: 'pyodide' },
{ type: 'text-input', id: 'sf_rgb_sandboxUrl', label: 'WS URL',
  default: 'ws://localhost:8765', placeholder: 'ws://localhost:8765',
  showWhen: 'sf_rgb_sandboxMode === local' },
{ type: 'status-indicator', id: 'sf_rgb_sandboxStatus', label: 'Status' },
```

`getScaffoldingSettings()` in `llm-config.js` reads `sf_rgb_sandboxMode` and `sf_rgb_sandboxUrl` and adds them to the `rgb` settings object as `rgb_sandbox_mode` and `rgb_sandbox_url`.

`attachSettingsListeners()` adds:
- `change` listener on `sf_rgb_sandboxMode`: when switched to `local`, call `rgbLocalSandboxConnect(url)` and update the status indicator; when switched to `pyodide`, call `rgbLocalSandboxDisconnect()`.
- `blur` listener on `sf_rgb_sandboxUrl`: if mode is `local`, reconnect to the new URL.

### Files Touched

| File | What Changes |
|------|-------------|
| `local_sandbox.py` | **NEW** — the standalone local server script |
| `static/js/scaffolding-rgb.js` | WebSocket client singleton + `rgbExecuteTool` bash branch updated |
| `static/js/config/scaffolding-schemas.js` | New fields in the `rgb` section |
| `static/js/llm-config.js` | Read new fields in the `rgb` branch of `getScaffoldingSettings()` |
| `static/js/ui.js` or `static/js/state.js` | `attachSettingsListeners()` — new listeners for sandbox mode toggle |
| `CHANGELOG.md` | Entry for this feature |

No server-side changes. No new Flask routes. No changes to `engine.js` or Pyodide infrastructure — Pyodide remains the default and fallback.

## TODOs

### Step 1: Write `local_sandbox.py`

1. Implement the script with `asyncio` + `websockets`.
2. Subprocess execution with configurable timeout (default 15s).
3. JSON protocol: request `{ id, code }`, response `{ id, stdout, stderr, error? }`.
4. Startup banner. Graceful `KeyboardInterrupt` shutdown.
5. **Verify**: run `python local_sandbox.py`, connect to it with `wscat` or a browser JS snippet, send `{"id":1,"code":"print(1+1)"}`, confirm response `{"id":1,"stdout":"2\n","stderr":""}`.

### Step 2: Schema — add sandbox settings fields

1. Add `section-divider`, `select` (sandbox mode), `text-input` (URL), and `status-indicator` to the `rgb` sections array in `scaffolding-schemas.js`.
2. Add conditional-show logic for the URL field (only visible when mode = `local`). This may require a `showWhen` field type the renderer already supports, or a class-based toggle in `attachSettingsListeners`.
3. **Verify**: RGB scaffolding settings panel renders the new fields; toggling mode shows/hides URL input.

### Step 3: `getScaffoldingSettings()` reads new fields

1. In `llm-config.js`, inside the `rgb` branch, read `sf_rgb_sandboxMode` and `sf_rgb_sandboxUrl`.
2. Add `rgb_sandbox_mode` and `rgb_sandbox_url` to the returned settings object.
3. **Verify**: `getScaffoldingSettings()` in the browser console returns the correct values when the panel fields are set.

### Step 4: WebSocket client in `scaffolding-rgb.js`

1. Add `_rgbLocalWs`, `_rgbLocalWsReady`, `_rgbLocalWsPending`, `_rgbLocalCallId` module-level vars.
2. Implement `rgbLocalSandboxConnect(url)`, `rgbLocalSandboxDisconnect()`, `rgbLocalSandboxExec(code)`, `rgbCheckLocalSandbox()`.
3. Update the `bash` case in `rgbExecuteTool()` to try local sandbox first, then fall through to Pyodide.
4. **Verify**: with `local_sandbox.py` running, enable local sandbox in settings, confirm the status indicator shows "Connected". Send a manual bash tool call from the browser console (`rgbLocalSandboxExec('print(42)')`), confirm result `"42\n"`.

### Step 5: `attachSettingsListeners()` wiring

1. Locate where RGB settings change listeners are added (currently in `ui.js` or `state.js` — grep for `sf_rgb`).
2. Add `change` listener on `sf_rgb_sandboxMode`:
   - On `local`: call `rgbLocalSandboxConnect(url)` and set status indicator to "Connecting…"
   - On `pyodide`: call `rgbLocalSandboxDisconnect()` and clear status indicator
3. Add `blur` listener on `sf_rgb_sandboxUrl`: reconnect if mode is `local`.
4. **Verify**: toggle mode in the UI, confirm WebSocket is opened/closed and status updates correctly.

### Step 6: End-to-end test

1. Start `local_sandbox.py`.
2. Open ARC-AGI-3, select RGB scaffolding, enable Local Sandbox, confirm Connected.
3. Run autoplay on `ls20` for 10 steps. Confirm bash tool calls execute (check browser console for `[RGB] bash -> local sandbox` logs) and that the game log file is written correctly.
4. Kill `local_sandbox.py` mid-session. Confirm the next bash call falls back to Pyodide gracefully (no crash, just a fallback message in tool result).
5. Re-enable local sandbox, confirm reconnect works.
6. Save session, reload page, resume session — confirm `rgb_sandbox_mode` setting is restored from localStorage.

### Step 7: Changelog + cleanup

1. Add `CHANGELOG.md` entry.
2. Ensure file headers are updated on every touched file.
3. Confirm no dead code left in `rgbExecuteTool()` (the old Pyodide-only bash path is now the else branch, not removed).

## Protocol Specification

Request (browser → local_sandbox.py):
```json
{ "id": 42, "code": "import os\nos.makedirs('/workspace', exist_ok=True)\nwith open('/workspace/game_log.txt','w') as f:\n    f.write('...')\nprint('done')" }
```

Response (local_sandbox.py → browser):
```json
{ "id": 42, "stdout": "done\n", "stderr": "" }
```

Error response:
```json
{ "id": 42, "stdout": "", "stderr": "", "error": "TimeoutExpired" }
```

The `id` field is echoed back so the browser can match concurrent responses to their awaiting Promises. In practice only one bash call is in-flight at a time (the tool loop is sequential), but the protocol is designed to handle concurrency correctly.

## Docs / Changelog Touchpoints

- `CHANGELOG.md` — new entry under next version: "feat: RGB local sandbox — local Python execution via WebSocket"
- `CLAUDE.md` — no changes needed (architecture section already covers client-side sandbox)
- This plan doc — mark as completed after Step 7 passes

## Open Questions (for approval)

1. **`showWhen` field type**: does `renderScaffoldingSettings()` already support conditionally hiding fields based on another field's value? If not, the simplest implementation is to always show the URL input and just let it be ignored when mode is `pyodide`. Confirm before Step 2.
2. **`websockets` dependency**: some Python environments may not have `websockets` installed. The startup banner should print `pip install websockets` if the import fails and exit cleanly. Confirm this UX is acceptable.
3. **Subprocess vs restricted eval**: running arbitrary code in a subprocess is the safest approach (isolated, timeoutable, clean env). A `restricted exec` inside the server process itself would be slightly faster but harder to isolate. Confirm subprocess is the right call.
