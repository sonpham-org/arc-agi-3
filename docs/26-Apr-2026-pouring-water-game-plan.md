# Pouring Water — New Game Plan

**Author:** Claude Opus 4.7 (1M context)
**Date:** 2026-04-26
**Game ID:** `pw01`
**Directory:** `environment_files/pw/00000001/`
**Title:** Pouring Water

---

## Scope

### In scope
- New live-mode game where the player tilts a kettle to pour water into a cup until the water level reaches a dotted target line.
- Deterministic pixel-level water simulation using a single-buffered falling-sand cellular automaton (gravity + diagonal slip + horizontal spread).
- Kettle rotation 0°–60° driven by action input cadence: every tick that receives a click (ACTION6) increments tilt by +1°; every tick without a click (ACTION7) decrements tilt by −1°.
- 3 levels of progressive difficulty (cup placement / obstacles / target fill threshold).
- Win condition: water column in the cup reaches the dotted target line.
- Lose condition: kettle empties while water-in-cup is below target.
- ARC-3 palette only. 64×64 grid. No RNG. Deterministic given the same action sequence.
- Smoke test that wins all 3 levels via scripted ACT6/ACT7 sequence.
- Metadata, server visibility, CHANGELOG entry, plan doc, file headers.

### Out of scope
- True SPH / Navier-Stokes physics (overkill for 64×64; falling-sand is the established pixel idiom and is what Powder Game / Sandspiel / Noita-style sims use).
- Pressure-based water (each pixel is independent — no mass flux equations).
- Smooth (sub-pixel) kettle rotation animation. Rotation is integer degrees, kettle shape recomputed per frame from a small local sprite + rotation matrix rounded to grid.
- Multiplayer / variable kettle sizes / multiple kettles.
- Adding ACT5 / d-pad — this is click-only.

---

## Architecture

### Files touched / created
| Path | Action | Why |
|------|--------|-----|
| `environment_files/pw/00000001/pw01.py` | **NEW** | Game class `Pw01`, water sim, kettle rotation, display. |
| `environment_files/pw/00000001/metadata.json` | **NEW** | `game_id: "pw01"`, `tags: ["live","simulation","physics"]`, `baseline_actions: [6]`, `default_fps: 30`. |
| `CHANGELOG.md` | **EDIT** | New `## [1.18.0]` entry under "Added". |
| `docs/26-Apr-2026-pouring-water-game-plan.md` | **NEW** | This plan. |

No server code changes required: `HIDDEN_GAMES` is currently `[]` (per `server/state.py:39`), so the new game appears automatically in `/api/games` once the env files exist. The Pyodide loader picks games up by directory name and class name (`Pw01`).

### Reused infrastructure
- `arcengine.ARCBaseGame`, `Camera`, `Level`, `RenderableUserDisplay` (same base imports as `fr01`, `pi01`, `lb03`, `px02`).
- Live-mode tick semantics: framework auto-sends `ACTION7` (no-input tick) at `default_fps` between user clicks. Verified by reading `fr01.py` (live) and `pi01.py` (live, `tags: ["live"]`).
- Click data shape: `self.action.id.value == 6`, `self.action.data.get("x", 0)` / `.get("y", 0)` (verified in `px02.py:1291`, `sn02.py:568`).
- Step boundary: every code path in `step()` ends with `self.complete_action()`; `self.next_level()` for win, `self.lose()` for game over (verified across all reference games).

### Water simulation design (deterministic falling-sand)

**Reference algorithm:** Macuyiko's blog (cited in research) and Noita/Powder Game patterns — single-buffered, pixel-as-object gravity with diagonal slip and horizontal spread, mass-conserving by *guarding against double-update via a per-tick `moved` set*.

**State:**
- `self.water: set[tuple[int,int]]` — free water pixels in world coordinates.
- `self.kettle_water: int` — integer water units still inside the kettle. Drains by N units per tick when tilt ≥ spill threshold (rate function of tilt angle).
- `self.tilt: int` — current rotation degrees, 0..60.
- `self.tick: int` — increments every step; used for left/right alternation.

**Per-step physics (run after kettle update):**
```
moved = set()
# Bottom-up scan to let gravity propagate in a single pass
for (x, y) in sorted(self.water, key=lambda p: -p[1]):
    if (x, y) in moved: continue
    # 1. Try down
    if empty(x, y+1): water.move((x,y) → (x,y+1)); moved.add new pos; continue
    # 2. Try diagonals — alternate order each tick for symmetric spread
    order = [(-1,1),(1,1)] if (self.tick % 2 == 0) else [(1,1),(-1,1)]
    moved_flag = False
    for dx, dy in order:
        if empty(x+dx, y+dy): move; moved_flag = True; break
    if moved_flag: continue
    # 3. Sideways spread (so the cup fills flat, not in a cone)
    order2 = [(-1,0),(1,0)] if (self.tick % 2 == 0) else [(1,0),(-1,0)]
    for dx, _ in order2:
        if empty(x+dx, y): move; break
```
This is fully deterministic (no `random`), conserves mass (no destruction except the bottom-row absorbing line), and produces flat water surfaces in cups. The alternating tick parity prevents the "cluster on one side" artefact noted in the macuyiko blog.

**Spawning:** at tilt ≥ `SPILL_THRESHOLD` (25°), one pixel per tick is emitted from the kettle's spout pixel into the world; rate doubles at tilt ≥ 45°. `kettle_water` decrements by the same amount; if `kettle_water == 0`, no spawn. Spout pixel is computed from the rotated kettle outline (lowest pixel of the spout-tip group).

**Kettle rotation:** kettle is a small local sprite (~12×10 pixels) with body + handle + spout. Each tick we rotate the local pixel coordinates by `self.tilt` degrees around the kettle's pivot (bottom-centre on the world surface), round to int, and rasterise. The body fills with a "kettle water" colour up to the *world-space horizontal* surface of `kettle_water` worth of liquid (approximation: visualise as a horizontal band whose height matches remaining capacity). This is a render-only approximation — the actual reservoir is the integer counter, not pixels in the kettle.

**Cup detection:** target line is a horizontal row of dotted pixels at `cup_target_y` inside the cup interior. Win when a contiguous water column inside the cup interior reaches `y ≤ cup_target_y` (i.e. the count of water pixels in the cup interior at or below the target line ≥ `cup_target_volume`, where `cup_target_volume` = (cup_inner_width) × (cup_floor_y − cup_target_y + 1)). Approximate: simply count water pixels inside the cup interior bounding box and compare to the target volume.

**Lose:** when `self.kettle_water == 0` AND no free water remains in the air (all water has settled) AND cup volume < target.

### Action wiring
```
def step(self):
    aid = self.action.id.value
    if aid == 6:
        self.tilt = min(60, self.tilt + 1)
    else:                       # ACTION7 auto-tick or any non-click action
        self.tilt = max(0, self.tilt - 1)
    self._update_kettle_pour()  # may emit water pixels
    self._step_water()          # physics
    self._check_win_lose()
    self.complete_action()
```
Click coordinates are intentionally ignored — per the user's spec, *holding* the mouse anywhere produces the rotation. This matches the "multiple clicking action" framing in the request.

### Levels (LEVEL_DATA list of dicts, all hardcoded)

| Lvl | Name | Cup x | Cup mouth width | Target line height | Kettle volume | Notes |
|-----|------|-------|-----------------|--------------------|---------------|-------|
| 1 | First Pour | x=42 | 10 | 50% | 80 | No obstacles. Mostly straight pour. |
| 2 | The Long Reach | x=50 | 8 | 60% | 100 | Cup further from kettle — must tilt to ~40° to arc the water in. |
| 3 | Around the Wall | x=46 | 8 | 65% | 120 | A solid wall obstacle between kettle and cup forces the player to tilt steeply (≥ 50°) so water arcs over. |

Levels are progressive in tilt-skill but every level is solvable by a fixed click cadence — verified in the smoke test.

### Display
- HUD (rows 0–3): tilt readout (numeric via 0–6 light bars on a 60-pixel scale), target volume vs current volume bar.
- Background: `C_BLACK` (5).
- Floor: `C_GRAY` (2) at y=63.
- Kettle outline: `C_DKGRAY` (3); kettle water inside: `C_BLUE` (9).
- Free water pixels: `C_BLUE` (9) when falling, `C_AZURE` (10) when settled in cup interior (visual feedback that water is "captured").
- Cup: `C_DKGRAY` (3) walls.
- Dotted target line: alternating `C_YELLOW` (11) / `C_BLACK` pixels across the cup mouth.
- Obstacle wall (level 3): `C_DKGRAY` (3).

### Determinism contract
- No `random`, `np.random`, or any RNG.
- All level data is constants.
- Tick parity controls left/right alternation in spread — fully determined by `self.tick`.
- Sorting `self.water` by `-y` gives a stable scan order (ties broken by Python's stable sort on tuple).
- `kettle_water` is integer; rotation is integer degrees; rasterised kettle pixels are deterministic (`int(round(...))`).

---

## TODOs (ordered, with verification)

1. **Create `environment_files/pw/00000001/` directory** and add `metadata.json`.
   - **Verify:** `cat metadata.json | python -m json.tool` parses.

2. **Build the kettle sprite + rotation rasteriser.** Hardcode local pixel offsets for body / handle / spout. Implement `_rotate_kettle(tilt_deg) -> dict[(x,y) → color]`.
   - **Verify:** in a `python -c` snippet, render the kettle at 0°, 30°, 60° to a 64×64 numpy array and assert spout pixel position moves rightward & down as tilt increases; assert no kettle pixel lands outside the play area for any angle 0..60.

3. **Implement falling-sand water step `_step_water()`** with the mass-conserving moved-set algorithm above.
   - **Verify:** unit-style snippet — drop a 5×5 square of water above a flat floor; after enough ticks confirm it settles into a flat ~25-pixel-wide puddle, no pixels lost or duplicated.

4. **Wire pour emission `_update_kettle_pour()`** — at tilt ≥ 25°, emit 1 water pixel/tick at the rotated spout pixel; at tilt ≥ 45°, emit 2/tick. Stop when `kettle_water == 0`.
   - **Verify:** click 30 times in a row → kettle_water decreases, water pixels start appearing.

5. **Implement cup-volume check + win/lose** in `_check_win_lose()`.
   - **Verify:** smoke test — when cup interior fills past target line, `self.next_level()` fires; when kettle empties and water settles below target, `self.lose()` fires.

6. **Implement display in `KettleDisplay.render_interface()`** — HUD bar, kettle, water, cup, target line, floor, obstacles.
   - **Verify:** dump a frame to PNG via the existing arcengine path or a `numpy.save`, eyeball that all elements render at 0° and at 50°.

7. **Define `LEVEL_DATA` (3 levels)** and `on_set_level()` reset.
   - **Verify:** `g = Pw01()` → `g.level_index == 0`; after `g.next_level()` → state resets cleanly.

8. **Mandatory smoke test (per CLAUDE.md)** — write a Python snippet that wins all 3 levels using the click action system, ending in `GameState.WIN`.
   ```bash
   source venv/bin/activate && python -c "
   import sys; sys.path.insert(0, 'environment_files/pw/00000001')
   import pw01
   g = pw01.Pw01()
   from arcengine.enums import ActionInput, GameAction
   click = lambda: g.perform_action(ActionInput(id=GameAction.ACTION6, data={'x':10,'y':30}))
   tick  = lambda: g.perform_action(ActionInput(id=GameAction.ACTION7))
   # … per-level scripted cadence …
   print(g.state)  # must be GameState.WIN
   "
   ```
   - **Verify:** prints `GameState.WIN`. If any level isn't winnable with a fixed cadence, retune `kettle_water` / `cup_target_volume` for that level until it is.

9. **Run pre-push QC** (per CLAUDE.md "Pre-Push QC"):
   ```
   python -c "from server.app import app; import db; import agent; import batch_runner; print('OK')"
   python batch_runner.py --games ls20 --concurrency 1 --max-steps 5
   ```
   - Provider tests skipped — no LLM keys required for this change.

10. **Update CHANGELOG.md** with a `[1.18.0]` "Added: pw01 Pouring Water" entry.

11. **Add file headers** to `pw01.py` (Author / Date / PURPOSE / SRP-DRY) per CLAUDE.md mandatory header rule.

---

## Docs / Changelog touchpoints

- **Plan doc:** `docs/26-Apr-2026-pouring-water-game-plan.md` (this file).
- **Changelog:** `CHANGELOG.md` — `## [1.18.0] — feat: pw01 Pouring Water game` entry under `### Added`. Mention live-mode + falling-sand water sim + 3 levels.
- **No README/SESSION-LOG-API/etc. updates required** — game additions are self-describing via `metadata.json` and don't change the streaming protocol or DB schema.

---

## Open question for approval

**Click semantics confirmation:** the spec says "holding the mouse … will rotate the kettle by 1 degree" — I'm interpreting that as *every live-mode tick during which the user is holding the mouse, an ACTION6 fires, so tilt += 1 per tick of holding, and tilt -= 1 per tick of release*. At default 30 FPS, going 0 → 60° takes ~2 seconds of held click, and falls back to 0 in ~2 seconds. If you want a slower / faster tilt rate, I'll change the per-tick delta. Otherwise I'll proceed with ±1°/tick.

Sources consulted:
- [Falling Sand cellular automata — Macuyiko blog](https://blog.macuyiko.com/post/2020/an-exploration-of-cellular-automata-and-graph-based-game-systems-part-4.html)
- [Noita-style pixel sim discussion — HN](https://news.ycombinator.com/item?id=31309616)
- [GitHub: luciopaiva/water — CA water flow](https://github.com/luciopaiva/water)
