# Author: Claude Sonnet 4.6
# Date: 2026-03-19 00:00
# PURPOSE: Tower Siege (ts01) v2 — two-player hot-seat puzzle. Player 1 (Attacker)
#          controls Sapper/Scout/Soldier units; Player 2 (Defender) manually controls
#          guards and can spawn reinforcements from the tower perimeter. Players alternate:
#          P1 acts → P2 acts → world advances (bombs tick, freeze decrements, turn++).
#          Win: any attacker unit reaches tower core. Lose: all attacker units eliminated
#          or turn limit reached. Click-only (ACTION6). Version bump from 00000001.
# SRP/DRY check: Pass — new version (00000002); v1 (00000001) left intact for replay.
"""
ts01 v2 – Tower Siege (Two-Player)

Player 1 (Attacker) — clicks to select and move Sapper/Scout/Soldier units.
Player 2 (Defender) — clicks to select and move guards, or spawn reinforcements
                      from cells adjacent to the tower exterior. Click outside the
                      grid to pass P2's turn without moving.

Units (Attacker — unlock progressively)
-----------------------------------------
Sapper  (Orange) L1+ : click adjacent breachable wall → bomb it (wall gone next turn)
Scout   (Blue)   L2+ : moves 1–2 cells in a straight line; click adjacent gap → grapple
Soldier (Green)  L3+ : moving onto a guard cell removes the guard (Soldier frozen 1 turn)

Guards (Defender)
------------------
Guards (Red) move 1 orthogonal step per turn under P2 control. Walking onto an attacker
unit eliminates it (or triggers Soldier contact-kill). P2 can also spend a reserve to
spawn a new guard on any open cell adjacent to the tower exterior walls.

Goal: Attacker lands any unit on the tower core (Yellow). Defender stops them.

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
GRID_X = 2      # grid top-left pixel x
GRID_Y = 10     # grid top-left pixel y (leaves 10px for HUD)
CELL   = 2      # pixels per cell
GW     = 20     # grid width in cells
GH     = 20     # grid height in cells

# ── Unit colour map ────────────────────────────────────────────────────────────
UNIT_COLOR = {'sapper': ORG, 'scout': BLUE, 'soldier': GRN}
UNIT_LABEL = {'sapper': 'SAP', 'scout': 'SCT', 'soldier': 'SOL'}

# ── Tower geometry (shared across all levels) ──────────────────────────────────
# Tower outer wall: cols 8-12, rows 3-7. Interior floor: rows 4-6, cols 9-11.
# Core target: (10, 5). Spawn zone: exterior cells adjacent to solid walls.
TOWER_CORE = (10, 5)
TOWER_INTERIOR = frozenset((x, y) for x in range(9, 12) for y in range(4, 7))

# Solid (indestructible) tower wall cells — bottom-centre (10,7) varies per level.
_TOWER_SOLID = frozenset([
    # top wall
    (8,3),(9,3),(10,3),(11,3),(12,3),
    # left wall
    (8,4),(8,5),(8,6),
    # right wall
    (12,4),(12,5),(12,6),
    # bottom wall corners (centre (10,7) varies per level)
    (8,7),(9,7),(11,7),(12,7),
])


# ── Level data ─────────────────────────────────────────────────────────────────
# Guards: list of {'x': int, 'y': int} starting positions — P2 moves them manually.
# guard_reserves: extra guards P2 can spawn during the level.
_LEVELS = [
    # ── L1: The Breach ─────────────────────────────────────────────────────────
    # Sapper vs 1 guard + 1 reserve. P1 must breach south wall and dodge guard.
    # P2 starts with guard at (10,11) blocking the direct south approach.
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
        'turn_limit': 18,
    },

    # ── L2: Timed Gate ─────────────────────────────────────────────────────────
    # Sapper+Scout vs 1 guard + 1 reserve. Gate at (10,7) opens every 3 turns.
    # Breach wall at (8,5) is the west approach. P2 must choose which to block.
    {
        'name': 'Timed Gate',
        'walls': _TOWER_SOLID - frozenset([(8, 5)]),
        'breach_walls': frozenset([(8, 5)]),
        'gate': {'x': 10, 'y': 7, 'period': 3, 'open_offset': 0},
        'gaps': frozenset(),
        'guards': [{'x': 10, 'y': 10}],
        'guard_reserves': 1,
        'unit_starts': [(4, 5), (10, 14), (10, 16)],
        'active_units': ['sapper', 'scout'],
        'turn_limit': 20,
    },

    # ── L3: Two Guards ─────────────────────────────────────────────────────────
    # All units vs 2 guards + 2 reserves. Gate east (12,5), breach south (10,7),
    # gap at (15,9) for Scout grapple. P2 manages two guards and reinforcements.
    {
        'name': 'Two Guards',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 4, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),
        'guards': [{'x': 10, 'y': 11}, {'x': 9, 'y': 8}],
        'guard_reserves': 2,
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 28,
    },

    # ── L4: Full Assault ───────────────────────────────────────────────────────
    # All units vs 3 guards + 2 reserves. P2 has strong defensive force.
    {
        'name': 'Full Assault',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 4, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),
        'guards': [{'x': 10, 'y': 11}, {'x': 11, 'y': 8}, {'x': 14, 'y': 5}],
        'guard_reserves': 2,
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 32,
    },

    # ── L5: The Gauntlet ───────────────────────────────────────────────────────
    # Same as L4 but tighter turn budget and more reserves — forces efficient play.
    {
        'name': 'The Gauntlet',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 4, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),
        'guards': [{'x': 10, 'y': 11}, {'x': 11, 'y': 8}, {'x': 14, 'y': 5}],
        'guard_reserves': 3,
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 22,
    },
]

_LEVEL_OBJECTS = [
    Level(sprites=[], grid_size=(GW, GH), name=d['name'], data=d)
    for d in _LEVELS
]


# ── Pixel helpers ──────────────────────────────────────────────────────────────

def _px(gx, gy):
    """Top-left pixel of grid cell (gx, gy)."""
    return GRID_X + gx * CELL, GRID_Y + gy * CELL


def _fill(frame, px, py, w, h, color):
    x0 = max(0, px);       y0 = max(0, py)
    x1 = min(CW, px + w);  y1 = min(CH, py + h)
    if x0 < x1 and y0 < y1:
        frame[y0:y1, x0:x1] = color


def _cell(frame, gx, gy, color):
    """Fill one grid cell with a colour."""
    px, py = _px(gx, gy)
    _fill(frame, px, py, CELL, CELL, color)


def _dot(frame, px, py, color):
    if 0 <= px < CW and 0 <= py < CH:
        frame[py, px] = color


# ── Tiny bitmap font (3×5) for HUD labels ─────────────────────────────────────
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
    '/': [(2,0),(1,1),(1,2),(0,3),(0,4)],
    'A': [(1,0),(0,1),(2,1),(0,2),(1,2),(2,2),(0,3),(2,3),(0,4),(2,4)],
    'C': [(0,0),(1,0),(2,0),(0,1),(0,2),(0,3),(0,4),(1,4),(2,4)],
    'D': [(0,0),(1,0),(0,1),(2,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4)],
    'E': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(0,3),(0,4),(1,4),(2,4)],
    'F': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(0,3),(0,4)],
    'G': [(0,0),(1,0),(2,0),(0,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
    'K': [(0,0),(2,0),(0,1),(1,1),(0,2),(0,3),(1,3),(0,4),(2,4)],
    'L': [(0,0),(0,1),(0,2),(0,3),(0,4),(1,4),(2,4)],
    'O': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
    'P': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(0,3),(0,4)],
    'R': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(0,3),(2,3),(0,4)],
    'S': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(2,2),(2,3),(0,4),(1,4),(2,4)],
    'T': [(0,0),(1,0),(2,0),(1,1),(1,2),(1,3),(1,4)],
    'X': [(0,0),(2,0),(1,2),(0,4),(2,4),(0,1),(2,1),(0,3),(2,3)],
}


def _draw_label(frame, px, py, text, color):
    """Draw text at pixel (px,py) using 3×5 bitmap font, 1px gap between chars."""
    cx = px
    for ch in text:
        pixels = _FONT.get(ch, [])
        for dx, dy in pixels:
            fx, fy = cx + dx, py + dy
            if 0 <= fx < CW and 0 <= fy < CH:
                frame[fy, fx] = color
        cx += 4   # 3 wide + 1 gap


# ── Renderer ───────────────────────────────────────────────────────────────────

class Ts01Display(RenderableUserDisplay):
    def __init__(self, game: "Ts01"):
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        frame[:] = VDGRAY

        # ── HUD bar (top 9 rows) ────────────────────────────────────────────
        _fill(frame, 0, 0, CW, 9, BLACK)

        # Level dots
        for i in range(5):
            c = YEL if i <= g.level_index else DGRAY
            _dot(frame, 2 + i * 4, 4, c)

        # Turn counter
        _draw_label(frame, 22, 2, f'T:{g.turn:02d}/{g.turn_limit:02d}', WHITE)

        # ── Floor ────────────────────────────────────────────────────────────
        for gy in range(GH):
            for gx in range(GW):
                _cell(frame, gx, gy, DGRAY)

        # ── Gaps ─────────────────────────────────────────────────────────────
        for (gx, gy) in g.gaps:
            _cell(frame, gx, gy, LBLUE)

        # ── Solid tower walls ─────────────────────────────────────────────────
        for (gx, gy) in g.walls:
            _cell(frame, gx, gy, GRAY)

        # ── Breachable walls ──────────────────────────────────────────────────
        for (gx, gy) in g.breach_walls:
            _cell(frame, gx, gy, LGRAY)

        # ── Pending bomb markers ──────────────────────────────────────────────
        for (gx, gy) in g.pending_bombs:
            _cell(frame, gx, gy, MAG)

        # ── Gate ──────────────────────────────────────────────────────────────
        if g.gate is not None:
            gx, gy = g.gate['x'], g.gate['y']
            color = GRN if g._gate_open() else MAR
            _cell(frame, gx, gy, color)

        # ── Tower core ────────────────────────────────────────────────────────
        cx, cy = TOWER_CORE
        _cell(frame, cx, cy, YEL)

        # ── Spawn zone indicators (P2's turn + has reserves + no guard selected) ──
        if g.current_player == 1 and g.guard_reserves > 0 and g.selected_guard_idx is None:
            for (sx, sy) in g._compute_spawn_zone():
                if not g._guard_at(sx, sy) and not g._occupied_by_unit(sx, sy):
                    px, py = _px(sx, sy)
                    _dot(frame, px, py, MAR)

        # ── Guards ────────────────────────────────────────────────────────────
        for idx, guard in enumerate(g.guards):
            if not guard.get('alive', True):
                continue
            gx, gy = guard['x'], guard['y']

            # Selection highlight for defender
            if g.current_player == 1 and g.selected_guard_idx == idx:
                px, py = _px(gx, gy)
                _fill(frame, px - 1, py - 1, CELL + 2, CELL + 2, LMAG)

            _cell(frame, gx, gy, RED)

        # ── Guard valid move hints (P2 has guard selected) ────────────────────
        if g.current_player == 1 and g.selected_guard_idx is not None:
            for (mx, my) in g.valid_guard_moves:
                px, py = _px(mx, my)
                _dot(frame, px, py, RED)

        # ── Attacker units ────────────────────────────────────────────────────
        for idx, unit in enumerate(g.units):
            if unit['locked'] or not unit['alive']:
                continue
            color = UNIT_COLOR[unit['type']]
            gx, gy = unit['x'], unit['y']

            # Selected highlight
            if g.current_player == 0 and g.selected_idx == idx:
                px, py = _px(gx, gy)
                _fill(frame, px - 1, py - 1, CELL + 2, CELL + 2, LMAG)

            # Frozen tint
            if unit.get('frozen', 0) > 0:
                _cell(frame, gx, gy, LGRAY)
                px, py = _px(gx, gy)
                _dot(frame, px, py, color)
            else:
                _cell(frame, gx, gy, color)

        # ── Valid move hints (P1 has unit selected) ───────────────────────────
        if g.current_player == 0 and g.selected_idx is not None:
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

        # Player turn indicator
        if g.current_player == 0:
            _draw_label(frame, panel_x + 2, 2, 'ATK', YEL)
        else:
            _draw_label(frame, panel_x + 2, 2, 'DEF', RED)

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
                if unit.get('frozen', 0) > 0:
                    color = LGRAY
                _dot(frame, panel_x + 1, row_y + 1, color)
                _draw_label(frame, panel_x + 4, row_y, UNIT_LABEL[unit['type']], WHITE)
                if unit['type'] == 'sapper' and unit.get('bomb_ready', False):
                    _dot(frame, panel_x + 1, row_y + 3, MAG)
                if unit['type'] == 'scout' and unit.get('grapple_ready', False):
                    _dot(frame, panel_x + 1, row_y + 3, LBLUE)
            row_y += 8

        # Separator
        _dot(frame, panel_x + 2, 35, DGRAY)
        _dot(frame, panel_x + 6, 35, DGRAY)
        _dot(frame, panel_x + 10, 35, DGRAY)

        # Guard count
        active_guards = [guard for guard in g.guards if guard.get('alive', True)]
        _draw_label(frame, panel_x + 2, 38, f'G:{len(active_guards)}', RED)

        # Reserves
        _draw_label(frame, panel_x + 2, 46, f'R:{g.guard_reserves}', MAR)

        # Pass hint (P2 only)
        if g.current_player == 1:
            _draw_label(frame, panel_x + 2, 55, 'PAS', DGRAY)

        return frame


# ── Game class ─────────────────────────────────────────────────────────────────

class Ts01(ARCBaseGame):
    def __init__(self):
        self.display = Ts01Display(self)

        # Shared state (populated in on_set_level)
        self.units = []
        self.walls = set()
        self.breach_walls = set()
        self.pending_bombs = {}
        self.gate = None
        self.gaps = set()
        self.guards = []
        self.guard_reserves = 0
        self.turn = 0
        self.turn_limit = 16

        # Attacker state
        self.selected_idx = None
        self.valid_targets = set()
        self.valid_tool_targets = set()

        # Defender state
        self.current_player = 0          # 0 = attacker, 1 = defender
        self.selected_guard_idx = None
        self.valid_guard_moves = set()

        super().__init__(
            'ts',
            _LEVEL_OBJECTS,
            Camera(0, 0, CW, CH, VDGRAY, VDGRAY, [self.display]),
            False,
            len(_LEVEL_OBJECTS),
            [6],
        )

    # ── Level setup ────────────────────────────────────────────────────────────

    def on_set_level(self, level: Level) -> None:
        d = _LEVELS[self.level_index]
        self.walls = set(d['walls'])
        self.breach_walls = set(d['breach_walls'])
        self.pending_bombs = {}
        self.gate = dict(d['gate']) if d['gate'] else None
        self.gaps = set(d['gaps'])

        # Guards: simple {x, y, alive} dicts (no auto-patrol — P2 moves them)
        self.guards = [
            {'x': g['x'], 'y': g['y'], 'alive': True}
            for g in d['guards']
        ]
        self.guard_reserves = d['guard_reserves']

        active = d['active_units']
        starts = d['unit_starts']
        self.units = [
            {
                'type': 'sapper',
                'x': starts[0][0], 'y': starts[0][1],
                'alive': True, 'frozen': 0,
                'bomb_ready': True,
                'locked': 'sapper' not in active,
            },
            {
                'type': 'scout',
                'x': starts[1][0], 'y': starts[1][1],
                'alive': True, 'frozen': 0,
                'grapple_ready': True,
                'locked': 'scout' not in active,
            },
            {
                'type': 'soldier',
                'x': starts[2][0], 'y': starts[2][1],
                'alive': True, 'frozen': 0,
                'locked': 'soldier' not in active,
            },
        ]

        self.selected_idx = None
        self.valid_targets = set()
        self.valid_tool_targets = set()
        self.selected_guard_idx = None
        self.valid_guard_moves = set()
        self.current_player = 0
        self.turn = 0
        self.turn_limit = d['turn_limit']

    # ── Step ───────────────────────────────────────────────────────────────────

    def step(self) -> None:
        if self.action.id.value != 6:
            self.complete_action()
            return

        data = self.action.data
        if not data or 'x' not in data or 'y' not in data:
            self.complete_action()
            return

        px = int(data['x'])
        py = int(data['y'])

        # Convert pixel → grid cell
        gx = (px - GRID_X) // CELL
        gy = (py - GRID_Y) // CELL
        in_grid = 0 <= gx < GW and 0 <= gy < GH

        if self.current_player == 0:
            # ── Attacker's turn ──────────────────────────────────────────────
            if not in_grid:
                self.complete_action()
                return

            action_taken = self._handle_attacker_click(gx, gy)

            # If all units are frozen, any in-grid click counts as a pass
            if not action_taken and self._all_units_frozen():
                action_taken = True

            if action_taken:
                self.selected_idx = None
                self.valid_targets = set()
                self.valid_tool_targets = set()
                # Check win/lose immediately after attacker acts (before world advance)
                result = self._check_win_lose(check_turn_limit=False)
                if result == 'win':
                    if not self.is_last_level():
                        self.next_level()
                    else:
                        self.win()
                elif result == 'lose':
                    self.lose()
                else:
                    self.current_player = 1  # switch to defender

        else:
            # ── Defender's turn ──────────────────────────────────────────────
            defender_acted = self._handle_defender_click(gx, gy, in_grid)

            if defender_acted:
                self.selected_guard_idx = None
                self.valid_guard_moves = set()
                self._advance_turn()
                result = self._check_win_lose(check_turn_limit=True)
                if result == 'win':
                    if not self.is_last_level():
                        self.next_level()
                    else:
                        self.win()
                elif result == 'lose':
                    self.lose()
                else:
                    self.current_player = 0  # back to attacker

        self.complete_action()

    # ── Attacker click handling ─────────────────────────────────────────────────

    def _handle_attacker_click(self, gx: int, gy: int) -> bool:
        """Process P1 click at grid cell (gx, gy). Returns True if action taken."""
        action_taken = False

        if self.selected_idx is None:
            for idx, unit in enumerate(self.units):
                if not unit['locked'] and unit['alive'] and unit['x'] == gx and unit['y'] == gy:
                    self.selected_idx = idx
                    self._update_valid_targets()
                    break
        else:
            unit = self.units[self.selected_idx]
            if unit['x'] == gx and unit['y'] == gy:
                # Clicked same unit → deselect
                self.selected_idx = None
                self.valid_targets = set()
                self.valid_tool_targets = set()
            elif (gx, gy) in self.valid_tool_targets:
                self._execute_tool(self.selected_idx, gx, gy)
                action_taken = True
            elif (gx, gy) in self.valid_targets:
                self._execute_move(self.selected_idx, gx, gy)
                action_taken = True
            else:
                # Try to re-select another unit
                reselected = False
                for idx, u in enumerate(self.units):
                    if not u['locked'] and u['alive'] and u['x'] == gx and u['y'] == gy:
                        self.selected_idx = idx
                        self._update_valid_targets()
                        reselected = True
                        break
                if not reselected:
                    self.selected_idx = None
                    self.valid_targets = set()
                    self.valid_tool_targets = set()

        return action_taken

    # ── Defender click handling ─────────────────────────────────────────────────

    def _handle_defender_click(self, gx: int, gy: int, in_grid: bool) -> bool:
        """Process P2 click. Returns True if action complete (turn should advance)."""
        # Non-grid click = pass
        if not in_grid:
            return True

        if self.selected_guard_idx is not None:
            # Guard is selected — expect move or deselect
            guard = self.guards[self.selected_guard_idx]
            if guard['x'] == gx and guard['y'] == gy:
                # Clicked same guard: deselect (no turn advance)
                self.selected_guard_idx = None
                self.valid_guard_moves = set()
                return False
            elif (gx, gy) in self.valid_guard_moves:
                # Move the guard
                self._execute_guard_move(self.selected_guard_idx, gx, gy)
                return True
            else:
                # Try to select a different guard
                for idx, g in enumerate(self.guards):
                    if g.get('alive', True) and g['x'] == gx and g['y'] == gy:
                        self.selected_guard_idx = idx
                        self.valid_guard_moves = self._guard_valid_moves(idx)
                        return False
                # Clicked elsewhere: deselect
                self.selected_guard_idx = None
                self.valid_guard_moves = set()
                return False
        else:
            # No guard selected — try to select a guard or spawn
            for idx, g in enumerate(self.guards):
                if g.get('alive', True) and g['x'] == gx and g['y'] == gy:
                    self.selected_guard_idx = idx
                    self.valid_guard_moves = self._guard_valid_moves(idx)
                    return False

            # Try to spawn on a valid spawn zone cell
            if self.guard_reserves > 0 and (gx, gy) in self._compute_spawn_zone():
                if not self._guard_at(gx, gy) and not self._occupied_by_unit(gx, gy):
                    self._spawn_guard(gx, gy)
                    return True

            return False

    # ── Attacker action execution ───────────────────────────────────────────────

    def _execute_move(self, idx: int, tx: int, ty: int) -> None:
        unit = self.units[idx]
        guard_at_dest = self._guard_at(tx, ty)
        if guard_at_dest is not None and unit['type'] == 'soldier':
            guard_at_dest['alive'] = False
            unit['frozen'] = 1
        unit['x'] = tx
        unit['y'] = ty

    def _execute_tool(self, idx: int, tx: int, ty: int) -> None:
        unit = self.units[idx]
        if unit['type'] == 'sapper' and unit['bomb_ready']:
            if (tx, ty) in self.breach_walls:
                self.pending_bombs[(tx, ty)] = 1
                unit['bomb_ready'] = False
        elif unit['type'] == 'scout' and unit['grapple_ready']:
            ux, uy = unit['x'], unit['y']
            lx = tx + (tx - ux)
            ly = ty + (ty - uy)
            unit['x'] = lx
            unit['y'] = ly
            unit['grapple_ready'] = False

    # ── Defender action execution ───────────────────────────────────────────────

    def _execute_guard_move(self, idx: int, tx: int, ty: int) -> None:
        """Move guard[idx] to (tx,ty); resolve collisions with attacker units."""
        guard = self.guards[idx]
        guard['x'] = tx
        guard['y'] = ty
        for unit in self.units:
            if unit['locked'] or not unit['alive']:
                continue
            if unit['x'] == tx and unit['y'] == ty:
                if unit['type'] == 'soldier':
                    guard['alive'] = False
                    unit['frozen'] = max(unit.get('frozen', 0), 1)
                else:
                    unit['alive'] = False

    def _spawn_guard(self, sx: int, sy: int) -> None:
        """Place a new guard at (sx,sy), consuming one reserve."""
        self.guards.append({'x': sx, 'y': sy, 'alive': True})
        self.guard_reserves -= 1

    # ── Valid target computation ────────────────────────────────────────────────

    def _guard_valid_moves(self, idx: int) -> set:
        """Return set of cells the selected guard can move to."""
        guard = self.guards[idx]
        gx, gy = guard['x'], guard['y']
        moves = set()
        for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
            nx, ny = gx + dx, gy + dy
            if not (0 <= nx < GW and 0 <= ny < GH):
                continue
            if (nx, ny) in self.walls:
                continue
            if (nx, ny) in self.breach_walls:
                continue
            if (nx, ny) in self.pending_bombs:
                continue
            if (nx, ny) in self.gaps:
                continue
            if self.gate and (nx, ny) == (self.gate['x'], self.gate['y']) and not self._gate_open():
                continue
            # No other guard on destination
            other = False
            for i, g in enumerate(self.guards):
                if i != idx and g.get('alive', True) and g['x'] == nx and g['y'] == ny:
                    other = True
                    break
            if not other:
                moves.add((nx, ny))
        return moves

    def _compute_spawn_zone(self) -> set:
        """Return open cells adjacent to solid tower walls, outside tower interior."""
        adjacent = set()
        for (wx, wy) in self.walls:
            for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
                nx, ny = wx + dx, wy + dy
                if not (0 <= nx < GW and 0 <= ny < GH):
                    continue
                if (nx, ny) in self.walls:
                    continue
                if (nx, ny) in self.breach_walls:
                    continue
                if (nx, ny) in self.pending_bombs:
                    continue
                if (nx, ny) in self.gaps:
                    continue
                if (nx, ny) in TOWER_INTERIOR:
                    continue
                adjacent.add((nx, ny))
        return adjacent

    def _update_valid_targets(self) -> None:
        """Recompute valid move/tool destinations for the selected attacker unit."""
        if self.selected_idx is None:
            self.valid_targets = set()
            self.valid_tool_targets = set()
            return

        unit = self.units[self.selected_idx]
        if not unit['alive'] or unit.get('frozen', 0) > 0:
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

    # ── Turn advance ────────────────────────────────────────────────────────────

    def _advance_turn(self) -> None:
        """World advance after each full round (P1 + P2 both acted)."""
        # Tick pending bombs
        for pos in list(self.pending_bombs.keys()):
            self.pending_bombs[pos] -= 1
        expired = [pos for pos, ticks in self.pending_bombs.items() if ticks <= 0]
        for pos in expired:
            self.breach_walls.discard(pos)
            del self.pending_bombs[pos]

        # Decrement freeze counters
        for unit in self.units:
            if unit.get('frozen', 0) > 0:
                unit['frozen'] -= 1

        # Remove dead guards
        self.guards = [g for g in self.guards if g.get('alive', True)]

        # Increment turn counter
        self.turn += 1

    # ── Win / lose ──────────────────────────────────────────────────────────────

    def _check_win_lose(self, check_turn_limit: bool = True) -> str:
        cx, cy = TOWER_CORE
        for unit in self.units:
            if not unit['locked'] and unit['alive'] and unit['x'] == cx and unit['y'] == cy:
                return 'win'
        alive = [u for u in self.units if not u['locked'] and u['alive']]
        if not alive:
            return 'lose'
        if check_turn_limit and self.turn >= self.turn_limit:
            return 'lose'
        return ''

    # ── Passability helpers ─────────────────────────────────────────────────────

    def _passable_for_unit(self, x: int, y: int, unit: dict) -> bool:
        if x < 0 or x >= GW or y < 0 or y >= GH:
            return False
        if (x, y) in self.walls:
            return False
        if (x, y) in self.breach_walls:
            return False
        if (x, y) in self.pending_bombs:
            return False
        if (x, y) in self.gaps:
            return False
        if self.gate and (x, y) == (self.gate['x'], self.gate['y']):
            return self._gate_open()
        if self._guard_at(x, y) is not None:
            return unit['type'] == 'soldier'
        return True

    def _is_blocked(self, x: int, y: int) -> bool:
        if x < 0 or x >= GW or y < 0 or y >= GH:
            return True
        if (x, y) in self.walls:
            return True
        if (x, y) in self.breach_walls or (x, y) in self.pending_bombs:
            return True
        if (x, y) in self.gaps:
            return True
        if self.gate and (x, y) == (self.gate['x'], self.gate['y']) and not self._gate_open():
            return True
        return False

    def _occupied_by_unit(self, x: int, y: int) -> bool:
        for unit in self.units:
            if not unit['locked'] and unit['alive'] and unit['x'] == x and unit['y'] == y:
                return True
        return False

    def _guard_at(self, x: int, y: int):
        """Return the guard dict at (x,y) or None."""
        for guard in self.guards:
            if guard.get('alive', True) and guard['x'] == x and guard['y'] == y:
                return guard
        return None

    def _gate_open(self) -> bool:
        if self.gate is None:
            return True
        return self.turn % self.gate['period'] == self.gate['open_offset']

    def _all_units_frozen(self) -> bool:
        """Return True if all alive unlocked attacker units are frozen."""
        alive = [u for u in self.units if not u['locked'] and u['alive']]
        return bool(alive) and all(u.get('frozen', 0) > 0 for u in alive)
