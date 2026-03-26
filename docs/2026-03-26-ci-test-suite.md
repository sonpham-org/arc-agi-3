# Author: Bubba (Claude Sonnet 4.6)
# Date: 26-March-2026
# PURPOSE: Plan document for PR #6 — fix broken CI, repair test suite, add meaningful
#   route-level coverage. Scoped to infrastructure only; zero changes to game logic,
#   agent code, or Son Pham's application behaviour.
# SRP/DRY check: Pass — one plan doc per PR scope

# Plan: CI & Test Suite Overhaul (PR #6)

**Branch:** `fix/ci-test-suite`
**Target:** `VoynichLabs/sonpham-arc3` → PR upstream to `sonpham-org/arc-agi-3`
**Scope:** Infrastructure only. No game logic, no agent code, no application behaviour changes.

---

## Problem Statement

CI has been red on every push for weeks. The root causes are:

1. **Python version mismatch** — workflow runs Python 3.11; `arc-agi>=0.9` requires Python 3.12+. Nothing in CI ever executes.
2. **Broken db mock tests (2)** — `test_db.py::TestInitDb` configures mocks incompletely; `_vacuum_if_bloated()` receives a `MagicMock` where it expects an `int`, throws `TypeError`.
3. **Brittle header compliance tests (3)** — `TestFileHeaders` hardcodes `"Mark Barney"` and `"Cascade"` (Windsurf's AI tool) as required author name strings. Any file touched by a different model or collaborator fails. The structural checks (Author:, PURPOSE:, SRP/DRY check:) are valuable; the name assertions are not.
4. **Flaky timing test (1)** — `test_provider_routing.py::TestProviderThrottling::test_throttle_respects_min_delay` asserts wall-clock elapsed time. Fails under CI load. State-based check is correct.
5. **Live API test file** — `tests/test_gemini_live.py` is a manual integration test requiring a real `GEMINI_API_KEY`. Currently excluded via `--ignore` flag but still lives in the test directory, which is confusing. Should be removed entirely.
6. **Zero Flask route coverage** — The services layer is mocked and tested. The Flask routes themselves (63 routes) have no test coverage. We have no signal that the app boots or that routes return sensible responses before Railway deploys.

---

## Deliverables

### 1. Fix `.github/workflows/ci.yml`

- Bump Python 3.11 → **3.12** (minimum required by `arc-agi>=0.9`)
- Pin `arc-agi==0.9.6` explicitly (latest available; `>=0.9` is too loose)
- Remove `--ignore=tests/test_gemini_live.py` (file will be deleted)
- Add comment block documenting Railway auto-deploy triggers:
  ```
  # Railway deployment note:
  # Pushes to 'master' → auto-deploy to production (arc3.sonpham.net)
  # Pushes to 'staging' → auto-deploy to staging environment
  # CI must pass before Railway deploys (branch protection — verify this is enabled)
  ```

### 2. Delete `tests/test_gemini_live.py`

Full removal. It's a manual developer tool, not a CI test. If needed in future, document in README under "Manual testing."

### 3. Fix `tests/test_refactor_modules.py::TestFileHeaders`

Remove all hardcoded name assertions. Keep structural checks only.

**Current (broken):**
```python
def test_python_files_have_author_header(self):
    for relpath in REFACTOR_FILES_PY:
        line = self._read_first_line(relpath)
        assert line.startswith("# Author:"), ...
        assert "Mark Barney" in line, ...   # ← DELETE THIS
        assert "Cascade" in line, ...       # ← DELETE THIS
```

**Fixed:**
```python
def test_python_files_have_author_header(self):
    for relpath in REFACTOR_FILES_PY:
        line = self._read_first_line(relpath)
        assert line.startswith("# Author:"), \
            f"{relpath}: first line must start with '# Author:', got: {line!r}"
```

Same fix applied to `test_js_files_have_author_header`. The `PURPOSE:` and `SRP/DRY check:` tests already check for structural presence only — no changes needed there.

### 4. Fix `tests/test_db.py::TestInitDb` (2 tests)

The mock for `os.path.getsize` (or equivalent) must return an `int`, not the default `MagicMock`.

**Pattern to apply:**
```python
mock_getsize.return_value = 100  # MB — configure before calling _init_db()
```

Exact fix requires reading the mock setup in both failing tests and patching the return value on the correct mock attribute. Both tests follow the same pattern.

### 5. Fix `tests/test_provider_routing.py::TestProviderThrottling`

Replace:
```python
elapsed = time.time() - start
assert elapsed >= MIN_DELAY
```

With a state-based check — assert that the throttle mechanism recorded the correct next-allowed timestamp, not that wall-clock time elapsed.

### 6. Add `tests/test_app_boots.py` (new)

Flask smoke test. No DB, no auth, no external APIs. Verifies the app object initialises and core routes respond.

```python
# Author: <model>
# Date: <date>
# PURPOSE: Flask boot smoke tests — verifies app creates successfully and core
#   routes return expected status codes. Uses Flask test client with DB mocked out.
#   Zero live API calls. Runs in < 1s.
# SRP/DRY check: Pass — one concern: does the app start?

import pytest
from unittest.mock import patch, MagicMock

@pytest.fixture
def client():
    with patch('db._init_db'), patch('db.get_connection', return_value=MagicMock()):
        from server.app import app
        app.config['TESTING'] = True
        with app.test_client() as c:
            yield c

def test_root_returns_200(client):
    r = client.get('/')
    assert r.status_code == 200

def test_games_api_returns_json(client):
    r = client.get('/api/games')
    assert r.status_code == 200
    assert r.content_type.startswith('application/json')

def test_auth_status_returns_json(client):
    r = client.get('/api/auth/status')
    assert r.status_code == 200

def test_unknown_route_returns_404(client):
    r = client.get('/this/does/not/exist')
    assert r.status_code == 404
```

(Implementation may need adjustment depending on how DB init is wired at import time — developer to verify fixture scope.)

### 7. Add `tests/test_routes.py` (new)

Route-level integration tests with mocked DB. Covers the major route groups with enough depth to catch regressions on shape and status codes.

**Route groups to cover:**

| Group | Routes | Tests |
|---|---|---|
| Game listing | `GET /api/games` | returns list, handles empty, handles missing game_id |
| Game source | `GET /api/games/<id>/source` | 200 for valid, 404 for unknown |
| Session start | `POST /api/start` | 200 with valid payload, 400 missing game_id |
| Session step | `POST /api/step` | 200 valid step, 400 missing session_id, 404 unknown session |
| Session reset | `POST /api/reset` | 200 valid, 404 unknown |
| Auth status | `GET /api/auth/status` | unauthenticated returns expected shape |
| Auth logout | `POST /api/auth/logout` | returns 200 |
| LLM proxy (Anthropic) | `POST /api/llm/anthropic-proxy` | 400 on missing body, 503 or relay on API error |
| Error handling | any route | 405 on wrong method, JSON error body shape |

All tests use `app.test_client()` with DB mocked. No live API calls.

---

## What This Does NOT Change

- Game environment files (`environment_files/`)
- Agent code (`agent.py`, `agent_llm.py`, etc.)
- Server application logic (`server/app.py`, services)
- Frontend JS/CSS
- Son Pham's `REFACTOR_FILES_PY` / `REFACTOR_FILES_JS` lists — the structural header checks remain, only the hardcoded name assertions are removed
- Any scoring, harness, or scaffolding behaviour

---

## Acceptance Criteria

- [ ] `pytest tests/ -v` runs without `--ignore` flags and passes completely
- [ ] CI workflow passes on Python 3.12
- [ ] `arc-agi==0.9.6` pinned and installs cleanly
- [ ] `TestFileHeaders` passes against any file regardless of author name
- [ ] Flask smoke test passes with mocked DB
- [ ] Route tests cover all 8 route groups listed above
- [ ] No live API calls in any test
- [ ] PR description includes note to Son Pham about `CLAUDE_CODE_TOKEN` in Railway (separate from this PR's scope but worth including as a reminder)

---

## Notes for Developers

- The `conftest.py` fixture `arcade` instantiates `arc_agi.Arcade()` — this works on Python 3.12+ with `arc-agi==0.9.6`
- `test_gemini_live.py` can be preserved locally if needed; just don't commit it back
- The DB mock issue in `test_db.py` comes from `db.py:143` — `_vacuum_if_bloated()` calls `os.path.getsize(DB_PATH)` and divides by `1024*1024`. The mock needs `os.path.getsize` patched to return an integer.
- Route tests: check `server/state.py` for how global state (game_sessions, etc.) is initialised — tests may need to reset it between runs to avoid bleed
