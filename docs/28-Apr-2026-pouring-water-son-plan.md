# Pouring Water Son (ps01) — Plan

*Author: Claude Opus 4.7 (1M context) | 2026-04-28*

## Scope

Clone `pw01` (Pouring Water) into a new game `ps01` ("Pouring Water Son") with these
gameplay changes vs. the original:

1. **Smaller cup** — narrower + shorter cup interior to make precision matter.
2. **Container water is fully simulated** — the kettle's reservoir is no longer a
   simple "fill-meter" rendered against the kettle outline; it is a body of
   water made of individually simulated pixels that respond to the kettle's
   tilt and orientation (sloshes toward the spout when tilted).
3. **Container follows mouse** — the kettle pivot tracks the live mouse
   x/y position rather than being fixed. The player aims the spout by moving
   the mouse; tilting still happens by holding the click.
4. **New win condition** — water inside the cup must settle around the dotted
   target line (within ±1 row tolerance) for 20 consecutive ticks. The
   instantaneous "highest_y at target_y once settled" rule from pw01 is
   replaced with a sustained-stability check — the player has to stop pouring
   and let the surface flatten *and stay there*.
5. **Single level only** — drop pw01's "To the Brim" and "Precision" levels;
   ship only one well-tuned starting level.

Out of scope: replay backwards-compat with old `pw01` sessions (this is a new
game id, so no migration needed). Multiplayer / leaderboard plumbing is
inherited from the platform — no game-side work required.

## Architecture

**New files**:
- `environment_files/ps/00000001/metadata.json` — game manifest
  (`game_id: "ps01"`, `tags: ["live", "simulation", "physics"]`).
- `environment_files/ps/00000001/ps01.py` — `Ps01(ARCBaseGame)` subclass.

**Reuse from `pw01`**:
- `_rotate(lx, ly, tilt)` rotation helper — copied verbatim (no shared utility
  exists; both games own their own copy, consistent with the SRP/DRY note in
  pw01's header).
- Falling-sand CA + cup-surface leveling logic — copied verbatim. They are
  the right algorithms for water settling and don't change between games.
- Kettle sprite layout (body / handle / spout) — same, but the **interior
  water rendering** is replaced with a true particle simulation.

**New mechanics**:
- *Kettle particle reservoir*: instead of `kettle_water: int` (a counter),
  store `kettle_particles: list[dict]` where each dict is
  `{'lx': float, 'ly': float}` — local coords inside the kettle body. On
  every tick, simulate gravity (in world frame) on these particles by:
  1. converting each `(lx, ly)` to world `(wx, wy)` via `_rotate`;
  2. applying world gravity (try to move down by 1 pixel in world frame);
  3. converting back to local; clamping inside the kettle interior polygon.

  Whichever particle has the lowest world-y *and* is at the spout's local
  cell `(5, -1)` is eligible to be ejected as an in-flight droplet.

- *Mouse-driven pivot*: `Ps01` reads `self.action.data.get('x', None)` and
  `self.action.data.get('y', None)` on every step. If present, lerps the
  current `kettle_pivot` toward the new mouse position by a fixed
  `MOUSE_FOLLOW_SPEED` (smooth tracking, not teleport — prevents the water
  reservoir from snapping unrealistically). Falls back to the last pivot
  if no mouse data was sent (e.g. ACTION7 idle ticks without coords).

- *Sustained win check*: track `self.stable_ticks` — count of consecutive
  ticks where the cup's highest-water row is within `±1` of `target_y` AND
  no in-flight particles AND `_water_settled_stable()` is True. When this
  reaches `WIN_HOLD_TICKS = 20`, call `next_level()` (which is the final
  level, so the game wins). Reset to 0 on any tick where the condition
  fails. Render the counter as a HUD progress bar (yellow → green ramp).

**Frontend changes (one-time wiring)**:
- `static/js/human-input.js`: add a global `_humanLiveMouseX/Y` state,
  updated on `mousemove` over the canvas. In `_humanLiveTick`, if the
  held action is `6`, pass `{x, y}` as data.
- `static/js/human-game.js`: extend `humanDoAction` to take an optional
  `actionData` argument so the live tick can supply mouse coords.

These changes are general (not ps01-specific) — they let any future
live-mode click game receive continuous mouse position, including pw01.
The pw01 game ignores this data, so behavior there is unchanged.

## TODOs (ordered)

1. **Plan doc** ✅ (this file).
2. **`ps01.py`** — write the game module:
   - copy `pw01.py` headers + constants
   - replace fixed kettle pivot with lerp-toward-mouse update
   - add particle reservoir + tilt-driven sloshing
   - add sustained win check with `WIN_HOLD_TICKS`
   - shrink cup geometry; one level only
   - **Verify**: run smoke test that wins L1 by holding click + steady aim
     for 20+ ticks once water reaches target_y.
3. **`metadata.json`** — game_id=ps01, title="Pouring Water Son",
   tags=["live", "simulation", "physics"], default_fps=30, baseline_actions=[6, 7].
4. **JS live-mouse wiring** — modify `human-input.js` + `human-game.js`.
   - **Verify**: open `http://127.0.0.1:5556` in Chromium, start ps01 in
     live mode, move mouse on canvas, confirm kettle pivot follows.
5. **Smoke test playthrough** — Python + Playwright pass (per CLAUDE.md
   "UI changes must be verified in a real browser" rule).
6. **Documentation** — `CHANGELOG.md` entry.

## Docs / Changelog touchpoints

- `CHANGELOG.md` — new "Added" entry under a fresh version bump describing
  the new game and the live-mouse infrastructure.
- No README updates needed (game list is auto-built from `/api/games`).
- No CLAUDE.md updates needed (file-header / changelog / smoke-test rules
  already cover new games).
