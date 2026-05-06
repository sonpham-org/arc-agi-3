# Demon Lord (`dl01`) — Game Plan

*Author: Claude Opus 4.7 | 2026-05-06*

---

## Scope

**In:** New ARC-AGI-3 game `dl01` — a single-player, d-pad sokoban-RPG. Player pushes light crystals to illuminate cells, killing shadow enemies and ultimately the Demon Lord. Five levels of escalating mechanic complexity culminating in a boss fight.

**Out:** Multiplayer, RNG, free-form combat (no HP/stat system), real-time movement (turn-based only), inventory (no item pickup beyond crystals).

---

## Concept Summary

Every cell on the map is either **lit** or **shadow**. Shadow demons are invulnerable in shadow and die instantly the moment their cell becomes lit. The player carries no weapon — the only verb is **move** (which also pushes adjacent crystals, sokoban-style). Crystals emit a light **beam** in all four cardinal directions until blocked by a wall, the map edge, or another crystal. Push crystals into the right positions and the beams sweep enemies away.

The Demon Lord sits in a sanctuary surrounded by **shadow shrines**. He is invulnerable until every shrine is simultaneously lit. Once all shrines are lit, the player kills him by stepping into his cell.

Win: kill the Demon Lord (final level) / clear all enemies and reach the exit (earlier levels). Lose: turn limit exceeded OR player steps into shadow that contains a live patrolling demon (later levels only).

---

## Architecture

| Component | Location | Notes |
|-----------|----------|-------|
| Game file | `environment_files/dl/00000001/dl01.py` | New file |
| Metadata | `environment_files/dl/00000001/metadata.json` | New file |
| Class | `Dl01(ARCBaseGame)` | PascalCase from game_id |
| Controls | `available_actions = [1, 2, 3, 4]` | D-pad only (no click) |
| Canvas | 64×64 px | Standard ARC canvas |
| Grid | 16×16 logical cells, 4 px/cell | Centered at `GRID_X=0, GRID_Y=0` |

No changes to server, frontend, or any existing files — pure new game addition. The game appears automatically in the Observatory game list via `server/state.py` directory scan.

---

## ARC3 Colour Assignments

| Role | Palette Index | Colour | Hex |
|------|---|---|---|
| Floor (shadow) | 4 | VeryDarkGray | `#333333` |
| Floor (lit) | 11 | Yellow | `#FFDC00` |
| Wall | 3 | DarkGray | `#666666` |
| Crystal (pushable) | 10 | LightBlue | `#88D8F1` |
| Player | 9 | Blue | `#1E93FF` |
| Shadow demon (stationary) | 15 | Purple | `#A356D6` |
| Patrolling demon | 8 | Red | `#F93C31` |
| Demon Lord (invulnerable) | 13 | Maroon | `#921231` |
| Demon Lord (vulnerable) | 6 | Magenta | `#E53AA3` |
| Shadow shrine (unlit) | 2 | Gray | `#999999` |
| Shadow shrine (lit) | 14 | Green | `#4FCC30` |
| Exit tile | 12 | Orange | `#FF851B` |
| HUD background | 5 | Black | `#000000` |
| HUD text / border | 0 | White | `#FFFFFF` |
| Beam-on-crystal marker | 7 | LightMagenta | `#FF7BCC` |

> Lit floor (Yellow 11) and lit shrine (Green 14) are intentionally different: shrines are objective markers, floor is just illumination state. Crystal sits *on top* of floor and renders Cyan whether lit or not — beams pass through it without revealing it.

---

## Light Beam Rule (the puzzle core)

After every player action and turn-advance, light is recomputed from scratch:

1. For each crystal at `(cx, cy)`:
   - Cast a beam in each of the four cardinal directions
   - Beam enters consecutive floor cells, **lighting** each one
   - Beam stops when it would enter a **wall**, **exit the grid**, or hit **another crystal**
   - Crystals do NOT block beams from other crystals when stacked? **They do block.** A crystal acts like a wall for other crystals' beams — this enables "shadow funnel" puzzles.
2. The crystal's own cell is NOT lit by itself (would trivialise level 1). Crystals only light the four orthogonal directions.
3. A cell is lit if any beam passes through it. Otherwise it is shadow.

Player and demons do NOT block beams (so a beam sweeps through them, killing demons, without being absorbed).

**Why this rule:** beams are easy to render (straight lines), easy to reason about (Manhattan straight lines), and create rich puzzle space (positioning a single crystal at the corner of a corridor changes which two demons die).

---

## Enemy Behaviours

| Enemy | Movement | Death condition | Damages player? |
|---|---|---|---|
| Shadow demon (Purple) | Stationary | Cell becomes lit | No (passive — player can walk through? No: blocks player movement, like a wall, until killed) |
| Patrolling demon (Red) | Moves 1 cell along fixed path each turn-advance, after player moves | Cell becomes lit at end of turn | YES — if patrolling demon ends turn on player's cell, player dies (lose) |
| Demon Lord (Maroon → Magenta) | Stationary | (1) all shadow shrines lit AND (2) player enters his cell | If player enters his cell while invulnerable → player dies |

Shadow demons block the player's move (you cannot walk into one) but do NOT block crystal pushes — pushing a crystal **through** a shadow demon's cell is allowed and kills the demon if the resulting beam configuration lights it.

Wait — that's awkward. Let me simplify: **shadow demons block crystal pushes too**. To kill a shadow demon you must rotate a beam onto it from elsewhere (around a wall corner, etc.). This keeps the rule "demons act like walls until lit" uniform.

---

## Turn Sequence (each step)

1. Player presses d-pad direction `d` ∈ {U, D, L, R}
2. Compute target cell `t = player + d`
3. **Resolve player action:**
   - If `t` is wall, edge, or shadow demon: **no-op, no turn advance** (free retry)
   - If `t` is the Demon Lord cell **and Lord is invulnerable**: player moves into the cell and **dies** → lose
   - If `t` is the Demon Lord cell **and Lord is vulnerable**: player kills Lord → win (level 5)
   - If `t` is a crystal: try push — let `p = t + d`. If `p` is empty floor (no wall, no crystal, no enemy, no shrine, in-bounds): move crystal `t→p`, move player `player→t`. Else no-op.
   - If `t` is empty floor / lit shrine / exit / dead-demon-cell: move player `player→t`.
4. **Recompute lighting** (from current crystal positions)
5. **Kill stationary shadow demons** whose cell is now lit (mark dead, remove from blocker set)
6. **Move patrolling demons** one step along their patrol path. After each, check:
   - If demon's new cell is on the player → **player dies, lose**
   - If demon's new cell is lit → demon dies (still counts as a move for the rest)
7. **Recompute lighting again** (in case patrolling demon just walked into a beam — purely defensive; doesn't change anything since demons don't block beams)
8. **Check shrines:** mark each shrine cell as lit/unlit based on beam coverage
9. **Check Demon Lord:** if all shrines lit → set vulnerable flag (color flips to Magenta)
10. Increment turn counter
11. **Win check:** all required enemies dead AND player on exit tile (levels 1–4) / Demon Lord killed (level 5)
12. **Lose check:** turn counter > limit
13. `complete_action()`

---

## Level Designs (16×16 grid, origin top-left, `(col, row)`)

Notation: `.` floor, `#` wall, `C` crystal, `P` player start, `D` shadow demon, `R` patrolling demon (with path noted), `S` shadow shrine, `L` Demon Lord, `E` exit.

### Level 1 — "First Light" (intro: push, beam, kill)

**Teaches:** push direction = walk direction; crystal lights 4 cardinals; lit cell kills demon.

```
Row  0: # # # # # # # # # # # # # # # #
Row  1: # . . . . . . . . . . . . . . #
Row  2: # . . . . . . . . . . . . . . #
Row  3: # . . . D . . . . . . . . . . #
Row  4: # . . . . . . . . . . . . . . #
Row  5: # . . . . . . . . . . . . . . #
Row  6: # . . . . . . . . . . . . . . #
Row  7: # . . . . . . . . . . . . E . #
Row  8: # . . . . . . . . . . . . . . #
Row  9: # . . . . . . . . . . . . . . #
Row 10: # . . . . . . . . . . . . . . #
Row 11: # . . . . . . . . . . . . . . #
Row 12: # . . . . . . . . . . . . . . #
Row 13: # . . P . . . . . . . . . . . #
Row 14: # . . . C . . . . . . . . . . #
Row 15: # # # # # # # # # # # # # # # #
```

- Player at (3,13), crystal at (4,14), demon at (4,3), exit at (13,7).
- Solution: push crystal up the col=4 corridor until its vertical beam hits row 3 (which it does immediately on push from any row ≥ 4 with no obstacle — beam reaches the demon as soon as crystal is in col 4).
- **Wait:** crystal is already in col 4 (same as demon). On turn 1, beam from (4,14) goes up through rows 13→0, lighting (4,3) → demon dies. So player just walks to exit.
- Turn limit: **20**. Min solution: 1 turn (kill happens on initial light recompute) + ~14 walk steps.

> **Design note:** initial lighting is computed at level start (before turn 1). So demon at (4,3) is killed at level start. Tutorial is "just walk to the exit" — player learns crystals make beams.

### Level 2 — "Two Beams" (intro: blocked beams)

**Teaches:** walls block beams; you must position crystals carefully.

```
Row  0: # # # # # # # # # # # # # # # #
Row  1: # . . . D . . # . . . . D . . #
Row  2: # . . . . . . # . . . . . . . #
Row  3: # . . . . . . # . . . . . . . #
Row  4: # . . . . . . # . . . . . . . #
Row  5: # . . . . . . . . . . . . . . #
Row  6: # . . . . . . . . . . . . . . #
Row  7: # . . . . . . . . . . . . E . #
Row  8: # . . . . . . . . . . . . . . #
Row  9: # . . . . . . . . . . . . . . #
Row 10: # . . . . . . . . . . . . . . #
Row 11: # . . . . . . . . . . . . . . #
Row 12: # . . C . . . . . . C . . . . #
Row 13: # . . . . . . . . . . . . . . #
Row 14: # . . . . . P . . . . . . . . #
Row 15: # # # # # # # # # # # # # # # #
```

- Wall divides upper map into two cells (rows 1–4, col 7). Two crystals already in cols 3 and 10; two demons in cols 4 and 12.
- Player must push **left crystal** right by 1 (to col 4) AND push **right crystal** left by 2 (to col 8 → wait, col 8 is already blocked? recheck wall). Adjusting: wall is only at (7, rows 1–4). Crystals at (3,12) and (10,12) need to reach cols 4 and 12 respectively to align with demons.
- Push left crystal right once → col 4, beam up kills left demon. Push right crystal right twice → col 12, beam up kills right demon.
- Turn limit: **30**.

### Level 3 — "Crystal Wall" (intro: crystals block other beams)

**Teaches:** a crystal blocks another crystal's beam, so order matters.

```
Single corridor, 3 demons in a row, 2 crystals. Player must push one crystal past
a fork, otherwise the second crystal's beam is absorbed by the first crystal
before reaching the rear demon.
```

Layout: a horizontal corridor (row 7, cols 1–14) with three demons at cols 4, 8, 12. Two crystals start at row 9. Player must:
- Push crystal A up to row 7 col 4 → kills demon at (4,7)? No — beam from (4, 7) goes left/right/up/down. Demon at (8,7) and (12,7) are in same row — beam going right from crystal at (4,7) hits demon at (8,7) first, lights (8,7), demon dies. Beam continues? **No: beam stops at demons? Decision: beam passes through dead-demon cells (which are now floor) but stops at live demons? That's inconsistent.**

**Resolution:** beams pass through demons (do not block). So a single crystal in row 7 lights ALL of row 7, killing all three demons in one shot — too easy.

**Redesign Level 3:** put a wall segment between demons so beams can only kill them one at a time, requiring crystal repositioning:

```
Row 7: # . . . D # . . D # . . D . . #   (walls at col 5 and col 9 in row 7)
```

Two crystals must each be pushed into a separate corridor section. Adds wall obstacles for player navigation. Turn limit: **40**.

### Level 4 — "Watchman" (intro: patrolling demon)

**Teaches:** patrolling demons damage you on contact and must be timed/lit.

```
- Single open chamber, 12×12 interior
- Player at (1,14), exit at (14,1)
- Patrolling demon R walks a 6-cell loop: (7,7)→(8,7)→(9,7)→(8,7)→(7,7)→(6,7)→ repeat
- Two crystals available; player must push one into row 7 to kill R, OR time
  movement to slip past while R is at the far end of its patrol
- Two stationary shadow demons block the direct route (cols 5 and 11, row 4) —
  must be killed with crystal beams to clear the way to exit
```

Turn limit: **45**.

### Level 5 — "The Demon Lord" (boss)

**Teaches:** all mechanics + win condition is killing the Lord, not reaching exit.

```
Row  0: # # # # # # # # # # # # # # # #
Row  1: # . . . . . . . . . . . . . . #
Row  2: # . . . . . . . . . . . . . . #
Row  3: # . . S . . # # # . . S . . . #     S = shadow shrines (3 total)
Row  4: # . . . . . # . # . . . . . . #
Row  5: # . . . . . # L # . . . . . . #     L = Demon Lord (centred sanctuary)
Row  6: # . . . . . # . # . . . . . . #
Row  7: # . . . . . # # # . . . . . . #
Row  8: # . . . . . . . . . . . . . . #
Row  9: # . . . . . . . S . . . . . . #     third shrine south of sanctuary
Row 10: # . . . . . . . . . . . . . . #
Row 11: # . . . . . . . . . . . . . . #
Row 12: # . . C . . . . . . . . C . . #     two crystals at row 12
Row 13: # . . . . . . . C . . . . . . #     third crystal at (8, 13)
Row 14: # . . . . . . . . . . . . . . #
Row 15: # # # # # # # # P # # # # # # #     player enters sanctuary's south door
```

- Sanctuary walls: (6–8, 3), (6, 4), (8, 4), (6, 5), (8, 5), (6, 6), (8, 6), (6–8, 7). Door is at (7, 7) → no wait, row 7 col 7 is the **bottom of sanctuary wall**. Let me re-spec: south door is at (7, 7) which means there's an opening for the player to enter once the Lord is vulnerable. Player walks down from row 15 through col 7, but needs path through middle wall — shrine at (7,9) is on the route.
- Three shrines at (3,3), (11,3), (7,9). Three crystals at (3,12), (12,12), (8,13).
- Solution: push crystal at (3,12) up col 3 → lights shrine at (3,3). Push crystal at (12,12) up col 12 → lights shrine at (11,3)? **No: beam at col 12 doesn't hit col 11.** Need either re-positioning or shrines on crystal columns.
- Adjust: shrines at **(3,3), (12,3), (7,10)** — then crystals at (3,12), (12,12), (7,12) cover them with vertical beams.
- After all three shrines lit → Lord turns Magenta. Player must navigate into sanctuary (south door at row 7 col 7) and step onto Lord at (7,5).
- Turn limit: **60**.

> **Open detail:** sanctuary internal layout will be locked down during implementation TODO #2. The architecture above is the target; exact wall coordinates may shift to make the solution exist and be tight.

---

## Game State (Python)

```python
self.player          = (col, row)          # tuple
self.crystals        = set()               # {(col, row), ...}
self.walls           = set()               # {(col, row), ...}
self.demons_static   = {}                  # {(col, row): {'alive': bool}}
self.demons_patrol   = []                  # [{'pos': (c,r), 'path': [(c,r), ...], 'idx': int, 'alive': bool}]
self.shrines         = {}                  # {(col, row): {'lit': bool}}
self.exit_cell       = (col, row)          # or None for level 5 (no exit; win = kill Lord)
self.demon_lord      = None                # {'pos': (c,r), 'vulnerable': bool, 'alive': bool} or None
self.lit_cells       = set()               # recomputed every turn from crystals
self.turn            = 0
self.turn_limit      = 20                  # set per level in on_set_level
```

---

## Rendering Layout (64×64 canvas)

```
 ┌──────────────────────────────────────────────────────────────────┐
 │  HUD top strip (rows 0–3, 4px tall): turn counter, level dots,    │
 │  shrine status (3 dots), Lord status (icon)                        │
 ├──────────────────────────────────────────────────────────────────┤
 │                                                                    │
 │   16×16 grid at CELL=4px → 64px wide × 60px tall (rows 4–63)      │
 │   GRID_X=0, GRID_Y=4                                              │
 │                                                                    │
 └──────────────────────────────────────────────────────────────────┘
```

Render order per cell (back to front): floor (lit/shadow) → shrine → exit → wall → crystal → demon (static or patrol) → Demon Lord → player. HUD overlays last.

---

## File Header (required)

```python
# Author: Claude Opus 4.7
# Date: 2026-05-06 HH:MM
# PURPOSE: Demon Lord (dl01) — 5-level d-pad sokoban-RPG. Player pushes light
#          crystals to illuminate cells; lit cells kill shadow demons. Final
#          level: light all 3 sanctuary shrines, then walk into the Demon Lord
#          to win. Integrates with arcengine via ARCBaseGame; d-pad only
#          (ACTION1-4).
# SRP/DRY check: Pass — no existing utility covers crystal-beam-lighting
#                sokoban rule. Pattern is novel for this codebase.
```

---

## TODOs (ordered)

- [ ] **1. Scaffold** — create `environment_files/dl/00000001/` and stub `dl01.py` with `Dl01` class, `__init__`, `on_set_level`, `step` skeleton; create `metadata.json`
- [ ] **2. Level data** — define all 5 `_LEVELS` dicts (player start, crystals, walls, demons, shrines, exit, Lord, turn limit); finalise Level 5 sanctuary layout
- [ ] **3. `on_set_level`** — load level data into game state; reset turn counter; compute initial lighting; kill any demons lit at start
- [ ] **4. Movement resolver** — `_try_move(direction)`: handle no-op (wall/edge/blocker), push (crystal → empty floor), walk; do NOT advance turn on no-op
- [ ] **5. Lighting recomputation** — `_recompute_lighting()`: iterate crystals, cast 4 beams, fill `self.lit_cells`. Beams stop at walls, edges, other crystals; pass through demons and player
- [ ] **6. Demon kill / patrol move** — after lighting recompute: kill static demons in lit cells; advance patrol demons one step along their `path`; check player-collision (lose); kill patrol demons that end on lit cells
- [ ] **7. Shrine + Lord state** — update each shrine's `lit` flag; if all shrines lit set Lord vulnerable
- [ ] **8. Win/lose** — after every step: levels 1–4 win = all demons dead AND player on exit; level 5 win = player walks into vulnerable Lord; lose = turn limit exceeded
- [ ] **9. Renderer** — `Dl01Display.render_interface()`: draw HUD strip, then grid (floor → shrine → exit → wall → crystal → demon → Lord → player); apply lit/shadow palette per floor cell
- [ ] **10. Smoke test** — automated playthrough that wins all 5 levels using `perform_action(ActionInput(id=GameAction.ACTION1..4))` — must end with `GameState.WIN`
- [ ] **11. Changelog** — add entry to `CHANGELOG.md`

---

## Verification Steps

After each TODO:
- **After #3:** `python -c "import sys; sys.path.insert(0,'environment_files/dl/00000001'); import dl01; g = dl01.Dl01(); print(g.level_index, len(g.crystals), len(g.walls))"` → `0 1 60` (or similar non-zero counts)
- **After #5:** unit-test lighting: place one crystal at (4,14) in level 1, recompute, assert `(4, 0)` through `(4, 13)` are all in `lit_cells`, and `(4, 14)` itself is NOT.
- **After #6:** drive a patrol demon onto a lit cell via scripted moves; assert `alive == False`.
- **After #8:** scripted run through level 1 reaches exit and `GameState.WIN`.
- **After #10:** mandatory smoke test (per CLAUDE.md "Mandatory Smoke Test") — full automated win on all 5 levels.

---

## Docs / Changelog

- **`CHANGELOG.md`** entry required: new game `dl01` Demon Lord — 5-level d-pad sokoban-RPG, crystal-beam lighting mechanic, Demon Lord boss fight.
- **No** other docs require updating. The game appears automatically in the Observatory game list via `server/state.py` directory scan.
- **No** `HIDDEN_GAMES` change needed (we want it visible in both staging and prod).

---

## Open Questions (need answer before implementation)

| # | Question | My recommendation |
|---|---|---|
| 1 | Should the player also block beams? | **DECIDED (user, 2026-05-06):** No. Player is transparent to beams. |
| 2 | Can the player walk onto a lit shrine cell? | **DECIDED (user, 2026-05-06):** Yes. Shrines are walkable markers; standing on one does not unlight it. |
| 3 | Can a crystal be pushed onto a shrine cell? | **DECIDED (user, 2026-05-06):** Yes. A crystal on a shrine does NOT light that shrine (crystals never light their own cell); the shrine only counts as lit if another crystal's beam reaches it. |
| 4 | If patrol demon walks onto a crystal cell, what happens? | **DECIDED (user, 2026-05-06):** Crystal blocks like a wall. Patrol demon waits one turn instead. |
| 5 | Level 5 — does walking onto the Lord while invulnerable kill the player, or just no-op? | **DECIDED (user, 2026-05-06):** Player dies on contact with invulnerable Lord. Adds real risk to navigating the sanctuary. |

---

## Risks

1. **Level 5 solvability** — Three crystals, three shrines, all on different columns; need to verify a turn-budget solution exists. Mitigation: prototype level 5 first with a quick BFS/manual solve before locking the layout.
2. **Crystal-blocks-crystal beam** rule may make levels 2/3 unintentionally trivial or impossible. Mitigation: validate during smoke test; adjust crystal/wall positions in TODO #2.
3. **Patrol demon timing** — turn-order edge case: if player's move lights a cell and the patrol demon then moves into that cell, demon dies. Acceptable; matches the spec.
