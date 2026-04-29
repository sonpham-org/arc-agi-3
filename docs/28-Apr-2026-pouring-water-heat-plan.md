# Pouring Water — Heat Mechanic & New Levels (v2)

**Author:** Claude Opus 4.7 (1M context)
**Date:** 2026-04-28
**Game ID:** `pw01`
**Version:** `00000001` → `00000002` (per CLAUDE.md game-versioning rule — code change requires version bump)

---

## Scope

### In
- Per-pixel water temperature (integer °C, 0..100) on all water — droplets, settled water, and the kettle reservoir.
- Heat / cold source tiles placed in level data; rendered as a static visual layer (red for fire, light-blue/white for cold).
- State transitions:
  - `temp >= 100` → water evaporates (pixel removed; spawns one smoke particle).
  - `temp <= 0` → water freezes into a solid ice block (acts as obstacle, also chills neighbours).
  - `temp >= 50` → water periodically emits smoke (rises 1 cell every N ticks, fades after age cap).
- Three new levels (4, 5, 6) that *require* the heat mechanic to win, plus existing levels 1–3 unchanged (still solvable as before — heat sources are absent so the new logic is a no-op).
- New version directory `environment_files/pw/00000002/`. Old `00000001/` left intact so existing replays keep working.
- Updated smoke test that wins all 6 levels.
- CHANGELOG entry, plan doc, file headers, metadata bump.

### Out
- Heat propagation through *air* (heat only transfers between adjacent water/ice/source cells — keeps the sim O(N) not O(grid²)).
- Steam physics. Smoke is a cosmetic upward-drifting marker, not a fluid.
- Per-source variable strength. Fire = +heat_rate per tick to adjacent water; ice/cold = −cold_rate. Single number per source type per level.
- New actions. Same ACT6 / ACT7 click-and-release as v1.
- Changes to levels 1–3.

---

## Architecture

### Files touched
| Path | Action | Why |
|------|--------|-----|
| `environment_files/pw/00000002/pw01.py` | **NEW** (copied from `00000001/pw01.py`, modified) | Heat mechanic + new levels. Old version left untouched per versioning rule. |
| `environment_files/pw/00000002/metadata.json` | **NEW** | `date_downloaded: "2026-04-28"`, same `game_id: "pw01"`, same tags. |
| `CHANGELOG.md` | **EDIT** | New `## [1.23.0]` entry. |
| `docs/28-Apr-2026-pouring-water-heat-plan.md` | **NEW** | This plan. |

The Pyodide loader picks the highest-numbered version directory automatically — no server changes needed.

### State additions (on `Pw01`)
- `self.water_temp: dict[(x,y), int]` — temperature for each settled water pixel.
- `self.particles[i]['temp']: int` — temperature for each in-flight droplet (carried into `water_temp` on landing).
- `self.ice: set[(x,y)]` — frozen cells. Treated as solid by `_is_solid`.
- `self.smoke: list[dict]` — `{'x','y','age'}` upward-drifting smoke pixels.
- `self.heat_sources: list[(x0,y0,x1,y1)]` and `self.cold_sources: list[(x0,y0,x1,y1)]` — populated from level data.

### Level-data additions (per LEVEL_DATA dict)
- `heat_sources: list[(x0,y0,x1,y1)]` — fire tiles. Default `[]`.
- `cold_sources: list[(x0,y0,x1,y1)]` — cold tiles. Default `[]`.
- `kettle_temp: int` — initial temperature of every droplet emitted from the kettle. Default `25` (room temp).
- `ambient_temp: int` — temperature water drifts toward each tick when not adjacent to a source. Default `25`.

### Heat update (called once per `step()`, after CA)
```
HEAT_PER_TICK = 4   # adjacency to fire raises temp by this much / tick
COLD_PER_TICK = 4   # adjacency to ice/cold raises temp by negative this / tick
DRIFT_PER_TICK = 1  # otherwise water drifts toward ambient by this much / tick

for each settled water pixel (x,y):
    delta = 0
    if any neighbour (4-conn) is in a heat_sources rect: delta += HEAT_PER_TICK
    if any neighbour is in a cold_sources rect or in self.ice: delta -= COLD_PER_TICK
    if delta == 0:
        if temp > ambient: temp -= DRIFT_PER_TICK
        elif temp < ambient: temp += DRIFT_PER_TICK
    else:
        temp += delta
    clamp 0..120  (allow brief overshoot before evaporation)

then transitions:
    temp >= 100 → remove pixel; emit smoke at (x,y).
    temp <= 0   → remove pixel; add to self.ice; remove from water_temp.
    temp >= 50 and (tick % SMOKE_PERIOD == 0) → emit one smoke particle at (x, y-1).

particles in flight: same logic, but neighbour test uses int(fx),int(fy) and they don't freeze mid-air (they freeze on landing if temp<=0 at landing time).
```

### Smoke
- Each smoke particle rises 1 row every 2 ticks; fades after `age >= 12` or off-screen.
- Renders as `C_LGRAY` (1) — visible against black background, distinct from water blue.
- Cosmetic only — not part of physics, doesn't block water.

### Ice (with gradual melting)
- Treated as solid by `_is_solid` (so settled water stacks on top of it).
- Acts as a cold source itself (chills adjacent water).
- Each ice cell carries its own temperature (`self.ice_temp: dict[(x,y), int]`, starts at `FREEZE_TEMP = 0`).
- Each tick:
  - Adjacent (4-conn) to a heat-source rect → ice temp += `HEAT_PER_TICK`.
  - Otherwise → ice temp drifts back toward `ICE_BASELINE = -10` by `DRIFT_PER_TICK` (so ice in a freezer stays frozen).
- When ice temp >= `MELT_THRESHOLD = 1` → cell converts back to water at that temp (added to `water_temp`, removed from `ice` / `ice_temp`).
- Cleared on `on_set_level` reset.

### Rendering
- Heat sources: `C_RED` (8) (fire) — drawn as a static layer below the water.
- Cold sources: `C_LBLUE` (10) — drawn statically.
- Ice: `C_WHITE` (0).
- Hot water (>=50): tint `C_LMAGENTA` (7) instead of `C_BLUE` (9) — visual cue that it's about to smoke.
- Boiling water (>=90): tint `C_RED` (8) — about to evaporate.
- Smoke: `C_LGRAY` (1).
- Existing kettle / cup / HUD rendering unchanged.

### New levels (4–6)

| Lvl | Name | Mechanic | Layout |
|-----|------|----------|--------|
| 4 | **Boiling Cup** | Fire under cup floor — water heats up after landing. Win = fill to target before evaporation drops you below the line. | Cup (28..58, 42..60), 1-row fire strip just under the cup floor (29..57, 61..61). `kettle_temp=25`, `ambient_temp=25`. Target row 51. Lots of kettle volume so the player can outrun evaporation. |
| 5 | **Frozen Reach** | Cold tiles around the cup walls. Water cools and freezes if you pour too slowly. | Cup (28..58, 42..60), cold strips along outside of left/right walls. `kettle_temp=60` (warm pour). Target row 47. Player must keep pour rate up so settled water doesn't fall to 0. |
| 6 | **Heat Gauntlet** | Fire patch between kettle and cup — droplets pass through and heat up; if too slow, they evaporate mid-air; if too fast, they overshoot. | Fire strip in the air column the spout arc passes through (x=24..27, y=20..22). `kettle_temp=20`. The player must tilt enough to clear the fire arc-wise but not so much that target row overshoots. |

All three are deterministic. Smoke test will win each by a fixed scripted cadence.

### Determinism contract (re-confirmed)
- No RNG anywhere.
- Heat update iterates over a sorted snapshot of `water_temp.keys()` so order is stable.
- Smoke list is processed in append order.
- Ice transitions deterministic on temperature (integer arithmetic).
- Tick parity already drives CA spread; heat does not introduce new tick-dependent randomness.

---

## TODOs (ordered, with verification)

1. **Copy `00000001/pw01.py` → `00000002/pw01.py`**, update file header date and PURPOSE block to mention heat mechanic.
   - Verify: `diff` shows only header + new fields stub at this stage.

2. **Add `self.water_temp`, `self.ice`, `self.smoke`, `self.heat_sources`, `self.cold_sources`** to `__init__` and `on_set_level`.
   - Verify: `python -c "import pw01; g = pw01.Pw01(); print(g.water_temp, g.ice, g.smoke)"` shows empty containers.

3. **Add `'temp'` field to particles in `_emit_pour`** (init from `LEVEL_DATA[i]['kettle_temp']`).
   - Verify: emit a particle, inspect `g.particles[0]['temp']`.

4. **Modify `_step_particles`** so that landing transfers `temp` into `water_temp[(ix,iy)]`.
   - Verify: pour into cup, inspect `g.water_temp` keys/values after a few ticks.

5. **Add `_step_heat()`** that runs after `_step_water_ca`. Computes per-pixel temp, applies transitions (evaporate / freeze / smoke).
   - Verify: place fire under a stationary water pixel, run 30 ticks, confirm pixel disappears with a smoke entry; place cold neighbour, confirm freeze.

6. **Add `_step_smoke()`** — drift up, age, cull.
   - Verify: spawn smoke, run 20 ticks, list shrinks.

7. **Update `_is_solid` to treat `self.ice` as solid**, and add ice as a cold neighbour in heat update.
   - Verify: drop water on top of an ice pixel; it should rest on the ice, not fall through.

8. **Update `PourDisplay.render_interface`** — draw heat / cold sources, ice, smoke, hot/boiling water tint.
   - Verify: dump a frame at level 4 after 50 ticks, inspect frame array shows red fire under cup and yellow/red water tints when temp climbs.

9. **Add levels 4, 5, 6 to `LEVEL_DATA`**, calibrate `kettle_volume` and target rows so each is solvable by a fixed cadence.
   - Verify: smoke test (next step).

10. **Update mandatory smoke test** in `docs/28-Apr-2026-pouring-water-heat-plan.md` (this plan) and run it from the repo root:
    ```bash
    venv/Scripts/python.exe -c "
    import sys; sys.path.insert(0, 'environment_files/pw/00000002')
    import pw01
    g = pw01.Pw01()
    from arcengine.enums import ActionInput, GameAction
    click = lambda: g.perform_action(ActionInput(id=GameAction.ACTION6, data={'x':10,'y':30}))
    tick  = lambda: g.perform_action(ActionInput(id=GameAction.ACTION7))
    # ...win all 6 levels with scripted cadence...
    print(g.state)  # must be GameState.WIN
    "
    ```
    Calibrate per-level `kettle_volume`, fire/cold rect sizes, `kettle_temp`, target row until the script wins. If a level can't be won deterministically with a fixed cadence, retune.

11. **Create `00000002/metadata.json`** with `date_downloaded: "2026-04-28"`. Tags / actions unchanged.
    - Verify: `python -m json.tool < metadata.json` parses.

12. **Pre-push QC** per CLAUDE.md:
    ```
    venv/Scripts/python.exe -c "from server.app import app; import db; import agent; import batch_runner; print('OK')"
    venv/Scripts/python.exe batch_runner.py --games ls20 --concurrency 1 --max-steps 5
    ```

13. **CHANGELOG.md** — `## [1.23.0]` under Added: heat mechanic + 3 new levels for pw01 (v2).

14. **File headers** updated on every edited Python file (pw01.py).

---

## Docs / Changelog touchpoints

- Plan doc: this file.
- CHANGELOG: `## [1.23.0]` Added entry.
- No README / SESSION-LOG-API / DB schema changes.

---

## Open questions for approval

1. **Severity tuning** — initial values `HEAT_PER_TICK=4`, `COLD_PER_TICK=4`, `DRIFT_PER_TICK=1`, `SMOKE_PERIOD=4` are guesses; I'll iterate on them in the smoke-test loop until levels 4–6 are deterministically winnable. OK to proceed and tune?
2. ~~Ice as a hard solid vs. melting~~ — **resolved 2026-04-28**: ice melts gradually under heat. Each ice cell carries a temperature; adjacent fire raises it, no fire nearby drifts it back toward an ice baseline. Above `MELT_THRESHOLD` the cell converts to water. See "Ice (with gradual melting)" above.
3. ~~Levels 1–3 untouched~~ — **resolved 2026-04-28**: confirmed left as-is.

I'll wait for your approval before writing any code.
