# Author: Claude Opus 4.7 (1M context)
# Date: 2026-04-26 12:00
# PURPOSE: Pouring Water (pw01) — live-mode physics game where the player
#   tilts a kettle (0-60 degrees) to pour water into a cup. Tilt rises by
#   2 degrees per click-tick (ACTION6) and falls by 1 degree per idle-tick
#   (ACTION7) to give a snappy pour feel. Water is simulated as a hybrid:
#   in-flight droplets carry float (x, y, vx, vy) with gravity for the
#   parabolic arc out of the spout, then settle into a deterministic
#   single-buffered falling-sand cellular automaton (down -> diagonal slip
#   -> sideways spread, with tick-parity alternation to prevent one-sided
#   clustering). Win when the count of water pixels collected inside the
#   cup interior reaches the level's target volume. 3 progressive levels.
#   Integration: subclass of arcengine.ARCBaseGame, registered as game_id
#   "pw01" via metadata.json. Listed automatically by /api/games once the
#   environment_files/pw/00000001/ directory exists.
# SRP/DRY check: Pass — searched environment_files/* for any existing
#   pixel-water sim, none found. Falling-sand and rotation helpers are
#   intrinsic to this game's mechanics so they live here, not in shared
#   utilities (no other game uses them).

import math
import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# ── Grid geometry ──────────────────────────────────────────────────────────
GW, GH = 64, 64
HUD_H = 4
PLAY_TOP = HUD_H
FLOOR_Y = GH - 1  # bottom row absorbs water (sink)

# ── ARC-3 palette indices ──────────────────────────────────────────────────
C_WHITE = 0
C_LGRAY = 1
C_GRAY = 2
C_DGRAY = 3
C_VDGRAY = 4
C_BLACK = 5
C_MAGENTA = 6
C_LMAGENTA = 7
C_RED = 8
C_BLUE = 9
C_LBLUE = 10
C_YELLOW = 11
C_ORANGE = 12
C_MAROON = 13
C_GREEN = 14
C_PURPLE = 15

# ── Physics constants ──────────────────────────────────────────────────────
TILT_MAX = 60
TILT_PER_CLICK = 2     # snappy tilt-up when holding the click
TILT_PER_RELEASE = 1   # slow decay back when released — pour-feel asymmetry
SPILL_TILT = 50        # water only flows out past this tilt (ramp is "dry")
GRAVITY = 0.30
HVEL_SLOPE = 0.10      # tilt -> vx multiplier
HVEL_TILT_OFFSET = 30  # at tilt 50 vx=2.0; at tilt 60 vx=3.0

# Emission rate: pixels emitted per tick, by tilt
def _emit_rate(tilt: int) -> int:
    if tilt < SPILL_TILT:
        return 0
    if tilt < 55:
        return 1
    if tilt < 60:
        return 2
    return 3

# ── Kettle sprite (local coords; pivot = bottom-centre of body) ────────────
# Layout (ly increasing downward; pivot at (0, 0) on body bottom row):
#
#   ly\lx | -3 -2 -1  0  1  2  3
#      -5 |  .  H  H  H  H  .  .   <- handle top
#      -4 |  .  H  .  .  H  .  .
#      -3 |  H  B  B  B  B  B  B   <- body top + handle attach
#      -2 |  B  B  B  B  B  B  B   <- body upper (S spout tail at lx 4-5)
#      -1 |  B  B  B  B  B  B  B   <- body lower (S spout tip at lx 5)
#       0 |  .  B  B  B  B  B  B   <- body bottom (pivot row)
#
# Spout tip = (5, -1). Water emits from one pixel below+right of spout tip.

KETTLE_BODY = [
    (-3, -3), (-2, -3), (-1, -3), (0, -3), (1, -3), (2, -3), (3, -3),
    (-3, -2), (-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2), (3, -2),
    (-3, -1), (-2, -1), (-1, -1), (0, -1), (1, -1), (2, -1), (3, -1),
    (-2,  0), (-1,  0), (0,  0), (1,  0), (2,  0), (3,  0),
]
KETTLE_HANDLE = [
    (-2, -5), (-1, -5), (0, -5), (1, -5),
    (-2, -4), (1, -4),
    (-3, -3),
]
KETTLE_SPOUT = [
    (4, -2), (5, -2),
    (4, -1), (5, -1),
]
KETTLE_SPOUT_TIP = (5, -1)

# Body interior cells (used for "kettle water" rendering inside the body).
KETTLE_INTERIOR = [
    (-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2),
    (-2, -1), (-1, -1), (0, -1), (1, -1), (2, -1),
    (-1,  0), (0,  0), (1,  0),
]
KETTLE_INTERIOR_TOP_LY = -2  # the "rim" interior y (relative to pivot)
KETTLE_INTERIOR_BOT_LY = 0
KETTLE_INTERIOR_CAPACITY = len(KETTLE_INTERIOR)


# ── Level data — all positions hardcoded, fully deterministic ──────────────
# kettle_pivot = world (x, y) where the kettle pivots
# cup_left, cup_right = wall x columns (inclusive)
# cup_top = mouth row (no top wall above this); cup_bottom = floor row of cup
# target_volume = water-pixel count inside cup interior to win
# kettle_volume = starting reservoir
# obstacles = list of (x0, y0, x1, y1) inclusive rectangles that block water
LIVES_PER_LEVEL = 5

LEVEL_DATA = [
    {
        'name': 'First Pour',
        'kettle_pivot': (18, 24),
        'cup_left': 38, 'cup_right': 50,
        'cup_top': 44, 'cup_bottom': 60,
        'target_volume': 60,
        'kettle_volume': 200,
        'obstacles': [],
    },
    {
        'name': 'Long Reach',
        'kettle_pivot': (16, 22),
        'cup_left': 44, 'cup_right': 54,
        'cup_top': 50, 'cup_bottom': 60,
        'target_volume': 45,
        'kettle_volume': 220,
        'obstacles': [],
    },
    {
        'name': 'Around the Wall',
        'kettle_pivot': (10, 12),
        'cup_left': 42, 'cup_right': 52,
        'cup_top': 50, 'cup_bottom': 60,
        'target_volume': 45,
        'kettle_volume': 280,
        'obstacles': [(28, 32, 30, 50)],
    },
]

levels = [
    Level(sprites=[], grid_size=(GW, GH), name=d['name'], data=d)
    for d in LEVEL_DATA
]


# ── Rotation helper ────────────────────────────────────────────────────────

def _rotate(lx: float, ly: float, tilt_deg: int) -> tuple[float, float]:
    """Rotate local (lx, ly) by tilt_deg clockwise on screen (y-down).

    Equivalent to standard CCW math rotation applied to screen coords:
        x' = lx*cos(t) - ly*sin(t)
        y' = lx*sin(t) + ly*cos(t)
    Positive tilt_deg tips the kettle to the right (spout downward).
    """
    t = math.radians(tilt_deg)
    c, s = math.cos(t), math.sin(t)
    return (lx * c - ly * s, lx * s + ly * c)


# ── Display ────────────────────────────────────────────────────────────────

class PourDisplay(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        g = self.game

        # Background
        frame[:, :] = C_BLACK

        # Floor row
        frame[FLOOR_Y, :] = C_DGRAY

        # Obstacles
        for (x0, y0, x1, y1) in g.obstacles:
            x0c, x1c = max(0, x0), min(GW - 1, x1)
            y0c, y1c = max(0, y0), min(GH - 1, y1)
            frame[y0c:y1c + 1, x0c:x1c + 1] = C_DGRAY

        # Cup walls
        cl, cr = g.cup_left, g.cup_right
        ct, cb = g.cup_top, g.cup_bottom
        # Left wall, right wall, bottom
        if 0 <= cl < GW:
            frame[ct:cb + 1, cl] = C_DGRAY
        if 0 <= cr < GW:
            frame[ct:cb + 1, cr] = C_DGRAY
        if ct <= cb < GH:
            frame[cb, cl:cr + 1] = C_DGRAY

        # Dotted target line (inside cup interior)
        target_y = g.cup_target_y
        if ct <= target_y < cb:
            for x in range(cl + 1, cr):
                if (x - (cl + 1)) % 2 == 0:
                    frame[target_y, x] = C_YELLOW

        # Kettle (rotated)
        px, py = g.kettle_pivot
        tilt = g.tilt
        # Render order: body interior water → body outline → handle → spout
        # First, body outline pixels (we draw all body, then overlay water on
        # interior cells to get the "water level" effect inside the kettle).
        body_world = {}
        for (lx, ly) in KETTLE_BODY:
            wx, wy = _rotate(lx, ly, tilt)
            ix, iy = int(round(px + wx)), int(round(py + wy))
            if 0 <= ix < GW and 0 <= iy < GH:
                body_world[(ix, iy)] = C_DGRAY

        # Kettle interior water — fill the lowest interior pixels first
        # (in world coords) according to remaining kettle_water.
        if g.kettle_water > 0:
            interior_world = []
            for (lx, ly) in KETTLE_INTERIOR:
                wx, wy = _rotate(lx, ly, tilt)
                ix, iy = int(round(px + wx)), int(round(py + wy))
                interior_world.append((ix, iy))
            # Sort by descending y (bottom-most first) — that's where water sits
            interior_world.sort(key=lambda p: -p[1])
            fill_count = min(
                len(interior_world),
                int(round(g.kettle_water / max(1, g.kettle_volume_initial)
                          * len(interior_world))),
            )
            for i in range(fill_count):
                ix, iy = interior_world[i]
                if 0 <= ix < GW and 0 <= iy < GH:
                    body_world[(ix, iy)] = C_BLUE

        # Spout (drawn over body so the spout colour wins at overlapping cells)
        for (lx, ly) in KETTLE_SPOUT:
            wx, wy = _rotate(lx, ly, tilt)
            ix, iy = int(round(px + wx)), int(round(py + wy))
            if 0 <= ix < GW and 0 <= iy < GH:
                body_world[(ix, iy)] = C_DGRAY

        # Handle (open loop)
        for (lx, ly) in KETTLE_HANDLE:
            wx, wy = _rotate(lx, ly, tilt)
            ix, iy = int(round(px + wx)), int(round(py + wy))
            if 0 <= ix < GW and 0 <= iy < GH:
                body_world[(ix, iy)] = C_GRAY

        # Commit kettle pixels
        for (ix, iy), col in body_world.items():
            if iy >= PLAY_TOP:
                frame[iy, ix] = col

        # In-flight droplets
        for p in g.particles:
            ix, iy = int(p['fx']), int(p['fy'])
            if 0 <= ix < GW and PLAY_TOP <= iy < GH:
                frame[iy, ix] = C_LBLUE

        # Settled water
        for (x, y) in g.water:
            if 0 <= x < GW and PLAY_TOP <= y < GH:
                # Water inside the cup interior renders azure (visual feedback)
                if cl < x < cr and ct <= y < cb:
                    frame[y, x] = C_LBLUE
                else:
                    frame[y, x] = C_BLUE

        # ── HUD ────────────────────────────────────────────────────────────
        frame[0:HUD_H, :] = C_VDGRAY

        # Tilt bar (left half): 60 cells of 1px each = full width if scaled
        # We render a 60px bar from x=2 to x=61, lighting up `tilt` cells.
        bar_y = 1
        for x in range(60):
            if x < g.tilt:
                if g.tilt >= SPILL_TILT:
                    frame[bar_y, 2 + x] = C_ORANGE
                else:
                    frame[bar_y, 2 + x] = C_GRAY
            else:
                frame[bar_y, 2 + x] = C_BLACK

        # Fill progress (third row of HUD): green up to current/target
        prog_y = 2
        prog_w = 50
        cur = min(g.cup_volume, g.target_volume)
        filled = int(prog_w * cur / max(1, g.target_volume))
        for x in range(prog_w):
            if x < filled:
                frame[prog_y, 2 + x] = C_GREEN
            else:
                frame[prog_y, 2 + x] = C_BLACK

        # Lives (right side of HUD row 2): red squares
        for i in range(g.lives):
            sx = 54 + i * 2
            if sx + 1 < GW:
                frame[prog_y, sx] = C_RED
                frame[prog_y, sx + 1] = C_RED

        # Spill flashes (over the play area, briefly)
        for (sx, sy, ttl) in g.spills:
            if 0 <= sx < GW and PLAY_TOP <= sy < GH and ttl > 3:
                frame[sy, sx] = C_RED

        return frame


# ── Game ───────────────────────────────────────────────────────────────────

class Pw01(ARCBaseGame):
    def __init__(self):
        self.display = PourDisplay(self)

        self.tilt = 0
        self.tick = 0
        self.water = set()         # settled water pixels: set[(x,y)]
        self.particles = []        # list of {'fx','fy','vx','vy'} dicts
        self.kettle_pivot = (16, 24)
        self.kettle_volume_initial = 0
        self.kettle_water = 0
        self.cup_left = 0
        self.cup_right = 0
        self.cup_top = 0
        self.cup_bottom = 0
        self.cup_target_y = 0
        self.target_volume = 0
        self.cup_volume = 0
        self.obstacles = []
        self.lives = LIVES_PER_LEVEL
        self.spills = []  # transient spill markers: list[(x, y, ttl)] for HUD flash

        # available_actions includes 7 so the live-mode idle tick uses
        # ACTION7 (release) instead of falling back to ACTION6 (click) —
        # otherwise the kettle would keep tilting up even when the player
        # is not pressing the mouse. See static/js/human.js:_humanLiveIdleAction.
        super().__init__(
            'pw', levels,
            Camera(0, 0, GW, GH, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [6, 7],
        )

    # ── Level setup ─────────────────────────────────────────────────────────

    def on_set_level(self, level):
        d = LEVEL_DATA[self.level_index]
        self.tilt = 0
        self.tick = 0
        self.water = set()
        self.particles = []
        self.kettle_pivot = d['kettle_pivot']
        self.kettle_volume_initial = d['kettle_volume']
        self.kettle_water = d['kettle_volume']
        self.cup_left = d['cup_left']
        self.cup_right = d['cup_right']
        self.cup_top = d['cup_top']
        self.cup_bottom = d['cup_bottom']
        self.target_volume = d['target_volume']
        self.cup_volume = 0
        self.obstacles = list(d['obstacles'])
        self.lives = LIVES_PER_LEVEL
        self.spills = []

        # Target line: water needs to reach this y-row inside the cup.
        # Place the line at the height where target_volume worth of water
        # would sit (assuming a flat surface across the inner width).
        inner_w = max(1, self.cup_right - self.cup_left - 1)
        rows_needed = max(1, math.ceil(self.target_volume / inner_w))
        # rows_needed counts inclusive interior rows from cup_bottom-1 upward.
        self.cup_target_y = self.cup_bottom - rows_needed

    # ── Solid-cell test ─────────────────────────────────────────────────────

    def _is_solid(self, x: int, y: int) -> bool:
        if not (0 <= x < GW and 0 <= y < GH):
            return True
        if y >= FLOOR_Y:
            return True
        # Cup walls
        if self.cup_top <= y <= self.cup_bottom:
            if x == self.cup_left or x == self.cup_right:
                return True
        if y == self.cup_bottom and self.cup_left <= x <= self.cup_right:
            return True
        # Obstacles
        for (x0, y0, x1, y1) in self.obstacles:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return True
        return False

    # ── Spout world position ────────────────────────────────────────────────

    def _spout_tip_world(self) -> tuple[float, float]:
        lx, ly = KETTLE_SPOUT_TIP
        rx, ry = _rotate(lx, ly, self.tilt)
        return (self.kettle_pivot[0] + rx, self.kettle_pivot[1] + ry)

    # ── Particle physics (in-flight water) ──────────────────────────────────

    def _step_particles(self):
        if not self.particles:
            return
        new_particles = []
        for p in self.particles:
            p['vy'] += GRAVITY
            # March pixel-at-a-time toward (fx+vx, fy+vy) so we don't tunnel
            # through walls or other water.
            tx = p['fx'] + p['vx']
            ty = p['fy'] + p['vy']
            cx, cy = p['fx'], p['fy']
            settled = False
            reached = False
            # Cap iterations defensively (vy can grow large for long falls)
            for _ in range(8):
                if int(cx) == int(tx) and int(cy) == int(ty):
                    reached = True
                    break
                # Step direction in integer grid
                dx = (1 if int(tx) > int(cx) else (-1 if int(tx) < int(cx) else 0))
                dy = (1 if int(ty) > int(cy) else (-1 if int(ty) < int(cy) else 0))
                # Try diagonal, then vertical, then horizontal
                tried = False
                for sx, sy in [(dx, dy), (0, dy), (dx, 0)]:
                    if sx == 0 and sy == 0:
                        continue
                    nix, niy = int(cx) + sx, int(cy) + sy
                    if self._is_solid(nix, niy) or (nix, niy) in self.water:
                        continue
                    # Move integer position; advance fractional position by 1
                    cx = float(nix) + (cx - int(cx))
                    cy = float(niy) + (cy - int(cy))
                    tried = True
                    break
                if not tried:
                    settled = True
                    break
            # If the march reached the analytical target, snap fractional
            # position so the carry doesn't drift across ticks (otherwise an
            # initial 0.87 frac stays at 0.87 after every move, and after
            # ten ticks the particle is 8 pixels past where physics says).
            if reached:
                cx, cy = tx, ty
            # Final integer landing cell. Use floor (`int()`), not `round()`,
            # because the march loop only ever steps into non-solid cells —
            # `int(cx)` is guaranteed non-solid, but `round(cx)` can flip into
            # an adjacent solid (a cup wall) and silently drop the drop.
            ix, iy = int(cx), int(cy)
            below_solid = self._is_solid(ix, iy + 1) or (ix, iy + 1) in self.water
            if settled or below_solid or iy >= FLOOR_Y - 1:
                if 0 <= ix < GW and PLAY_TOP <= iy < GH and not self._is_solid(ix, iy):
                    in_cup = (self.cup_left < ix < self.cup_right
                              and self.cup_top <= iy < self.cup_bottom)
                    if in_cup:
                        self.water.add((ix, iy))
                    else:
                        # Spill — drop landed outside the cup. Lose a life
                        # and flash a brief marker on the HUD.
                        self.lives -= 1
                        self.spills.append((ix, iy, 6))
                # Else: particle falls off the world (lost)
                continue
            # Carry fractional position; commit cx,cy to fx,fy
            p['fx'], p['fy'] = cx, cy
            new_particles.append(p)
        self.particles = new_particles

    # ── Cellular-automaton step for settled water ───────────────────────────

    def _step_water_ca(self):
        if not self.water:
            return
        occupied = set(self.water)
        # Bottom-up scan; tie-break by alternating x order per tick parity
        order_left_first = (self.tick % 2 == 0)
        x_key = (lambda p: p[0]) if order_left_first else (lambda p: -p[0])
        sorted_water = sorted(self.water, key=lambda p: (-p[1], x_key(p)))
        for (x, y) in sorted_water:
            # 1. Try down
            candidates = [(x, y + 1)]
            # 2. Diagonals
            if order_left_first:
                candidates += [(x - 1, y + 1), (x + 1, y + 1)]
            else:
                candidates += [(x + 1, y + 1), (x - 1, y + 1)]
            # 3. Sideways spread — only if there's vertical pressure
            # (water above) so a single-layer puddle doesn't slither forever.
            if (x, y - 1) in occupied:
                if order_left_first:
                    candidates += [(x - 1, y), (x + 1, y)]
                else:
                    candidates += [(x + 1, y), (x - 1, y)]
            for (nx, ny) in candidates:
                if not (0 <= nx < GW and PLAY_TOP <= ny < GH):
                    continue
                if self._is_solid(nx, ny):
                    continue
                if (nx, ny) in occupied:
                    continue
                occupied.discard((x, y))
                occupied.add((nx, ny))
                break
        self.water = occupied

    # ── Pour emission ───────────────────────────────────────────────────────

    def _emit_pour(self):
        rate = _emit_rate(self.tilt)
        if rate == 0 or self.kettle_water <= 0:
            return
        sx, sy = self._spout_tip_world()
        # Water exits one pixel below the spout tip
        emit_x = sx
        emit_y = sy + 1.0
        # Initial horizontal velocity scales with tilt
        vx = max(0.0, (self.tilt - HVEL_TILT_OFFSET) * HVEL_SLOPE)
        vy = 0.4  # small initial downward kick for a clean curl
        for _ in range(rate):
            if self.kettle_water <= 0:
                break
            self.particles.append({
                'fx': emit_x, 'fy': emit_y, 'vx': vx, 'vy': vy,
            })
            self.kettle_water -= 1

    # ── Cup volume + win/lose ───────────────────────────────────────────────

    def _recount_cup(self):
        cl, cr, ct, cb = self.cup_left, self.cup_right, self.cup_top, self.cup_bottom
        n = 0
        for (x, y) in self.water:
            if cl < x < cr and ct <= y < cb:
                n += 1
        self.cup_volume = n

    def _check_end(self):
        if self.cup_volume >= self.target_volume:
            self.next_level()
            return True
        # Spilling water over the floor immediately loses lives — when out
        # of lives, the run ends.
        if self.lives <= 0:
            self.lose()
            return True
        # Or: kettle empty and no water in flight, with the cup still short
        # of the target — also a loss (out of water).
        if self.kettle_water <= 0 and not self.particles:
            if self._water_settled_stable():
                self.lose()
                return True
        return False

    def _water_settled_stable(self) -> bool:
        # Water is "stable" if every pixel has solid (or other water) below.
        for (x, y) in self.water:
            if y + 1 >= GH:
                continue
            if not (self._is_solid(x, y + 1) or (x, y + 1) in self.water):
                return False
            # Also stable horizontally if both diagonals below are blocked or
            # the pixel can't slip sideways into a lower position.
            for sx in (-1, 1):
                nx, ny = x + sx, y + 1
                if (0 <= nx < GW and 0 <= ny < GH
                        and not self._is_solid(nx, ny)
                        and (nx, ny) not in self.water):
                    return False
        return True

    # ── Main step ───────────────────────────────────────────────────────────

    def step(self):
        aid = self.action.id.value
        if aid == 6:
            self.tilt = min(TILT_MAX, self.tilt + TILT_PER_CLICK)
        else:
            self.tilt = max(0, self.tilt - TILT_PER_RELEASE)

        self.tick += 1

        self._emit_pour()
        self._step_particles()
        self._step_water_ca()
        self._recount_cup()

        # Decay spill markers
        if self.spills:
            self.spills = [(x, y, t - 1) for (x, y, t) in self.spills if t > 1]

        self._check_end()
        self.complete_action()
