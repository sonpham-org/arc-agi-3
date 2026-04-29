# Author: Claude Opus 4.7 (1M context)
# Date: 2026-04-28 12:00
# PURPOSE: Pouring Water Son (ps01) — variant of pw01 with three new mechanics:
#   (1) the kettle pivot tracks the mouse position on every live tick, so
#   the player aims the spout by moving the cursor; (2) the water inside
#   the kettle is a true particle simulation — the reservoir is rendered as
#   N water cells settled at the world-y minima of the rotated interior
#   polygon, so the surface visibly tilts toward the spout when the kettle
#   tips; (3) winning requires the cup-water surface to sit within ±1 row
#   of the dotted target line for WIN_HOLD_TICKS (20) consecutive ticks —
#   the player must stop pouring AND let the surface flatten AND keep it
#   flat. Cup is also smaller than pw01 (12×12 outer, 11×11 interior) and
#   the game ships with a single level.
#   Integration: subclass of arcengine.ARCBaseGame, registered as game_id
#   "ps01" via metadata.json. Listed automatically by /api/games once the
#   environment_files/ps/00000001/ directory exists. Uses the same live-mode
#   ACTION6/ACTION7 contract as pw01; relies on a frontend change in
#   static/js/human-input.js + human-game.js to forward mouse position
#   {x, y} on every live tick.
# SRP/DRY check: Pass — searched environment_files/* for other live
#   physics games; pw01 is the only sibling. Rotation helper, falling-sand
#   CA, and surface-leveling logic are duplicated from pw01 because they
#   are intrinsic to each game's behaviour and the pw01 header explicitly
#   notes they shouldn't be lifted into shared utilities.

import math
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# ── Grid geometry ──────────────────────────────────────────────────────────
GW, GH = 64, 64
HUD_H = 4
PLAY_TOP = HUD_H
FLOOR_Y = GH - 1

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
TILT_PER_CLICK = 2
TILT_PER_RELEASE = 1
SPILL_TILT = 40
GRAVITY = 0.30
HVEL_SLOPE = 0.10
HVEL_TILT_OFFSET = 18

# Mouse follow: snap pivot directly to mouse position each tick (clamped to
# the safe play area so the bigger kettle never enters the HUD or the cup).
# Kettle extends from lx=-5..7 and ly=-9..0, so leave room on all sides.
PIVOT_X_MIN, PIVOT_X_MAX = 12, 28
PIVOT_Y_MIN, PIVOT_Y_MAX = 14, 30

# Win condition: water level must sit within ±tolerance of target_y for
# WIN_HOLD_TICKS consecutive ticks.
WIN_HOLD_TICKS = 20
WIN_TOLERANCE = 1


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
# Big kettle: 11-wide × 7-tall body with a 9×5 = 45-cell interior. Starts
# half-full so the water has empty cells to slosh into when tipped.
#
#   ly\lx | -5 -4 -3 -2 -1  0  1  2  3  4  5  6  7
#      -9 |  .  .  H  H  H  H  H  H  H  .  .  .  .   <- handle top arch
#      -8 |  .  H  .  .  .  .  .  .  .  H  .  .  .   <- handle slope
#      -7 |  .  H  .  .  .  .  .  .  .  H  .  .  .
#      -6 |  .  .  B  B  B  B  B  B  B  .  .  .  .   <- body top tapered
#      -5 |  B  B  B  B  B  B  B  B  B  B  B  .  .   <- body
#      -4 |  B  B  B  B  B  B  B  B  B  B  B  .  .
#      -3 |  B  B  B  B  B  B  B  B  B  B  B  S  S   <- body + spout tail
#      -2 |  B  B  B  B  B  B  B  B  B  B  B  S  S   <- body + spout tip (7,-2)
#      -1 |  B  B  B  B  B  B  B  B  B  B  B  .  .
#       0 |  .  .  B  B  B  B  B  B  B  .  .  .  .   <- body bottom tapered

KETTLE_BODY = [
    # ly=-6 (top tapered): lx -3..3
    (-3, -6), (-2, -6), (-1, -6), (0, -6), (1, -6), (2, -6), (3, -6),
    # ly=-5..-1 (full belly): lx -5..5
    *[(lx, -5) for lx in range(-5, 6)],
    *[(lx, -4) for lx in range(-5, 6)],
    *[(lx, -3) for lx in range(-5, 6)],
    *[(lx, -2) for lx in range(-5, 6)],
    *[(lx, -1) for lx in range(-5, 6)],
    # ly=0 (bottom tapered): lx -3..3
    (-3,  0), (-2,  0), (-1,  0), (0,  0), (1,  0), (2,  0), (3,  0),
]
KETTLE_HANDLE = [
    # Top arch
    (-3, -9), (-2, -9), (-1, -9), (0, -9), (1, -9), (2, -9), (3, -9),
    # Side slopes
    (-4, -8), (4, -8),
    (-4, -7), (4, -7),
]
KETTLE_SPOUT = [
    (6, -3), (7, -3),
    (6, -2), (7, -2),
]
KETTLE_SPOUT_TIP = (7, -2)

# Interior: 9 wide × 5 tall = 45 cells (lx -4..4, ly -5..-1).
KETTLE_INTERIOR = [
    (lx, ly)
    for ly in range(-5, 0)
    for lx in range(-4, 5)
]
KETTLE_INTERIOR_CAPACITY = len(KETTLE_INTERIOR)  # 45
INTERIOR_SET = set(KETTLE_INTERIOR)
# Spout-feeder cells: rightmost interior column (lx=4) at the spout's height.
# Water that reaches these cells is what physically pours out of the spout.
SPOUT_FEEDER_CELLS = [(4, -3), (4, -2)]


# ── Level data — single level (per design: focus on getting L1 right) ─────
LEVEL_DATA = [
    {
        'name': 'Steady Pour',
        # Cup doubled in each dimension (was 9×10): 18×20 outer → 17×19 interior.
        # cup_left..cup_right: 18-wide; cup_top..cup_bottom: 20-tall.
        'kettle_pivot_init': (16, 18),
        'cup_left': 30, 'cup_right': 47,
        'cup_top': 38, 'cup_bottom': 57,
        'target_y': 47,  # roughly mid-cup
        # Pour volume — needs to fill a 17×11-row band to reach the line.
        # Cup interior at target = 17 × (57-47) ≈ 170 cells; kettle holds
        # half of its 45 visible + a hidden back-reservoir for the rest.
        'kettle_volume': 280,
        'obstacles': [],
    },
]

levels = [
    Level(sprites=[], grid_size=(GW, GH), name=d['name'], data=d)
    for d in LEVEL_DATA
]


# ── Rotation helper ────────────────────────────────────────────────────────

def _rotate(lx: float, ly: float, tilt_deg: int) -> tuple[float, float]:
    """Rotate local (lx, ly) by tilt_deg clockwise on screen (y-down)."""
    t = math.radians(tilt_deg)
    c, s = math.cos(t), math.sin(t)
    return (lx * c - ly * s, lx * s + ly * c)


# ── Display ────────────────────────────────────────────────────────────────

class PourDisplay(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        g = self.game

        frame[:, :] = C_BLACK
        frame[FLOOR_Y, :] = C_DGRAY

        for (x0, y0, x1, y1) in g.obstacles:
            x0c, x1c = max(0, x0), min(GW - 1, x1)
            y0c, y1c = max(0, y0), min(GH - 1, y1)
            frame[y0c:y1c + 1, x0c:x1c + 1] = C_DGRAY

        # Cup walls
        cl, cr = g.cup_left, g.cup_right
        ct, cb = g.cup_top, g.cup_bottom
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

        # ── Kettle ─────────────────────────────────────────────────────────
        px, py = g.kettle_pivot
        tilt = g.tilt

        body_world = {}
        for (lx, ly) in KETTLE_BODY:
            wx, wy = _rotate(lx, ly, tilt)
            ix, iy = int(round(px + wx)), int(round(py + wy))
            if 0 <= ix < GW and 0 <= iy < GH:
                body_world[(ix, iy)] = C_DGRAY

        # Simulated kettle water — each particle has its own (lx, ly) cell in
        # the kettle's local frame. The simulation runs in local coords with
        # a gravity vector rotated by -tilt, so when the kettle tips the
        # particles physically pile up on the down-tilted side and the
        # surface flattens with falling-sand mechanics. Render each particle
        # at its world-frame cell.
        for (lx, ly) in g.kettle_particles:
            wx, wy = _rotate(lx, ly, tilt)
            ix, iy = int(round(px + wx)), int(round(py + wy))
            if 0 <= ix < GW and 0 <= iy < GH:
                body_world[(ix, iy)] = C_BLUE

        # Spout (overlaid after body so spout colour wins)
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
                if cl < x < cr and ct <= y < cb:
                    frame[y, x] = C_LBLUE
                else:
                    frame[y, x] = C_BLUE

        # ── HUD ────────────────────────────────────────────────────────────
        frame[0:HUD_H, :] = C_VDGRAY

        # Tilt bar (row 1)
        bar_y = 1
        for x in range(60):
            if x < g.tilt:
                if g.tilt >= SPILL_TILT:
                    frame[bar_y, 2 + x] = C_ORANGE
                else:
                    frame[bar_y, 2 + x] = C_GRAY
            else:
                frame[bar_y, 2 + x] = C_BLACK

        # Stable-hold progress bar (row 2): yellow → green ramp filling as
        # stable_ticks → WIN_HOLD_TICKS. Replaces pw01's volume-progress bar
        # because the win condition is now time-on-target, not volume.
        prog_y = 2
        prog_w = 50
        filled = int(prog_w * g.stable_ticks / max(1, WIN_HOLD_TICKS))
        for x in range(prog_w):
            if x < filled:
                ratio = g.stable_ticks / max(1, WIN_HOLD_TICKS)
                frame[prog_y, 2 + x] = C_GREEN if ratio >= 0.999 else C_YELLOW
            else:
                frame[prog_y, 2 + x] = C_BLACK

        # Spill flashes
        for (sx, sy, ttl) in g.spills:
            if 0 <= sx < GW and PLAY_TOP <= sy < GH and ttl > 3:
                frame[sy, sx] = C_RED

        return frame


# ── Game ───────────────────────────────────────────────────────────────────

class Ps01(ARCBaseGame):
    def __init__(self):
        self.display = PourDisplay(self)

        self.tilt = 0
        self.tick = 0
        self.water = set()
        self.particles = []
        self.kettle_pivot = (32, 18)
        self.kettle_volume_initial = 0
        self.kettle_particles = []  # list[(lx, ly)] — water cells in kettle local frame
        self.cup_left = 0
        self.cup_right = 0
        self.cup_top = 0
        self.cup_bottom = 0
        self.cup_target_y = 0
        self.cup_volume = 0
        self.obstacles = []
        self.spills = []
        self.stable_ticks = 0  # consecutive ticks the surface has been on target

        super().__init__(
            'ps', levels,
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
        self.kettle_pivot = d['kettle_pivot_init']
        self.kettle_volume_initial = d['kettle_volume']
        # Seed the kettle ~half-full so the water has empty cells to slosh
        # into as the player tilts. Stack from the bottom of the interior
        # (local-frame, which == world-frame at tilt=0).
        self.kettle_particles = []
        sorted_interior = sorted(KETTLE_INTERIOR, key=lambda p: (-p[1], p[0]))
        visible_seed = min(d['kettle_volume'], KETTLE_INTERIOR_CAPACITY // 2)
        for i in range(visible_seed):
            self.kettle_particles.append(sorted_interior[i])
        # The rest sits in a hidden back-reservoir that drips into the
        # kettle (top-back corner) as visible particles leave through the
        # spout. The visible water level stays around half-full while
        # there's reservoir left, then drains for real once it's empty.
        self._kettle_reservoir = max(0, d['kettle_volume'] - visible_seed)
        self.cup_left = d['cup_left']
        self.cup_right = d['cup_right']
        self.cup_top = d['cup_top']
        self.cup_bottom = d['cup_bottom']
        self.cup_target_y = d['target_y']
        self.cup_volume = 0
        self.obstacles = list(d['obstacles'])
        self.spills = []
        self.stable_ticks = 0

    # ── Mouse-driven pivot ──────────────────────────────────────────────────

    def _update_pivot_from_mouse(self):
        """If the action carries mouse coords, snap pivot to (x, y) clamped
        to the safe play area. Missing coords → leave pivot unchanged."""
        data = getattr(self.action, 'data', None) or {}
        mx = data.get('x', None)
        my = data.get('y', None)
        if mx is None or my is None:
            return
        try:
            mx, my = int(mx), int(my)
        except (TypeError, ValueError):
            return
        mx = max(PIVOT_X_MIN, min(PIVOT_X_MAX, mx))
        my = max(PIVOT_Y_MIN, min(PIVOT_Y_MAX, my))
        self.kettle_pivot = (mx, my)

    # ── Kettle-water local-frame falling-sand ───────────────────────────────

    def _step_kettle_water(self):
        """Advance the in-kettle water sim one tick. Operates in the kettle's
        LOCAL frame (where the interior is a fixed 7×3 box) and uses a
        gravity vector rotated by -tilt so the sand falls toward whichever
        wall is currently lowest in world space. Result: water visibly piles
        up on the spout side as the kettle tips."""
        if not self.kettle_particles:
            return
        # Local-frame gravity: world-(0,1) rotated by -tilt.
        t = math.radians(self.tilt)
        gx_f, gy_f = math.sin(t), math.cos(t)
        # Discrete primary direction (one of 8 neighbours, picked from the
        # angle of (gx_f, gy_f)).
        def _disc(v):
            if v > 0.3827:   # > sin(22.5°)
                return 1
            if v < -0.3827:
                return -1
            return 0
        gdx, gdy = _disc(gx_f), _disc(gy_f)
        if gdx == 0 and gdy == 0:
            gdy = 1
        # Diagonal alternatives perpendicular-ish to gravity, biased toward
        # the steeper component so water "rolls" off the high side.
        # Candidate moves in priority order:
        #   1. straight along gravity
        #   2. the two diagonals adjacent to the gravity direction
        candidates_dirs = [(gdx, gdy)]
        if gdx == 0:
            candidates_dirs += [(-1, gdy), (1, gdy)]
        elif gdy == 0:
            candidates_dirs += [(gdx, -1), (gdx, 1)]
        else:
            # Pure diagonal — also try the two cardinal components.
            candidates_dirs += [(gdx, 0), (0, gdy)]

        interior = INTERIOR_SET
        # Sort particles bottom-up in world-y so lowest piles up first
        def world_y(p):
            return p[0] * gx_f + p[1] * gy_f  # = world-y component (= dot with gravity)
        particles_sorted = sorted(self.kettle_particles, key=lambda p: -world_y(p))
        occupied = set(particles_sorted)
        new_set = set(particles_sorted)
        for (lx, ly) in particles_sorted:
            for (dx, dy) in candidates_dirs:
                nx, nly = lx + dx, ly + dy
                if (nx, nly) not in interior:
                    continue
                if (nx, nly) in occupied:
                    continue
                # Move
                occupied.discard((lx, ly))
                occupied.add((nx, nly))
                new_set.discard((lx, ly))
                new_set.add((nx, nly))
                break
        self.kettle_particles = list(new_set)

    # ── Solid-cell test ─────────────────────────────────────────────────────

    def _is_solid(self, x: int, y: int) -> bool:
        if not (0 <= x < GW and 0 <= y < GH):
            return True
        if y >= FLOOR_Y:
            return True
        if self.cup_top <= y <= self.cup_bottom:
            if x == self.cup_left or x == self.cup_right:
                return True
        if y == self.cup_bottom and self.cup_left <= x <= self.cup_right:
            return True
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
            tx = p['fx'] + p['vx']
            ty = p['fy'] + p['vy']
            cx, cy = p['fx'], p['fy']
            settled = False
            reached = False
            for _ in range(8):
                if int(cx) == int(tx) and int(cy) == int(ty):
                    reached = True
                    break
                dx = (1 if int(tx) > int(cx) else (-1 if int(tx) < int(cx) else 0))
                dy = (1 if int(ty) > int(cy) else (-1 if int(ty) < int(cy) else 0))
                tried = False
                for sx, sy in [(dx, dy), (0, dy), (dx, 0)]:
                    if sx == 0 and sy == 0:
                        continue
                    nix, niy = int(cx) + sx, int(cy) + sy
                    if self._is_solid(nix, niy) or (nix, niy) in self.water:
                        continue
                    cx = float(nix) + (cx - int(cx))
                    cy = float(niy) + (cy - int(cy))
                    tried = True
                    break
                if not tried:
                    settled = True
                    break
            if reached:
                cx, cy = tx, ty
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
                        # Cascades over the rim — discarded.
                        pass
                    else:
                        # Off-aim spill — flash a marker so the player sees
                        # they missed (no life cost in ps01; the win check
                        # is based on stable on-target time, not lives).
                        self.spills.append((ix, iy, 6))
                continue
            p['fx'], p['fy'] = cx, cy
            new_particles.append(p)
        self.particles = new_particles

    # ── Cellular automaton + active surface levelling for cup water ─────────

    def _step_water_ca(self):
        if not self.water:
            return
        for _ in range(4):
            self._step_water_ca_once()
        for _ in range(20):
            if not self._level_cup_surface_once():
                break

    def _level_cup_surface_once(self) -> bool:
        heights = {}
        for x in range(self.cup_left + 1, self.cup_right):
            top = None
            for y in range(self.cup_top, self.cup_bottom):
                if (x, y) in self.water:
                    top = y
                    break
            heights[x] = top if top is not None else self.cup_bottom

        def transfer(src_x: int, dst_x: int, src_h: int, dst_h: int) -> bool:
            new_dst_h = dst_h - 1
            if new_dst_h < self.cup_top:
                return False
            new_src_h = src_h + 1
            if new_src_h > self.cup_bottom:
                return False
            if (dst_x, new_dst_h) in self.water:
                return False
            self.water.discard((src_x, src_h))
            self.water.add((dst_x, new_dst_h))
            heights[src_x] = new_src_h
            heights[dst_x] = new_dst_h
            return True

        moved = False
        for x in range(self.cup_left + 1, self.cup_right - 1):
            h1, h2 = heights[x], heights[x + 1]
            if h2 - h1 >= 2 and transfer(x, x + 1, h1, h2):
                moved = True
            elif h1 - h2 >= 2 and transfer(x + 1, x, h2, h1):
                moved = True
        for x in range(self.cup_right - 2, self.cup_left, -1):
            h1, h2 = heights[x], heights[x + 1]
            if h2 - h1 >= 2 and transfer(x, x + 1, h1, h2):
                moved = True
            elif h1 - h2 >= 2 and transfer(x + 1, x, h2, h1):
                moved = True
        return moved

    def _step_water_ca_once(self):
        occupied = set(self.water)
        order_left_first = (self.tick % 2 == 0)
        x_key = (lambda p: p[0]) if order_left_first else (lambda p: -p[0])
        sorted_water = sorted(self.water, key=lambda p: (-p[1], x_key(p)))
        for (x, y) in sorted_water:
            candidates = [(x, y + 1)]
            if order_left_first:
                candidates += [(x - 1, y + 1), (x + 1, y + 1)]
            else:
                candidates += [(x + 1, y + 1), (x - 1, y + 1)]
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
        # Emission requires (a) tilt past SPILL_TILT and (b) at least one
        # simulated water cell touching the spout exit (lx=3, ly in {-1, -2}).
        # That means the kettle physics actually has to feed the spout — at
        # tilt 0 with full water, no emission, because the surface sits
        # below the spout opening. Tip the kettle, the sloshing brings water
        # to the spout-side wall, and then it pours.
        rate = _emit_rate(self.tilt)
        if rate == 0:
            return
        if not self.kettle_particles and self._kettle_reservoir <= 0:
            return
        sx, sy = self._spout_tip_world()
        emit_x = sx
        emit_y = sy + 1.0
        vx = max(0.0, (self.tilt - HVEL_TILT_OFFSET) * HVEL_SLOPE)
        vy = 0.4
        emitted = 0
        for _ in range(rate):
            # Find the highest-priority feeder cell that has water and emit
            # one particle from it. Highest priority = lowest in world frame
            # (= where water actually piles up at the current tilt).
            chosen = None
            best_wy = None
            for cell in SPOUT_FEEDER_CELLS:
                if cell in self.kettle_particles:
                    _, wy = _rotate(cell[0], cell[1], self.tilt)
                    if best_wy is None or wy > best_wy:
                        best_wy = wy
                        chosen = cell
            if chosen is None:
                break
            self.kettle_particles.remove(chosen)
            self.particles.append({
                'fx': emit_x, 'fy': emit_y, 'vx': vx, 'vy': vy,
            })
            emitted += 1
            # Refill from the hidden back-reservoir at the top-back interior
            # cell. With the bigger kettle, top-back is (-4, -5).
            if self._kettle_reservoir > 0:
                refill_cell = (-4, -5)
                if refill_cell not in self.kettle_particles:
                    self.kettle_particles.append(refill_cell)
                    self._kettle_reservoir -= 1

    # ── Cup volume + win check ──────────────────────────────────────────────

    def _recount_cup(self):
        cl, cr, ct, cb = self.cup_left, self.cup_right, self.cup_top, self.cup_bottom
        n = 0
        for (x, y) in self.water:
            if cl < x < cr and ct <= y < cb:
                n += 1
        self.cup_volume = n

    def _highest_y_in_cup(self):
        highest_y = None
        for (x, y) in self.water:
            if (self.cup_left < x < self.cup_right
                    and self.cup_top <= y < self.cup_bottom):
                if highest_y is None or y < highest_y:
                    highest_y = y
        return highest_y

    def _surface_is_on_target(self) -> bool:
        # On-target iff: no in-flight particles AND water settled AND
        # highest_y is within ±tolerance of target_y. Pour-in-progress
        # always fails because particles are still flying.
        if self.particles:
            return False
        if not self._water_settled_stable():
            return False
        h = self._highest_y_in_cup()
        if h is None:
            return False
        return (self.cup_target_y - WIN_TOLERANCE
                <= h
                <= self.cup_target_y + WIN_TOLERANCE)

    def _check_end(self):
        if self._surface_is_on_target():
            self.stable_ticks += 1
            if self.stable_ticks >= WIN_HOLD_TICKS:
                self.next_level()
                return True
        else:
            self.stable_ticks = 0
        return False

    def _water_settled_stable(self) -> bool:
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

        # Pivot follows mouse ONLY while the player is holding the click
        # (ACTION6). On release (ACTION7), the kettle stays put — that's how
        # you stop pouring without also losing your aim.
        if aid == 6:
            self._update_pivot_from_mouse()
            self.tilt = min(TILT_MAX, self.tilt + TILT_PER_CLICK)
        else:
            self.tilt = max(0, self.tilt - TILT_PER_RELEASE)

        self.tick += 1

        self._step_kettle_water()
        self._emit_pour()
        self._step_particles()
        self._step_water_ca()
        self._recount_cup()

        if self.spills:
            self.spills = [(x, y, t - 1) for (x, y, t) in self.spills if t > 1]

        self._check_end()
        self.complete_action()
