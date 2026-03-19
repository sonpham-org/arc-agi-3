# Plan: Tower Siege (ts01) — Real-Time Two-Player Mode

**Date:** 2026-03-19
**Author:** Claude Sonnet 4.6

---

## Scope

**In:**
- Replace alternating turn-based logic with real-time continuous ticking via ACT7 (live mode)
- Both players interact freely via clicks at any time — no "whose turn" enforcement
- Per-entity action cooldowns prevent spam (unit/guard can only move once every N ticks)
- Redesign level tick limits, gate periods, bomb timers, and freeze durations to feel right at real-time speed
- Version bump to `00000003`

**Out:**
- Networking/remote play
- Keyboard input (still click-only, ACTION6 + ACT7)
- Any new unit or guard types

---

## Core Design

### Live Mode
- Add `7` to `available_actions` → `[6, 7]`
- Add `"live"` to metadata `tags`
- Set `"default_fps": 4` in metadata (0.25s per tick — fast enough to feel live, slow enough to see what's happening)

### ACT7 tick (world advance, auto-sent by client)
```
bombs tick down  →  remove expired walls
freeze counters decrement
action cooldowns decrement (per unit/guard)
turn++
check win/lose (turn limit)
```
Guards do **not** auto-move. P2 still manually controls them.

### ACTION6 click (either player, any time)
```
convert pixel → grid cell
if selected_idx set (unit selected by P1):
    try move/tool; check win
elif selected_guard_idx set (guard selected by P2):
    try guard move / spawn
else:
    try select unit → if not found, try select guard
```
No `current_player` state. Both players self-enforce (P1 clicks units, P2 clicks guards). When a unit is selected, all clicks route through attacker logic first. When a guard is selected, defender logic handles it.

### Per-entity action cooldowns
After any action (move, tool use, guard move, spawn), the entity gets a cooldown of N ticks. While cooldown > 0, the entity cannot be selected or acted upon.

| Entity | Cooldown after action |
|--------|----------------------|
| Sapper / Scout / Soldier move | 3 ticks (0.75s) |
| Sapper bomb plant | 3 ticks (0.75s) |
| Scout grapple | 3 ticks (0.75s) |
| Guard move by P2 | 4 ticks (1.0s) |
| Spawn (new guard) | immediate (limited by reserve count only) |

Cooldown shown as a dim dot on the unit/guard cell when cooling.

### Bomb timer
Real-time bomb: `BOMB_TICKS = 4` (was 1). Wall removed 4 ticks after bomb planted = 1 second.

### Freeze after Soldier contact-kill
`FREEZE_TICKS = 4` (was 1). Soldier can't act for 1 second after contact-kill.

### Gate periods redesigned
At 4 FPS, old `period=3` opens/closes every 0.75s — unplayably fast. New gate period = `12` ticks (3s cycle). `open_offset=0` → open at ticks 0,12,24...

---

## Level Redesigns

At 4 FPS, 1 second = 4 ticks. Turn limits in ticks:

| Level | P1 | P2 | Tick limit | Time (~s) |
|-------|----|----|-----------|-----------|
| L1 The Breach | Sapper | 1 guard + 1 reserve | 120 | 30s |
| L2 Timed Gate | Sapper+Scout | 1 guard + 1 reserve | 160 | 40s |
| L3 Two Guards | All | 2 guards + 2 reserves | 200 | 50s |
| L4 Full Assault | All | 3 guards + 2 reserves | 240 | 60s |
| L5 The Gauntlet | All | 3 guards + 3 reserves | 160 | 40s |

Gate: `period=12, open_offset=0` for all gated levels.

---

## HUD / UI Changes

### HUD bar (top)
- Level dots: unchanged
- Replace `T:XX/YY` (turns) with `{seconds_left}s` countdown (e.g., `28s`)
- Add small `LV` (live) indicator or blinking dot to signal live mode

### Right panel
- Remove `ATK`/`DEF` label (no current player)
- Add `LIVE` label at top (static, green)
- Unit rows: same as before, but show cooldown as a dim dot when unit can't act
- Guard count `G:N` and reserves `R:N`: unchanged
- Remove `PAS` hint (no passing in real-time)

### Grid
- Cooldown dim: when a unit/guard is on cooldown, render it 1 shade darker (use DGRAY dot overlay instead of dim cell fill)
- Spawn zone maroon dots: show whenever P2 has reserves and no guard is selected (unchanged)

---

## File Changes

| File | Change |
|---|---|
| `environment_files/ts/00000003/ts01.py` | New version — real-time logic, redesigned levels |
| `environment_files/ts/00000003/metadata.json` | `tags: ["live"]`, `default_fps: 4`, date 2026-03-19 |
| `CHANGELOG.md` | Entry |

`00000001` (single-player) and `00000002` (turn-based 2P) left intact.

---

## TODOs

1. [ ] Create `environment_files/ts/00000003/`
2. [ ] Write `ts01.py`:
   - Add `BOMB_TICKS=4`, `FREEZE_TICKS=4`, `UNIT_COOLDOWN=3`, `GUARD_COOLDOWN=4` constants
   - Add `move_cooldown` field to unit and guard dicts
   - Redesign level data (new tick limits, gate periods, guard positions)
   - Simplify `step()`: ACT7 → `_tick()`, ACTION6 → `_handle_click()`
   - `_tick()`: decrement bombs/freeze/cooldowns, turn++, check lose
   - `_handle_click()`: no current_player, cooldown-gated, unified unit+guard routing
   - Update renderer: `{N}s` countdown, LIVE label, cooldown dim indicator
3. [ ] Write `metadata.json`
4. [ ] Update `CHANGELOG.md`
5. [ ] Smoke test: import check + simulate ACT7 ticks + ACTION6 clicks
6. [ ] Push to staging

---

## Open Questions

1. Should P2's guard-move cooldown (4 ticks) feel right, or should it match attacker speed (3 ticks)?
2. Should the HUD show remaining seconds (countdown) or elapsed ticks?
