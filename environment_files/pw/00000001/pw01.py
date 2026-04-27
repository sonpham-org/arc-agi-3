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
SPILL_TILT = 40        # water starts flowing past this tilt (was 50)
GRAVITY = 0.30
HVEL_SLOPE = 0.10      # tilt -> vx multiplier
HVEL_TILT_OFFSET = 18  # at tilt 40 vx=2.2; at tilt 60 vx=4.2

# Emission rate: scales smoothly across 40..60 so pouring isn't all-or-nothing.
def _emit_rate(tilt: int) -> int:
    if tilt < SPILL_TILT:
        return 0
    if tilt < 45:
        return 1
    if tilt < 50:
        return 2
    if tilt < 55:
        return 3
    if tilt < 60:
        return 4
    return 5

# ── Kettle sprite (local coords; pivot = bottom-centre of body) ────────────
# Layout (ly increasing downward; pivot at (0, 0) on body bottom row).
# Spout-tip kept at (5, -1) so the water trajectory stays the same as the
# original; the body, handle, and interior are scaled up around it.
#
#   ly\lx | -4 -3 -2 -1  0  1  2  3  4  5
#      -7 |  .  .  H  H  H  H  H  .  .  .   <- handle top arch
#      -6 |  .  H  .  .  .  .  .  H  .  .   <- handle slope
#      -5 |  .  H  .  .  .  .  .  H  .  .   <- handle slope
#      -4 |  .  B  B  B  B  B  B  B  .  .   <- body top (tapered)
#      -3 |  B  B  B  B  B  B  B  B  B  .   <- body
#      -2 |  B  B  B  B  B  B  B  B  S  S   <- body + spout tail
#      -1 |  B  B  B  B  B  B  B  B  S  S   <- body + spout tip (5,-1)
#       0 |  .  B  B  B  B  B  B  B  .  .   <- body bottom (pivot row)

KETTLE_BODY = [
    # ly=-4 (tapered top): lx -3..3
    (-3, -4), (-2, -4), (-1, -4), (0, -4), (1, -4), (2, -4), (3, -4),
    # ly=-3..-1: lx -4..4 (full belly)
    (-4, -3), (-3, -3), (-2, -3), (-1, -3), (0, -3), (1, -3), (2, -3), (3, -3), (4, -3),
    (-4, -2), (-3, -2), (-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2), (3, -2), (4, -2),
    (-4, -1), (-3, -1), (-2, -1), (-1, -1), (0, -1), (1, -1), (2, -1), (3, -1), (4, -1),
    # ly=0 (tapered bottom): lx -3..3
    (-3,  0), (-2,  0), (-1,  0), (0,  0), (1,  0), (2,  0), (3,  0),
]
KETTLE_HANDLE = [
    # Top arch
    (-2, -7), (-1, -7), (0, -7), (1, -7), (2, -7),
    # Side slopes — connect down to body top corners (lx -3, lx 3 at ly -4)
    (-3, -6), (3, -6),
    (-3, -5), (3, -5),
]
KETTLE_SPOUT = [
    (4, -2), (5, -2),
    (4, -1), (5, -1),
]
KETTLE_SPOUT_TIP = (5, -1)

# Body interior cells (used for "kettle water" rendering inside the body).
# The 7×3 inner block — leaves a 1-cell wall on every side.
KETTLE_INTERIOR = [
    (-3, -3), (-2, -3), (-1, -3), (0, -3), (1, -3), (2, -3), (3, -3),
    (-3, -2), (-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2), (3, -2),
    (-3, -1), (-2, -1), (-1, -1), (0, -1), (1, -1), (2, -1), (3, -1),
]
KETTLE_INTERIOR_TOP_LY = -3
KETTLE_INTERIOR_BOT_LY = -1
KETTLE_INTERIOR_CAPACITY = len(KETTLE_INTERIOR)


# ── Level data — all positions hardcoded, fully deterministic ──────────────
# kettle_pivot = world (x, y) where the kettle pivots
# cup_left, cup_right = wall x columns (inclusive)
# cup_top = mouth row (no top wall above this); cup_bottom = floor row of cup
# target_volume = water-pixel count inside cup interior to win
# kettle_volume = starting reservoir
# obstacles = list of (x0, y0, x1, y1) inclusive rectangles that block water
LIVES_PER_LEVEL = 5

# Levels are calibrated so water lands inside the cup at every tilt 40-60
# (no aim challenge). The challenge is timing — stop pouring before the
# water level overshoots the dotted target line. Kettle pivot, spout
# trajectory, and cup walls are tuned so a stream from any reasonable
# tilt arrives inside the rim. Going past the line (overflowing the rim)
# costs a life per drop.
LEVEL_DATA = [
    # L1: half-fill — easy first level. Plenty of margin.
    {
        'name': 'First Pour',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 42, 'cup_bottom': 60,
        'target_y': 51,
        'kettle_volume': 320,
        'obstacles': [],
    },
    # L2: leveled at full — fill cup right up to the brim, no overflow.
    {
        'name': 'To the Brim',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 44, 'cup_bottom': 60,
        'target_y': 45,
        'kettle_volume': 600,
        'obstacles': [],
    },
    # L3: precision target — 75% fill. Tight stop window.
    {
        'name': 'Precision',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 42, 'cup_bottom': 60,
        'target_y': 47,
        'kettle_volume': 480,
        'obstacles': [],
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
        self.cup_target_y = d['target_y']
        # target_volume drives the HUD progress bar (not the win check).
        inner_w = max(1, self.cup_right - self.cup_left - 1)
        fill_rows = max(1, self.cup_bottom - self.cup_target_y)
        self.target_volume = inner_w * fill_rows
        self.cup_volume = 0
        self.obstacles = list(d['obstacles'])
        self.lives = LIVES_PER_LEVEL
        self.spills = []

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
                    between_walls = (self.cup_left < ix < self.cup_right
                                     and iy < self.cup_top)
                    if in_cup:
                        self.water.add((ix, iy))
                    elif between_walls:
                        # Cup is full and the drop tried to land above the
                        # rim. Physically it cascades over the side and is
                        # lost; we just discard it. No life cost — the
                        # failure mode for overpouring is detected at
                        # settle-time below (highest_y stuck at the rim
                        # without the player stopping in time).
                        pass
                    else:
                        # Drop landed outside the cup walls entirely (off-aim
                        # — shouldn't happen with current level layouts but
                        # kept as a safety net).
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
        # 4 falling-sand passes for general gravity / diagonal slip behaviour…
        for _ in range(4):
            self._step_water_ca_once()
        # …followed by an active surface-leveling pass inside the cup. CA
        # alone is slow and prone to zigzag oscillations at this scale, so
        # we explicitly transfer water from tall columns to adjacent short
        # ones until heights are within 1 pixel everywhere. This makes the
        # cup surface flatten nearly instantly (the way real water would).
        for _ in range(20):
            if not self._level_cup_surface_once():
                break

    def _level_cup_surface_once(self) -> bool:
        # Compute the topmost water row per column inside the cup interior.
        # Returns True if any water moved (= surface still not flat).
        heights = {}
        for x in range(self.cup_left + 1, self.cup_right):
            top = None
            for y in range(self.cup_top, self.cup_bottom):
                if (x, y) in self.water:
                    top = y
                    break
            heights[x] = top if top is not None else self.cup_bottom

        def transfer(src_x: int, dst_x: int, src_h: int, dst_h: int) -> bool:
            # Move one water cell from `src_x` (taller, top at src_h) to
            # `dst_x` (shorter, top at dst_h). Refuses to put water above
            # the rim or below the floor.
            new_dst_h = dst_h - 1
            if new_dst_h < self.cup_top:
                return False  # destination column already at rim — no room
            new_src_h = src_h + 1
            if new_src_h > self.cup_bottom:
                return False  # nothing to take (shouldn't happen)
            if (dst_x, new_dst_h) in self.water:
                return False  # safety — slot already occupied
            self.water.discard((src_x, src_h))
            self.water.add((dst_x, new_dst_h))
            heights[src_x] = new_src_h
            heights[dst_x] = new_dst_h
            return True

        moved = False
        # Left-to-right sweep
        for x in range(self.cup_left + 1, self.cup_right - 1):
            h1, h2 = heights[x], heights[x + 1]
            if h2 - h1 >= 2 and transfer(x, x + 1, h1, h2):
                moved = True
            elif h1 - h2 >= 2 and transfer(x + 1, x, h2, h1):
                moved = True
        # Right-to-left sweep — symmetric, no left/right bias
        for x in range(self.cup_right - 2, self.cup_left, -1):
            h1, h2 = heights[x], heights[x + 1]
            if h2 - h1 >= 2 and transfer(x, x + 1, h1, h2):
                moved = True
            elif h1 - h2 >= 2 and transfer(x + 1, x, h2, h1):
                moved = True
        return moved

    def _step_water_ca_once(self):
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
            # 3. Sideways spread — water in self.water only ever lives
            # inside the cup interior (spilled drops are removed before they
            # hit the CA), so unconditional sideways flow naturally
            # auto-equalises the surface to a flat level.
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
        # Spilling water over the floor immediately loses lives — when out
        # of lives, the run ends.
        if self.lives <= 0:
            self.lose()
            return True

        settled = not self.particles and self._water_settled_stable()

        # Highest water point inside cup interior (lowest y in screen coords).
        highest_y = None
        for (x, y) in self.water:
            if (self.cup_left < x < self.cup_right
                    and self.cup_top <= y < self.cup_bottom):
                if highest_y is None or y < highest_y:
                    highest_y = y

        if settled:
            tolerance = 1  # ±1 row CA-jitter slack on either side of the line
            if highest_y is not None:
                if (self.cup_target_y - tolerance
                        <= highest_y
                        <= self.cup_target_y + tolerance):
                    # Settled water surface is at the dotted line — win.
                    self.next_level()
                    return True
                if highest_y < self.cup_target_y - tolerance:
                    # Surface above target = overpour — fail.
                    self.lose()
                    return True
            if self.kettle_water <= 0:
                # Below target and no water left to pour — underpour fail.
                self.lose()
                return True
        return False

    def _water_settled_stable(self) -> bool:
        # Stable when every pixel has solid (or water) directly below it
        # and cannot slip diagonally lower. The active surface-leveling
        # pass keeps the horizontal surface within 1 row everywhere, so
        # we don't need a sideways-flow check here — the win/lose
        # tolerance (±1 around target_y) already absorbs the residual
        # zigzag.
        for (x, y) in self.water:
            if y + 1 >= GH:
                continue
            if not (self._is_solid(x, y + 1) or (x, y + 1) in self.water):
                return False
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
