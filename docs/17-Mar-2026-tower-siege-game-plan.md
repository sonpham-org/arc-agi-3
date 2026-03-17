# Tower Siege (`ts01`) — Game Plan

*Author: Claude Sonnet 4.6 | 2026-03-17*

---

## Scope

**In:** New ARC-AGI-3 game `ts01` — a single-player, click-based siege puzzle with three unit types (Sapper, Scout, Soldier), five levels of increasing complexity, and progressive unit unlocks.

**Out:** Multiplayer, adaptive AI defender, procedural generation, any random elements.

---

## Concept Summary

The player controls an attacking squad trying to breach a fortified tower and reach its core cell. The tower is defended by deterministic walls, timed gates, chasm gaps, and scripted guard patrols. One action per turn (move OR use tool). Win: any unit steps on the tower core. Lose: turn limit exceeded or all living units eliminated.

---

## Architecture

| Component | Location | Notes |
|-----------|----------|-------|
| Game file | `environment_files/ts/00000001/ts01.py` | New file |
| Metadata | `environment_files/ts/00000001/metadata.json` | New file |
| Class | `Ts01(ARCBaseGame)` | PascalCase from game_id |
| Controls | `available_actions = [6]` | Click-only (ACTION6) |
| Canvas | 64×64 px | Standard ARC canvas |
| Grid | 20×20 logical cells, 2 px/cell | Centered: GRID_X=12, GRID_Y=12 |

No changes to server, frontend, or any existing files — pure new game addition.

---

## ARC3 Colour Assignments

| Role | Palette Index | Colour Name | Hex |
|------|--------------|-------------|-----|
| Floor | 4 | VeryDarkGray | `#333333` |
| Tower wall (solid) | 3 | DarkGray | `#666666` |
| Tower core (target) | 11 | Yellow | `#FFDC00` |
| Breachable wall | 2 | Gray | `#999999` |
| Gate (closed) | 13 | Maroon | `#921231` |
| Gate (open) | 14 | Green | `#4FCC30` |
| Gap (chasm/water) | 10 | LightBlue | `#88D8F1` |
| Guard | 8 | Red | `#F93C31` |
| Sapper unit | 12 | Orange | `#FF851B` |
| Scout unit | 9 | Blue | `#1E93FF` |
| Soldier unit | 14 | Green | `#4FCC30` |
| Selected unit highlight | 7 | LightMagenta | `#FF7BCC` |
| Pending bomb marker | 6 | Magenta | `#E53AA3` |
| Background | 0 | White | `#FFFFFF` |
| HUD text/border | 5 | Black | `#000000` |
| Frozen overlay | 1 | LightGray | `#CCCCCC` |

> Note: Soldier and Gate-open share Green (14). They are never adjacent in the same level and context makes them unambiguous.

---

## Unit Types

| Unit | Colour | Tool | Tool rule | Movement |
|------|--------|------|-----------|----------|
| Sapper | Orange (12) | Bomb | Click adjacent wall → wall removed at START of next turn (1-turn delay). One bomb per level. | 1 cell cardinal |
| Scout | Blue (9) | Grapple | Click a gap cell within 1 cell → Scout lands on far side. One grapple per level. | 1–2 cells cardinal (straight line, path must be clear) |
| Soldier | Green (14) | Contact-kill (auto) | Moving onto a guard cell removes the guard; Soldier frozen for 1 turn afterward. | 1 cell cardinal |

**Scout movement clarification:** Scout can move 1 or 2 cells in a straight cardinal direction in one click. Intermediate cell must be floor (not wall/gap/guard). Click destination to move.

---

## Click State Machine

```
IDLE
  ├─ click own unit (alive, not frozen) → UNIT_SELECTED (highlight unit)
  └─ click anything else → no-op

UNIT_SELECTED
  ├─ click same unit → back to IDLE (deselect)
  ├─ click valid move destination → MOVE (consume turn)
  ├─ click valid tool target → USE_TOOL (consume turn)
  └─ click different own unit → select that unit instead
```

Each turn: player takes exactly one action (move or tool use). After action → advance turn counter → move guards → tick gate → tick pending bombs → check win/lose.

---

## Turn Sequence (each step)

1. Player clicks → state machine resolves action
2. If action valid: execute unit action
3. Tick pending bombs (decrement delay; if 0, remove wall)
4. Move guards one step along their fixed patrol path
5. After guard movement: check collisions with units
   - Guard lands on Sapper/Scout → unit eliminated
   - Guard lands on Soldier → guard eliminated, Soldier frozen 1 turn
6. Increment turn counter
7. Check win: any unit on tower core cell → win
8. Check lose: turn counter > turn limit OR no alive units
9. `complete_action()`

---

## Level Designs (20×20 grid, origin at top-left)

Tower position is constant across all levels: outer walls at rows 3–7, cols 7–12; tower core (target) at **(10, 5)** — inside the north section of the tower.

### Level 1 — "The Breach" (Sapper only)

**Goal:** Teach bomb delay. One wall blocks direct path.

```
Layout (rows 0–19, cols 0–19):
Row 3:  . . . . . . . W W W W W W . . . . . . .
Row 4:  . . . . . . . W . . . . W . . . . . . .
Row 5:  . . . . . . . W . . T . W . . . . . . .  ← T = tower core (10,5)
Row 6:  . . . . . . . W . . . . W . . . . . . .
Row 7:  . . . . . . . W W B W W W . . . . . . .  ← B = breachable wall (10,7)
Rows 8–18: open floor
Row 18: . . . . . . . . . . S . . . . . . . . .  ← Sapper starts (10,18)
```

- `W` = solid tower wall (impassable, indestructible)
- `B` = breachable wall (Gray, bombable by Sapper)
- `T` = tower core cell (Yellow, target)
- Turn limit: **14**
- Minimum solution: 7 moves + 1 bomb = 8 turns

### Level 2 — "Timed Gate" (Sapper + Scout)

**Goal:** Teach gate timing (Scout) and two-unit coordination (Sapper on left path, Scout on right).

```
Row 3:  . . . . W W W W W W W W W W W . . . . .   ← top wall
Row 5:  . . . . W . T . . . . . . . W . . . . .   ← tower core (6,5)
Row 7:  . . . . W B W G W . . . . . W . . . . .   ← B=breachable(5,7), G=gate(7,7)
Row 8:  . . . . . . . ~ . . . . . . . . . . . .   ← ~ = gap cell (7,8)
Rows 9–18: open
Row 18: . S . . . . . . . . . . . . c . . . . .   ← Sapper(1,18), Scout(14,18)
```

- Gate at (7,7): closed on turns 1–2, open on turn 3, closed 4–5, open 6, ...  (period 3, open 1 of every 3)
- Gap at (7,8): Scout must grapple from (7,9) to (7,7) — but gate must be open to land
- Sapper bombs left breachable wall at (5,7)
- Both paths lead to same tower interior
- Turn limit: **20**

### Level 3 — "The Guard" (Sapper + Scout + Soldier)

**Goal:** Teach guard patrol and contact-kill (Soldier). Guard patrols a 4-cell loop around the south approach.

```
Guard patrol loop: (10,10)→(10,11)→(10,12)→(10,11)→(10,10) (back-and-forth on col 10)
Wall at (10,9): breachable, blocks direct approach
Gate at (8,7): opens every 4 turns (Scout route, left side)
Gap at (13,10): Scout grapple option (right side)

Starts:
  Sapper  → (5, 17)
  Scout   → (10, 17)
  Soldier → (15, 17)
```

- Turn limit: **24**
- Can solve by: Soldier kills guard (timing), Sapper bombs wall, march through; OR use Scout to grapple right and avoid guard

### Level 4 — "Full Assault" (all three)

**Goal:** Require all three units simultaneously. Two guards, one gate, one gap, one breachable wall.

```
Guard A: patrols east corridor (cols 13–15, row 10), back-and-forth
Guard B: patrols south gate approach (rows 12–14, col 10), back-and-forth
Gate at (10,7): period 5, open on turns 5,10,15,...
Gap at (6,10): Scout must grapple
Breachable wall at (10,8)

Starts:
  Sapper  → (3, 17)
  Scout   → (10, 17)
  Soldier → (16, 17)
```

- Intended solution: Scout grapples left and enters via side; Sapper bombs south wall while Soldier engages Guard B; Scout wins by reaching core from west
- Turn limit: **28**

### Level 5 — "The Gauntlet" (all three, tight budget)

**Goal:** Same configuration as Level 4 but turn limit halved — forces efficient ordering.

- Same layout as Level 4 (identical guard routes, gate, gap, wall)
- Turn limit: **18** (forces near-optimal play)
- This is the AI difficulty spike

---

## Game State (Python)

```python
self.units = [
    # always present but marked 'locked' until unlocked at this level
    {'type': 'sapper',  'x': 0, 'y': 0, 'alive': True, 'frozen': 0, 'bomb_ready': True, 'locked': False},
    {'type': 'scout',   'x': 0, 'y': 0, 'alive': True, 'frozen': 0, 'grapple_ready': True, 'locked': True},
    {'type': 'soldier', 'x': 0, 'y': 0, 'alive': True, 'frozen': 0, 'locked': True},
]
self.selected_idx   = None          # index into self.units, or None
self.walls          = set()         # (x, y) solid indestructible tower walls
self.breach_walls   = set()         # (x, y) bombable walls (Gray)
self.pending_bombs  = {}            # (x, y) → turns_until_removal (1 = removes this end-of-turn)
self.gate           = None          # {'x','y','period','open_on'} or None
self.gaps           = set()         # (x, y) impassable without grapple
self.guards         = []            # [{'x','y','path':[(x,y)...],'path_idx':int,'dir':1}]
self.tower_core     = (10, 5)       # win target cell
self.turn           = 0
self.turn_limit     = 14            # set per level in on_set_level
```

---

## Rendering Layout (64×64 canvas)

```
 0,0 ┌──────────────────────────────────────────────────────────────────┐ 63,0
     │  HUD bar (top 10px): level dots, turn counter, unit status icons │
10,10│  ┌────────────────────────────────────────────────┐              │
     │  │  20×20 grid at CELL=2px  (40×40px area)        │              │
     │  │  GRID_X=12, GRID_Y=12                          │              │
     │  └────────────────────────────────────────────────┘              │
     │  (right margin: 12px — unit legend: colour dot + label)          │
 0,63└──────────────────────────────────────────────────────────────────┘63,63
```

HUD top bar shows: level number (dots), `T:XX` turn counter, unit status (colour dot = alive, gray dot = dead/locked).

---

## File Header (required)

```python
# Author: Claude Sonnet 4.6
# Date: 2026-03-17 HH:MM
# PURPOSE: Tower Siege (ts01) — 5-level click-based siege puzzle. Player controls
#          3 unit types (Sapper/bomb, Scout/grapple, Soldier/contact-kill) that
#          unlock progressively. Must breach a fortified tower within a turn limit.
#          Integrates with arcengine via ARCBaseGame; click-only (ACTION6).
# SRP/DRY check: Pass — no existing utility covers multi-unit click-puzzle pattern.
```

---

## TODOs (ordered)

- [ ] **1. Scaffold** — create `environment_files/ts/00000001/` directory and stub `ts01.py` with class, `__init__`, `on_set_level`, `step` skeleton
- [ ] **2. Level data** — define all 5 `_LEVELS` dicts with unit starts, wall/gate/gap/guard positions, turn limits
- [ ] **3. `on_set_level`** — load level data into game state; unlock units per level; reset all state
- [ ] **4. Click resolver** — implement `_pixel_to_grid`, `_handle_click`, state machine (IDLE → UNIT_SELECTED → action)
- [ ] **5. Valid move/tool logic** — `_valid_moves(unit_idx)`, `_valid_tool_targets(unit_idx)`; Scout 1–2 cell movement, Sapper adjacent-wall bomb, Scout grapple over gap
- [ ] **6. Turn advance** — `_advance_turn()`: tick pending bombs, move guards, check guard collisions, increment turn
- [ ] **7. Win/lose** — check after every `_advance_turn()` call
- [ ] **8. Renderer** — `Ts01Display.render_interface()`: draw floor, walls, gaps, gate, tower core, guards, units (with selected highlight, frozen tint, bomb marker), HUD
- [ ] **9. Metadata** — write `metadata.json`
- [ ] **10. Smoke test** — run the mandatory automated playthrough that wins every level
- [ ] **11. Changelog** — add entry to `CHANGELOG.md`

---

## Verification Steps

After each TODO:
- **After #3:** `python -c "from ts01 import Ts01; g = Ts01(); print(g.level_index)"` → `0`
- **After #6:** Manual click test: select Sapper, move it, confirm turn counter increments
- **After #7:** Drive Sapper to tower core → confirm `GameState.WIN`
- **After #10:** Automated smoke test wins all 5 levels from a script using `perform_action(ActionInput(id=GameAction.ACTION6, data={'x':..., 'y':...}))`

---

## Docs / Changelog

- `CHANGELOG.md` entry required: new game `ts01` Tower Siege with 5 levels, 3 unit types, progressive unlocks
- No other docs require updating (game appears automatically in game list via `server/state.py` scan)

---

## Open Questions (resolved)

| Question | Decision |
|----------|----------|
| Controls | Click-only (ACTION6) |
| Unit count | 3 (Sapper, Scout, Soldier) |
| Unit unlock | Progressive (Sapper L1, +Scout L2, +Soldier L3) |
| Attacker tools | Yes: bomb (delay), grapple (one-use), contact-kill (auto) |
| Guard behaviour on Sapper/Scout contact | Unit eliminated |
| Turn structure | One action per turn (move OR tool), then world advances |
