# Author: Claude Sonnet 4.6
# Date: 2026-03-20 00:00
# PURPOSE: Tower Siege (ts01) v5 — split input: attacker uses keyboard (arrow keys to
#          move, Z to cycle units), defender uses mouse (click to select/move guards and
#          spawn). World auto-ticks via ACT7 at 4 FPS. Attacker 2x move speed
#          (UNIT_COOLDOWN=2 / GUARD_COOLDOWN=4). Version bump from 00000004.
# SRP/DRY check: Pass — new version (00000005); prior versions left intact for replay.
"""
ts01 v5 – Tower Siege (Split Controls: Keyboard Attacker / Mouse Defender)

ATTACKER (Player 1) — keyboard:
  Arrow keys  : move the selected unit one step (or use tool if adjacent)
  Z           : cycle to the next available unit (skips locked / dead / cooldown)

DEFENDER (Player 2) — mouse:
  Click guard : select it; click an adjacent cell to move it
  Click maroon dot (spawn zone) : place a reserve guard there

Both players act freely — no turn order. World auto-ticks at 4 FPS.
Action cooldowns: attacker unit = 2 ticks (0.5 s), guard = 4 ticks (1.0 s).

Units (Attacker)
-----------------
Sapper  (Orange) : press arrow toward a breach wall (LGRAY) to plant a bomb (1 s fuse)
Scout   (Blue)   : press arrow to move 1 step; pressing toward a gap grapples over it
Soldier (Green)  : pressing arrow onto a guard eliminates it (Soldier frozen 1 s)

Guards (Defender)
------------------
Click a red guard to select it; click an adjacent cell to move it one step.
Click a maroon dot near the tower to spawn a reserve guard.

Canvas: 64×64, grid 20×20 at 2px/cell at offset (2,10), right panel x=44..63
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# ── ARC3 colour palette ────────────────────────────────────────────────────────
WHITE  = 0
LGRAY  = 1
GRAY   = 2
DGRAY  = 3
VDGRAY = 4
BLACK  = 5
MAG    = 6
LMAG   = 7
RED    = 8
BLUE   = 9
LBLUE  = 10
YEL    = 11
ORG    = 12
MAR    = 13
GRN    = 14
PUR    = 15

# ── Canvas / Grid constants ────────────────────────────────────────────────────
CW     = 64
CH     = 64
GRID_X = 2
GRID_Y = 10
CELL   = 2
GW     = 20
GH     = 20

# ── Timing constants ───────────────────────────────────────────────────────────
DEFAULT_FPS    = 4   # ticks per second
BOMB_TICKS     = 4   # fuse duration (= 1 s)
FREEZE_TICKS   = 4   # Soldier freeze after contact-kill (= 1 s)
UNIT_COOLDOWN  = 2   # attacker cooldown per action (= 0.5 s) — 2× faster than guard
GUARD_COOLDOWN = 4   # defender cooldown per guard move (= 1 s)

# ── Direction map: ACTION1=Up, ACTION2=Down, ACTION3=Left, ACTION4=Right ───────
_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

# ── Unit colours / labels ──────────────────────────────────────────────────────
UNIT_COLOR = {'sapper': ORG, 'scout': BLUE, 'soldier': GRN}
UNIT_LABEL = {'sapper': 'SAP', 'scout': 'SCT', 'soldier': 'SOL'}

# ── Tower geometry ─────────────────────────────────────────────────────────────
TOWER_CORE     = (10, 5)
TOWER_INTERIOR = frozenset((x, y) for x in range(9, 12) for y in range(4, 7))

_TOWER_SOLID = frozenset([
    (8,3),(9,3),(10,3),(11,3),(12,3),
    (8,4),(8,5),(8,6),
    (12,4),(12,5),(12,6),
    (8,7),(9,7),(11,7),(12,7),
])


# ── Level data ─────────────────────────────────────────────────────────────────
_LEVELS = [
    {
        'name': 'The Breach',
        'walls': _TOWER_SOLID,
        'breach_walls': frozenset([(10, 7)]),
        'gate': None,
        'gaps': frozenset(),
        'guards': [{'x': 10, 'y': 11}],
        'guard_reserves': 1,
        'unit_starts': [(10, 16), (10, 16), (10, 16)],
        'active_units': ['sapper'],
        'turn_limit': 120,
    },
    {
        'name': 'Timed Gate',
        'walls': _TOWER_SOLID - frozenset([(8, 5)]),
        'breach_walls': frozenset([(8, 5)]),
        'gate': {'x': 10, 'y': 7, 'period': 12, 'open_offset': 0},
        'gaps': frozenset(),
        'guards': [{'x': 10, 'y': 10}],
        'guard_reserves': 1,
        'unit_starts': [(4, 5), (10, 14), (10, 16)],
        'active_units': ['sapper', 'scout'],
        'turn_limit': 160,
    },
    {
        'name': 'Two Guards',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 12, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),
        'guards': [{'x': 10, 'y': 11}, {'x': 9, 'y': 8}],
        'guard_reserves': 2,
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 200,
    },
    {
        'name': 'Full Assault',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 12, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),
        'guards': [{'x': 10, 'y': 11}, {'x': 11, 'y': 8}, {'x': 14, 'y': 5}],
        'guard_reserves': 2,
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 240,
    },
    {
        'name': 'The Gauntlet',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 12, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),
        'guards': [{'x': 10, 'y': 11}, {'x': 11, 'y': 8}, {'x': 14, 'y': 5}],
        'guard_reserves': 3,
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 160,
    },
]

_LEVEL_OBJECTS = [
    Level(sprites=[], grid_size=(GW, GH), name=d['name'], data=d)
    for d in _LEVELS
]


# ── Pixel helpers ──────────────────────────────────────────────────────────────

def _px(gx, gy):
    return GRID_X + gx * CELL, GRID_Y + gy * CELL

def _fill(frame, px, py, w, h, color):
    x0 = max(0, px);      y0 = max(0, py)
    x1 = min(CW, px + w); y1 = min(CH, py + h)
    if x0 < x1 and y0 < y1:
        frame[y0:y1, x0:x1] = color

def _cell(frame, gx, gy, color):
    px, py = _px(gx, gy)
    _fill(frame, px, py, CELL, CELL, color)

def _dot(frame, px, py, color):
    if 0 <= px < CW and 0 <= py < CH:
        frame[py, px] = color


# ── Bitmap font (3×5) ──────────────────────────────────────────────────────────
_FONT = {
    '0': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
    '1': [(1,0),(1,1),(1,2),(1,3),(1,4)],
    '2': [(0,0),(1,0),(2,0),(2,1),(0,2),(1,2),(2,2),(0,3),(0,4),(1,4),(2,4)],
    '3': [(0,0),(1,0),(2,0),(2,1),(1,2),(2,2),(2,3),(0,4),(1,4),(2,4)],
    '4': [(0,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(2,3),(2,4)],
    '5': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(2,2),(2,3),(0,4),(1,4),(2,4)],
    '6': [(0,0),(1,0),(0,1),(0,2),(1,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
    '7': [(0,0),(1,0),(2,0),(2,1),(2,2),(2,3),(2,4)],
    '8': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
    '9': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(2,3),(0,4),(1,4),(2,4)],
    ':': [(1,1),(1,3)],
    'A': [(1,0),(0,1),(2,1),(0,2),(1,2),(2,2),(0,3),(2,3),(0,4),(2,4)],
    'C': [(0,0),(1,0),(2,0),(0,1),(0,2),(0,3),(0,4),(1,4),(2,4)],
    'D': [(0,0),(1,0),(0,1),(2,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4)],
    'E': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(0,3),(0,4),(1,4),(2,4)],
    'G': [(0,0),(1,0),(2,0),(0,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
    'I': [(1,0),(1,1),(1,2),(1,3),(1,4)],
    'K': [(0,0),(2,0),(0,1),(1,1),(0,2),(0,3),(1,3),(0,4),(2,4)],
    'L': [(0,0),(0,1),(0,2),(0,3),(0,4),(1,4),(2,4)],
    'O': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
    'P': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(0,3),(0,4)],
    'R': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(0,3),(2,3),(0,4)],
    'S': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(2,2),(2,3),(0,4),(1,4),(2,4)],
    'T': [(0,0),(1,0),(2,0),(1,1),(1,2),(1,3),(1,4)],
    'V': [(0,0),(2,0),(0,1),(2,1),(0,2),(2,2),(1,3),(1,4)],
    'X': [(0,0),(2,0),(1,2),(0,4),(2,4),(0,1),(2,1),(0,3),(2,3)],
}

def _draw_label(frame, px, py, text, color):
    cx = px
    for ch in text:
        for dx, dy in _FONT.get(ch, []):
            fx, fy = cx + dx, py + dy
            if 0 <= fx < CW and 0 <= fy < CH:
                frame[fy, fx] = color
        cx += 4


# ── Renderer ───────────────────────────────────────────────────────────────────

class Ts01Display(RenderableUserDisplay):
    def __init__(self, game: "Ts01"):
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        frame[:] = VDGRAY

        # ── HUD ──────────────────────────────────────────────────────────────
        _fill(frame, 0, 0, CW, 9, BLACK)
        for i in range(5):
            _dot(frame, 2 + i * 4, 4, YEL if i <= g.level_index else DGRAY)
        secs = max(0, (g.turn_limit - g.turn) // DEFAULT_FPS)
        _draw_label(frame, 22, 2, f'{secs:02d}S', RED if secs < 10 else WHITE)

        # ── Floor ─────────────────────────────────────────────────────────────
        for gy in range(GH):
            for gx in range(GW):
                _cell(frame, gx, gy, DGRAY)

        # ── Gaps ─────────────────────────────────────────────────────────────
        for (gx, gy) in g.gaps:
            _cell(frame, gx, gy, LBLUE)

        # ── Solid walls ───────────────────────────────────────────────────────
        for (gx, gy) in g.walls:
            _cell(frame, gx, gy, GRAY)

        # ── Breachable walls ──────────────────────────────────────────────────
        for (gx, gy) in g.breach_walls:
            _cell(frame, gx, gy, LGRAY)

        # ── Pending bombs ─────────────────────────────────────────────────────
        for (gx, gy) in g.pending_bombs:
            _cell(frame, gx, gy, MAG)

        # ── Gate ──────────────────────────────────────────────────────────────
        if g.gate:
            gx, gy = g.gate['x'], g.gate['y']
            _cell(frame, gx, gy, GRN if g._gate_open() else MAR)

        # ── Tower core ────────────────────────────────────────────────────────
        _cell(frame, TOWER_CORE[0], TOWER_CORE[1], YEL)

        # ── Spawn zone dots (defender has reserves + no guard selected) ────────
        if g.guard_reserves > 0 and g.selected_guard_idx is None:
            for (sx, sy) in g._compute_spawn_zone():
                if not g._guard_at(sx, sy) and not g._occupied_by_unit(sx, sy):
                    px, py = _px(sx, sy)
                    _dot(frame, px, py, MAR)

        # ── Guards ────────────────────────────────────────────────────────────
        for idx, guard in enumerate(g.guards):
            if not guard.get('alive', True):
                continue
            gx, gy = guard['x'], guard['y']
            on_cd = guard.get('cooldown', 0) > 0
            if g.selected_guard_idx == idx:
                px, py = _px(gx, gy)
                _fill(frame, px - 1, py - 1, CELL + 2, CELL + 2, LMAG)
            if on_cd:
                _cell(frame, gx, gy, DGRAY)
                px, py = _px(gx, gy)
                _dot(frame, px, py, RED)
            else:
                _cell(frame, gx, gy, RED)

        # ── Guard valid-move dots ─────────────────────────────────────────────
        if g.selected_guard_idx is not None:
            for (mx, my) in g.valid_guard_moves:
                px, py = _px(mx, my)
                _dot(frame, px, py, RED)

        # ── Attacker units ────────────────────────────────────────────────────
        for idx, unit in enumerate(g.units):
            if unit['locked'] or not unit['alive']:
                continue
            color = UNIT_COLOR[unit['type']]
            gx, gy = unit['x'], unit['y']
            not_ready = unit.get('frozen', 0) > 0 or unit.get('cooldown', 0) > 0
            if g.selected_idx == idx:
                px, py = _px(gx, gy)
                _fill(frame, px - 1, py - 1, CELL + 2, CELL + 2, LMAG)
            if not_ready:
                _cell(frame, gx, gy, LGRAY)
                px, py = _px(gx, gy)
                _dot(frame, px, py, color)
            else:
                _cell(frame, gx, gy, color)

        # ── Unit move-hint dots (white = move, full = tool) ───────────────────
        if g.selected_idx is not None:
            for (mx, my) in g.valid_targets:
                if (mx, my) in g.valid_tool_targets:
                    px, py = _px(mx, my)
                    _dot(frame, px, py, WHITE)
                    _dot(frame, px+1, py, WHITE)
                    _dot(frame, px, py+1, WHITE)
                    _dot(frame, px+1, py+1, WHITE)
                else:
                    px, py = _px(mx, my)
                    _dot(frame, px, py, WHITE)

        # ── Right panel ───────────────────────────────────────────────────────
        panel_x = 44
        _fill(frame, panel_x, 0, CW - panel_x, CH, BLACK)

        # LIVE indicator
        _dot(frame, panel_x + 1, 3, GRN)
        _draw_label(frame, panel_x + 4, 1, 'LIVE', GRN)

        # Attacker unit status
        row_y = 10
        for unit in g.units:
            if unit['locked']:
                _dot(frame, panel_x + 1, row_y + 1, DGRAY)
                _draw_label(frame, panel_x + 4, row_y, UNIT_LABEL[unit['type']], DGRAY)
            elif not unit['alive']:
                _dot(frame, panel_x + 1, row_y + 1, DGRAY)
                _draw_label(frame, panel_x + 4, row_y, 'XXX', RED)
            else:
                color = UNIT_COLOR[unit['type']]
                not_ready = unit.get('frozen', 0) > 0 or unit.get('cooldown', 0) > 0
                _dot(frame, panel_x + 1, row_y + 1, LGRAY if not_ready else color)
                _draw_label(frame, panel_x + 4, row_y, UNIT_LABEL[unit['type']], WHITE)
                if unit['type'] == 'sapper' and unit.get('bomb_ready', False):
                    _dot(frame, panel_x + 1, row_y + 3, MAG)
                if unit['type'] == 'scout' and unit.get('grapple_ready', False):
                    _dot(frame, panel_x + 1, row_y + 3, LBLUE)
            row_y += 8

        # Separator + guard info
        for sx in [panel_x + 2, panel_x + 6, panel_x + 10]:
            _dot(frame, sx, 35, DGRAY)
        active_guards = [gd for gd in g.guards if gd.get('alive', True)]
        _draw_label(frame, panel_x + 2, 38, f'G:{len(active_guards)}', RED)
        _draw_label(frame, panel_x + 2, 46, f'R:{g.guard_reserves}', MAR)

        return frame


# ── Game class ─────────────────────────────────────────────────────────────────

class Ts01(ARCBaseGame):
    def __init__(self):
        self.display = Ts01Display(self)

        self.units = []
        self.walls = set()
        self.breach_walls = set()
        self.pending_bombs = {}
        self.gate = None
        self.gaps = set()
        self.guards = []
        self.guard_reserves = 0
        self.turn = 0
        self.turn_limit = 120

        self.selected_idx = None        # attacker unit currently selected
        self.valid_targets = set()
        self.valid_tool_targets = set()

        self.selected_guard_idx = None  # defender guard currently selected
        self.valid_guard_moves = set()

        super().__init__(
            'ts',
            _LEVEL_OBJECTS,
            Camera(0, 0, CW, CH, VDGRAY, VDGRAY, [self.display]),
            False,
            len(_LEVEL_OBJECTS),
            [1, 2, 3, 4, 5, 6, 7],  # arrows + Z(5) + click(6) + tick(7)
        )

    # ── Level setup ────────────────────────────────────────────────────────────

    def on_set_level(self, level: Level) -> None:
        d = _LEVELS[self.level_index]
        self.walls = set(d['walls'])
        self.breach_walls = set(d['breach_walls'])
        self.pending_bombs = {}
        self.gate = dict(d['gate']) if d['gate'] else None
        self.gaps = set(d['gaps'])

        self.guards = [
            {'x': g['x'], 'y': g['y'], 'alive': True, 'cooldown': 0}
            for g in d['guards']
        ]
        self.guard_reserves = d['guard_reserves']

        active = d['active_units']
        starts = d['unit_starts']
        self.units = [
            {
                'type': 'sapper',
                'x': starts[0][0], 'y': starts[0][1],
                'alive': True, 'frozen': 0, 'cooldown': 0,
                'bomb_ready': True,
                'locked': 'sapper' not in active,
            },
            {
                'type': 'scout',
                'x': starts[1][0], 'y': starts[1][1],
                'alive': True, 'frozen': 0, 'cooldown': 0,
                'grapple_ready': True,
                'locked': 'scout' not in active,
            },
            {
                'type': 'soldier',
                'x': starts[2][0], 'y': starts[2][1],
                'alive': True, 'frozen': 0, 'cooldown': 0,
                'locked': 'soldier' not in active,
            },
        ]

        self.selected_idx = None
        self.valid_targets = set()
        self.valid_tool_targets = set()
        self.selected_guard_idx = None
        self.valid_guard_moves = set()
        self.turn = 0
        self.turn_limit = d['turn_limit']

        # Auto-select first available attacker unit
        self._select_first_unit()

    # ── Step entry ─────────────────────────────────────────────────────────────

    def step(self) -> None:
        action_id = self.action.id.value

        if action_id == 7:
            # ACT7 — world tick (auto from live mode or X key)
            self._tick()

        elif action_id == 5:
            # Z key — cycle to next attacker unit
            self._cycle_unit()

        elif action_id in _DIR:
            # Arrow keys — move selected attacker unit
            self._move_unit(action_id)

        elif action_id == 6:
            # Mouse click — defender only
            data = self.action.data
            if data and 'x' in data and 'y' in data:
                px = int(data['x'])
                py = int(data['y'])
                gx = (px - GRID_X) // CELL
                gy = (py - GRID_Y) // CELL
                if 0 <= gx < GW and 0 <= gy < GH:
                    self._handle_defender_click(gx, gy)

        self.complete_action()

    # ── World tick ─────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        # Tick bombs
        for pos in list(self.pending_bombs.keys()):
            self.pending_bombs[pos] -= 1
        expired = [pos for pos, t in self.pending_bombs.items() if t <= 0]
        for pos in expired:
            self.breach_walls.discard(pos)
            del self.pending_bombs[pos]

        # Decrement freeze / cooldown on units
        for unit in self.units:
            if unit.get('frozen', 0) > 0:
                unit['frozen'] -= 1
            if unit.get('cooldown', 0) > 0:
                unit['cooldown'] -= 1

        # Decrement cooldown on guards
        for guard in self.guards:
            if guard.get('cooldown', 0) > 0:
                guard['cooldown'] -= 1

        # Remove dead guards
        self.guards = [g for g in self.guards if g.get('alive', True)]

        # Refresh move hints for selected unit (cooldown may have just expired)
        if self.selected_idx is not None:
            self._update_valid_targets()

        self.turn += 1

        # Lose: all attacker units gone or time up
        alive = [u for u in self.units if not u['locked'] and u['alive']]
        if not alive or self.turn >= self.turn_limit:
            self.lose()

    # ── Attacker keyboard: Z = cycle unit ──────────────────────────────────────

    def _cycle_unit(self) -> None:
        """Z key: cycle to the next available (non-locked, alive, ready) unit."""
        available = [
            i for i, u in enumerate(self.units)
            if not u['locked'] and u['alive']
            and u.get('frozen', 0) == 0 and u.get('cooldown', 0) == 0
        ]
        if not available:
            return
        if self.selected_idx not in available:
            self.selected_idx = available[0]
        else:
            pos = available.index(self.selected_idx)
            self.selected_idx = available[(pos + 1) % len(available)]
        self._update_valid_targets()

    # ── Attacker keyboard: arrow = move/use-tool ───────────────────────────────

    def _move_unit(self, action_id: int) -> None:
        """Arrow key: move selected unit or use tool in that direction."""
        if self.selected_idx is None:
            return
        unit = self.units[self.selected_idx]
        if not unit['alive'] or unit.get('frozen', 0) > 0 or unit.get('cooldown', 0) > 0:
            return

        dx, dy = _DIR[action_id]
        ux, uy = unit['x'], unit['y']
        tx, ty = ux + dx, uy + dy

        # Tool use: Sapper bomb (arrow toward breach wall)
        if (unit['type'] == 'sapper' and unit.get('bomb_ready', False)
                and (tx, ty) in self.breach_walls
                and (tx, ty) not in self.pending_bombs):
            self.pending_bombs[(tx, ty)] = BOMB_TICKS
            unit['bomb_ready'] = False
            unit['cooldown'] = UNIT_COOLDOWN
            self._update_valid_targets()
            return

        # Tool use: Scout grapple (arrow toward adjacent gap)
        if (unit['type'] == 'scout' and unit.get('grapple_ready', False)
                and (tx, ty) in self.gaps):
            lx, ly = tx + dx, ty + dy
            if 0 <= lx < GW and 0 <= ly < GH and not self._is_blocked(lx, ly):
                unit['x'] = lx
                unit['y'] = ly
                unit['grapple_ready'] = False
                unit['cooldown'] = UNIT_COOLDOWN
                self._update_valid_targets()
                if self._check_win():
                    self._win_or_advance()
                return

        # Normal move
        if self._passable_for_unit(tx, ty, unit):
            guard_here = self._guard_at(tx, ty)
            if guard_here is not None and unit['type'] == 'soldier':
                guard_here['alive'] = False
                unit['frozen'] = FREEZE_TICKS
            unit['x'] = tx
            unit['y'] = ty
            unit['cooldown'] = UNIT_COOLDOWN
            # Keep unit selected; refresh hints for new position
            self._update_valid_targets()
            if self._check_win():
                self._win_or_advance()

    # ── Defender mouse click ────────────────────────────────────────────────────

    def _handle_defender_click(self, gx: int, gy: int) -> None:
        """Mouse click routes exclusively to defender (guard) logic."""
        if self.selected_guard_idx is not None:
            self._do_defender_action(gx, gy)
        else:
            # Try to select a guard
            for idx, guard in enumerate(self.guards):
                if guard.get('alive', True) and guard['x'] == gx and guard['y'] == gy:
                    if guard.get('cooldown', 0) == 0:
                        self.selected_guard_idx = idx
                        self.valid_guard_moves = self._guard_valid_moves(idx)
                    return

            # Try to spawn a reserve guard
            if self.guard_reserves > 0 and (gx, gy) in self._compute_spawn_zone():
                if not self._guard_at(gx, gy) and not self._occupied_by_unit(gx, gy):
                    self._spawn_guard(gx, gy)

    def _do_defender_action(self, gx: int, gy: int) -> None:
        """Handle click while a guard is selected."""
        guard = self.guards[self.selected_guard_idx]

        if guard['x'] == gx and guard['y'] == gy:
            self._clear_guard_selection()
            return

        if (gx, gy) in self.valid_guard_moves:
            self._execute_guard_move(self.selected_guard_idx, gx, gy)
            guard['cooldown'] = GUARD_COOLDOWN
            self._clear_guard_selection()
            alive = [u for u in self.units if not u['locked'] and u['alive']]
            if not alive:
                self.lose()
            return

        # Re-select a different guard
        for idx, g in enumerate(self.guards):
            if g.get('alive', True) and g['x'] == gx and g['y'] == gy:
                if g.get('cooldown', 0) == 0:
                    self.selected_guard_idx = idx
                    self.valid_guard_moves = self._guard_valid_moves(idx)
                return

        # Spawn while guard selected
        if self.guard_reserves > 0 and (gx, gy) in self._compute_spawn_zone():
            if not self._guard_at(gx, gy) and not self._occupied_by_unit(gx, gy):
                self._spawn_guard(gx, gy)
                self._clear_guard_selection()
                return

        self._clear_guard_selection()

    def _execute_guard_move(self, idx: int, tx: int, ty: int) -> None:
        guard = self.guards[idx]
        guard['x'] = tx
        guard['y'] = ty
        for unit in self.units:
            if unit['locked'] or not unit['alive']:
                continue
            if unit['x'] == tx and unit['y'] == ty:
                if unit['type'] == 'soldier':
                    guard['alive'] = False
                    unit['frozen'] = max(unit.get('frozen', 0), FREEZE_TICKS)
                else:
                    unit['alive'] = False

    def _spawn_guard(self, sx: int, sy: int) -> None:
        self.guards.append({'x': sx, 'y': sy, 'alive': True, 'cooldown': 0})
        self.guard_reserves -= 1

    # ── Selection helpers ──────────────────────────────────────────────────────

    def _select_first_unit(self) -> None:
        """Auto-select the first available attacker unit at level start."""
        for i, u in enumerate(self.units):
            if not u['locked'] and u['alive']:
                self.selected_idx = i
                self._update_valid_targets()
                return

    def _clear_guard_selection(self) -> None:
        self.selected_guard_idx = None
        self.valid_guard_moves = set()

    # ── Win helpers ────────────────────────────────────────────────────────────

    def _check_win(self) -> bool:
        cx, cy = TOWER_CORE
        return any(
            not u['locked'] and u['alive'] and u['x'] == cx and u['y'] == cy
            for u in self.units
        )

    def _win_or_advance(self) -> None:
        if not self.is_last_level():
            self.next_level()
        else:
            self.win()

    # ── Valid target computation ────────────────────────────────────────────────

    def _guard_valid_moves(self, idx: int) -> set:
        guard = self.guards[idx]
        gx, gy = guard['x'], guard['y']
        moves = set()
        for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
            nx, ny = gx + dx, gy + dy
            if not (0 <= nx < GW and 0 <= ny < GH):
                continue
            if (nx, ny) in self.walls or (nx, ny) in self.breach_walls:
                continue
            if (nx, ny) in self.pending_bombs or (nx, ny) in self.gaps:
                continue
            if self.gate and (nx, ny) == (self.gate['x'], self.gate['y']) and not self._gate_open():
                continue
            if any(i != idx and g.get('alive', True) and g['x'] == nx and g['y'] == ny
                   for i, g in enumerate(self.guards)):
                continue
            moves.add((nx, ny))
        return moves

    def _compute_spawn_zone(self) -> set:
        adjacent = set()
        for (wx, wy) in self.walls:
            for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
                nx, ny = wx + dx, wy + dy
                if not (0 <= nx < GW and 0 <= ny < GH):
                    continue
                if (nx, ny) in self.walls or (nx, ny) in self.breach_walls:
                    continue
                if (nx, ny) in self.pending_bombs or (nx, ny) in self.gaps:
                    continue
                if (nx, ny) in TOWER_INTERIOR:
                    continue
                adjacent.add((nx, ny))
        return adjacent

    def _update_valid_targets(self) -> None:
        if self.selected_idx is None:
            self.valid_targets = set()
            self.valid_tool_targets = set()
            return
        unit = self.units[self.selected_idx]
        if not unit['alive'] or unit.get('frozen', 0) > 0 or unit.get('cooldown', 0) > 0:
            self.valid_targets = set()
            self.valid_tool_targets = set()
            return

        moves = set()
        tools = set()
        ux, uy = unit['x'], unit['y']

        for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
            nx, ny = ux + dx, uy + dy
            if self._passable_for_unit(nx, ny, unit):
                moves.add((nx, ny))
            if unit['type'] == 'scout':
                if self._passable_for_unit(nx, ny, unit) and not self._occupied_by_unit(nx, ny):
                    nx2, ny2 = ux + 2*dx, uy + 2*dy
                    if self._passable_for_unit(nx2, ny2, unit):
                        moves.add((nx2, ny2))

        if unit['type'] == 'sapper' and unit.get('bomb_ready', False):
            for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
                nx, ny = ux + dx, uy + dy
                if (nx, ny) in self.breach_walls and (nx, ny) not in self.pending_bombs:
                    tools.add((nx, ny))

        if unit['type'] == 'scout' and unit.get('grapple_ready', False):
            for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
                nx, ny = ux + dx, uy + dy
                if (nx, ny) in self.gaps:
                    lx, ly = nx + dx, ny + dy
                    if 0 <= lx < GW and 0 <= ly < GH and not self._is_blocked(lx, ly):
                        tools.add((nx, ny))

        self.valid_targets = moves | tools
        self.valid_tool_targets = tools

    # ── Passability ────────────────────────────────────────────────────────────

    def _passable_for_unit(self, x: int, y: int, unit: dict) -> bool:
        if x < 0 or x >= GW or y < 0 or y >= GH:
            return False
        if (x, y) in self.walls or (x, y) in self.breach_walls:
            return False
        if (x, y) in self.pending_bombs or (x, y) in self.gaps:
            return False
        if self.gate and (x, y) == (self.gate['x'], self.gate['y']):
            return self._gate_open()
        if self._guard_at(x, y) is not None:
            return unit['type'] == 'soldier'
        return True

    def _is_blocked(self, x: int, y: int) -> bool:
        if x < 0 or x >= GW or y < 0 or y >= GH:
            return True
        if (x, y) in self.walls or (x, y) in self.breach_walls:
            return True
        if (x, y) in self.pending_bombs or (x, y) in self.gaps:
            return True
        if self.gate and (x, y) == (self.gate['x'], self.gate['y']) and not self._gate_open():
            return True
        return False

    def _occupied_by_unit(self, x: int, y: int) -> bool:
        return any(
            not u['locked'] and u['alive'] and u['x'] == x and u['y'] == y
            for u in self.units
        )

    def _guard_at(self, x: int, y: int):
        for guard in self.guards:
            if guard.get('alive', True) and guard['x'] == x and guard['y'] == y:
                return guard
        return None

    def _gate_open(self) -> bool:
        if self.gate is None:
            return True
        return self.turn % self.gate['period'] == self.gate['open_offset']
