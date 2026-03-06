# The Hijacker - A grid puzzle where the player can possess different vehicles
#
# D-pad (1-4) to move, ACTION5 to hijack an adjacent vehicle.
# Person: walks on floor. Tank: walks on floor, breaks cracked walls.
# Boat: moves on water only. Drone: flies over anything (except border walls).
# Reach the gold exit tile to complete each level.

import numpy as np
from arcengine import (
    ARCBaseGame,
    Camera,
    Level,
    RenderableUserDisplay,
)

# --- Colors ---
C_BLACK = 0
C_GREEN = 2
C_GRAY = 3
C_MID = 5
C_PINK = 6
C_ORANGE = 7
C_AZURE = 8
C_BLUE = 9
C_GOLD = 11
C_RED = 12
C_WHITE = 15

# --- Tile types ---
T_FLOOR = 0
T_WALL = 1
T_WATER = 2
T_CRACKED = 3

# --- Vehicle types ---
V_PERSON = 0
V_TANK = 1
V_BOAT = 2
V_DRONE = 3

VEHICLE_COLORS = {V_PERSON: C_PINK, V_TANK: C_RED, V_BOAT: C_GREEN, V_DRONE: C_ORANGE}
TILE_COLORS = {T_FLOOR: C_MID, T_WALL: C_WHITE, T_WATER: C_BLUE, T_CRACKED: C_GRAY}

CELL = 4


# =============================================================================
# Barrier helpers
# =============================================================================

def _hbar(y, x_start, x_end, tile_type, gate_x=None, gate_type=None):
    """Horizontal barrier from x_start to x_end at row y.
    gate_x gets gate_type instead of tile_type."""
    tiles = {}
    for x in range(x_start, x_end + 1):
        if x == gate_x and gate_type is not None:
            tiles[(x, y)] = gate_type
        else:
            tiles[(x, y)] = tile_type
    return tiles


def _vbar(x, y_start, y_end, tile_type, gate_y=None, gate_type=None):
    """Vertical barrier from y_start to y_end at column x.
    gate_y gets gate_type instead of tile_type."""
    tiles = {}
    for y in range(y_start, y_end + 1):
        if y == gate_y and gate_type is not None:
            tiles[(x, y)] = gate_type
        else:
            tiles[(x, y)] = tile_type
    return tiles


# =============================================================================
# Level definitions
# =============================================================================

LEVELS = [
    # L1: "First Ride" (7x7) - Intro to tank
    {
        "name": "First Ride",
        "grid_w": 7, "grid_h": 7,
        "tiles": {(4, 3): T_CRACKED},
        "player": (1, 3),
        "player_type": V_PERSON,
        "vehicles": [(3, 3, V_TANK)],
        "exit": (5, 3),
    },

    # L2: "Water Crossing" (7x7) - Intro to boat
    {
        "name": "Water Crossing",
        "grid_w": 7, "grid_h": 7,
        "tiles": dict(_hbar(3, 1, 5, T_WATER)),
        "player": (3, 1),
        "player_type": V_PERSON,
        "vehicles": [(2, 3, V_BOAT), (2, 4, V_PERSON)],
        "exit": (5, 4),
    },

    # L3: "Over the Wall" (8x8) - Intro to drone
    {
        "name": "Over the Wall",
        "grid_w": 8, "grid_h": 8,
        "tiles": dict(_hbar(3, 1, 6, T_WALL)),
        "player": (2, 2),
        "player_type": V_PERSON,
        "vehicles": [(4, 2, V_DRONE)],
        "exit": (6, 5),
    },

    # L4: "Tank and Boat" (8x8) - Tank + Boat combo
    {
        "name": "Tank and Boat",
        "grid_w": 8, "grid_h": 8,
        "tiles": {
            **_hbar(3, 1, 6, T_WALL, gate_x=2, gate_type=T_CRACKED),
            **_hbar(4, 1, 6, T_WATER),
        },
        "player": (1, 1),
        "player_type": V_PERSON,
        "vehicles": [(3, 2, V_TANK), (2, 4, V_BOAT), (2, 5, V_PERSON)],
        "exit": (6, 5),
    },

    # L5: "Tank Relay" (9x9) - Two cracked wall columns
    {
        "name": "Tank Relay",
        "grid_w": 9, "grid_h": 9,
        "tiles": {
            **_vbar(4, 1, 7, T_WALL, gate_y=3, gate_type=T_CRACKED),
            **_vbar(6, 1, 7, T_WALL, gate_y=1, gate_type=T_CRACKED),
        },
        "player": (1, 1),
        "player_type": V_PERSON,
        "vehicles": [(3, 3, V_TANK)],
        "exit": (7, 1),
    },

    # L6: "Island Hop" (9x9) - Double boat crossing
    {
        "name": "Island Hop",
        "grid_w": 9, "grid_h": 9,
        "tiles": {
            **_hbar(2, 1, 7, T_WALL, gate_x=4, gate_type=T_FLOOR),
            **_hbar(3, 1, 7, T_WATER),
            **_hbar(4, 1, 7, T_WALL, gate_x=4, gate_type=T_FLOOR),
            **_hbar(5, 1, 7, T_WATER),
            **_hbar(6, 1, 7, T_WALL, gate_x=4, gate_type=T_FLOOR),
        },
        "player": (4, 1),
        "player_type": V_PERSON,
        "vehicles": [
            (4, 3, V_BOAT),
            (4, 4, V_PERSON),
            (4, 5, V_BOAT),
            (4, 6, V_PERSON),
        ],
        "exit": (7, 7),
    },

    # L7: "Triple Threat" (10x10) - All 3 vehicle types
    {
        "name": "Triple Threat",
        "grid_w": 10, "grid_h": 10,
        "tiles": {
            **_hbar(2, 1, 8, T_WALL, gate_x=3, gate_type=T_CRACKED),
            **_hbar(4, 1, 8, T_WATER),
            **_hbar(6, 1, 8, T_WALL),
        },
        "player": (1, 1),
        "player_type": V_PERSON,
        "vehicles": [
            (2, 1, V_TANK),
            (3, 4, V_BOAT),
            (3, 5, V_PERSON),
            (5, 5, V_DRONE),
        ],
        "exit": (8, 8),
    },

    # L8: "Maze Runner" (10x10) - Tank + Boat + Drone maze
    {
        "name": "Maze Runner",
        "grid_w": 10, "grid_h": 10,
        "tiles": {
            **_hbar(3, 1, 8, T_WALL, gate_x=4, gate_type=T_CRACKED),
            **_hbar(5, 1, 8, T_WATER),
            **_hbar(7, 1, 8, T_WALL),
        },
        "player": (1, 1),
        "player_type": V_PERSON,
        "vehicles": [
            (2, 2, V_TANK),
            (3, 5, V_BOAT),
            (3, 6, V_PERSON),
            (5, 6, V_DRONE),
        ],
        "exit": (8, 8),
    },

    # L9: "Vehicle Chain" (10x10) - All vehicles, mirrored start
    {
        "name": "Vehicle Chain",
        "grid_w": 10, "grid_h": 10,
        "tiles": {
            **_hbar(2, 1, 8, T_WALL, gate_x=6, gate_type=T_CRACKED),
            **_hbar(4, 1, 8, T_WATER),
            **_hbar(6, 1, 8, T_WALL),
        },
        "player": (8, 1),
        "player_type": V_PERSON,
        "vehicles": [
            (8, 2, V_TANK),
            (5, 4, V_BOAT),
            (5, 5, V_PERSON),
            (7, 5, V_DRONE),
        ],
        "exit": (8, 8),
    },

    # L10: "Grand Heist" (12x10) - All mechanics, larger grid
    {
        "name": "Grand Heist",
        "grid_w": 12, "grid_h": 10,
        "tiles": {
            **_hbar(2, 1, 10, T_WALL, gate_x=3, gate_type=T_CRACKED),
            **_hbar(4, 1, 10, T_WATER),
            **_hbar(6, 1, 10, T_WALL),
        },
        "player": (1, 1),
        "player_type": V_PERSON,
        "vehicles": [
            (3, 1, V_TANK),
            (5, 4, V_BOAT),
            (5, 5, V_PERSON),
            (7, 5, V_DRONE),
        ],
        "exit": (10, 7),
    },
]


# =============================================================================
# Display
# =============================================================================

class Hj01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        # Draw tiles
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.border_walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    t = g.tiles.get((gx, gy), T_FLOOR)
                    frame[py:py + CELL, px:px + CELL] = TILE_COLORS.get(t, C_MID)

        # Draw exit
        ex, ey = g.exit_pos
        px, py = ox + ex * CELL, oy + ey * CELL
        frame[py:py + CELL, px:px + CELL] = C_GOLD

        # Draw parked vehicles
        for vx, vy, vt in g.parked:
            px, py = ox + vx * CELL, oy + vy * CELL
            frame[py:py + CELL, px:px + CELL] = VEHICLE_COLORS[vt]

        # Draw player (current vehicle)
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        return frame


# =============================================================================
# Game
# =============================================================================

class Hj01(ARCBaseGame):
    def __init__(self):
        self.display = Hj01Display(self)
        levels = []
        for d in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=d,
                name=d["name"],
            ))
        super().__init__(
            "hj01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4, 5],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.tiles = dict(d.get("tiles", {}))
        self.border_walls = set()
        for x in range(self.grid_w):
            self.border_walls.add((x, 0))
            self.border_walls.add((x, self.grid_h - 1))
        for y in range(self.grid_h):
            self.border_walls.add((0, y))
            self.border_walls.add((self.grid_w - 1, y))
        self.px, self.py = d["player"]
        self.player_type = d["player_type"]
        self.parked = [list(v) for v in d["vehicles"]]
        self.exit_pos = tuple(d["exit"])

    def _can_move(self, x, y, vtype):
        """Check if vehicle type can move to (x,y). May modify tiles (tank breaks cracked)."""
        if x < 0 or y < 0 or x >= self.grid_w or y >= self.grid_h:
            return False
        if (x, y) in self.border_walls:
            return False
        t = self.tiles.get((x, y), T_FLOOR)
        if vtype == V_PERSON:
            return t == T_FLOOR
        if vtype == V_TANK:
            if t == T_CRACKED:
                self.tiles[(x, y)] = T_FLOOR
                return True
            return t == T_FLOOR
        if vtype == V_BOAT:
            return t == T_WATER
        if vtype == V_DRONE:
            return t in (T_FLOOR, T_WALL, T_CRACKED, T_WATER)
        return False

    def _vehicle_at(self, x, y):
        """Return index of parked vehicle at (x,y), or -1."""
        for i, (vx, vy, vt) in enumerate(self.parked):
            if vx == x and vy == y:
                return i
        return -1

    def step(self):
        aid = self.action.id.value

        if aid == 5:
            # Hijack: swap with first adjacent parked vehicle
            for ddx, ddy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                vi = self._vehicle_at(self.px + ddx, self.py + ddy)
                if vi >= 0:
                    vx, vy, vt = self.parked[vi]
                    self.parked[vi] = [self.px, self.py, self.player_type]
                    self.px, self.py = vx, vy
                    self.player_type = vt
                    break
            self.complete_action()
            return

        dx, dy = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}.get(aid, (0, 0))
        if dx == 0 and dy == 0:
            self.complete_action()
            return

        nx, ny = self.px + dx, self.py + dy

        # Can't move into a parked vehicle
        if self._vehicle_at(nx, ny) >= 0:
            self.complete_action()
            return

        # Check movement rules for current vehicle type
        if not self._can_move(nx, ny, self.player_type):
            self.complete_action()
            return

        self.px, self.py = nx, ny

        # Check if reached exit
        if (self.px, self.py) == self.exit_pos:
            self.next_level()

        self.complete_action()
