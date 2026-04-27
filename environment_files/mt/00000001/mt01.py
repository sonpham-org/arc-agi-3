# Author: Claude Opus 4.7 (1M context)
# Date: 2026-04-26 17:30
# PURPOSE: Mortar (mt01) — discrete-input game where the player walks
#   to a mortar, mounts it (Z = ACTION5), dials in an angle and force,
#   and FIRES (X = ACTION7) a shell at a target. The shell flies in a
#   visible parabolic arc that the player can watch — each integration
#   tick of the shell is rendered as its own frame, played back at the
#   game's default_fps. After landing, a 6×6 companion sprite next to
#   the mortar shows comparative feedback ("CLOSER" / "FURTHER" /
#   "SAME" / "HIT") in a 10×10 speech bubble. 3 levels: open field,
#   hill in the way, full mountain occlusion. Win = impact within 1
#   cell of target. Lose = shells exhausted (8 per level). Fully
#   deterministic ballistics (Euler integration, fixed gravity, no RNG).
#   Integration: subclass of arcengine.ARCBaseGame, registered as
#   game_id "mt01" via metadata.json. Listed automatically by
#   /api/games once the environment_files/mt/00000001/ directory exists.
#   2× sprites compared to the initial draft — every character (player,
#   companion, mortar base/tube, target flag, speech bubble, impact
#   crater) is doubled in each dimension for legibility.
# SRP/DRY check: Pass — no shared sprite or ballistics utility in the
#   project; ab01's Angry-Birds shooter is the closest analog but
#   renders trajectories and uses click-and-drag aim, not walk-mount.

import math
import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# ── Grid geometry ──────────────────────────────────────────────────────────
GW, GH = 64, 64
HUD_H = 5            # rows 0..4 are HUD
GROUND_Y = 55        # first row of terrain (rows 55..63 are ground band)

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

# ── Sprite sizes (2× the initial draft) ────────────────────────────────────
PLAYER_W, PLAYER_H = 6, 6
COMPANION_W, COMPANION_H = 6, 6
MORTAR_BASE_W, MORTAR_BASE_H = 10, 4
MORTAR_TUBE_LEN = 10                  # tube extends this many cells from base top
TARGET_W, TARGET_H = 6, 12            # 1px pole + 5x6 flag
BUBBLE_W, BUBBLE_H = 10, 10           # 8x8 interior; 6x6 symbol drawn centered
SHELL_R = 1                           # shell rendered as a 3x3 cross

# ── Ballistics constants ───────────────────────────────────────────────────
GRAVITY = 0.35
MAX_SIM_STEPS = 400  # safety cap on integration loop

# Angle 20..80 in 5-degree steps; force 3..12 in 1-step
ANGLE_MIN, ANGLE_MAX, ANGLE_STEP = 20, 80, 5
FORCE_MIN, FORCE_MAX = 3, 12
DEFAULT_ANGLE = 45
DEFAULT_FORCE = 5

AMMO_PER_LEVEL = 8
HIT_X_TOL = 1   # |impact_x - target_x| ≤ HIT_X_TOL counts as a hit
HIT_Y_TOL = 2


# ── Level data ─────────────────────────────────────────────────────────────
# terrain_profile: list of (x_start, x_end, top_y) — cells with y >= top_y
#   are solid ground in that x-range. Default top_y = GROUND_Y elsewhere.
# Targets re-tuned for the new (taller) muzzle position.
LEVEL_DATA = [
    {
        'name': 'Open Field',
        'mortar_x': 12,
        'companion_x': 22,
        'player_spawn_x': 32,
        'target_pos': (43, 56),
        'terrain_profile': [],
    },
    {
        'name': 'Over the Hill',
        'mortar_x': 10,
        'companion_x': 20,
        'player_spawn_x': 28,
        'target_pos': (47, 56),
        # Hill bump from x=28..34 going up 8 cells: top_y = 47
        'terrain_profile': [(28, 34, 47)],
    },
    {
        'name': 'Beyond the Mountain',
        'mortar_x': 10,
        'companion_x': 20,
        'player_spawn_x': 28,
        'target_pos': (56, 56),
        # Mountain x=24..40 going up to top_y=37
        'terrain_profile': [(24, 40, 37)],
    },
]

levels = [
    Level(sprites=[], grid_size=(GW, GH), name=d['name'], data=d)
    for d in LEVEL_DATA
]


# ── Sprite helpers ─────────────────────────────────────────────────────────

def _draw_rect(frame, x, y, w, h, color):
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(GW, x + w), min(GH, y + h)
    if x0 < x1 and y0 < y1:
        frame[y0:y1, x0:x1] = color


def _pset(frame, x, y, color):
    if 0 <= x < GW and 0 <= y < GH:
        frame[y, x] = color


def _draw_pattern(frame, x0, y0, pattern, color):
    """Draw a 2D bool/int pattern of pixels at (x0,y0). 1/True = pixel set."""
    for dy, row in enumerate(pattern):
        for dx, v in enumerate(row):
            if v:
                _pset(frame, x0 + dx, y0 + dy, color)


# ── 6×6 speech-bubble symbols ──────────────────────────────────────────────
# Larger than the original 3×3 versions so they're readable when the
# bubble is just a few centimetres tall on screen.

SYM_CLOSER = [   # green up-arrow
    [0, 0, 1, 1, 0, 0],
    [0, 1, 1, 1, 1, 0],
    [1, 1, 1, 1, 1, 1],
    [0, 0, 1, 1, 0, 0],
    [0, 0, 1, 1, 0, 0],
    [0, 0, 1, 1, 0, 0],
]
SYM_FURTHER = [   # red down-arrow
    [0, 0, 1, 1, 0, 0],
    [0, 0, 1, 1, 0, 0],
    [0, 0, 1, 1, 0, 0],
    [1, 1, 1, 1, 1, 1],
    [0, 1, 1, 1, 1, 0],
    [0, 0, 1, 1, 0, 0],
]
SYM_SAME = [   # yellow ‖ (two horizontal bars)
    [0, 0, 0, 0, 0, 0],
    [1, 1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0],
    [1, 1, 1, 1, 1, 1],
    [0, 0, 0, 0, 0, 0],
]
SYM_FIRE = [   # white • (filled disc — first shot, no comparison)
    [0, 0, 1, 1, 0, 0],
    [0, 1, 1, 1, 1, 0],
    [1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1],
    [0, 1, 1, 1, 1, 0],
    [0, 0, 1, 1, 0, 0],
]
SYM_HIT = [   # yellow ★
    [0, 0, 1, 1, 0, 0],
    [0, 0, 1, 1, 0, 0],
    [1, 1, 1, 1, 1, 1],
    [0, 1, 1, 1, 1, 0],
    [0, 1, 1, 1, 1, 0],
    [1, 1, 0, 0, 1, 1],
]


# ── Display ────────────────────────────────────────────────────────────────

class MortarDisplay(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        g = self.game

        # Background sky
        frame[:, :] = C_BLACK

        # ── Terrain ─────────────────────────────────────────────────────────
        for x in range(GW):
            top = g.ground_top[x]
            for y in range(top, GH):
                if y == top:
                    frame[y, x] = C_GREEN if top == GROUND_Y else C_DGRAY
                else:
                    frame[y, x] = C_DGRAY

        # ── Target (red flag, 6×12) ─────────────────────────────────────────
        tx, ty = g.target_pos
        # Pole: 1 column, 12 tall, bottom at ty
        _draw_rect(frame, tx, ty - 11, 1, 12, C_VDGRAY)
        # Flag: 5×6 triangle attached to the top of the pole, to the right
        for fy in range(6):
            for fx in range(5):
                if fx <= 4 - abs(fy - 2):  # taper toward the right
                    _pset(frame, tx + 1 + fx, ty - 11 + fy, C_RED)

        # ── Mortar base (10×4) ──────────────────────────────────────────────
        mx = g.mortar_x
        my_base_top = g.ground_top[mx] - MORTAR_BASE_H
        # Base: dark gray rectangle
        _draw_rect(frame, mx - 4, my_base_top, MORTAR_BASE_W, MORTAR_BASE_H, C_DGRAY)
        # Wheel pivots: 2x2 black squares at base bottom corners
        _draw_rect(frame, mx - 4, my_base_top + MORTAR_BASE_H - 2, 2, 2, C_BLACK)
        _draw_rect(frame, mx + 4, my_base_top + MORTAR_BASE_H - 2, 2, 2, C_BLACK)

        # Mortar tube: 2-pixel-wide line from (mx, my_base_top) at angle.
        tube_origin = (mx, my_base_top)
        ang_rad = math.radians(g.angle)
        for i in range(1, MORTAR_TUBE_LEN + 1):
            tx_t = tube_origin[0] + i * math.cos(ang_rad)
            ty_t = tube_origin[1] - i * math.sin(ang_rad)
            ix, iy = int(round(tx_t)), int(round(ty_t))
            color = C_ORANGE if i >= MORTAR_TUBE_LEN - 1 else C_VDGRAY
            # 2-wide tube — also paint the perpendicular pixel
            _pset(frame, ix, iy, color)
            _pset(frame, ix, iy + 1, color)

        # ── Companion (6×6) ─────────────────────────────────────────────────
        cx = g.companion_x
        cy_top = g.ground_top[cx] - COMPANION_H
        _draw_rect(frame, cx - 2, cy_top, COMPANION_W, COMPANION_H, C_LBLUE)
        # Eyes: 2 white 1×1 pixels on the upper third
        _pset(frame, cx - 1, cy_top + 1, C_WHITE)
        _pset(frame, cx + 2, cy_top + 1, C_WHITE)
        # Mouth: 2-wide horizontal strip
        _pset(frame, cx,     cy_top + 3, C_BLACK)
        _pset(frame, cx + 1, cy_top + 3, C_BLACK)

        # ── Speech bubble (10×10) ──────────────────────────────────────────
        # Sits to the right of and above the companion's head.
        bx = cx + 4
        by = cy_top - BUBBLE_H - 1
        # Outer border
        _draw_rect(frame, bx, by, BUBBLE_W, BUBBLE_H, C_WHITE)
        # Inner cavity (8×8)
        _draw_rect(frame, bx + 1, by + 1, BUBBLE_W - 2, BUBBLE_H - 2, C_BLACK)
        # Tail — 2 vertical pixels pointing toward the companion
        _pset(frame, bx, by + BUBBLE_H, C_WHITE)
        _pset(frame, bx + 1, by + BUBBLE_H, C_WHITE)
        _pset(frame, bx, by + BUBBLE_H + 1, C_WHITE)

        # Symbol (6×6) centered in the 8×8 cavity
        fb = g.last_feedback
        sym, sym_color = None, None
        if fb == 'CLOSER':
            sym, sym_color = SYM_CLOSER, C_GREEN
        elif fb == 'FURTHER':
            sym, sym_color = SYM_FURTHER, C_RED
        elif fb == 'SAME':
            sym, sym_color = SYM_SAME, C_YELLOW
        elif fb == 'FIRE':
            sym, sym_color = SYM_FIRE, C_WHITE
        elif fb == 'HIT':
            sym, sym_color = SYM_HIT, C_YELLOW
        if sym is not None:
            _draw_pattern(frame, bx + 2, by + 2, sym, sym_color)

        # ── Player (6×6, only in walk mode) ─────────────────────────────────
        if g.mode == 'walk':
            px = g.player_x
            # Player rests on top of the ground at its centre column
            ground_under = int(min(g.ground_top[x] for x in range(px, min(px + PLAYER_W, GW))))
            py_top = ground_under - PLAYER_H
            _draw_rect(frame, px, py_top, PLAYER_W, PLAYER_H, C_YELLOW)
            # Helmet stripe (top 2 rows white) so it reads as a soldier
            _draw_rect(frame, px, py_top, PLAYER_W, 1, C_WHITE)
            # Eye dots
            _pset(frame, px + 1, py_top + 2, C_BLACK)
            _pset(frame, px + 4, py_top + 2, C_BLACK)

        # ── Shell in flight ─────────────────────────────────────────────────
        if g.shell is not None:
            sx, sy = int(round(g.shell['fx'])), int(round(g.shell['fy']))
            # Render as a 3-pixel cross + body so it's visible mid-flight
            for dy, dx in [(-1, 0), (0, -1), (0, 0), (0, 1), (1, 0)]:
                _pset(frame, sx + dx, sy + dy, C_ORANGE)

        # ── Impact flash (after the shell lands, until next FIRE) ──────────
        if g.impact is not None:
            ix, iy = g.impact
            # 5×5 burst with red core and orange ring
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if abs(dx) + abs(dy) <= 2:  # diamond
                        _pset(frame, ix + dx, iy + dy, C_ORANGE)
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    _pset(frame, ix + dx, iy + dy, C_RED)
            _pset(frame, ix, iy, C_YELLOW)

        # ── HUD (rows 0..4) ─────────────────────────────────────────────────
        frame[0:HUD_H, :] = C_VDGRAY

        # Angle bar: row 1, x=2..32 — 30 cells, lit count = (angle-20)/2
        ang_lit = max(0, min(30, (g.angle - ANGLE_MIN) // 2))
        for i in range(30):
            color = C_BLUE if i < ang_lit else C_BLACK
            _pset(frame, 2 + i, 1, color)
        _pset(frame, 0, 1, C_YELLOW)

        # Force bar: row 3, x=2..14 — 10 cells, lit count = force-2
        frc_lit = max(0, min(10, g.force - 2))
        for i in range(10):
            color = C_RED if i < frc_lit else C_BLACK
            _pset(frame, 2 + i, 3, color)
        _pset(frame, 0, 3, C_YELLOW)

        # Ammo: row 1, x=40..63 — small red squares
        for i in range(g.ammo):
            sx = 40 + i * 3
            if sx + 1 < GW:
                _pset(frame, sx, 1, C_MAROON)
                _pset(frame, sx + 1, 1, C_MAROON)

        # Mode indicator (row 2..4 right side)
        # 'W' (walk) = yellow 3x3, 'M' (mortar) = orange 3x3
        mode_x = 58
        if g.mode == 'walk':
            _draw_rect(frame, mode_x, 2, 3, 3, C_YELLOW)
        else:
            _draw_rect(frame, mode_x, 2, 3, 3, C_ORANGE)

        return frame


# ── Game ───────────────────────────────────────────────────────────────────

class Mt01(ARCBaseGame):
    def __init__(self):
        self.display = MortarDisplay(self)

        # State (set in on_set_level too)
        self.mode = 'walk'
        self.player_x = 0
        self.mortar_x = 0
        self.companion_x = 0
        self.target_pos = (0, 0)
        self.angle = DEFAULT_ANGLE
        self.force = DEFAULT_FORCE
        self.ammo = AMMO_PER_LEVEL
        self.last_distance = None
        self.last_feedback = 'NONE'
        self.impact = None
        self.shell = None        # dict {fx,fy,vx,vy} while in flight; None otherwise
        self.ground_top = np.full(GW, GROUND_Y, dtype=np.int32)

        super().__init__(
            'mt', levels,
            Camera(0, 0, GW, GH, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4, 5, 7],
        )

    # ── Level setup ─────────────────────────────────────────────────────────

    def on_set_level(self, level):
        d = LEVEL_DATA[self.level_index]
        self.mode = 'walk'
        self.mortar_x = d['mortar_x']
        self.companion_x = d['companion_x']
        self.player_x = d['player_spawn_x']
        self.target_pos = d['target_pos']
        self.angle = DEFAULT_ANGLE
        self.force = DEFAULT_FORCE
        self.ammo = AMMO_PER_LEVEL
        self.last_distance = None
        self.last_feedback = 'NONE'
        self.impact = None
        self.shell = None

        # Build terrain top-row map
        self.ground_top = np.full(GW, GROUND_Y, dtype=np.int32)
        for (x0, x1, top_y) in d['terrain_profile']:
            for x in range(x0, x1 + 1):
                if 0 <= x < GW:
                    self.ground_top[x] = top_y

    # ── Solidity helpers ────────────────────────────────────────────────────

    def _is_ground(self, x: int, y: int) -> bool:
        if not (0 <= x < GW):
            return False
        return y >= self.ground_top[x]

    def _adjacent_to_mortar(self) -> bool:
        # Player (6 wide) covers x..x+5; mortar base (10 wide) covers
        # mortar_x-4..mortar_x+5
        plx, prx = self.player_x, self.player_x + PLAYER_W - 1
        mlx, mrx = self.mortar_x - 4, self.mortar_x + 5
        return prx + 1 >= mlx and plx - 1 <= mrx

    # ── Walk-mode movement ──────────────────────────────────────────────────

    def _try_walk(self, dx: int):
        new_x = self.player_x + dx
        if new_x < 0 or new_x + PLAYER_W - 1 >= GW:
            return
        cur_ground = int(min(self.ground_top[x]
                             for x in range(self.player_x,
                                            self.player_x + PLAYER_W)))
        new_ground = int(min(self.ground_top[x]
                             for x in range(new_x, new_x + PLAYER_W)))
        # Don't allow climbing more than 1 cell up per step
        if new_ground < cur_ground - 1:
            return
        # Don't walk into the mortar base
        plx, prx = new_x, new_x + PLAYER_W - 1
        mlx, mrx = self.mortar_x - 4, self.mortar_x + 5
        if prx >= mlx and plx <= mrx:
            return
        self.player_x = new_x

    # ── Ballistics — shell launch + per-tick advance ────────────────────────

    def _muzzle_xy(self) -> tuple[float, float]:
        """Tip of the rotated tube, in world coordinates."""
        mx = self.mortar_x
        my_base_top = float(self.ground_top[mx] - MORTAR_BASE_H)
        ang = math.radians(self.angle)
        return (mx + MORTAR_TUBE_LEN * math.cos(ang),
                my_base_top - MORTAR_TUBE_LEN * math.sin(ang))

    def _launch_shell(self):
        muzzle_x, muzzle_y = self._muzzle_xy()
        ang_rad = math.radians(self.angle)
        vx = self.force * math.cos(ang_rad)
        vy = -self.force * math.sin(ang_rad)
        self.shell = {
            'fx': muzzle_x,
            'fy': muzzle_y,
            'vx': vx,
            'vy': vy,
            'steps': 0,
        }

    def _tick_shell(self):
        """Advance the in-flight shell one Euler tick. Sets self.shell to
        None when the shell lands or leaves the world; in that case the
        impact (or None for off-screen) is captured into self.impact and
        self._pending_impact is set so step() knows to resolve it."""
        s = self.shell
        s['fx'] += s['vx']
        s['fy'] += s['vy']
        s['vy'] += GRAVITY
        s['steps'] += 1
        ix, iy = int(round(s['fx'])), int(round(s['fy']))

        if s['steps'] > MAX_SIM_STEPS:
            # Defensive cap — count as off-screen miss
            self.shell = None
            self.impact = None
            return

        if iy >= GH:
            # Off the bottom — clamp to floor and treat as ground hit
            self.shell = None
            self.impact = (max(0, min(GW - 1, ix)), GH - 1)
            return
        if ix < 0 or ix >= GW:
            # Off the side
            self.shell = None
            self.impact = None
            return
        if iy < 0:
            # Above the world — keep flying
            return
        if self._is_ground(ix, iy):
            self.shell = None
            self.impact = (ix, iy)
            return
        # Otherwise still in the air

    def _resolve_impact(self):
        """Called once after shell lands. Sets feedback, win/lose."""
        impact = self.impact
        if impact is None:
            dx = 9999
            hit = False
        else:
            dx = abs(impact[0] - self.target_pos[0])
            hit = (abs(impact[0] - self.target_pos[0]) <= HIT_X_TOL
                   and abs(impact[1] - self.target_pos[1]) <= HIT_Y_TOL)

        if hit:
            self.last_feedback = 'HIT'
        elif self.last_distance is None:
            self.last_feedback = 'FIRE'
        elif dx < self.last_distance:
            self.last_feedback = 'CLOSER'
        elif dx > self.last_distance:
            self.last_feedback = 'FURTHER'
        else:
            self.last_feedback = 'SAME'
        self.last_distance = dx

        if hit:
            self.next_level()
        elif self.ammo <= 0:
            self.lose()

    # ── Main step ───────────────────────────────────────────────────────────

    def step(self):
        # If a shell is in flight, every step() call advances its physics
        # by one tick and emits a frame. complete_action() is held back
        # until the shell lands — the engine renders one frame per step()
        # iteration and ships them as a thinned animation list.
        if self.shell is not None:
            self._tick_shell()
            if self.shell is None:
                self._resolve_impact()
                self.complete_action()
            return

        aid = self.action.id.value

        if self.mode == 'walk':
            if aid == 3:
                self._try_walk(-1)
            elif aid == 4:
                self._try_walk(1)
            elif aid == 5:   # Z — mount mortar if adjacent
                if self._adjacent_to_mortar():
                    self.mode = 'mortar'
            # ACTION1, 2, 7 are ignored in walk mode
            self.complete_action()
            return

        # ── Mortar mode ────────────────────────────────────────────────────
        if aid == 1:
            self.angle = min(ANGLE_MAX, self.angle + ANGLE_STEP)
        elif aid == 2:
            self.angle = max(ANGLE_MIN, self.angle - ANGLE_STEP)
        elif aid == 3:
            self.force = max(FORCE_MIN, self.force - 1)
        elif aid == 4:
            self.force = min(FORCE_MAX, self.force + 1)
        elif aid == 5:   # Z — dismount, return to walking
            self.mode = 'walk'
        elif aid == 7:   # X — FIRE
            if self.ammo > 0:
                self.ammo -= 1
                self.impact = None       # clear previous impact while shell flies
                self._launch_shell()     # initialises self.shell; animation begins next step()
                # Don't complete_action — engine loop will keep calling
                # step() until the shell lands.
                return
        self.complete_action()
