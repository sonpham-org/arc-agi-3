# ARC-AGI-3 Project Instructions

## Terminology

- **"Replay"** = the share page (`share.html` / `/share/<id>` endpoint), NOT the in-app replay in `index.html`
- **"Step"** = a single game step (one action executed in the environment)
- **"Turn"** = one complete agent invocation (an LLM call + all steps in its plan), or one human action. Each turn gets a unique `turnId`. Undo reverts an entire turn, not individual steps.
- **"Call"** = one LLM agent invocation (may produce a multi-step plan). Compact context triggers after N Calls, not Steps.

## Reasoning View Consistency

The Reasoning view must look the same across ALL viewing modes and pages:
- **`index.html`**: live agent session, resumed session, branched session, in-app replay (all use `renderRestoredReasoning()`)
- **`share.html`**: public share/replay page (has its own rendering but must match the same grouped format)

When updating reasoning rendering in one place, update ALL others to match. Key principles:
- Steps are grouped into plan groups (LLM call + its plan followers), not shown individually
- Plan steps show as numbered action buttons; green = completed/current, unlit = pending
- Scrubber progressively lights up plan steps as you advance
- Human actions show separately in yellow
- Both pages must use the same grouping logic (check `llm_response.parsed` for plan leader, absorb followers by plan capacity)
- Branched sessions must show parent reasoning up to the branch point (trace back via `parent_session_id` / `branch_at_step`)

## Turso (Remote DB) Upload

To upload local sessions to Turso, you must source `.env` first since `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are not set in the shell by default:

```bash
set -a && source .env && set +a
```

Then use `libsql_experimental` to connect and write directly. The server's `_turso_import_session()` won't work from a standalone script because env vars are read at module import time. Instead, connect directly:

```python
import libsql_experimental as libsql
conn = libsql.connect("turso_replica.db", sync_url=url, auth_token=token)
```

Upload sessions with >5 steps to avoid cluttering Turso with empty/trivial sessions.
