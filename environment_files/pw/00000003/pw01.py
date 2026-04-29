# Author: Claude Opus 4.7 (1M context)
# Date: 2026-04-29 10:00
# PURPOSE: Pouring Water v3 (pw01) — adds a player-controlled thermostat
#   on top of the v2 heat mechanic. W (ACT1) raises a -5..+5 thermostat
#   integer; S (ACT2) lowers it. Each tick the thermostat value is added
#   to every water pixel, the kettle bulk temp, and every ice cell — a
#   global "stove knob" that stacks on top of fire/cold/drift logic. HUD
#   shows the thermostat as a strip lit outward from centre. Other than
#   adding 1, 2 to available_actions and the new state/render/step
#   wiring, this is identical to v2.
#
#   v2 mechanic recap: per-pixel water temp, evaporate at >=100, freeze
#   at <=0, smoke at >=50. Ice melts gradually under heat. Levels 4-6
#   require the heat mechanic to win.
# SRP/DRY check: Pass — thermostat lives with the game (no existing
#   shared "global temp delta" utility).

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
SPILL_TILT = 40        # water starts flowing past this tilt
GRAVITY = 0.30
HVEL_SLOPE = 0.10
HVEL_TILT_OFFSET = 18

# ── Heat mechanic constants ────────────────────────────────────────────────
HEAT_PER_TICK = 4       # adjacency to fire raises temp by this much / tick
COLD_PER_TICK = 4       # adjacency to ice / cold lowers temp by this much / tick
DRIFT_PER_TICK = 1      # otherwise water drifts toward ambient by this much / tick
SMOKE_TEMP = 50         # at or above: water emits smoke periodically
EVAP_TEMP = 100         # at or above: water evaporates
FREEZE_TEMP = 0         # at or below: water freezes into ice
SMOKE_PERIOD = 4        # 1 smoke puff every N ticks per smoke-emitting cell
SMOKE_RISE_PERIOD = 2   # smoke moves up every N ticks
SMOKE_MAX_AGE = 12      # smoke fades after this many ticks
ICE_BASELINE = -10      # ice cells with no adjacent fire drift toward this temp
MELT_THRESHOLD = 1      # ice converts back to water at this temp

# ── Thermostat (player W/S control) ────────────────────────────────────────
THERMOSTAT_MAX = 5      # absolute cap; thermostat in [-5, +5]
THERMOSTAT_COOLDOWN = 5 # ticks between thermostat changes (so 30-FPS held
                        # W doesn't slam to +5 in five frames)

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

KETTLE_BODY = [
    (-3, -4), (-2, -4), (-1, -4), (0, -4), (1, -4), (2, -4), (3, -4),
    (-4, -3), (-3, -3), (-2, -3), (-1, -3), (0, -3), (1, -3), (2, -3), (3, -3), (4, -3),
    (-4, -2), (-3, -2), (-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2), (3, -2), (4, -2),
    (-4, -1), (-3, -1), (-2, -1), (-1, -1), (0, -1), (1, -1), (2, -1), (3, -1), (4, -1),
    (-3,  0), (-2,  0), (-1,  0), (0,  0), (1,  0), (2,  0), (3,  0),
]
KETTLE_HANDLE = [
    (-2, -7), (-1, -7), (0, -7), (1, -7), (2, -7),
    (-3, -6), (3, -6),
    (-3, -5), (3, -5),
]
KETTLE_SPOUT = [
    (4, -2), (5, -2),
    (4, -1), (5, -1),
]
KETTLE_SPOUT_TIP = (5, -1)

KETTLE_INTERIOR = [
    (-3, -3), (-2, -3), (-1, -3), (0, -3), (1, -3), (2, -3), (3, -3),
    (-3, -2), (-2, -2), (-1, -2), (0, -2), (1, -2), (2, -2), (3, -2),
    (-3, -1), (-2, -1), (-1, -1), (0, -1), (1, -1), (2, -1), (3, -1),
]
KETTLE_INTERIOR_TOP_LY = -3
KETTLE_INTERIOR_BOT_LY = -1
KETTLE_INTERIOR_CAPACITY = len(KETTLE_INTERIOR)


# ── Level data ─────────────────────────────────────────────────────────────
LIVES_PER_LEVEL = 5

LEVEL_DATA = [
    # L1: half-fill — easy first level. (unchanged from v1)
    {
        'name': 'First Pour',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 42, 'cup_bottom': 60,
        'target_y': 51,
        'kettle_volume': 320,
        'obstacles': [],
        'kettle_temp': 25, 'ambient_temp': 25,
        'heat_sources': [], 'cold_sources': [],
    },
    # L2: leveled at full. (unchanged)
    {
        'name': 'To the Brim',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 44, 'cup_bottom': 60,
        'target_y': 45,
        'kettle_volume': 600,
        'obstacles': [],
        'kettle_temp': 25, 'ambient_temp': 25,
        'heat_sources': [], 'cold_sources': [],
    },
    # L3: precision target. (unchanged)
    {
        'name': 'Precision',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 42, 'cup_bottom': 60,
        'target_y': 47,
        'kettle_volume': 480,
        'obstacles': [],
        'kettle_temp': 25, 'ambient_temp': 25,
        'heat_sources': [], 'cold_sources': [],
    },
    # L4: BOILING CUP — fire strip just under the cup floor.
    {
        'name': 'Boiling Cup',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 42, 'cup_bottom': 60,
        'target_y': 51,
        'kettle_volume': 600,
        'obstacles': [],
        'kettle_temp': 25, 'ambient_temp': 25,
        'heat_sources': [(29, 61, 57, 62)],
        'cold_sources': [],
    },
    # L5: FROZEN CUP — cold strip just under the cup floor (mirror of L4).
    # Settled water at the bottom of the cup chills toward freezing; the
    # warm kettle (kettle_temp=60) gives a thermal head start so droplets
    # arrive hot enough to keep the surface above zero before pour ends.
    # If pour rate drops too low, the bottom freezes into ice, ice acts
    # as another cold source, and the column freezes upward.
    {
        'name': 'Frozen Cup',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 42, 'cup_bottom': 60,
        'target_y': 51,
        'kettle_volume': 540,
        'obstacles': [],
        'kettle_temp': 60, 'ambient_temp': 25,
        'heat_sources': [],
        'cold_sources': [(29, 61, 57, 62)],
    },
    # L6: HEAT GAUNTLET — fire bar across the air column the spout arc
    # passes through. With kettle_temp = 85 the kettle is already smoking;
    # drops gain +4 °C per tick while adjacent to fire. At low tilt (vx ~2)
    # drops spend 4-5 ticks crossing the bar and evaporate mid-air. At
    # high tilt (vx ~4) they cross in 2 ticks and arrive hot but intact.
    {
        'name': 'Heat Gauntlet',
        'kettle_pivot': (18, 24),
        'cup_left': 28, 'cup_right': 58,
        'cup_top': 42, 'cup_bottom': 60,
        'target_y': 51,
        'kettle_volume': 700,
        'obstacles': [],
        'kettle_temp': 85, 'ambient_temp': 25,
        'heat_sources': [(24, 30, 30, 32)],
        'cold_sources': [],
    },
]

levels = [
    Level(sprites=[], grid_size=(GW, GH), name=d['name'], data=d)
    for d in LEVEL_DATA
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _rotate(lx: float, ly: float, tilt_deg: int) -> tuple[float, float]:
    """Rotate local (lx, ly) by tilt_deg clockwise on screen (y-down)."""
    t = math.radians(tilt_deg)
    c, s = math.cos(t), math.sin(t)
    return (lx * c - ly * s, lx * s + ly * c)


def _in_any_rect(x: int, y: int, rects: list) -> bool:
    for (x0, y0, x1, y1) in rects:
        if x0 <= x <= x1 and y0 <= y <= y1:
            return True
    return False


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

        # Heat sources (drawn before water so water on top is visible)
        for (x0, y0, x1, y1) in g.heat_sources:
            x0c, x1c = max(0, x0), min(GW - 1, x1)
            y0c, y1c = max(PLAY_TOP, y0), min(GH - 1, y1)
            if x0c <= x1c and y0c <= y1c:
                frame[y0c:y1c + 1, x0c:x1c + 1] = C_RED

        # Cold sources
        for (x0, y0, x1, y1) in g.cold_sources:
            x0c, x1c = max(0, x0), min(GW - 1, x1)
            y0c, y1c = max(PLAY_TOP, y0), min(GH - 1, y1)
            if x0c <= x1c and y0c <= y1c:
                frame[y0c:y1c + 1, x0c:x1c + 1] = C_LBLUE

        # Obstacles
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

        # Kettle (rotated)
        px, py = g.kettle_pivot
        tilt = g.tilt
        body_world = {}
        for (lx, ly) in KETTLE_BODY:
            wx, wy = _rotate(lx, ly, tilt)
            ix, iy = int(round(px + wx)), int(round(py + wy))
            if 0 <= ix < GW and 0 <= iy < GH:
                body_world[(ix, iy)] = C_DGRAY

        if g.kettle_water > 0:
            interior_world = []
            for (lx, ly) in KETTLE_INTERIOR:
                wx, wy = _rotate(lx, ly, tilt)
                ix, iy = int(round(px + wx)), int(round(py + wy))
                interior_world.append((ix, iy))
            interior_world.sort(key=lambda p: -p[1])
            fill_count = min(
                len(interior_world),
                int(round(g.kettle_water / max(1, g.kettle_volume_initial)
                          * len(interior_world))),
            )
            # Pick kettle-water tint by reservoir temp.
            if g.kettle_temp >= EVAP_TEMP - 10:
                kw_col = C_RED
            elif g.kettle_temp >= SMOKE_TEMP:
                kw_col = C_LMAGENTA
            elif g.kettle_temp <= FREEZE_TEMP + 5:
                kw_col = C_LBLUE
            else:
                kw_col = C_BLUE
            for i in range(fill_count):
                ix, iy = interior_world[i]
                if 0 <= ix < GW and 0 <= iy < GH:
                    body_world[(ix, iy)] = kw_col

        for (lx, ly) in KETTLE_SPOUT:
            wx, wy = _rotate(lx, ly, tilt)
            ix, iy = int(round(px + wx)), int(round(py + wy))
            if 0 <= ix < GW and 0 <= iy < GH:
                body_world[(ix, iy)] = C_DGRAY

        for (lx, ly) in KETTLE_HANDLE:
            wx, wy = _rotate(lx, ly, tilt)
            ix, iy = int(round(px + wx)), int(round(py + wy))
            if 0 <= ix < GW and 0 <= iy < GH:
                body_world[(ix, iy)] = C_GRAY

        for (ix, iy), col in body_world.items():
            if iy >= PLAY_TOP:
                frame[iy, ix] = col

        # Ice (drawn after kettle so it shows up over fire if overlap)
        for (x, y) in g.ice:
            if 0 <= x < GW and PLAY_TOP <= y < GH:
                frame[y, x] = C_WHITE

        # In-flight droplets — colour by temp
        for p in g.particles:
            ix, iy = int(p['fx']), int(p['fy'])
            if 0 <= ix < GW and PLAY_TOP <= iy < GH:
                t = p.get('temp', 25)
                if t >= EVAP_TEMP - 10:
                    frame[iy, ix] = C_RED
                elif t >= SMOKE_TEMP:
                    frame[iy, ix] = C_LMAGENTA
                else:
                    frame[iy, ix] = C_LBLUE

        # Settled water — colour by temp
        for (x, y) in g.water:
            if 0 <= x < GW and PLAY_TOP <= y < GH:
                t = g.water_temp.get((x, y), 25)
                in_cup = cl < x < cr and ct <= y < cb
                if t >= EVAP_TEMP - 10:
                    frame[y, x] = C_RED
                elif t >= SMOKE_TEMP:
                    frame[y, x] = C_LMAGENTA
                elif t <= FREEZE_TEMP + 5:
                    frame[y, x] = C_LBLUE
                elif in_cup:
                    frame[y, x] = C_LBLUE
                else:
                    frame[y, x] = C_BLUE

        # Smoke (drawn last so it's always on top)
        for s in g.smoke:
            sx, sy = s['x'], s['y']
            if 0 <= sx < GW and PLAY_TOP <= sy < GH:
                frame[sy, sx] = C_LGRAY

        # ── HUD ────────────────────────────────────────────────────────────
        frame[0:HUD_H, :] = C_VDGRAY

        bar_y = 1
        for x in range(60):
            if x < g.tilt:
                if g.tilt >= SPILL_TILT:
                    frame[bar_y, 2 + x] = C_ORANGE
                else:
                    frame[bar_y, 2 + x] = C_GRAY
            else:
                frame[bar_y, 2 + x] = C_BLACK

        prog_y = 2
        prog_w = 50
        cur = min(g.cup_volume, g.target_volume)
        filled = int(prog_w * cur / max(1, g.target_volume))
        for x in range(prog_w):
            if x < filled:
                frame[prog_y, 2 + x] = C_GREEN
            else:
                frame[prog_y, 2 + x] = C_BLACK

        for i in range(g.lives):
            sx = 54 + i * 2
            if sx + 1 < GW:
                frame[prog_y, sx] = C_RED
                frame[prog_y, sx + 1] = C_RED

        for (sx, sy, ttl) in g.spills:
            if 0 <= sx < GW and PLAY_TOP <= sy < GH and ttl > 3:
                frame[sy, sx] = C_RED

        # Thermostat strip on HUD row 3: 11 cells centred near right edge,
        # one cell per thermostat step. Centre cell is always lit gray
        # (the "off" position). Outward cells light orange (positive
        # thermostat = heat) or light-blue (negative = cold) up to abs
        # value of thermostat.
        therm_y = 3
        therm_centre_x = 36
        for i in range(-THERMOSTAT_MAX, THERMOSTAT_MAX + 1):
            cx = therm_centre_x + i
            if not (0 <= cx < GW):
                continue
            if i == 0:
                frame[therm_y, cx] = C_GRAY
            elif i > 0:
                frame[therm_y, cx] = C_ORANGE if i <= g.thermostat else C_BLACK
            else:
                frame[therm_y, cx] = C_LBLUE if i >= g.thermostat else C_BLACK

        return frame


# ── Game ───────────────────────────────────────────────────────────────────

class Pw01(ARCBaseGame):
    def __init__(self):
        self.display = PourDisplay(self)

        self.tilt = 0
        self.tick = 0
        self.thermostat = 0       # player stove knob, -5..+5
        self._therm_cooldown = 0  # ticks remaining until next W/S accepted
        self.water = set()
        self.water_temp = {}      # (x,y) -> int temperature
        self.particles = []
        self.smoke = []           # list[{'x','y','age'}]
        self.ice = set()          # frozen cells (act as solid)
        self.ice_temp = {}        # (x,y) -> int temperature for ice cells
        self.heat_sources = []
        self.cold_sources = []
        self.kettle_pivot = (16, 24)
        self.kettle_volume_initial = 0
        self.kettle_water = 0
        self.kettle_temp = 25
        self.ambient_temp = 25
        self.cup_left = 0
        self.cup_right = 0
        self.cup_top = 0
        self.cup_bottom = 0
        self.cup_target_y = 0
        self.target_volume = 0
        self.cup_volume = 0
        self.obstacles = []
        self.lives = LIVES_PER_LEVEL
        self.spills = []
        self._last_level_index = -1

        # Available actions: 1=W (heat up), 2=S (heat down), 6=click
        # (tilt), 7=idle tick. ACT1/ACT2 enable W/S keyboard mapping
        # via static/js/human-input.js:115's keyMap.
        super().__init__(
            'pw', levels,
            Camera(0, 0, GW, GH, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 6, 7],
        )

    # ── Level setup ─────────────────────────────────────────────────────────

    def on_set_level(self, level):
        d = LEVEL_DATA[self.level_index]
        self.tilt = 0
        self.tick = 0
        self.thermostat = 0
        self._therm_cooldown = 0
        self.water = set()
        self.water_temp = {}
        self.particles = []
        self.smoke = []
        self.ice = set()
        self.ice_temp = {}
        self.kettle_pivot = d['kettle_pivot']
        self.kettle_volume_initial = d['kettle_volume']
        self.kettle_water = d['kettle_volume']
        self.kettle_temp = d.get('kettle_temp', 25)
        self.ambient_temp = d.get('ambient_temp', 25)
        self.heat_sources = list(d.get('heat_sources', []))
        self.cold_sources = list(d.get('cold_sources', []))
        self.cup_left = d['cup_left']
        self.cup_right = d['cup_right']
        self.cup_top = d['cup_top']
        self.cup_bottom = d['cup_bottom']
        self.cup_target_y = d['target_y']
        inner_w = max(1, self.cup_right - self.cup_left - 1)
        fill_rows = max(1, self.cup_bottom - self.cup_target_y)
        self.target_volume = inner_w * fill_rows
        self.cup_volume = 0
        self.obstacles = list(d['obstacles'])
        if self.level_index != self._last_level_index:
            self.lives = LIVES_PER_LEVEL
            self._last_level_index = self.level_index
        self.spills = []

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
        if (x, y) in self.ice:
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
            # Mid-flight heat exchange — boolean any-neighbour, single
            # +/-HEAT_PER_TICK delta per tick regardless of how many
            # neighbour cells are in fire/cold rects.
            near_fire_p = False
            near_cold_p = False
            for (nx, ny) in ((ix + 1, iy), (ix - 1, iy), (ix, iy + 1), (ix, iy - 1)):
                if _in_any_rect(nx, ny, self.heat_sources):
                    near_fire_p = True
                if _in_any_rect(nx, ny, self.cold_sources):
                    near_cold_p = True
            if near_fire_p:
                p['temp'] = p.get('temp', 25) + HEAT_PER_TICK
            if near_cold_p:
                p['temp'] = p.get('temp', 25) - COLD_PER_TICK
            # (heat update for in-flight droplet uses any-neighbour logic
            # via the loop below, which already runs once per neighbour;
            # the assignment overwrites rather than adds — see fix above.)
            if p.get('temp', 25) >= EVAP_TEMP:
                self.smoke.append({'x': ix, 'y': iy, 'age': 0})
                continue
            if settled or below_solid or iy >= FLOOR_Y - 1:
                if 0 <= ix < GW and PLAY_TOP <= iy < GH and not self._is_solid(ix, iy):
                    in_cup = (self.cup_left < ix < self.cup_right
                              and self.cup_top <= iy < self.cup_bottom)
                    between_walls = (self.cup_left < ix < self.cup_right
                                     and iy < self.cup_top)
                    if in_cup:
                        self.water.add((ix, iy))
                        self.water_temp[(ix, iy)] = p.get('temp', 25)
                    elif between_walls:
                        pass
                    else:
                        self.lives -= 1
                        self.spills.append((ix, iy, 6))
                continue
            p['fx'], p['fy'] = cx, cy
            new_particles.append(p)
        self.particles = new_particles

    # ── Cellular-automaton step for settled water ───────────────────────────

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
            t = self.water_temp.pop((src_x, src_h), self.ambient_temp)
            self.water.discard((src_x, src_h))
            self.water.add((dst_x, new_dst_h))
            self.water_temp[(dst_x, new_dst_h)] = t
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
                t = self.water_temp.pop((x, y), self.ambient_temp)
                self.water_temp[(nx, ny)] = t
                break
        self.water = occupied
        self.water_temp = {k: v for k, v in self.water_temp.items() if k in self.water}

    # ── Pour emission ───────────────────────────────────────────────────────

    def _emit_pour(self):
        rate = _emit_rate(self.tilt)
        if rate == 0 or self.kettle_water <= 0:
            return
        sx, sy = self._spout_tip_world()
        emit_x = sx
        emit_y = sy + 1.0
        vx = max(0.0, (self.tilt - HVEL_TILT_OFFSET) * HVEL_SLOPE)
        vy = 0.4
        for _ in range(rate):
            if self.kettle_water <= 0:
                break
            self.particles.append({
                'fx': emit_x, 'fy': emit_y, 'vx': vx, 'vy': vy,
                'temp': self.kettle_temp,
            })
            self.kettle_water -= 1

    # ── Heat update (settled water + ice + kettle) ──────────────────────────

    def _neighbours_4(self, x: int, y: int):
        return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))

    def _step_heat(self):
        # Settled water
        new_temps = {}
        evaporate = []
        freeze = []
        smoke_emit = []
        for (x, y) in sorted(self.water):
            t = self.water_temp.get((x, y), self.ambient_temp)
            # Boolean any-neighbour test — having more fire neighbours
            # doesn't multiply the heat (otherwise water tucked into the
            # corner of a fire L would heat 3-4× faster than a cell on a
            # straight edge, which is hard to reason about).
            near_fire = False
            near_cold = False
            for (nx, ny) in self._neighbours_4(x, y):
                if _in_any_rect(nx, ny, self.heat_sources):
                    near_fire = True
                if _in_any_rect(nx, ny, self.cold_sources):
                    near_cold = True
                if (nx, ny) in self.ice:
                    near_cold = True
            delta = 0
            if near_fire:
                delta += HEAT_PER_TICK
            if near_cold:
                delta -= COLD_PER_TICK
            if delta == 0:
                if t > self.ambient_temp:
                    t -= DRIFT_PER_TICK
                elif t < self.ambient_temp:
                    t += DRIFT_PER_TICK
            else:
                t += delta
            # Player thermostat — global +/- delta on top of source/drift.
            t += self.thermostat
            if t > 120:
                t = 120
            if t < -20:
                t = -20
            if t >= EVAP_TEMP:
                evaporate.append((x, y))
            elif t <= FREEZE_TEMP:
                freeze.append((x, y, t))
            else:
                new_temps[(x, y)] = t
                if t >= SMOKE_TEMP and (self.tick % SMOKE_PERIOD == 0):
                    smoke_emit.append((x, y))
        for (x, y) in evaporate:
            self.water.discard((x, y))
            self.water_temp.pop((x, y), None)
            self.smoke.append({'x': x, 'y': y, 'age': 0})
        for (x, y, t) in freeze:
            self.water.discard((x, y))
            self.water_temp.pop((x, y), None)
            self.ice.add((x, y))
            self.ice_temp[(x, y)] = t
        for (x, y) in new_temps:
            self.water_temp[(x, y)] = new_temps[(x, y)]
        for (x, y) in smoke_emit:
            self.smoke.append({'x': x, 'y': max(PLAY_TOP, y - 1), 'age': 0})

        # Kettle reservoir bulk temperature — heats / cools based on rects
        # adjacent to the kettle pivot. Boolean any-neighbour for
        # consistency with water-cell logic.
        kp_x, kp_y = self.kettle_pivot
        kdelta = 0
        near_fire_k = False
        near_cold_k = False
        for (nx, ny) in self._neighbours_4(kp_x, kp_y):
            if _in_any_rect(nx, ny, self.heat_sources):
                near_fire_k = True
            if _in_any_rect(nx, ny, self.cold_sources):
                near_cold_k = True
        if near_fire_k:
            kdelta += HEAT_PER_TICK
        if near_cold_k:
            kdelta -= COLD_PER_TICK
        if kdelta == 0:
            if self.kettle_temp > self.ambient_temp:
                self.kettle_temp -= DRIFT_PER_TICK
            elif self.kettle_temp < self.ambient_temp:
                self.kettle_temp += DRIFT_PER_TICK
        else:
            self.kettle_temp += kdelta
        # Player thermostat affects the kettle bulk temperature too.
        self.kettle_temp += self.thermostat
        if self.kettle_temp > 120:
            self.kettle_temp = 120
        if self.kettle_temp < -20:
            self.kettle_temp = -20

        # Ice cells: gain heat from adjacent fire, otherwise drift toward
        # ICE_BASELINE. Above MELT_THRESHOLD the cell converts back to water.
        # Boolean any-neighbour mirroring water heat logic.
        melted = []
        new_ice_temps = {}
        for (x, y) in sorted(self.ice):
            t = self.ice_temp.get((x, y), FREEZE_TEMP)
            heated = False
            for (nx, ny) in self._neighbours_4(x, y):
                if _in_any_rect(nx, ny, self.heat_sources):
                    heated = True
                    break
            if heated:
                t += HEAT_PER_TICK
            if not heated:
                if t > ICE_BASELINE:
                    t -= DRIFT_PER_TICK
                elif t < ICE_BASELINE:
                    t += DRIFT_PER_TICK
            # Player thermostat also nudges ice temperature.
            t += self.thermostat
            if t > 120:
                t = 120
            if t < -20:
                t = -20
            if t >= MELT_THRESHOLD:
                melted.append((x, y, t))
            else:
                new_ice_temps[(x, y)] = t
        for (x, y, t) in melted:
            self.ice.discard((x, y))
            self.ice_temp.pop((x, y), None)
            self.water.add((x, y))
            self.water_temp[(x, y)] = t
        for (x, y) in new_ice_temps:
            self.ice_temp[(x, y)] = new_ice_temps[(x, y)]

    # ── Smoke (cosmetic upward drift) ───────────────────────────────────────

    def _step_smoke(self):
        if not self.smoke:
            return
        new_smoke = []
        rise = (self.tick % SMOKE_RISE_PERIOD == 0)
        for s in self.smoke:
            s['age'] += 1
            if s['age'] >= SMOKE_MAX_AGE:
                continue
            if rise:
                s['y'] -= 1
            if s['y'] < PLAY_TOP:
                continue
            new_smoke.append(s)
        self.smoke = new_smoke

    # ── Cup volume + win/lose ───────────────────────────────────────────────

    def _recount_cup(self):
        cl, cr, ct, cb = self.cup_left, self.cup_right, self.cup_top, self.cup_bottom
        n = 0
        for (x, y) in self.water:
            if cl < x < cr and ct <= y < cb:
                n += 1
        self.cup_volume = n

    def _check_end(self):
        if self.lives <= 0:
            self.lose()
            return True

        settled = not self.particles and self._water_settled_stable()
        if not settled:
            return False

        highest_y = None
        for (x, y) in self.water:
            if (self.cup_left < x < self.cup_right
                    and self.cup_top <= y < self.cup_bottom):
                if highest_y is None or y < highest_y:
                    highest_y = y

        tolerance = 1
        if highest_y is not None:
            if (self.cup_target_y - tolerance
                    <= highest_y
                    <= self.cup_target_y + tolerance):
                self.next_level()
                return True
            if highest_y < self.cup_target_y - tolerance:
                self._reset_attempt()
                return False
        return False

    def _reset_attempt(self):
        self.lives -= 1
        if self.lives <= 0:
            self.lose()
            return
        self.water = set()
        self.water_temp = {}
        self.particles = []
        self.smoke = []
        self.ice = set()
        self.ice_temp = {}
        self.tilt = 0
        self.thermostat = 0
        self._therm_cooldown = 0
        self.spills = []
        self.kettle_water = self.kettle_volume_initial
        d = LEVEL_DATA[self.level_index]
        self.kettle_temp = d.get('kettle_temp', 25)
        self.cup_volume = 0

    def handle_reset(self) -> None:
        if self._action_count > 0 and self._state.name != 'WIN':
            self.lives -= 1
            if self.lives <= 0:
                self.lose()
                return
        super().handle_reset()

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
        # Thermostat: W (ACT1) raises, S (ACT2) lowers. Held keys are
        # rate-limited by THERMOSTAT_COOLDOWN so a 200ms tap moves ~1
        # step rather than slamming to the cap. The cooldown resets on
        # each accepted change.
        if self._therm_cooldown > 0:
            self._therm_cooldown -= 1
        if aid == 1 and self._therm_cooldown == 0:
            self.thermostat = min(THERMOSTAT_MAX, self.thermostat + 1)
            self._therm_cooldown = THERMOSTAT_COOLDOWN
        elif aid == 2 and self._therm_cooldown == 0:
            self.thermostat = max(-THERMOSTAT_MAX, self.thermostat - 1)
            self._therm_cooldown = THERMOSTAT_COOLDOWN
        # Tilt: only ACT6 raises it; everything else (W/S/idle) decays.
        if aid == 6:
            self.tilt = min(TILT_MAX, self.tilt + TILT_PER_CLICK)
        else:
            self.tilt = max(0, self.tilt - TILT_PER_RELEASE)

        self.tick += 1

        self._emit_pour()
        self._step_particles()
        self._step_water_ca()
        self._step_heat()
        self._step_smoke()
        self._recount_cup()

        if self.spills:
            self.spills = [(x, y, t - 1) for (x, y, t) in self.spills if t > 1]

        self._check_end()
        self.complete_action()
