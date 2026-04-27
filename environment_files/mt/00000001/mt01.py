# Author: Claude Opus 4.7 (1M context)
# Date: 2026-04-26 14:30
# PURPOSE: Mortar (mt01) — discrete-input game where the player walks to
#   a mortar, mounts it (ACTION5/Z), dials in an angle and force, and
#   fires a shell at a target. The shell's trajectory is intentionally
#   NOT rendered — only the impact crater is shown briefly. A companion
#   sprite next to the mortar gives feedback ("CLOSER" / "FURTHER" /
#   "SAME" / "HIT") relative to the previous shot, so the player can
#   adjust by ear rather than by sight. 3 levels: open field, hill in
#   the way, full mountain occlusion. Win = impact within 1 cell of
#   target. Lose = shells exhausted (8 per level). Fully deterministic
#   ballistics (Euler integration, fixed gravity, no RNG).
#   Integration: subclass of arcengine.ARCBaseGame, registered as
#   game_id "mt01" via metadata.json. Listed automatically by
#   /api/games once the environment_files/mt/00000001/ directory exists.
# SRP/DRY check: Pass — searched environment_files/* for any existing
#   ballistic / hidden-trajectory game; ab01 is the closest reference
#   (Angry Birds with VISIBLE trajectory) but its mechanics are
#   click-and-launch, not walk-mount-fire, and it always renders the
#   flight path. mt01's hidden-trajectory + companion-feedback loop is
#   unique. Sprite/terrain helpers are intrinsic to this game's layout.

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
HIT_Y_TOL = 2   # |impact_y - target_y| ≤ HIT_Y_TOL


# ── Level data — fully hardcoded, no RNG ───────────────────────────────────
# terrain_profile: list of (x_start, x_end, top_y) — cells with y >= top_y
#   are solid ground in that x-range. The default top_y for any column not
#   covered by a profile entry is GROUND_Y.
# mortar_x: x-column of the mortar's centre (5-wide base)
# companion_x: x-column of the companion's centre (3-wide sprite)
# player_spawn_x: x-column of the player's left edge at level start
# target_pos: (target_x, target_y) the impact must land within HIT_*_TOL
LEVEL_DATA = [
    {
        'name': 'Open Field',
        'mortar_x': 10,
        'companion_x': 16,
        'player_spawn_x': 28,
        'target_pos': (43, 56),
        'terrain_profile': [],   # flat
    },
    {
        'name': 'Over the Hill',
        'mortar_x': 8,
        'companion_x': 14,
        'player_spawn_x': 22,
        'target_pos': (48, 56),
        # Hill bump from x=26..32 going up 8 cells: top_y = 47
        'terrain_profile': [(26, 32, 47)],
    },
    {
        'name': 'Beyond the Mountain',
        'mortar_x': 8,
        'companion_x': 14,
        'player_spawn_x': 18,
        'target_pos': (59, 56),
        # Mountain x=22..38 going up to top_y=37
        'terrain_profile': [(22, 38, 37)],
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


# ── Display ────────────────────────────────────────────────────────────────

class MortarDisplay(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        g = self.game

        # Background sky
        frame[:, :] = C_BLACK

        # ── Terrain ─────────────────────────────────────────────────────────
        # Default flat ground row 55..63
        for x in range(GW):
            top = g.ground_top[x]
            for y in range(top, GH):
                # Top row of ground = grass tint (lighter), rest dark gray
                if y == top:
                    frame[y, x] = C_GREEN if top == GROUND_Y else C_DGRAY
                else:
                    frame[y, x] = C_DGRAY

        # ── Target (red flag) ───────────────────────────────────────────────
        tx, ty = g.target_pos
        # Pole: 1 column, 6 tall, bottom at ty
        _draw_rect(frame, tx, ty - 5, 1, 6, C_VDGRAY)
        # Flag: 3x3 triangle, attached at top of pole
        _pset(frame, tx + 1, ty - 5, C_RED)
        _pset(frame, tx + 2, ty - 5, C_RED)
        _pset(frame, tx + 1, ty - 4, C_RED)
        _pset(frame, tx + 2, ty - 4, C_RED)
        _pset(frame, tx + 1, ty - 3, C_RED)

        # ── Mortar base ─────────────────────────────────────────────────────
        mx = g.mortar_x
        my_base_top = g.ground_top[mx] - 2
        # Base: 5 wide x 2 tall, dark gray
        _draw_rect(frame, mx - 2, my_base_top, 5, 2, C_DGRAY)
        # Wheel pivots (2 black pixels at base bottom-corners)
        _pset(frame, mx - 2, my_base_top + 1, C_BLACK)
        _pset(frame, mx + 2, my_base_top + 1, C_BLACK)

        # Mortar tube: 1px line from (mx, my_base_top) at angle, length 5
        tube_origin = (mx, my_base_top)
        ang_rad = math.radians(g.angle)
        for i in range(1, 6):
            tx_t = tube_origin[0] + i * math.cos(ang_rad)
            ty_t = tube_origin[1] - i * math.sin(ang_rad)
            ix, iy = int(round(tx_t)), int(round(ty_t))
            color = C_ORANGE if i == 5 else C_VDGRAY
            _pset(frame, ix, iy, color)

        # ── Companion ───────────────────────────────────────────────────────
        cx = g.companion_x
        cy_top = g.ground_top[cx] - 3
        _draw_rect(frame, cx - 1, cy_top, 3, 3, C_LBLUE)
        _pset(frame, cx, cy_top, C_WHITE)        # face highlight

        # Speech bubble — always rendered to show feedback state. Sits to
        # the right of and above the companion's head.
        bx, by = cx + 3, cy_top - 6
        # 5x5 bubble: white border, black interior
        _draw_rect(frame, bx, by, 5, 5, C_WHITE)
        _draw_rect(frame, bx + 1, by + 1, 3, 3, C_BLACK)
        # Bubble tail (1 pixel) toward companion
        _pset(frame, bx, by + 5, C_WHITE)

        fb = g.last_feedback
        # Symbol drawn in the 3x3 interior at (bx+1, by+1)..(bx+3, by+3)
        ix0, iy0 = bx + 1, by + 1
        if fb == 'CLOSER':
            # Green up-arrow: top-centre, two side pixels below it, base
            _pset(frame, ix0 + 1, iy0, C_GREEN)
            _pset(frame, ix0,     iy0 + 1, C_GREEN)
            _pset(frame, ix0 + 2, iy0 + 1, C_GREEN)
            _pset(frame, ix0 + 1, iy0 + 2, C_GREEN)
        elif fb == 'FURTHER':
            # Red down-arrow
            _pset(frame, ix0 + 1, iy0, C_RED)
            _pset(frame, ix0,     iy0 + 1, C_RED)
            _pset(frame, ix0 + 2, iy0 + 1, C_RED)
            _pset(frame, ix0 + 1, iy0 + 2, C_RED)
            # Tail (extra row to show "going down")
            _pset(frame, ix0 + 1, iy0 + 2, C_RED)
        elif fb == 'SAME':
            # Yellow horizontal bar
            _pset(frame, ix0,     iy0 + 1, C_YELLOW)
            _pset(frame, ix0 + 1, iy0 + 1, C_YELLOW)
            _pset(frame, ix0 + 2, iy0 + 1, C_YELLOW)
        elif fb == 'FIRE':
            # White dot — first shot, no comparison yet
            _pset(frame, ix0 + 1, iy0 + 1, C_WHITE)
        elif fb == 'HIT':
            # Yellow star (diamond plus crosshair)
            _pset(frame, ix0 + 1, iy0, C_YELLOW)
            _pset(frame, ix0,     iy0 + 1, C_YELLOW)
            _pset(frame, ix0 + 1, iy0 + 1, C_YELLOW)
            _pset(frame, ix0 + 2, iy0 + 1, C_YELLOW)
            _pset(frame, ix0 + 1, iy0 + 2, C_YELLOW)
        # else 'NONE' — empty bubble (just shows readiness)

        # ── Player (only in walk mode) ──────────────────────────────────────
        if g.mode == 'walk':
            px = g.player_x
            py_bot = g.ground_top[px + 1] - 1
            py_top = py_bot - 2
            _draw_rect(frame, px, py_top, 3, 3, C_YELLOW)
            _pset(frame, px + 1, py_top, C_WHITE)   # head highlight

        # ── Impact flash (only after firing, until next fire/level reset) ──
        if g.impact is not None:
            ix, iy = g.impact
            # 3x3 orange burst with red centre
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    _pset(frame, ix + dx, iy + dy, C_ORANGE)
            _pset(frame, ix, iy, C_RED)

        # ── HUD (rows 0..4) ─────────────────────────────────────────────────
        frame[0:HUD_H, :] = C_VDGRAY

        # Angle bar: row 1, x=2..32 — 30 cells, lit count = (angle-20)/2
        ang_lit = max(0, min(30, (g.angle - ANGLE_MIN) // 2))
        for i in range(30):
            color = C_BLUE if i < ang_lit else C_BLACK
            _pset(frame, 2 + i, 1, color)
        # Angle marker: a tiny "A" pixel at left (yellow tag)
        _pset(frame, 0, 1, C_YELLOW)

        # Force bar: row 3, x=2..14 — 10 cells, lit count = force-2
        frc_lit = max(0, min(10, g.force - 2))
        for i in range(10):
            color = C_RED if i < frc_lit else C_BLACK
            _pset(frame, 2 + i, 3, color)
        _pset(frame, 0, 3, C_YELLOW)

        # Ammo: row 1, x=40..63 — N pairs of red squares
        for i in range(g.ammo):
            sx = 40 + i * 3
            if sx + 1 < GW:
                _pset(frame, sx, 1, C_MAROON)
                _pset(frame, sx + 1, 1, C_MAROON)

        # Mode indicator: row 3, x=58..62
        # 'W' (walking) = 3x3 yellow, 'M' (mortar) = 3x3 orange
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
        # Player covers x..x+2; mortar base covers mortar_x-2..mortar_x+2
        plx, prx = self.player_x, self.player_x + 2
        mlx, mrx = self.mortar_x - 2, self.mortar_x + 2
        # Adjacent = bounding boxes touching or overlapping by ≤ 1 cell gap
        return prx + 1 >= mlx and plx - 1 <= mrx

    # ── Walk-mode movement ──────────────────────────────────────────────────

    def _try_walk(self, dx: int):
        # Move 1 cell horizontally if the destination has standable ground
        # (within 1 cell of current ground height — otherwise too steep).
        new_x = self.player_x + dx
        if new_x < 0 or new_x + 2 >= GW:
            return  # would walk off-screen
        # Player must be able to stand on every cell it covers
        cur_ground = int(self.ground_top[self.player_x + 1])
        new_ground_left = int(self.ground_top[new_x])
        new_ground_right = int(self.ground_top[new_x + 2])
        new_ground = min(new_ground_left, new_ground_right)
        # Don't allow climbing more than 1 cell up per step
        if new_ground < cur_ground - 1:
            return
        # Don't walk into the mortar
        mlx, mrx = self.mortar_x - 2, self.mortar_x + 2
        if new_x + 2 >= mlx and new_x <= mrx:
            return
        self.player_x = new_x

    # ── Ballistics ──────────────────────────────────────────────────────────

    def _fire_shell(self):
        # Muzzle position: top of the mortar base, slightly above
        muzzle_x = float(self.mortar_x)
        muzzle_y = float(self.ground_top[self.mortar_x] - 3)

        ang_rad = math.radians(self.angle)
        vx = self.force * math.cos(ang_rad)
        vy = -self.force * math.sin(ang_rad)   # screen y increases downward

        x, y = muzzle_x, muzzle_y
        impact_pos = None
        for _ in range(MAX_SIM_STEPS):
            x += vx
            y += vy
            vy += GRAVITY
            ix, iy = int(round(x)), int(round(y))
            if iy >= GH:
                # Off-screen below the world: snap to bottom row, keep ix
                impact_pos = (max(0, min(GW - 1, ix)), GH - 1)
                break
            if ix < 0 or ix >= GW:
                # Off-screen left/right: count as a max-distance miss
                impact_pos = None
                break
            if iy < 0:
                # Above world (still ascending) — just keep going
                continue
            if self._is_ground(ix, iy):
                impact_pos = (ix, iy)
                break

        return impact_pos

    # ── Main step ───────────────────────────────────────────────────────────

    def step(self):
        aid = self.action.id.value

        if self.mode == 'walk':
            if aid == 3:
                self._try_walk(-1)
            elif aid == 4:
                self._try_walk(1)
            elif aid == 1 or aid == 2:
                pass   # vertical movement unused in walk mode
            elif aid == 5:
                if self._adjacent_to_mortar():
                    self.mode = 'mortar'
            elif aid == 7:
                pass   # already in walk mode
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
        elif aid == 7:
            self.mode = 'walk'
        elif aid == 5:
            # FIRE — only if there's ammo left
            if self.ammo > 0:
                self.ammo -= 1
                impact = self._fire_shell()
                self.impact = impact
                # Compute distance to target (∞ if shell flew off-screen)
                if impact is None:
                    dx = 9999
                else:
                    dx = abs(impact[0] - self.target_pos[0])

                # Hit check: x within tol and y within tol (impact must
                # land near the target's foot, not anywhere on the pole).
                hit = False
                if impact is not None:
                    if (abs(impact[0] - self.target_pos[0]) <= HIT_X_TOL
                            and abs(impact[1] - self.target_pos[1]) <= HIT_Y_TOL):
                        hit = True

                # Feedback
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

                # Win/lose
                if hit:
                    self.next_level()
                elif self.ammo <= 0:
                    self.lose()

        self.complete_action()
