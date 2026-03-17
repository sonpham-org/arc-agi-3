# Author: Claude Sonnet 4.6
# Date: 2026-03-17 12:00
# PURPOSE: Tower Siege (ts01) — 5-level click-based siege puzzle. Player controls
#          3 unit types (Sapper/bomb, Scout/grapple, Soldier/contact-kill) that
#          unlock progressively (Sapper L1+, Scout L2+, Soldier L3+). Each turn the
#          player selects one unit and performs one action (move or use tool); then
#          the world advances (bomb ticks, guards move, collisions resolve). Win by
#          landing any unit on the tower core cell within the turn limit.
#          Integrates with arcengine via ARCBaseGame; click-only (ACTION6).
# SRP/DRY check: Pass — no existing utility covers multi-unit click-puzzle pattern.
"""
ts01 – Tower Siege  (ARC-AGI-3 game)

Controls
--------
ACTION6 (click): Select a unit, then click to move or use tool.

Units (unlock progressively)
-----------------------------
Sapper  (Orange) L1+ : click adjacent breachable wall → bomb it (wall gone next turn)
Scout   (Blue)   L2+ : moves 1–2 cells in a straight line; click adjacent gap → grapple over
Soldier (Green)  L3+ : moving onto a guard cell removes the guard (Soldier frozen 1 turn)

Goal: Land any unit on the tower core (Yellow cell) before the turn limit expires.

One action per turn. After each action: bomb timers tick, guards move, collisions resolve.

L1 The Breach       – Sapper only; one breachable south wall; learn bomb delay
L2 Timed Gate       – +Scout; south gate timing + west breach; two-unit flexibility
L3 The Guard        – +Soldier; guard patrols south approach; contact-kill required
L4 Full Assault     – all three; two guards + gate + gap; multi-unit coordination
L5 The Gauntlet     – same layout as L4, half the turn budget

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
# Tower outer wall: cols 8-12, rows 3-7 on the 20×20 grid.
# Interior (floor): rows 4-6, cols 9-11. Core target: (10, 5).
TOWER_CORE = (10, 5)

# Solid (indestructible) tower wall cells — bottom row excluded so levels can
# place breach wall / gate / solid cell at (10,7) individually.
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
# Each dict describes one level. Keys:
#   walls          : frozenset of (col,row) impassable solid cells
#   breach_walls   : frozenset of (col,row) bombable (Sapper) cells
#   gate           : None | {'x','y','period','open_offset'}
#                    gate cell open when self.turn % period == open_offset
#   gaps           : frozenset of (col,row) gap cells (LightBlue, impassable
#                    except via Scout grapple)
#   guards         : list of guard dicts {'path':[(x,y)…], 'pi':int}
#                    guard cycles through path positions with pi = (pi+1) % len(path)
#   unit_starts    : [(x,y), (x,y), (x,y)]  for sapper, scout, soldier
#   active_units   : list of type strings that are unlocked this level
#   turn_limit     : int

_LEVELS = [
    # ── L1: The Breach ─────────────────────────────────────────────────────────
    # Sapper only. One breachable south-centre wall. Straight approach column 10.
    # Min solution: 7 moves north + 1 bomb + 3 moves = 11 turns.
    {
        'name': 'The Breach',
        'walls': _TOWER_SOLID,
        'breach_walls': frozenset([(10, 7)]),
        'gate': None,
        'gaps': frozenset(),
        'guards': [],
        'unit_starts': [(10, 16), (10, 16), (10, 16)],
        'active_units': ['sapper'],
        'turn_limit': 16,
    },

    # ── L2: Timed Gate ─────────────────────────────────────────────────────────
    # Sapper + Scout. Two independent approach paths:
    #   South gate (Scout): gate at (10,7) period=3, open at turns 0,3,6,9.
    #     Scout (10,10)→(10,9)[t1]→(10,8)[t2]→(10,7)[t3,gate open]→(10,6)[t4]→(10,5) WIN.
    #   West breach (Sapper): breach wall (8,5); Sapper (4,5)→…→(7,5)[t3], bomb[t4],
    #     wall gone[t5], (8,5)[t5]→(9,5)[t6]→(10,5) WIN at t7.
    # Note: (8,5) must NOT be in walls (it's a breach wall, not solid). Remove from
    # _TOWER_SOLID so breach_walls is the sole authority on passability.
    {
        'name': 'Timed Gate',
        'walls': _TOWER_SOLID - frozenset([(8, 5)]),    # (8,5) is breach, not solid
        'breach_walls': frozenset([(8, 5)]),
        'gate': {'x': 10, 'y': 7, 'period': 3, 'open_offset': 0},
        'gaps': frozenset(),
        'guards': [],
        'unit_starts': [(4, 5), (10, 10), (10, 16)],   # sapper west, scout south
        'active_units': ['sapper', 'scout'],
        'turn_limit': 18,
    },

    # ── L3: The Guard ──────────────────────────────────────────────────────────
    # All three units. Guard cycles (8,8)→…→(12,8)→…→(8,8) blocking south row.
    # Soldier must contact-kill guard (walks onto guard's cell). Sapper then bombs
    # (10,7) from (10,8). Scout uses east gate (12,5) via gap grapple at (15,9).
    # Gate (12,5) removed from walls so gate logic controls it.
    {
        'name': 'The Guard',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 4, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),   # Scout grapples (15,10)→(15,8)
        'guards': [
            {
                'path': [(8,8),(9,8),(10,8),(11,8),(12,8),
                         (11,8),(10,8),(9,8)],
                'pi': 0,
            },
        ],
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 28,
    },

    # ── L4: Full Assault ───────────────────────────────────────────────────────
    # All three units, two guards, gate + gap + breach wall.
    # Guard A cycles (8,8)↔(10,8): blocks south centre.
    # Guard B cycles (13,5)↔(13,8): blocks east corridor to gate (12,5).
    # Soldier clears Guard A; Sapper bombs (10,7); Scout grapples gap and times
    # guard B to enter gate (12,5).
    {
        'name': 'Full Assault',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 4, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),
        'guards': [
            {
                'path': [(8,8),(9,8),(10,8),(9,8)],
                'pi': 0,
            },
            {
                'path': [(13,5),(13,6),(13,7),(13,8),(13,7),(13,6)],
                'pi': 3,    # starts at (13,8)
            },
        ],
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 32,
    },

    # ── L5: The Gauntlet ───────────────────────────────────────────────────────
    # Same layout as L4, turn limit cut to 20 — forces efficient ordering.
    {
        'name': 'The Gauntlet',
        'walls': _TOWER_SOLID - frozenset([(12, 5)]),
        'breach_walls': frozenset([(10, 7)]),
        'gate': {'x': 12, 'y': 5, 'period': 4, 'open_offset': 0},
        'gaps': frozenset([(15, 9)]),
        'guards': [
            {
                'path': [(8,8),(9,8),(10,8),(9,8)],
                'pi': 0,
            },
            {
                'path': [(13,5),(13,6),(13,7),(13,8),(13,7),(13,6)],
                'pi': 3,
            },
        ],
        'unit_starts': [(4, 16), (16, 16), (10, 17)],
        'active_units': ['sapper', 'scout', 'soldier'],
        'turn_limit': 20,
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


# ── Renderer ───────────────────────────────────────────────────────────────────

class Ts01Display(RenderableUserDisplay):
    def __init__(self, game: "Ts01"):
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        frame[:] = VDGRAY   # dark background

        # ── HUD bar (top 9 rows) ────────────────────────────────────────────
        _fill(frame, 0, 0, CW, 9, BLACK)

        # Level dots (5 dots, top-left corner)
        for i in range(5):
            c = YEL if i <= g.level_index else DGRAY
            _dot(frame, 2 + i * 4, 4, c)

        # Turn counter (right side of HUD)
        turn_text_x = 30
        _draw_label(frame, turn_text_x, 2, f'T:{g.turn:02d}/{g.turn_limit:02d}', WHITE)

        # ── Floor (open grid area) ──────────────────────────────────────────
        for gy in range(GH):
            for gx in range(GW):
                _cell(frame, gx, gy, DGRAY)

        # ── Gaps ────────────────────────────────────────────────────────────
        for (gx, gy) in g.gaps:
            _cell(frame, gx, gy, LBLUE)

        # ── Solid tower walls ────────────────────────────────────────────────
        for (gx, gy) in g.walls:
            _cell(frame, gx, gy, GRAY)

        # ── Breachable walls (slightly lighter than solid) ───────────────────
        for (gx, gy) in g.breach_walls:
            _cell(frame, gx, gy, LGRAY)

        # ── Pending bomb markers (Magenta on breachable cell) ────────────────
        for (gx, gy) in g.pending_bombs:
            _cell(frame, gx, gy, MAG)

        # ── Gate ─────────────────────────────────────────────────────────────
        if g.gate is not None:
            gx, gy = g.gate['x'], g.gate['y']
            color = GRN if g._gate_open() else MAR
            _cell(frame, gx, gy, color)

        # ── Tower core (target) ───────────────────────────────────────────────
        cx, cy = TOWER_CORE
        _cell(frame, cx, cy, YEL)

        # ── Guards ────────────────────────────────────────────────────────────
        for guard in g.guards:
            gx, gy = guard['path'][guard['pi']]
            _cell(frame, gx, gy, RED)

        # ── Units ─────────────────────────────────────────────────────────────
        for idx, unit in enumerate(g.units):
            if unit['locked'] or not unit['alive']:
                continue
            color = UNIT_COLOR[unit['type']]
            gx, gy = unit['x'], unit['y']

            # Selected highlight: draw a 1-px LightMagenta border
            if g.selected_idx == idx:
                px, py = _px(gx, gy)
                _fill(frame, px - 1, py - 1, CELL + 2, CELL + 2, LMAG)

            # Frozen tint: draw lighter centre dot
            if unit.get('frozen', 0) > 0:
                _cell(frame, gx, gy, LGRAY)
                # small color dot inside
                px, py = _px(gx, gy)
                _dot(frame, px, py, color)
            else:
                _cell(frame, gx, gy, color)

        # ── Valid move highlights (when unit selected) ─────────────────────────
        if g.selected_idx is not None:
            for (mx, my) in g.valid_targets:
                if (mx, my) in g.valid_tool_targets:
                    # Tool target: draw bright White highlight
                    px, py = _px(mx, my)
                    _dot(frame, px, py, WHITE)
                    _dot(frame, px+1, py, WHITE)
                    _dot(frame, px, py+1, WHITE)
                    _dot(frame, px+1, py+1, WHITE)
                else:
                    # Move target: small white dot at centre
                    px, py = _px(mx, my)
                    _dot(frame, px, py, WHITE)

        # ── Right panel: unit status ──────────────────────────────────────────
        panel_x = 44
        _fill(frame, panel_x, 0, CW - panel_x, CH, BLACK)
        row_y = 10
        for unit in g.units:
            if unit['locked']:
                # Show locked unit as dim dot + label
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
                # Tool ready indicator
                if unit['type'] == 'sapper' and unit.get('bomb_ready', False):
                    _dot(frame, panel_x + 1, row_y + 3, MAG)
                if unit['type'] == 'scout' and unit.get('grapple_ready', False):
                    _dot(frame, panel_x + 1, row_y + 3, LBLUE)
            row_y += 8

        return frame


# ── Tiny bitmap font (3×5) for HUD labels ─────────────────────────────────────
# Each char: list of (dx,dy) lit pixels within a 3-wide × 5-tall box.
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
    'T': [(0,0),(1,0),(2,0),(1,1),(1,2),(1,3),(1,4)],
    ':': [(1,1),(1,3)],
    '/': [(2,0),(1,1),(1,2),(0,3),(0,4)],
    'S': [(0,0),(1,0),(2,0),(0,1),(0,2),(1,2),(2,2),(2,3),(0,4),(1,4),(2,4)],
    'A': [(1,0),(0,1),(2,1),(0,2),(1,2),(2,2),(0,3),(2,3),(0,4),(2,4)],
    'P': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(1,2),(2,2),(0,3),(0,4)],
    'C': [(0,0),(1,0),(2,0),(0,1),(0,2),(0,3),(0,4),(1,4),(2,4)],
    'O': [(0,0),(1,0),(2,0),(0,1),(2,1),(0,2),(2,2),(0,3),(2,3),(0,4),(1,4),(2,4)],
    'L': [(0,0),(0,1),(0,2),(0,3),(0,4),(1,4),(2,4)],
    'X': [(0,0),(2,0),(1,2),(0,4),(2,4),(0,1),(2,1),(0,3),(2,3)],
}

def _draw_label(frame, px, py, text, color):
    """Draw up to 5-char text at pixel (px,py) using 3×5 bitmap font, 1px gap."""
    cx = px
    for ch in text:
        pixels = _FONT.get(ch, [])
        for dx, dy in pixels:
            fx, fy = cx + dx, py + dy
            if 0 <= fx < CW and 0 <= fy < CH:
                frame[fy, fx] = color
        cx += 4   # 3 wide + 1 gap


# ── Game class ─────────────────────────────────────────────────────────────────

class Ts01(ARCBaseGame):
    def __init__(self):
        self.display = Ts01Display(self)

        # Game state (populated in on_set_level)
        self.units = []
        self.selected_idx = None
        self.walls = set()
        self.breach_walls = set()
        self.pending_bombs = {}   # (x,y) → turns until removal
        self.gate = None
        self.gaps = set()
        self.guards = []
        self.turn = 0
        self.turn_limit = 16
        self.valid_targets = set()        # move destinations for selected unit
        self.valid_tool_targets = set()   # subset that are tool-use targets

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

        # Deep-copy guard state (cyclic path follower, no dir needed)
        self.guards = [
            {'path': list(g['path']), 'pi': g['pi'], 'alive': True}
            for g in d['guards']
        ]

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

        # Check if click is inside the grid
        in_grid = 0 <= gx < GW and 0 <= gy < GH

        if not in_grid:
            self.complete_action()
            return

        action_taken = False

        if self.selected_idx is None:
            # Try to select a unit at (gx, gy)
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
                # Execute tool action
                self._execute_tool(self.selected_idx, gx, gy)
                action_taken = True
            elif (gx, gy) in self.valid_targets:
                # Execute move (check if moving onto a guard = contact-kill)
                self._execute_move(self.selected_idx, gx, gy)
                action_taken = True
            else:
                # Try to select a different unit at click position
                reselected = False
                for idx, u in enumerate(self.units):
                    if not u['locked'] and u['alive'] and u['x'] == gx and u['y'] == gy:
                        self.selected_idx = idx
                        self._update_valid_targets()
                        reselected = True
                        break
                if not reselected:
                    # Clicked empty/invalid cell — deselect
                    self.selected_idx = None
                    self.valid_targets = set()
                    self.valid_tool_targets = set()

        if action_taken:
            self.selected_idx = None
            self.valid_targets = set()
            self.valid_tool_targets = set()
            self._advance_turn()
            result = self._check_win_lose()
            if result == 'win':
                if not self.is_last_level():
                    self.next_level()
                else:
                    self.win()
            elif result == 'lose':
                self.lose()

        self.complete_action()

    # ── Action execution ────────────────────────────────────────────────────────

    def _execute_move(self, idx: int, tx: int, ty: int) -> None:
        unit = self.units[idx]
        # Check if destination has a guard (contact-kill for Soldier)
        guard_at_dest = self._guard_at(tx, ty)
        if guard_at_dest is not None:
            if unit['type'] == 'soldier':
                guard_at_dest['alive'] = False
                unit['frozen'] = 1
            # Non-soldier moving into guard: unit eliminated (shouldn't happen — guard cells excluded from valid moves for non-soldiers)
        unit['x'] = tx
        unit['y'] = ty

    def _execute_tool(self, idx: int, tx: int, ty: int) -> None:
        unit = self.units[idx]
        if unit['type'] == 'sapper' and unit['bomb_ready']:
            # Plant bomb on breachable wall at (tx,ty)
            if (tx, ty) in self.breach_walls:
                self.pending_bombs[(tx, ty)] = 1
                unit['bomb_ready'] = False
        elif unit['type'] == 'scout' and unit['grapple_ready']:
            # Grapple: Scout jumps OVER gap at (tx,ty) to the far side
            ux, uy = unit['x'], unit['y']
            # Landing cell is mirrored through the gap cell
            lx = tx + (tx - ux)
            ly = ty + (ty - uy)
            unit['x'] = lx
            unit['y'] = ly
            unit['grapple_ready'] = False

    # ── Turn advance ────────────────────────────────────────────────────────────

    def _advance_turn(self) -> None:
        # 1. Tick pending bombs: decrement first, then remove walls that reach 0.
        # Initial ticks=1 → wall gone after exactly 1 turn (1 advance call).
        for pos in list(self.pending_bombs.keys()):
            self.pending_bombs[pos] -= 1
        expired = [pos for pos, ticks in self.pending_bombs.items() if ticks <= 0]
        for pos in expired:
            self.breach_walls.discard(pos)
            del self.pending_bombs[pos]

        # 2. Move guards one step along their cyclic patrol path
        for guard in self.guards:
            if not guard.get('alive', True):
                continue
            guard['pi'] = (guard['pi'] + 1) % len(guard['path'])
            gx, gy = guard['path'][guard['pi']]

            # Collision with units after guard moves
            for unit in self.units:
                if unit['locked'] or not unit['alive']:
                    continue
                if unit['x'] == gx and unit['y'] == gy:
                    if unit['type'] == 'soldier':
                        guard['alive'] = False
                        unit['frozen'] = max(unit.get('frozen', 0), 1)
                    else:
                        unit['alive'] = False

        # 3. Remove dead guards
        self.guards = [g for g in self.guards if g.get('alive', True)]

        # 4. Decrement freeze counters
        for unit in self.units:
            if unit.get('frozen', 0) > 0:
                unit['frozen'] -= 1

        # 5. Advance turn counter
        self.turn += 1

    # ── Win / lose ──────────────────────────────────────────────────────────────

    def _check_win_lose(self) -> str:
        cx, cy = TOWER_CORE
        for unit in self.units:
            if not unit['locked'] and unit['alive'] and unit['x'] == cx and unit['y'] == cy:
                return 'win'
        alive = [u for u in self.units if not u['locked'] and u['alive']]
        if not alive:
            return 'lose'
        if self.turn >= self.turn_limit:
            return 'lose'
        return ''

    # ── Valid target computation ────────────────────────────────────────────────

    def _update_valid_targets(self) -> None:
        """Recompute valid move and tool destinations for the selected unit."""
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
            # Scout: 2-cell move (intermediate must also be passable and clear of units)
            if unit['type'] == 'scout':
                if self._passable_for_unit(nx, ny, unit) and not self._occupied_by_unit(nx, ny):
                    nx2, ny2 = ux + 2*dx, uy + 2*dy
                    if self._passable_for_unit(nx2, ny2, unit):
                        moves.add((nx2, ny2))

        # Tool targets
        if unit['type'] == 'sapper' and unit.get('bomb_ready', False):
            for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
                nx, ny = ux + dx, uy + dy
                if (nx, ny) in self.breach_walls and (nx, ny) not in self.pending_bombs:
                    tools.add((nx, ny))

        if unit['type'] == 'scout' and unit.get('grapple_ready', False):
            for dx, dy in [(0,-1),(0,1),(-1,0),(1,0)]:
                nx, ny = ux + dx, uy + dy
                if (nx, ny) in self.gaps:
                    # Landing cell must be in bounds and passable
                    lx, ly = nx + dx, ny + dy
                    if 0 <= lx < GW and 0 <= ly < GH:
                        if not self._is_blocked(lx, ly):
                            tools.add((nx, ny))

        self.valid_targets = moves | tools
        self.valid_tool_targets = tools

    def _passable_for_unit(self, x: int, y: int, unit: dict) -> bool:
        """Return True if the given cell is reachable by this unit type."""
        if x < 0 or x >= GW or y < 0 or y >= GH:
            return False
        if (x, y) in self.walls:
            return False
        if (x, y) in self.breach_walls:
            return False
        if (x, y) in self.pending_bombs:
            return False
        if (x, y) in self.gaps:
            return False   # gaps are not walkable (only grappable)
        if self.gate and (x, y) == (self.gate['x'], self.gate['y']):
            return self._gate_open()
        # Guard cells: only Soldier can walk into them (contact-kill)
        if self._guard_at(x, y) is not None:
            return unit['type'] == 'soldier'
        return True

    def _is_blocked(self, x: int, y: int) -> bool:
        """Return True if the cell is impassable (walls, gaps, other units)."""
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
        """Return True if any alive, non-locked unit occupies (x,y)."""
        for unit in self.units:
            if not unit['locked'] and unit['alive'] and unit['x'] == x and unit['y'] == y:
                return True
        return False

    def _gate_open(self) -> bool:
        if self.gate is None:
            return True
        return self.turn % self.gate['period'] == self.gate['open_offset']

    def _guard_at(self, x: int, y: int):
        """Return the guard dict at (x,y) or None."""
        for guard in self.guards:
            if guard['alive']:
                gx, gy = guard['path'][guard['pi']]
                if gx == x and gy == y:
                    return guard
        return None
