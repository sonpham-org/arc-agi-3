# Fix: Human Play sidebar is empty (prod + fresh clone) — 06-Apr-2026

## Problem

`GET /api/games` on `arc3.sonpham.net` returns `[]`. The "Play as Human" sidebar
loads, calls `_loadHumanGames()` → `fetchJSON('/api/games')`, gets an empty
array, renders an empty list, and there is no game card to click. Selecting,
starting a session, the d-pad, and the keyboard handlers are all wired
correctly — they just never get reached because no game can be picked.

### Root cause

Two commits combine to produce the empty list:

1. `779ddae` — `chore: gitignore environment_files/` removed the game source
   tree from version control. After this commit, every fresh deploy (Railway
   included) starts without an `environment_files/` directory, so
   `arc_agi.Arcade()._scan_for_environments()` finds nothing locally and every
   `EnvironmentInfo` returned by `get_environments()` has `local_dir = None`.

2. `f3ed3ed` — `fix: hide unplayable Foundation games` added
   `if e.local_dir is not None` to `list_games()` in `server/app.py:485` so
   undownloaded Foundation games would not 500 in `game_source()`. Combined
   with (1), that filter now silently drops **every** game instead of just the
   handful of remote-only Foundation entries it was meant to hide.

Verified by running `arc_agi.Arcade().get_environments()` against the
installed `arc_agi` package: 25 environments returned from the ARC Prize API,
all with `local_dir=None`. `curl -A 'Mozilla/5.0' https://arc3.sonpham.net/api/games?show_all=1`
also returns `[]`, confirming the empty list happens before the
`HIDDEN_GAMES` filter on prod.

### Why prod is broken even though Railway has a Volume

The Volume only persists files that were written into it. After 779ddae,
nothing in the deploy pipeline writes the env files, so the Volume's
`environment_files/` directory either never existed or was rotated out.
Either way, the running prod server has no local game sources.

## Scope

**In:**
- Restore the human-play game list on prod and fresh clones without
  re-checking `environment_files/` into git.
- Make `/api/start` and `/api/games/<id>/source` resilient to undownloaded
  games: download on demand, never crash.
- Add a `CHANGELOG.md` entry.
- File headers updated on every Python file we touch.

**Out:**
- No frontend changes. The bug is entirely server-side; the human-play JS
  works the moment `/api/games` returns a non-empty list.
- No changes to gitignore. Env files stay out of git — we materialize them at
  runtime.
- No changes to the Railway Volume layout, deploy pipeline, or
  `requirements.txt`. We use the `arc_agi` API that is already installed.
- No new endpoints. We extend three existing handlers in place.
- No changes to `HIDDEN_GAMES` semantics or the prod-mode filter.
- No retry/backoff frameworks; we trust the `arc_agi` client's own behavior.

## Architecture

All changes live in `server/app.py` and `server/helpers.py`. The backbone is
the existing `arc_agi.Arcade.make(game_id)` call, which downloads a game into
`environment_files/<id>/<version>/` and returns a wrapper. We already use
`arc.make` indirectly via `game_service.start_game`; we just need to call it
in two more places and bootstrap the cache once.

### Three coordinated changes

**1. `server/helpers.py` — new `ensure_game_local(game_id)` helper.**
Calls `get_arcade().make(game_id)`. Returns the resulting `EnvironmentInfo`
(after re-querying `get_environments()` so `local_dir` is populated), or
`None` if the download failed. Wrapped in a per-game `threading.Lock` from a
module-level `dict` so two concurrent requests for the same game don't both
try to download. Logs a single info line on download. This is the only new
public surface.

**2. `server/app.py:list_games()` — bootstrap-on-empty.**
After the existing dedup loop, before the `local_dir is not None` filter:

```python
unplayable = [e for e in seen.values() if e.local_dir is None]
if unplayable and len(unplayable) == len(seen):
    # Cold start: no games are local. Bootstrap them.
    for e in unplayable:
        ensure_game_local(e.game_id)
    # Rescan and rebuild `seen` from the freshly-populated cache.
    seen = _dedup_environments(get_arcade().get_environments())
```

The bootstrap only fires when **every** environment is remote-only — i.e. the
cold-start case we just diagnosed. In normal operation (some games local,
some not), behavior is unchanged: remote-only Foundation games are still
filtered out, exactly as `f3ed3ed` intended.

To keep the change reviewable, the existing dedup loop in `list_games()` is
extracted into a private `_dedup_environments(envs)` helper so we can call it
twice without copy-pasting 25 lines.

The bootstrap is synchronous but only runs **once per process** — after the
first call, every env has `local_dir` set and the conditional is skipped.
First-request latency is the cost of downloading ~25 small game files (a few
seconds at most). No background threads, no startup hooks: we keep the
existing lazy `get_arcade()` pattern.

**3. `server/app.py:game_source()` — download-or-404, never 500.**
Currently `game_source()` calls `Path(local_dir)` and crashes when
`local_dir is None`. Replace the unconditional path lookup with:

```python
env = _find_env_by_id(arc, game_id)
if env is None:
    return jsonify({"error": "unknown game"}), 404
if env.local_dir is None:
    env = ensure_game_local(game_id)
if env is None or env.local_dir is None:
    return jsonify({"error": "game source not available"}), 404
```

Same hardening, smaller blast radius, applied to `/api/start` indirectly:
`game_service.start_game` already uses `arc.make`, which downloads on
demand, but it raises on failure. We catch that in the existing
`@app.route("/api/start")` handler and return `{"error": "..."}` JSON
instead of letting Flask render a 500 HTML page.

### What is reused

- `arc_agi.Arcade.make` — already imported, already used by
  `game_service.start_game`. We do not add a new download path.
- `get_arcade()` lazy singleton in `server/helpers.py` — we extend it, not
  replace it.
- `_env_date`, `_is_newer_env` already handle `local_dir=None` (hardened in
  `f3ed3ed`), so the rescan-after-bootstrap dedup pass needs no changes.

### What is *not* changed

- `bot_protection`, `turnstile_required` — orthogonal.
- `HIDDEN_GAMES` filter — still runs after bootstrap; prod-hidden games stay
  hidden.
- Frontend (`human.js`, `human-session.js`, etc.) — the bug is server-side.
- `environment_files/` gitignore — env files stay out of git, materialized
  at runtime. No deploy pipeline change.

## TODOs

Each TODO has an explicit verification step. Verification is run against the
local server (`server.app:app`) using the venv at `/tmp/arc3venv` that I
already set up during investigation.

1. **Extract `_dedup_environments(envs)` helper in `server/app.py`.**
   Pure refactor of the existing dedup loop in `list_games()`. No behavior
   change.
   - *Verify:* `python -c "from server.app import app; print('OK')"` and run
     `curl http://127.0.0.1:5099/api/games`. Result must be unchanged from the
     pre-refactor baseline (still `[]` at this point — bootstrap not yet
     wired).

2. **Add `ensure_game_local(game_id)` to `server/helpers.py`.**
   Includes per-game lock dict and module-level lock for the dict itself.
   File header updated.
   - *Verify:* `python -c "from server.helpers import ensure_game_local; e = ensure_game_local('ls20'); print(e.game_id, e.local_dir)"`. Must
     print `ls20-... environment_files/.../...` and the directory must exist
     on disk afterwards.

3. **Wire bootstrap-on-empty into `list_games()` in `server/app.py`.**
   Only runs when **all** envs are remote-only. File header updated.
   - *Verify:*
     a. `rm -rf environment_files` (cold start).
     b. `curl http://127.0.0.1:5099/api/games | python -m json.tool | head`.
        Must return at least one game with a non-null `game_id`.
     c. Second request returns instantly (no re-download — cache populated).
     d. `ls environment_files/` shows the freshly-downloaded game dirs.

4. **Harden `game_source()` in `server/app.py`.**
   Use `ensure_game_local` for missing `local_dir`; return JSON 404 instead
   of 500.
   - *Verify:* `curl -i http://127.0.0.1:5099/api/games/zz99/source` returns
     HTTP 404 with `Content-Type: application/json` and a JSON error body —
     not an HTML 500 page.

5. **Harden `/api/start` error path in `server/app.py`.**
   Wrap the existing `game_service.start_game` call so download/network
   failures return `{"error": "..."}` JSON, not a 500.
   - *Verify:* `curl -X POST -H 'Content-Type: application/json' -d '{"game_id":"zz99"}' http://127.0.0.1:5099/api/start` returns JSON with an
     `error` key, not HTML.

6. **End-to-end smoke: human play actually works on a fresh clone.**
   - *Verify:*
     a. Stop server, `rm -rf environment_files`, restart server.
     b. `curl http://127.0.0.1:5099/api/games` returns ≥1 game.
     c. Pick the first `game_id` from the response, hit
        `curl -X POST -H 'Content-Type: application/json' -d '{"game_id":"<id>"}' http://127.0.0.1:5099/api/start`.
        Must return JSON with `session_id`, `grid`, `available_actions`.
     d. Hit `/api/step` with that `session_id` and an action. Must return a
        new `grid`.
   - This is the real test — if these three calls succeed, the human-play UI
     can drive a full session.

7. **Update `CHANGELOG.md`** with a `[1.16.1]` entry under **Fixed** describing
   the symptom, the root cause (commits 779ddae + f3ed3ed interaction), and
   the fix (bootstrap-on-empty + handler hardening).

## Docs / Changelog touchpoints

- `CHANGELOG.md` — new `[1.16.1]` entry, *Fixed* section. Required by
  CLAUDE.md "Required: Changelog".
- `docs/06-Apr-2026-fix-human-play-empty-game-list-plan.md` — this file.
- `README.md` — **no change**. The fix is self-bootstrapping; users do not
  need new instructions.
- File headers on `server/app.py` and `server/helpers.py` — updated to today's
  date and current model name per CLAUDE.md "Required: File Headers".

## Risks and rollback

- **Cold-start latency.** First `/api/games` after a deploy will block while
  the arcade downloads ~25 games. If this exceeds Railway's request timeout,
  users get a 502 on first hit and a working list on retry. Acceptable
  because (a) it only happens once per process, (b) the alternative is the
  current state where it never works at all. If it turns out to be too slow
  in practice, the followup is to move the bootstrap into a background
  thread spawned at app startup — but that is a separate change with its own
  plan doc.
- **Download failure.** If `arc.make` raises for one game, we log and skip
  that game. The other 24 still populate. We do **not** retry — the
  `arc_agi` client owns retry semantics.
- **Rollback.** Revert the `server/app.py` and `server/helpers.py` diffs.
  Nothing is persisted to the DB, so rollback is a clean code revert.

## Out of scope (followups, not part of this PR)

- Background-thread bootstrap at app startup (only if cold-start latency
  proves to be a real problem).
- Shipping `environment_files/` outside git via Git LFS or a Railway build
  step — the runtime bootstrap makes this unnecessary.
- Frontend "Loading games..." UX improvements during the cold-start window.
