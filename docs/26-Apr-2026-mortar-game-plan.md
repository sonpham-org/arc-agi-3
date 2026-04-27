# Mortar — New Game Plan

**Author:** Claude Opus 4.7 (1M context)
**Date:** 2026-04-26
**Game ID:** `mt01`
**Directory:** `environment_files/mt/00000001/`
**Title:** Mortar

---

## Scope

### In scope
- New turn-based (non-live) game where the player walks to a mortar
  emplacement, mounts it, dials in an angle and a force, and fires a
  shell at a target. The shell's flight path is hidden — the player
  never sees the trajectory. Only the impact crater is shown briefly,
  followed by feedback from a companion who says "CLOSER", "FURTHER",
  "SAME", or "HIT!" relative to the previous shot.
- Two operating modes inside one game:
  1. **Walking mode** — player is a 3×3 sprite, moves with ACTION1–4,
     presses ACTION5 (Z) to interact with the mortar when adjacent.
  2. **Mortar mode** — entered after pressing Z next to the mortar.
     ACTION1/2 = angle ±5°, ACTION3/4 = force ∓1, ACTION5 = FIRE!
     ACTION7 (X) exits mortar mode back to walking.
- Deterministic projectile physics: shell launched at chosen angle/force,
  integrated with a fixed-step ballistic loop until it hits ground
  level. No wind, no RNG, no fluid sim — just `vy += g; x += vx; y += vy`.
- Companion sprite (3×3, blue) standing next to the mortar — shows a
  speech-bubble indicator above its head with the most recent feedback
  symbol (up-arrow / down-arrow / equals / star).
- 3 levels of progressive difficulty:
  1. **Open Field** — target visible on a flat field, mid-range.
  2. **Over the Hill** — a hill blocks line-of-sight to the target.
  3. **Beyond the Mountain** — a tall mountain hides the target;
     player must rely entirely on companion feedback.
- Win condition (per level): impact within 1 grid cell of the target.
- Lose condition: ammo runs out (8 shells per level).
- ARC-3 palette only. 64×64 grid. Fully deterministic.
- Mandatory smoke test that wins all 3 levels via scripted action sequence.
- Mandatory browser test via Playwright — walk, mount, dial, fire,
  confirm impact + companion feedback render correctly.
- Metadata, server visibility, CHANGELOG entry, plan doc, file headers.

### Out of scope
- Live mode (no ACTION7 idle ticks; this is a discrete-input game).
- Wind / weather / variable gravity.
- Splash damage or area-of-effect targets — single point target only.
- Target moves between shots — target is stationary across the whole level.
- Multiple mortars / multiple targets in one level.
- Mouse / ACTION6 input.

---

## Architecture

### Files touched / created
| Path | Action | Why |
|------|--------|-----|
| `environment_files/mt/00000001/mt01.py` | **NEW** | Game class `Mt01`, walking, mortar mode, ballistics, display. |
| `environment_files/mt/00000001/metadata.json` | **NEW** | `game_id: "mt01"`, `tags: []`, `baseline_actions: [1,2,3,4,5,7]`, `default_fps: 10`. |
| `CHANGELOG.md` | **EDIT** | New `## [1.19.0]` entry under `### Added`. |
| `docs/26-Apr-2026-mortar-game-plan.md` | **NEW** | This plan. |

No server-side code changes. `HIDDEN_GAMES` is empty; new prefix `mt` is
unused (closest existing prefixes are `mr`/`m0r0`, both different
games). Pyodide loader picks games up by directory + class name.

### Reused infrastructure
- `arcengine.ARCBaseGame`, `Camera`, `Level`, `RenderableUserDisplay`
  (same imports as `ab01`, `pw01`, `sn02`, `pi01`).
- Discrete-input pattern from `ab01.py` — `aid = self.action.id.value`,
  branch on `1..7`, end every code path with `self.complete_action()`.
- Hardcoded level-data list with `Level(sprites=[], grid_size=(64,64),
  name=…, data=d)` per `ab01.py` and `pw01.py`.
- Per-level state reset in `on_set_level()` per the same reference games.

### Game state
```python
self.mode: str           # 'walk' or 'mortar'
self.player: tuple[int,int]  # (x,y) in walking mode
self.mortar_pos: tuple[int,int]  # fixed per level (anchored at base of tube)
self.companion_pos: tuple[int,int]  # fixed per level
self.target_pos: tuple[int,int]  # fixed per level
self.angle: int          # 20..80 degrees, step 5
self.force: int          # 3..12, step 1
self.ammo: int           # shells remaining (starts at 8)
self.last_distance: int | None  # |impact_x - target_x| from previous shot, None if first shot
self.last_feedback: str  # 'NONE' | 'CLOSER' | 'FURTHER' | 'SAME' | 'HIT'
self.impact: tuple[int,int] | None  # last impact for HUD flash
self.impact_ttl: int     # frames left to render impact
self.terrain: numpy.ndarray  # (GH, GW) palette indices for ground/hills (precomputed per level)
```

### Ballistics
On FIRE:
```python
g = 0.35
vx = force * cos(angle_rad)
vy = -force * sin(angle_rad)        # screen y is down → up = negative
x, y = mortar_muzzle  # (mx, my-2) approx
for _ in range(400):                # safety cap
    x += vx
    y += vy
    vy += g
    ix, iy = int(round(x)), int(round(y))
    if iy >= GH or ix < 0 or ix >= GW:
        break
    if self._is_ground(ix, iy):
        impact = (ix, iy); break
else:
    impact = None  # off-screen — count as max-distance miss
```
This is a fixed-step Euler integration — same scheme as `ab01.py:_simulate_bird()`.
Determinism comes from integer angle, integer force, integer gravity
constant (well, fixed float), and a deterministic loop count.

### Walking mode rules
- 64×64 grid. Player sprite 3×3 centered on `(player_x, player_y)`.
- Movement step: 1 cell per ACTION (snappy, no live ticks).
- Walk only on the "ground band" (rows 56..62) and only on non-ground
  (non-hill) columns. Cannot climb hills.
- Player blocked by mortar sprite — can stand directly adjacent to it.
- Press ACTION5 when player's bounding box is adjacent (8-neighbour) to
  the mortar sprite → `mode = 'mortar'`.

### Mortar mode rules
- Player sprite hidden (player is "operating" the mortar — replaced by
  a hand on the mortar's adjustment knob, optional render).
- ACTION1: `angle = min(80, angle+5)`
- ACTION2: `angle = max(20, angle-5)`
- ACTION3: `force = max(3, force-1)`
- ACTION4: `force = min(12, force+1)`
- ACTION5: FIRE → run ballistics → compute impact, set feedback → ammo -= 1
  → check win/lose
- ACTION7: `mode = 'walk'`, restore player sprite next to mortar

### Companion feedback
On each FIRE:
1. Compute `dx = abs(impact_x - target_x)` if impact exists, else `dx = 9999`.
2. Hit: `dx <= 1 AND abs(impact_y - target_y) <= 2` → `feedback = 'HIT'`,
   call `self.next_level()`.
3. Else if `last_distance is None` → `feedback = 'FIRE'` (first shot).
4. Else if `dx < last_distance` → `feedback = 'CLOSER'`.
5. Else if `dx > last_distance` → `feedback = 'FURTHER'`.
6. Else → `feedback = 'SAME'`.
7. `last_distance = dx`.

Feedback rendered as:
- A 5×5 speech-bubble above the companion's head, drawn each frame.
- Symbol inside bubble:
  - `CLOSER`: green up-arrow (▲)
  - `FURTHER`: red down-arrow (▼)
  - `SAME`: yellow horizontal bar (=)
  - `FIRE`: white dot (no comparison yet)
  - `HIT`: 5-pointed gold star
  - `NONE` (before first shot): empty bubble

### Display layout
- **HUD top 5 rows** (rows 0..4):
  - `ANG` numeric bar: row 1, x=2..32, lit cells = (angle-20)/2 (max 30 cells for angle 20..80).
  - `FRC` numeric bar: row 3, x=2..14, lit cells = force-2 (max 10 cells).
  - Ammo: row 1, x=50..63 — N red squares, one per shell remaining.
  - Mode indicator: row 3, x=50..63 — 'W' or 'M' rendered as 3×3 sprite.
- **Sky** (rows 5..54): black.
- **Terrain** (rows 55..63 baseline): hills/mountains rendered as palette
  indices precomputed in `self.terrain`.
- **Player**: 3×3 yellow square with white head pixel (when in walk mode).
- **Mortar**: 5×4 dark-gray base + a 1-pixel tube angled at `self.angle`
  (rotates with the angle so the player can tell roughly where they are aiming).
- **Companion**: 3×3 light-blue body with a smaller white pixel for face.
- **Target**: 3×6 red flag — pole + flag triangle.
- **Impact flash**: 3×3 orange + red ring at `self.impact` for 8 ticks
  after firing.
- **Speech bubble**: 5×5 box above companion's head, palette-indexed so
  the symbol stands out.

### Determinism
- No `random` / `np.random` — verified by `grep -n random mt01.py`
  before committing.
- All level data hardcoded.
- Trajectory uses `math.cos / sin` with integer angle in degrees and
  integer force — fully deterministic.
- Terrain rasterised at `on_set_level()` from constant lists.

### Levels

| Lvl | Name | Mortar pos | Target pos | Terrain notes |
|-----|------|-----------|-----------|---------------|
| 1 | Open Field | x=10, y=60 | x=42, y=62 | Flat ground row 60..63. |
| 2 | Over the Hill | x=8, y=60 | x=50, y=62 | Hill bump 8 cells tall at x=24..32 — blocks low-angle shots. |
| 3 | Beyond the Mountain | x=8, y=60 | x=55, y=62 | Tall 18-cell mountain at x=20..38 — target completely hidden behind it; requires high arc. |

Each level is solvable by a fixed action sequence — verified in the smoke test.

---

## TODOs (ordered, with verification)

1. **Create `environment_files/mt/00000001/` + `metadata.json`.**
   - Verify: `python -c "import json; print(json.load(open('environment_files/mt/00000001/metadata.json')))"`.

2. **Implement `mt01.py` skeleton** — ARCBaseGame subclass, `Mt01` class
   name (Pyodide loader requirement), CLAUDE.md-mandatory file header.
   - Verify: `python -c "import sys; sys.path.insert(0,'environment_files/mt/00000001'); import mt01; g = mt01.Mt01(); print(g)"` runs without error.

3. **Render terrain + sprites** — write `MortarDisplay.render_interface()`
   that draws sky, hills/mountain, mortar, companion, target, player.
   - Verify: snapshot one frame to a numpy array, eyeball palette indices
     in a quick `print` of `frame[55:64, :]` to confirm terrain shape.

4. **Walking mode movement** — implement `_step_walk()` for ACTION1–4
   moving the player by 1 cell with ground/wall collision.
   - Verify: scripted ACTION4 *N* times moves player from x=12 to x=12+N
     until they hit the mortar.

5. **Walking → mortar mode toggle** — ACTION5 next to mortar enters
   mortar mode; ACTION7 inside mortar mode returns to walking.
   - Verify: walk player adjacent to mortar, press ACTION5, assert
     `g.mode == 'mortar'`. Press ACTION7, assert `g.mode == 'walk'`.

6. **Mortar adjustments** — ACTION1/2 angle, ACTION3/4 force; clamped.
   - Verify: in mortar mode, run a sequence of ACTION1×20 then ACTION2×20
     and assert `g.angle` clamps to 80 then drops to 20.

7. **Ballistics + impact + companion feedback** — implement
   `_fire_shell()`, integration loop, distance comparison, feedback set.
   - Verify: with mortar at (10, 60) and target at (42, 62), brute-force
     find an angle/force pair that hits within 1 cell; assert that pair
     produces `feedback == 'HIT'` and `state == GameState.WIN` (after
     finishing the smoke playthrough).

8. **Win/lose** — call `self.next_level()` on hit, `self.lose()` when
   ammo hits 0 without a hit.
   - Verify: smoke test below.

9. **Mandatory smoke test (CLAUDE.md)** — script the full playthrough:
   ```bash
   source venv/bin/activate && python -c "
   import sys; sys.path.insert(0, 'environment_files/mt/00000001')
   import mt01
   g = mt01.Mt01()
   from arcengine.enums import ActionInput, GameAction
   A = lambda a: g.perform_action(ActionInput(id=a))
   # — Per-level scripted sequence: walk to mortar, press Z, dial, fire —
   ...
   print(g.state)  # must be GameState.WIN
   "
   ```
   - Verify: prints `GameState.WIN`. If a level isn't winnable with the
     scripted angle/force, retune target placement until it is.

10. **Mandatory browser test (CLAUDE.md UI rule)** — start Flask locally,
    drive `index.html` with Playwright, walk to mortar, press Z, adjust
    angle/force, fire, screenshot, assert HUD updated and impact flashed.
    - Verify: Playwright run completes without console errors and a
      post-fire screenshot shows the impact + speech bubble symbol.

11. **Pre-Push QC (CLAUDE.md):**
    ```
    python -c "from server.app import app; import db; import agent; import batch_runner; print('OK')"
    python batch_runner.py --games ls20 --concurrency 1 --max-steps 5
    ```
    Skip provider tests — no LLM keys needed.

12. **CHANGELOG.md** — add `## [1.19.0] — feat: mt01 Mortar` under `### Added`.

13. **File header** — Author/Date/PURPOSE/SRP-DRY block at top of `mt01.py`.

---

## Docs / Changelog touchpoints

- **Plan doc:** `docs/26-Apr-2026-mortar-game-plan.md` (this file).
- **Changelog:** `CHANGELOG.md` `## [1.19.0]` entry under `### Added` —
  describe the walking + mortar dual-mode design, the hidden-trajectory
  rule, and the companion-feedback mechanic.
- **No README/SESSION-LOG-API/etc. updates** — game additions are
  self-describing through `metadata.json` and don't change the streaming
  protocol or DB schema.

---

## Open question (proceeding with my best guess)

**Hit tolerance:** I'm using `|impact_x - target_x| ≤ 1` AND
`|impact_y - target_y| ≤ 2` to register a hit. That gives roughly a
3×5 hit window, which feels fair given the discrete 5° angle / integer
force adjustments. If you want a tighter / looser window, say so and
I'll change the constant.
