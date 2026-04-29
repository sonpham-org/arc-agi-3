# Pouring Water — Player Thermostat (W / S keys)

**Author:** Claude Opus 4.7 (1M context)
**Date:** 2026-04-29
**Game ID:** `pw01`
**Version:** `00000002` → `00000003` (per CLAUDE.md game-versioning rule)

---

## Scope

### In
- A player-controlled **thermostat** integer in the range `-5..+5`,
  starting at `0`.
- **W** (ACT1) raises the thermostat by 1 (cap +5).
- **S** (ACT2) lowers it by 1 (cap -5).
- Each tick, settled water, in-kettle reservoir bulk temp, and ice cells
  get an additional `+thermostat` °C delta. Stacks on top of fire / cold
  / drift logic.
- HUD shows a thermostat strip (5 cells left, 5 right of centre, lit by
  current value with color cue: orange for hot, light-blue for cold).
- New version dir `environment_files/pw/00000003/`. Old `00000002/`
  unchanged.
- Smoke test still wins all 6 levels (thermostat stays at 0 → no-op).

### Out
- No changes to `static/js/human-input.js`. W and S are already mapped
  to ACT1 / ACT2 (`human-input.js:115`); we simply add `1, 2` to
  `available_actions` so the framework forwards those keys.
- No changes to existing levels' fire/cold rects.
- No changes to JS bundling.

---

## Architecture

| Path | Action | Why |
|------|--------|-----|
| `environment_files/pw/00000003/pw01.py` | NEW | Copy of v2 + thermostat. |
| `environment_files/pw/00000003/metadata.json` | NEW | `date_downloaded: "2026-04-29"`. |
| `environment_files/pw/00000003/smoke_test.py` | NEW | Same harness, points at v3. |
| `CHANGELOG.md` | EDIT | `[1.24.0]` entry. |
| `docs/29-Apr-2026-pouring-water-thermostat-plan.md` | NEW | This doc. |

### State + step()
```python
self.thermostat: int = 0   # in [-5, +5]

def step(self):
    aid = self.action.id.value
    if aid == 1:
        self.thermostat = min(THERMOSTAT_MAX, self.thermostat + 1)
    elif aid == 2:
        self.thermostat = max(-THERMOSTAT_MAX, self.thermostat - 1)
    # tilt (existing logic)
    if aid == 6:
        self.tilt = min(TILT_MAX, self.tilt + TILT_PER_CLICK)
    else:
        self.tilt = max(0, self.tilt - TILT_PER_RELEASE)
    ...
```

### Heat update
At the end of each cell's per-tick temp computation (after existing
fire/cold/drift logic but before clamp/transition):
```python
t += self.thermostat
```
Same for kettle and ice.

### HUD
Row 3 (currently unused): centred 11-cell thermostat strip. Cell at
centre = always orange/light-blue/black depending on sign. Cells light
up outward proportional to `|thermostat|`.

### Determinism
Still deterministic — thermostat is integer state derived from the
action stream.

### Smoke test impact
Thermostat starts at 0 and the existing smoke test never sends ACT1 or
ACT2, so all six levels' click counts (46/80/70/200/190/220) carry
over unchanged.

---

## TODOs

1. Copy `00000002/pw01.py` → `00000003/pw01.py`. Update header.
2. Add `THERMOSTAT_MAX = 5`. Add `self.thermostat = 0` to `__init__` and
   reset in `on_set_level` and `_reset_attempt`.
3. Wire ACT1/ACT2 in `step()`. Add `1, 2` to `available_actions`.
4. Add `t += self.thermostat` in three places in `_step_heat` (water,
   kettle, ice).
5. Render HUD strip in `PourDisplay.render_interface`.
6. Copy / update smoke test with v3 path. Run, confirm WIN.
7. Add metadata.json (`date_downloaded: "2026-04-29"`).
8. CHANGELOG `[1.24.0]` Added.

No open questions — proceeding immediately based on user's option-1
choice.
