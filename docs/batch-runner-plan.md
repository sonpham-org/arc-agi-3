# Batch Runner API — Architecture Analysis & Fix Plan

> **Status:** Planning only — no code changes in this document.
> **Author:** Claude Sonnet 4.6, 2026-03-11
> **Scope:** `server.py` lines 2279–2384 (`/api/batch/*`), `batch_runner.py`, `agent.py`

---

## 1. What We Are Trying to Achieve

The batch runner API exists to let automated systems (CI, evaluation scripts, the web UI) trigger multi-game agent runs without SSH access to the server. The requirements are:

1. **Triggerable over HTTP** — a caller can start a batch run with specific games, model, and parameters
2. **Monitorable** — the caller can poll status and see per-game results
3. **Cancellable** — a running batch can be stopped without killing the web server
4. **Isolated** — a batch run crash must not affect the web server's ability to serve other requests
5. **Authenticated** — only authorized callers can trigger batch runs; dev mode has a clear, deliberate bypass (not an accidental one)

The current code achieves #1 and partially #2. It fails on #3, #4, and the intent of #5.

---

## 2. Current Architecture (and What's Wrong With It)

### 2.1 Thread-Based Execution: No Isolation

```python
def _run():
    run_batch(games=resolved_games, cfg=cfg, ...)

t = threading.Thread(target=_run, daemon=True)
t.start()
```

`run_batch` runs in a daemon thread inside the Flask process. Problems:

- **No isolation**: `run_batch` calls `agent.py` which makes real LLM API calls, spawns game envs, writes to SQLite. Any unhandled exception propagates into a thread that silently dies. A deadlock or OOM in `run_batch` can starve the web server's thread pool.
- **No cancel**: `t.daemon = True` means the thread dies when the process dies — but there's no way to stop it while the process is running. Once `/api/batch/start` returns, the batch is uncontrollable.
- **GIL contention**: Python's GIL means heavy CPU work in the batch thread (grid rendering, game simulation) competes with Flask request handling.

### 2.2 Auth Is a Footgun

```python
BATCH_API_KEYS = set(
    k.strip() for k in os.environ.get("BATCH_API_KEYS", "").split(",") if k.strip()
)

def _require_batch_auth():
    if not BATCH_API_KEYS:
        return None  # no keys configured = open access (local dev)
    ...
```

**The intent is "open in local dev."** The reality is that anyone who can reach port 5000 (including on a misconfigured Railway instance) can trigger unlimited batch runs without authentication. The Railway staging environment uses port 5000. If `BATCH_API_KEYS` is not set in the Railway env vars (which is easy to miss), the batch API is publicly accessible.

The correct intent should be: *staging with no keys configured = explicitly disabled (not open)*. The only open-access mode should be when explicitly opted in via a flag.

### 2.3 Lazy Imports Hide Breakage

```python
@app.route("/api/batch/start", methods=["POST"])
def batch_start():
    ...
    from batch_runner import run_batch, load_config as br_load_config
    from agent import MODELS
```

`batch_runner` and `agent` are imported inside the handler, not at module load time. If there's an import error in either (missing dependency, syntax error), it won't be caught until someone hits the endpoint. The standard pre-push import check (`python -c "import server"`) will pass even if `batch_runner` is broken.

### 2.4 No Cancel Endpoint

There is no `/api/batch/<id>/cancel`. Once started, a batch runs to completion (or until the server restarts). The only way to stop it is to kill the server process.

### 2.5 Config Mutation Risk

```python
cfg = br_load_config()
if model:
    cfg["reasoning"]["executor_model"] = model
```

`br_load_config()` presumably returns a dict. This mutates it and passes it to `run_batch`. If `br_load_config()` returns a reference to a module-level singleton (rather than a fresh copy each time), concurrent batch runs could mutate each other's configs.

---

## 3. Proposed Architecture

### 3.1 Core Principle: Subprocess Isolation

Instead of a thread, launch `batch_runner.py` as a **subprocess**. This gives:

- Complete process isolation — a crash in `batch_runner.py` doesn't affect the web server
- Cancellation via `subprocess.terminate()` or `subprocess.kill()`
- No GIL contention
- A natural way to capture stdout/stderr for logging
- Already how human operators run the batch runner from CLI

The batch runner already writes its status to SQLite (`batch_runs`, `batch_games` tables), so the status endpoint doesn't need to change — it still reads from DB.

### 3.2 Subprocess Approach — Sketch

```python
import subprocess
import sys

# In-memory map of batch_id → subprocess.Popen
_batch_processes: dict[str, subprocess.Popen] = {}

@app.route("/api/batch/start", methods=["POST"])
def batch_start():
    auth_err = _require_batch_auth()
    if auth_err:
        return auth_err

    data = request.get_json(force=True)
    # ... validate inputs ...

    batch_id = f"api-{secrets.token_hex(8)}"

    cmd = [
        sys.executable, "batch_runner.py",
        "--games", ",".join(resolved_games),
        "--concurrency", str(concurrency),
        "--max-steps", str(max_steps),
        "--repeat", str(repeat),
        "--resume", batch_id,  # batch_runner uses this as batch_id
    ]
    if model:
        cmd += ["--model", model]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=app.root_path,
    )
    _batch_processes[batch_id] = proc

    return jsonify({"batch_id": batch_id, "games": resolved_games, "status": "started"})


@app.route("/api/batch/<batch_id>/cancel", methods=["POST"])
def batch_cancel(batch_id):
    auth_err = _require_batch_auth()
    if auth_err:
        return auth_err

    proc = _batch_processes.get(batch_id)
    if proc is None:
        return jsonify({"error": "Batch not found or already finished"}), 404
    if proc.poll() is not None:
        return jsonify({"status": "already_finished"})
    proc.terminate()
    return jsonify({"status": "cancelled"})
```

**Important:** `_batch_processes` is in-memory. If the server restarts, running processes become orphaned — their PIDs are gone. The DB still has partial status from `batch_runner.py`'s own writes. This is acceptable: orphaned processes will finish on their own, and the DB status will reflect their final state when they exit. The cancel endpoint simply won't work for pre-restart batches.

### 3.3 Fix Auth: Staging-Explicit Open Mode

Replace the current implicit "no keys = open" with an explicit opt-in:

```python
BATCH_API_KEYS = set(
    k.strip() for k in os.environ.get("BATCH_API_KEYS", "").split(",") if k.strip()
)
BATCH_OPEN_ACCESS = os.environ.get("BATCH_OPEN_ACCESS", "").lower() in ("1", "true", "yes")

def _require_batch_auth():
    if BATCH_OPEN_ACCESS:
        return None  # explicitly opted in to open access
    if not BATCH_API_KEYS:
        return jsonify({"error": "Batch API not configured (set BATCH_API_KEYS or BATCH_OPEN_ACCESS=1)"}), 403
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Missing Authorization header"}), 401
    token = auth[7:]
    if token not in BATCH_API_KEYS:
        return jsonify({"error": "Invalid API key"}), 403
    return None
```

Local dev: set `BATCH_OPEN_ACCESS=1` in `.env`. Railway staging: set `BATCH_API_KEYS`. Forgetting both now returns a clear error instead of silently allowing access.

### 3.4 Fix Lazy Imports

Move `batch_runner` and `agent` imports to module level with a try/except that logs a warning if they fail:

```python
try:
    import batch_runner as _batch_runner
except ImportError as e:
    _batch_runner = None
    app.logger.warning(f"batch_runner import failed: {e}. Batch API disabled.")
```

In `batch_start`, check `if _batch_runner is None: return jsonify({"error": "Batch runner not available"}), 503`.

### 3.5 Fix Config Mutation

```python
cfg = copy.deepcopy(br_load_config())
```

One line. Guarantees concurrent batch calls don't share config state.

---

## 4. Decomposition Plan: Extract `routes/batch.py`

The batch API is self-contained enough to extract cleanly.

### Target structure

```
server.py          — remove /api/batch/* routes, remove _require_batch_auth
routes/
  batch.py         — Blueprint: /api/batch/start, /api/batch/<id>, /api/batch/<id>/cancel
                     Owns: _require_batch_auth, _batch_processes dict
```

### Registration

```python
from routes.batch import batch_bp
app.register_blueprint(batch_bp, url_prefix="/api/batch")
```

The Blueprint is small (~100 lines after cleanup) and has no shared state with the rest of `server.py` other than `_get_db()` (imported from `db.py`).

---

## 5. Implementation Order

| Step | Change | Risk | Test |
|------|--------|------|------|
| **B.1** | Fix lazy imports — move to module level with try/except | Low | Import check catches `batch_runner` errors at startup |
| **B.2** | Fix config mutation — `copy.deepcopy(br_load_config())` | Trivial | No behavior change unless concurrent batches |
| **B.3** | Fix auth — add `BATCH_OPEN_ACCESS`, fail closed when no keys | Low | Set `BATCH_OPEN_ACCESS=1` in local `.env` |
| **B.4** | Switch from thread to subprocess | **Medium** | Verify batch_runner writes DB correctly when launched as subprocess; test cancel endpoint |
| **B.5** | Add `/api/batch/<id>/cancel` endpoint | Low | POST to cancel, verify process terminates |
| **B.6** | Extract `routes/batch.py` Blueprint | Low | Import check + `/api/batch/start` smoke test |

### Critical test after Step B.4 (subprocess switch)

```bash
# 1. Start server
python server.py &

# 2. Trigger a batch
curl -H "Authorization: Bearer <key>" -X POST http://localhost:5000/api/batch/start \
  -d '{"games": ["ls20"], "max_steps": 5}'

# 3. Poll status — verify batch_runs record is created
curl http://localhost:5000/api/batch/<batch_id>

# 4. Test cancel
curl -X POST http://localhost:5000/api/batch/<batch_id>/cancel

# 5. Verify server still responds after cancel
curl http://localhost:5000/api/games
```

---

## 6. Relationship to Session Persistence Plan

The batch runner calls `agent.py` which calls `server.py`'s `/api/step` endpoint (in online mode) or runs game envs directly (in local mode). The session persistence fixes in the session plan apply to agent-recorded sessions whether they come from the batch runner or the web UI. The two plans are independent and can be implemented in parallel.

The one coupling point: `batch_start` currently does `from agent import MODELS` to validate the model parameter. After the models consolidation in Phase 5c (see `docs/modularization/phase-5-plan.md`), this becomes `from models import MODELS`. Step B.1 (fix lazy imports) and Phase 5c should be coordinated — do 5c first, then B.1, so the module-level import uses the right source.

---

## 7. What We Are Not Fixing (Explicitly Out of Scope)

- **Batch runner internal logic** (`batch_runner.py`) — the issues here are about how it is *hosted* by the web server, not how it works internally
- **Rate limiting batch runs** — a caller could trigger many concurrent batches; no concurrency limit exists. Accept for now; add a `max_concurrent_batches` check later if needed
- **Persistent process tracking across restarts** — PIDs are in-memory. Orphaned processes are accepted. A file-based PID store could be added later if needed
- **Streaming batch output** — the status endpoint returns DB snapshots, not real-time logs. Server-sent events or websockets would be needed for live output; out of scope
