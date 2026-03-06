# Relic Runner - A grid-based key-and-door collection puzzle
#
# D-pad to move (actions 1-4: up/down/left/right).
# Collect colored keys to open matching colored doors.
# Reach the gold exit to complete each level.
#
# Fully deterministic - no random elements.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# --- Cell size ---
CELL = 4  # 4x4 pixels per grid cell

# --- Colors (ARC palette indices) ---
C_BLACK  = 0   # background / void
C_GREEN  = 2   # green key/door
C_GRAY   = 3   # opened door (becomes floor)
C_MID    = 5   # floor
C_ORANGE = 7   # key marker (dot inside key tile)
C_AZURE  = 8   # player
C_BLUE   = 9   # blue key/door
C_GOLD   = 11  # exit
C_RED    = 12  # red key/door
C_WHITE  = 15  # walls

# Color indices for keys/doors: 0=red, 1=blue, 2=green
KEY_COLORS = [C_RED, C_BLUE, C_GREEN]

# Direction map: action_id -> (dx, dy)
_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}


# ============================================================================
# Border helper
# ============================================================================

def _border(w, h):
    """Return a set of all border cells for a w x h grid."""
    s = set()
    for x in range(w):
        s.add((x, 0))
        s.add((x, h - 1))
    for y in range(h):
        s.add((0, y))
        s.add((w - 1, y))
    return s


# ============================================================================
# Level definitions
# ============================================================================
# Each level:
#   name: display name
#   grid_w, grid_h: dimensions (border cells are auto-walls)
#   walls: set of (x,y) interior wall positions (borders added automatically)
#   player: (x, y) start position
#   exit: (x, y) exit position
#   keys: list of (x, y, color_index)  -- 0=red, 1=blue, 2=green
#   doors: list of (x, y, color_index)

LEVELS = [
    # L1: 7x7, 1 red key, 1 red door
    # Simple intro: pick up red key, walk through red door to exit
    #
    #  W W W W W W W
    #  W P . . . . W
    #  W . . . . . W
    #  W . . W W D W
    #  W . K . . . W
    #  W . . . . E W
    #  W W W W W W W
    {
        "name": "One Key",
        "grid_w": 7, "grid_h": 7,
        "walls": _border(7, 7) | {(3, 3), (4, 3)},
        "player": (1, 1),
        "exit": (5, 5),
        "keys": [(2, 4, 0)],       # red key at (2,4)
        "doors": [(5, 3, 0)],      # red door at (5,3)
    },

    # L2: 7x7, 1 red + 1 blue key, 2 doors
    # Red key opens path to blue key, blue key opens path to exit
    #
    #  W W W W W W W
    #  W P . . . . W
    #  W . W Rd. . W
    #  W . W . Bk. W
    #  W Rk W Bd. . W
    #  W . . . . E W
    #  W W W W W W W
    {
        "name": "Two Keys",
        "grid_w": 7, "grid_h": 7,
        "walls": _border(7, 7) | {(2, 2), (2, 3), (2, 4)},
        "player": (1, 1),
        "exit": (5, 5),
        "keys": [(1, 4, 0), (4, 3, 1)],     # red key at (1,4), blue key at (4,3)
        "doors": [(3, 2, 0), (3, 4, 1)],    # red door at (3,2), blue door at (3,4)
    },

    # L3: 8x8, 2 keys, must collect in order (red key behind blue-free path,
    # blue key accessible, but blue door blocks exit path)
    #
    #  W W W W W W W W
    #  W P . . . . . W
    #  W . W W Rd W . W
    #  W . W . . W . W
    #  W . . . Rk W . W
    #  W . W W W W . W
    #  W . . Bd . . E W
    #  W W W W W W W W
    {
        "name": "Key Chain",
        "grid_w": 8, "grid_h": 8,
        "walls": _border(8, 8) | {(2, 2), (3, 2), (5, 2), (2, 3), (5, 3),
                                   (5, 4), (2, 5), (3, 5), (4, 5), (5, 5)},
        "player": (1, 1),
        "exit": (6, 6),
        "keys": [(4, 4, 0), (1, 6, 1)],     # red key at (4,4), blue key at (1,6)
        "doors": [(4, 2, 0), (3, 6, 1)],    # red door at (4,2), blue door at (3,6)
    },

    # L4: 8x8, 3 keys (R,B,G), 3 doors, one key behind a door
    # Red key free, opens red door revealing blue key,
    # blue key opens blue door revealing green key,
    # green key opens green door to exit
    #
    #  W W W W W W W W
    #  W P . Rd. . . W
    #  W . . W Bk . . W
    #  W Rk . W Bd . . W
    #  W . . W . Gk . W
    #  W . . W Gd . . W
    #  W . . . . . E W
    #  W W W W W W W W
    {
        "name": "Door Chain",
        "grid_w": 8, "grid_h": 8,
        "walls": _border(8, 8) | {(3, 2), (3, 3), (3, 4), (3, 5)},
        "player": (1, 1),
        "exit": (6, 6),
        "keys": [(1, 3, 0), (4, 2, 1), (5, 4, 2)],    # R at (1,3), B at (4,2), G at (5,4)
        "doors": [(3, 1, 0), (4, 3, 1), (4, 5, 2)],   # R door at (3,1), B door at (4,3), G door at (4,5)
    },

    # L5: 9x9, 3 keys, complex door chain with walls creating maze corridors
    #
    #  W W W W W W W W W
    #  W P . . W . . . W
    #  W . W . W . W . W
    #  W . W Rk W Rd W . W
    #  W . . . Bd . . . W
    #  W . W . W . W . W
    #  W . W Bk W Gd W . W
    #  W . . . . . . E W
    #  W W W W W W W W W
    {
        "name": "Maze Keys",
        "grid_w": 9, "grid_h": 9,
        "walls": _border(9, 9) | {(4, 1), (2, 2), (4, 2), (6, 2),
                                   (2, 3), (4, 3), (6, 3),
                                   (4, 5), (2, 5), (6, 5),
                                   (2, 6), (4, 6)},
        "player": (1, 1),
        "exit": (7, 7),
        "keys": [(3, 3, 0), (3, 6, 1), (1, 7, 2)],      # R at (3,3), B at (3,6), G at (1,7)
        "doors": [(5, 3, 0), (4, 4, 1), (6, 6, 2)],     # R door at (5,3), B door at (4,4), G door opens bottom-right
    },

    # L6: 9x9, 3 keys, walls + doors creating winding path
    #
    #  W W W W W W W W W
    #  W P . . . . . . W
    #  W W W W W Rd W . W
    #  W . . . . . W . W
    #  W . W W W W W . W
    #  W . . . Bk . . . W
    #  W . W Bd W W W W W
    #  W Rk . . . Gk Gd E W
    #  W W W W W W W W W
    {
        "name": "Winding Doors",
        "grid_w": 9, "grid_h": 9,
        "walls": _border(9, 9) | {(1, 2), (2, 2), (3, 2), (4, 2), (6, 2),
                                   (6, 3),
                                   (2, 4), (3, 4), (4, 4), (5, 4), (6, 4),
                                   (2, 6), (4, 6), (5, 6), (6, 6), (7, 6)},
        "player": (1, 1),
        "exit": (7, 7),
        "keys": [(1, 7, 0), (4, 5, 1), (5, 7, 2)],      # R at (1,7), B at (4,5), G at (5,7)
        "doors": [(5, 2, 0), (3, 6, 1), (6, 7, 2)],     # R at (5,2), B at (3,6), G at (6,7)
    },

    # L7: 10x10, 4 keys (R,R,B,G), nested doors
    # Two red keys needed (both open all red doors), blue opens blue, green opens green
    #
    #  W W W W W W W W W W
    #  W P . . . . Rd . . W
    #  W . W W W . W . . W
    #  W . W Rk . . W Bk . W
    #  W . W W W . W . . W
    #  W . . . . . Rd . . W
    #  W W W W W . W W W W
    #  W . . Bd . . . . . W
    #  W . Gk . Gd . . . E W
    #  W W W W W W W W W W
    {
        "name": "Double Red",
        "grid_w": 10, "grid_h": 10,
        "walls": _border(10, 10) | {(2, 2), (3, 2), (4, 2), (6, 2),
                                     (2, 3), (6, 3),
                                     (2, 4), (3, 4), (4, 4), (6, 4),
                                     (1, 6), (2, 6), (3, 6), (4, 6), (6, 6), (7, 6), (8, 6)},
        "player": (1, 1),
        "exit": (8, 8),
        "keys": [(3, 3, 0), (7, 3, 1), (2, 8, 2)],   # R at (3,3), B at (7,3), G at (2,8)
        "doors": [(6, 1, 0), (6, 5, 0), (3, 7, 1), (4, 8, 2)],  # 2 red doors, 1 blue, 1 green
    },

    # L8: 10x10, 4 keys, multi-path maze
    # Must navigate complex walls, collect keys in correct order
    #
    #  W W W W W W W W W W
    #  W P . Rd . . . . . W
    #  W . . W . W W W . W
    #  W . . W . . Bk . . W
    #  W W Bd W . W W W . W
    #  W Rk . . . . . . . W
    #  W . . W W W . W W W
    #  W . . . . W . Gd . W
    #  W . W Gk . W . . E W
    #  W W W W W W W W W W
    {
        "name": "Four Locks",
        "grid_w": 10, "grid_h": 10,
        "walls": _border(10, 10) | {(3, 2), (5, 2), (6, 2), (7, 2),
                                     (3, 3),
                                     (3, 4), (5, 4), (6, 4), (7, 4),
                                     (3, 6), (4, 6), (5, 6), (7, 6), (8, 6),
                                     (5, 7),
                                     (2, 8), (5, 8)},
        "player": (1, 1),
        "exit": (8, 8),
        "keys": [(1, 5, 0), (6, 3, 1), (3, 8, 2), (7, 1, 2)],   # R, B, G, G (second green key)
        "doors": [(3, 1, 0), (2, 4, 1), (7, 7, 2)],
    },

    # L9: 10x10, 5 keys, tight routing through winding corridors
    #
    #  W W W W W W W W W W
    #  W P . . . W . Rk . W
    #  W . W W . W . W . W
    #  W . . Rd . . . W . W
    #  W W W W . W . . . W
    #  W . . . . W Bk . . W
    #  W . W Bd . . . W W W
    #  W . W . . W Gk . . W
    #  W . . . Gd . . . E W
    #  W W W W W W W W W W
    {
        "name": "Five Keys",
        "grid_w": 10, "grid_h": 10,
        "walls": _border(10, 10) | {(5, 1), (2, 2), (3, 2), (5, 2), (7, 2),
                                     (7, 3),
                                     (1, 4), (2, 4), (3, 4), (5, 4),
                                     (5, 5),
                                     (2, 6), (7, 6), (8, 6),
                                     (2, 7), (5, 7)},
        "player": (1, 1),
        "exit": (8, 8),
        "keys": [(7, 1, 0), (6, 5, 1), (6, 7, 2), (1, 8, 1), (4, 1, 2)],
        "doors": [(3, 3, 0), (3, 6, 1), (4, 8, 2)],
    },

    # L10: 12x10, 5 keys, grand maze
    # Layout designed with clear path:
    #   Start (1,1), go right to (5,1), down to (5,3), left to get Rk(2,3)
    #   Go back up through dR(6,1) to right half, get Bk(10,1)
    #   Go down right side, get Gk(10,5)
    #   Go through dB(6,4) to lower-left, get Rk2(1,7), Bk2(3,7)
    #   Go through dG(8,6) to exit(10,8)
    #
    #  W W W W W W W W W W W W
    #  W P . . . . dR . . . Bk W
    #  W . . W W . W W W . . W
    #  W . Rk W . . . . . . . W
    #  W . . W . . dB . W W . W
    #  W W . W . W . . W . Gk W
    #  W . . . . W . . dG . . W
    #  W Rk . Bk W . . . . . . W
    #  W . W . . . . . . . E W
    #  W W W W W W W W W W W W
    {
        "name": "Grand Maze",
        "grid_w": 12, "grid_h": 10,
        "walls": _border(12, 10) | {(3, 2), (4, 2), (6, 2), (7, 2), (8, 2),
                                     (3, 3),
                                     (3, 4), (7, 4), (8, 4),
                                     (1, 5), (3, 5), (5, 5), (7, 5),
                                     (5, 6),
                                     (4, 7),
                                     (2, 8)},
        "player": (1, 1),
        "exit": (10, 8),
        "keys": [(2, 3, 0), (10, 1, 1), (10, 5, 2), (1, 7, 0), (3, 7, 1)],
        "doors": [(6, 1, 0), (6, 4, 1), (8, 6, 2)],
    },
]


# ============================================================================
# Display
# ============================================================================

class Rr01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        ox, oy = g._offset_x, g._offset_y

        # Clear to black
        frame[:, :] = C_BLACK

        # Draw floor and walls
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                    continue
                if (gx, gy) in g.walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Draw opened doors as gray floor
        for (dx, dy) in g.opened_doors:
            px, py = ox + dx * CELL, oy + dy * CELL
            if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
                frame[py:py + CELL, px:px + CELL] = C_GRAY

        # Draw closed doors (colored block with black center dot = door marker)
        for (dx, dy, dc) in g.doors:
            if (dx, dy) not in g.opened_doors:
                px, py = ox + dx * CELL, oy + dy * CELL
                if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
                    frame[py:py + CELL, px:px + CELL] = KEY_COLORS[dc]
                    frame[py + 1:py + 3, px + 1:px + 3] = C_BLACK  # door marker

        # Draw remaining keys (colored block with white center dot = key marker)
        for (kx, ky, kc) in g.remaining_keys:
            px, py = ox + kx * CELL, oy + ky * CELL
            if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
                frame[py:py + CELL, px:px + CELL] = KEY_COLORS[kc]
                frame[py + 1:py + 3, px + 1:px + 3] = C_WHITE  # key marker

        # Draw exit
        ex, ey = g.exit_pos
        px, py = ox + ex * CELL, oy + ey * CELL
        if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
            frame[py:py + CELL, px:px + CELL] = C_GOLD

        # Draw player
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        if 0 <= ppx and ppx + CELL <= 64 and 0 <= ppy and ppy + CELL <= 64:
            frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        # HUD: collected key indicators (top-left corner)
        hud_y = 0
        for i, color_idx in enumerate(sorted(g.collected_colors)):
            hx = 1 + i * 5
            if hx + 3 > 64:
                break
            frame[hud_y:hud_y + 2, hx:hx + 3] = KEY_COLORS[color_idx]

        return frame


# ============================================================================
# Game
# ============================================================================

class Rr01(ARCBaseGame):
    def __init__(self):
        self.display = Rr01Display(self)

        # State (set properly in on_set_level)
        self.grid_w = 7
        self.grid_h = 7
        self.walls = set()
        self.px = 1
        self.py = 1
        self.exit_pos = (5, 5)
        self.remaining_keys = []
        self.doors = []
        self.opened_doors = set()
        self.collected_colors = set()
        self._offset_x = 0
        self._offset_y = 0

        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))

        super().__init__(
            "rr01",
            levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4],  # d-pad only
        )

    def on_set_level(self, level: Level) -> None:
        ldef = LEVELS[self.level_index]
        self.grid_w = ldef["grid_w"]
        self.grid_h = ldef["grid_h"]

        # Build wall set: borders + interior walls
        self.walls = set(ldef["walls"])

        # Center grid in 64x64 frame
        self._offset_x = (64 - self.grid_w * CELL) // 2
        self._offset_y = (64 - self.grid_h * CELL) // 2

        # Player position
        self.px, self.py = ldef["player"]

        # Exit
        self.exit_pos = tuple(ldef["exit"])

        # Keys: list of [x, y, color_index]
        self.remaining_keys = [list(k) for k in ldef["keys"]]

        # Doors: list of (x, y, color_index) -- original definitions
        self.doors = list(ldef["doors"])

        # Track which door positions are opened
        self.opened_doors = set()

        # Track collected key colors
        self.collected_colors = set()

    def step(self) -> None:
        aid = self.action.id.value

        # D-pad: 1=up, 2=down, 3=left, 4=right
        delta = _DIR.get(aid)
        if delta is None:
            self.complete_action()
            return

        dx, dy = delta
        nx, ny = self.px + dx, self.py + dy

        # Check wall collision
        if (nx, ny) in self.walls:
            self.complete_action()
            return

        # Check out of bounds
        if nx < 0 or ny < 0 or nx >= self.grid_w or ny >= self.grid_h:
            self.complete_action()
            return

        # Check if blocked by a closed door
        for ddx, ddy, dc in self.doors:
            if (ddx, ddy) == (nx, ny) and (ddx, ddy) not in self.opened_doors:
                self.complete_action()
                return

        # Move player
        self.px, self.py = nx, ny

        # Check key pickup
        for i in range(len(self.remaining_keys) - 1, -1, -1):
            kx, ky, kc = self.remaining_keys[i]
            if self.px == kx and self.py == ky:
                self.collected_colors.add(kc)
                self.remaining_keys.pop(i)
                # Open ALL doors of this color
                for ddx, ddy, dc in self.doors:
                    if dc == kc:
                        self.opened_doors.add((ddx, ddy))

        # Check exit
        if (self.px, self.py) == self.exit_pos:
            self.next_level()

        self.complete_action()
