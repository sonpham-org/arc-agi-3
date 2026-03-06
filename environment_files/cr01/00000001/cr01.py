# Crumbling Route - A turn-based pathfinding puzzle
#
# D-pad to move. Every tile you step off of falls into the abyss.
# Collect all keys before reaching the exit door.
# Plan your route carefully - one wrong step and you're stuck!

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# --- Grid cell size ---
CELL = 4  # 4x4 pixels per cell, fits up to 16x16 grids in 64x64

# --- Colors (ARC palette indices) ---
C_BLACK   = 0   # abyss / fallen tile
C_GRAY    = 3   # cracked tile (one step left before falling)
C_MID     = 5   # normal floor
C_ORANGE  = 7   # key
C_AZURE   = 8   # player
C_GOLD    = 11  # exit door
C_YELLOW  = 4   # teleporter
C_WHITE   = 15  # sturdy floor (never crumbles)
C_RED     = 12  # exit locked indicator
C_LIME    = 14  # exit open indicator
C_DBLUE   = 1   # HUD background

# --- Tile types ---
T_ABYSS   = 0
T_FLOOR   = 1
T_STURDY  = 2
T_CRACKED = 3   # survives one step-off, then becomes floor, then abyss
T_TELEPORT = 4

# Tile color map
TILE_COLORS = {
    T_ABYSS:   C_BLACK,
    T_FLOOR:   C_MID,
    T_STURDY:  C_WHITE,
    T_CRACKED: C_GRAY,
    T_TELEPORT: C_YELLOW,
}

# ============================================================================
# Level definitions
# ============================================================================
# Each level is a dict with:
#   grid_w, grid_h: grid dimensions
#   tiles: dict of (gx, gy) -> tile_type (missing = abyss)
#   player_start: (gx, gy)
#   keys: list of (gx, gy)
#   exit_pos: (gx, gy)
#   teleporters: list of ((gx1,gy1), (gx2,gy2)) pairs (optional)
#   name: level name

LEVELS = [
    # Level 1: Simple 4x3, 1 key, straight path
    # Layout:
    #   P . . .
    #   . K . .
    #   . . . E
    {
        "name": "First Steps",
        "grid_w": 4, "grid_h": 3,
        "tiles": {
            (0,0): T_FLOOR, (1,0): T_FLOOR, (2,0): T_FLOOR, (3,0): T_FLOOR,
            (0,1): T_FLOOR, (1,1): T_FLOOR, (2,1): T_FLOOR, (3,1): T_FLOOR,
            (0,2): T_FLOOR, (1,2): T_FLOOR, (2,2): T_FLOOR, (3,2): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(1, 1)],
        "exit_pos": (3, 2),
        "teleporters": [],
    },

    # Level 2: 5x3, 2 keys
    # Layout:
    #   P . . K .
    #   . . . . .
    #   . K . . E
    {
        "name": "Two Keys",
        "grid_w": 5, "grid_h": 3,
        "tiles": {
            (0,0): T_FLOOR, (1,0): T_FLOOR, (2,0): T_FLOOR, (3,0): T_FLOOR, (4,0): T_FLOOR,
            (0,1): T_FLOOR, (1,1): T_FLOOR, (2,1): T_FLOOR, (3,1): T_FLOOR, (4,1): T_FLOOR,
            (0,2): T_FLOOR, (1,2): T_FLOOR, (2,2): T_FLOOR, (3,2): T_FLOOR, (4,2): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(3, 0), (1, 2)],
        "exit_pos": (4, 2),
        "teleporters": [],
    },

    # Level 3: 6x5, 3 keys, need careful routing
    # Layout (S = sturdy):
    #   P . . . . .
    #   . _ . K . .
    #   . . . . _ .
    #   . K . . . .
    #   . . . K . E
    {
        "name": "Winding Path",
        "grid_w": 6, "grid_h": 5,
        "tiles": {
            (0,0): T_FLOOR, (1,0): T_FLOOR, (2,0): T_FLOOR, (3,0): T_FLOOR, (4,0): T_FLOOR, (5,0): T_FLOOR,
            (0,1): T_FLOOR,                  (2,1): T_FLOOR, (3,1): T_FLOOR, (4,1): T_FLOOR, (5,1): T_FLOOR,
            (0,2): T_FLOOR, (1,2): T_FLOOR, (2,2): T_FLOOR, (3,2): T_FLOOR,                  (5,2): T_FLOOR,
            (0,3): T_FLOOR, (1,3): T_FLOOR, (2,3): T_FLOOR, (3,3): T_FLOOR, (4,3): T_FLOOR, (5,3): T_FLOOR,
            (0,4): T_FLOOR, (1,4): T_FLOOR, (2,4): T_FLOOR, (3,4): T_FLOOR, (4,4): T_FLOOR, (5,4): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(3, 1), (1, 3), (3, 4)],
        "exit_pos": (5, 4),
        "teleporters": [],
    },

    # Level 4: 7x5, 4 keys, tighter routing
    # Has some abyss holes to navigate around
    {
        "name": "Island Hop",
        "grid_w": 7, "grid_h": 5,
        "tiles": {
            (0,0): T_FLOOR, (1,0): T_FLOOR, (2,0): T_FLOOR, (3,0): T_FLOOR, (4,0): T_FLOOR, (5,0): T_FLOOR, (6,0): T_FLOOR,
            (0,1): T_FLOOR, (1,1): T_FLOOR,                  (3,1): T_FLOOR, (4,1): T_FLOOR,                  (6,1): T_FLOOR,
            (0,2): T_FLOOR, (1,2): T_FLOOR, (2,2): T_FLOOR, (3,2): T_FLOOR, (4,2): T_FLOOR, (5,2): T_FLOOR, (6,2): T_FLOOR,
            (0,3): T_FLOOR,                  (2,3): T_FLOOR, (3,3): T_FLOOR,                  (5,3): T_FLOOR, (6,3): T_FLOOR,
            (0,4): T_FLOOR, (1,4): T_FLOOR, (2,4): T_FLOOR, (3,4): T_FLOOR, (4,4): T_FLOOR, (5,4): T_FLOOR, (6,4): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(6, 0), (0, 4), (6, 1), (3, 4)],
        "exit_pos": (6, 4),
        "teleporters": [],
    },

    # Level 5: Introduces cracked tiles (survive one step-off)
    # 6x4 grid with cracked tiles forming alternate routes
    {
        "name": "Cracked Ground",
        "grid_w": 6, "grid_h": 4,
        "tiles": {
            (0,0): T_FLOOR,   (1,0): T_FLOOR,   (2,0): T_FLOOR,   (3,0): T_CRACKED, (4,0): T_FLOOR,   (5,0): T_FLOOR,
            (0,1): T_FLOOR,   (1,1): T_CRACKED,  (2,1): T_FLOOR,   (3,1): T_FLOOR,   (4,1): T_CRACKED, (5,1): T_FLOOR,
            (0,2): T_FLOOR,   (1,2): T_FLOOR,    (2,2): T_CRACKED, (3,2): T_FLOOR,   (4,2): T_FLOOR,   (5,2): T_FLOOR,
            (0,3): T_FLOOR,   (1,3): T_FLOOR,    (2,3): T_FLOOR,   (3,3): T_FLOOR,   (4,3): T_FLOOR,   (5,3): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(5, 0), (0, 3)],
        "exit_pos": (5, 3),
        "teleporters": [],
    },

    # Level 6: More cracked tiles + sturdy tiles
    # 7x5 grid
    {
        "name": "Sturdy Bridge",
        "grid_w": 7, "grid_h": 5,
        "tiles": {
            (0,0): T_FLOOR,   (1,0): T_FLOOR,   (2,0): T_FLOOR,   (3,0): T_CRACKED, (4,0): T_FLOOR,   (5,0): T_FLOOR,   (6,0): T_FLOOR,
            (0,1): T_FLOOR,                       (2,1): T_CRACKED, (3,1): T_STURDY,  (4,1): T_CRACKED, (5,1): T_FLOOR,   (6,1): T_FLOOR,
            (0,2): T_FLOOR,   (1,2): T_FLOOR,    (2,2): T_FLOOR,   (3,2): T_STURDY,  (4,2): T_FLOOR,   (5,2): T_FLOOR,   (6,2): T_FLOOR,
            (0,3): T_FLOOR,   (1,3): T_CRACKED,  (2,3): T_FLOOR,   (3,3): T_STURDY,  (4,3): T_CRACKED, (5,3): T_FLOOR,   (6,3): T_FLOOR,
            (0,4): T_FLOOR,   (1,4): T_FLOOR,    (2,4): T_FLOOR,   (3,4): T_FLOOR,   (4,4): T_FLOOR,   (5,4): T_FLOOR,   (6,4): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(6, 0), (0, 4), (6, 4)],
        "exit_pos": (3, 4),
        "teleporters": [],
    },

    # Level 7: Introduces teleporters
    # Two halves separated by gap at col 4. Teleporter bridges them.
    # Solution path (one-way trip): D*4(0,4)[key],R*3(3,4),U*2(3,2)[tp->5,2],U*2(5,0),R*2(7,0),D*4(7,4)[exit]
    {
        "name": "Warp Zone",
        "grid_w": 8, "grid_h": 5,
        "tiles": {
            (0,0): T_FLOOR, (1,0): T_FLOOR, (2,0): T_FLOOR, (3,0): T_FLOOR,                  (5,0): T_FLOOR, (6,0): T_FLOOR, (7,0): T_FLOOR,
            (0,1): T_FLOOR, (1,1): T_FLOOR, (2,1): T_FLOOR, (3,1): T_FLOOR,                  (5,1): T_FLOOR, (6,1): T_FLOOR, (7,1): T_FLOOR,
            (0,2): T_FLOOR, (1,2): T_FLOOR, (2,2): T_FLOOR, (3,2): T_TELEPORT,               (5,2): T_TELEPORT, (6,2): T_FLOOR, (7,2): T_FLOOR,
            (0,3): T_FLOOR, (1,3): T_FLOOR, (2,3): T_FLOOR, (3,3): T_FLOOR,                  (5,3): T_FLOOR, (6,3): T_FLOOR, (7,3): T_FLOOR,
            (0,4): T_FLOOR, (1,4): T_FLOOR, (2,4): T_FLOOR, (3,4): T_FLOOR,                  (5,4): T_FLOOR, (6,4): T_FLOOR, (7,4): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(0, 4), (7, 0)],
        "exit_pos": (7, 4),
        "teleporters": [((3, 2), (5, 2))],
    },

    # Level 8: Teleporters + cracked tiles
    # Three islands connected by two teleporters. One-way path through each.
    # Solution: D*5(0,5)[key],R*2(2,5),U*5(2,0)[tp->4,0],D*5(4,5)[key],
    #   R*2(6,5)[tp->8,0],R(9,0)[key],D*5(9,5)[exit]
    {
        "name": "Warp Maze",
        "grid_w": 10, "grid_h": 6,
        "tiles": {
            (0,0): T_FLOOR,   (1,0): T_FLOOR,   (2,0): T_TELEPORT,                  (4,0): T_TELEPORT, (5,0): T_FLOOR, (6,0): T_FLOOR,                     (8,0): T_TELEPORT, (9,0): T_FLOOR,
            (0,1): T_FLOOR,   (1,1): T_CRACKED,  (2,1): T_FLOOR,                     (4,1): T_FLOOR,   (5,1): T_CRACKED, (6,1): T_FLOOR,                    (8,1): T_FLOOR, (9,1): T_FLOOR,
            (0,2): T_FLOOR,   (1,2): T_FLOOR,    (2,2): T_FLOOR,                     (4,2): T_FLOOR,   (5,2): T_FLOOR, (6,2): T_FLOOR,                      (8,2): T_FLOOR, (9,2): T_FLOOR,
            (0,3): T_FLOOR,   (1,3): T_FLOOR,    (2,3): T_FLOOR,                     (4,3): T_FLOOR,   (5,3): T_FLOOR, (6,3): T_CRACKED,                    (8,3): T_FLOOR, (9,3): T_FLOOR,
            (0,4): T_FLOOR,   (1,4): T_FLOOR,    (2,4): T_FLOOR,                     (4,4): T_FLOOR,   (5,4): T_FLOOR, (6,4): T_FLOOR,                      (8,4): T_FLOOR, (9,4): T_FLOOR,
            (0,5): T_FLOOR,   (1,5): T_FLOOR,    (2,5): T_FLOOR,                     (4,5): T_FLOOR,   (5,5): T_FLOOR, (6,5): T_TELEPORT,                   (8,5): T_FLOOR, (9,5): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(0, 5), (4, 5), (9, 0)],
        # Solution: D*5(0,5)[key], R*2(2,5), U*5(2,0)[tp->4,0], D*5(4,5)[key],
        # R*2(6,5)[tp->8,5]... wait, tp at (6,5) paired with (8,0)?
        # Actually let me pair: (2,0)<->(4,0) and (6,5)<->(8,0)
        # After tp from (6,5) to (8,0): at (8,0). Then R(9,0)[key], D*5(9,5)[exit]
        "exit_pos": (9, 5),
        "teleporters": [((2, 0), (4, 0)), ((6, 5), (8, 0))],
    },

    # Level 9: Large S-shaped maze with cracked and sturdy tiles
    # 10x7 grid. Sturdy column at x=4 enables return trips.
    # Solution: R*9(9,0)[key]->D*3(9,3)[key]->L*9(0,3)->D*3(0,6)[key]->R*4(4,6)->U*2(4,4)[sturdy]
    # ->U*2(4,2)[sturdy+key]->D*2(4,4)[sturdy]->D*2(4,6)->R*5(9,6)[exit]
    {
        "name": "The Labyrinth",
        "grid_w": 10, "grid_h": 7,
        "tiles": {
            (0,0): T_FLOOR, (1,0): T_FLOOR, (2,0): T_FLOOR, (3,0): T_FLOOR, (4,0): T_FLOOR, (5,0): T_FLOOR, (6,0): T_FLOOR, (7,0): T_FLOOR, (8,0): T_FLOOR, (9,0): T_FLOOR,
            (0,1): T_FLOOR, (1,1): T_FLOOR, (2,1): T_CRACKED, (3,1): T_FLOOR, (4,1): T_FLOOR, (5,1): T_FLOOR, (6,1): T_FLOOR, (7,1): T_CRACKED, (8,1): T_FLOOR, (9,1): T_FLOOR,
            (0,2): T_FLOOR, (1,2): T_FLOOR, (2,2): T_FLOOR, (3,2): T_FLOOR, (4,2): T_STURDY, (5,2): T_FLOOR, (6,2): T_FLOOR, (7,2): T_FLOOR, (8,2): T_FLOOR, (9,2): T_FLOOR,
            (0,3): T_FLOOR, (1,3): T_FLOOR, (2,3): T_FLOOR, (3,3): T_CRACKED, (4,3): T_FLOOR, (5,3): T_FLOOR, (6,3): T_CRACKED, (7,3): T_FLOOR, (8,3): T_FLOOR, (9,3): T_FLOOR,
            (0,4): T_FLOOR, (1,4): T_FLOOR, (2,4): T_FLOOR, (3,4): T_FLOOR, (4,4): T_STURDY, (5,4): T_FLOOR, (6,4): T_FLOOR, (7,4): T_FLOOR, (8,4): T_FLOOR, (9,4): T_FLOOR,
            (0,5): T_FLOOR, (1,5): T_CRACKED, (2,5): T_FLOOR, (3,5): T_FLOOR, (4,5): T_FLOOR, (5,5): T_FLOOR, (6,5): T_FLOOR, (7,5): T_FLOOR, (8,5): T_CRACKED, (9,5): T_FLOOR,
            (0,6): T_FLOOR, (1,6): T_FLOOR, (2,6): T_FLOOR, (3,6): T_FLOOR, (4,6): T_FLOOR, (5,6): T_FLOOR, (6,6): T_FLOOR, (7,6): T_FLOOR, (8,6): T_FLOOR, (9,6): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(9, 0), (5, 3), (0, 3), (0, 6)],
        "exit_pos": (9, 6),
        "teleporters": [],
    },

    # Level 10: Grand finale - double S-shape with all mechanics
    # 10x8 grid. Clean S-path through cracked tiles.
    # Solution: R*9(9,0)[key], D*2(9,2), L*9(0,2)[key], D*3(0,5)[key],
    #   R*9(9,5)[key], D*2(9,7)[key], L*5(4,7)[exit]
    {
        "name": "The Gauntlet",
        "grid_w": 10, "grid_h": 8,
        "tiles": {
            (0,0): T_FLOOR, (1,0): T_FLOOR, (2,0): T_FLOOR, (3,0): T_CRACKED, (4,0): T_FLOOR, (5,0): T_FLOOR, (6,0): T_FLOOR, (7,0): T_CRACKED, (8,0): T_FLOOR, (9,0): T_FLOOR,
            (0,1): T_FLOOR, (1,1): T_FLOOR, (2,1): T_FLOOR, (3,1): T_FLOOR, (4,1): T_FLOOR, (5,1): T_FLOOR, (6,1): T_FLOOR, (7,1): T_FLOOR, (8,1): T_FLOOR, (9,1): T_FLOOR,
            (0,2): T_FLOOR, (1,2): T_CRACKED, (2,2): T_FLOOR, (3,2): T_FLOOR, (4,2): T_FLOOR, (5,2): T_FLOOR, (6,2): T_FLOOR, (7,2): T_FLOOR, (8,2): T_CRACKED, (9,2): T_FLOOR,
            (0,3): T_FLOOR, (1,3): T_FLOOR, (2,3): T_FLOOR, (3,3): T_CRACKED, (4,3): T_FLOOR, (5,3): T_FLOOR, (6,3): T_FLOOR, (7,3): T_FLOOR, (8,3): T_FLOOR, (9,3): T_FLOOR,
            (0,4): T_FLOOR, (1,4): T_FLOOR, (2,4): T_FLOOR, (3,4): T_FLOOR, (4,4): T_FLOOR, (5,4): T_FLOOR, (6,4): T_CRACKED, (7,4): T_FLOOR, (8,4): T_FLOOR, (9,4): T_FLOOR,
            (0,5): T_FLOOR, (1,5): T_CRACKED, (2,5): T_FLOOR, (3,5): T_FLOOR, (4,5): T_FLOOR, (5,5): T_FLOOR, (6,5): T_FLOOR, (7,5): T_FLOOR, (8,5): T_FLOOR, (9,5): T_FLOOR,
            (0,6): T_FLOOR, (1,6): T_FLOOR, (2,6): T_CRACKED, (3,6): T_FLOOR, (4,6): T_FLOOR, (5,6): T_FLOOR, (6,6): T_FLOOR, (7,6): T_FLOOR, (8,6): T_CRACKED, (9,6): T_FLOOR,
            (0,7): T_FLOOR, (1,7): T_FLOOR, (2,7): T_FLOOR, (3,7): T_FLOOR, (4,7): T_FLOOR, (5,7): T_FLOOR, (6,7): T_FLOOR, (7,7): T_FLOOR, (8,7): T_FLOOR, (9,7): T_FLOOR,
        },
        "player_start": (0, 0),
        "keys": [(9, 0), (0, 2), (0, 5), (9, 5), (9, 7)],
        "exit_pos": (4, 7),
        "teleporters": [],
    },
]

# ============================================================================
# Display
# ============================================================================

class Cr01Display(RenderableUserDisplay):
    def __init__(self, game: "Cr01"):
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        ox, oy = g._offset_x, g._offset_y

        # Clear to black (abyss)
        frame[:, :] = C_BLACK

        # Draw tiles
        for (gx, gy), ttype in g.grid.items():
            px, py = ox + gx * CELL, oy + gy * CELL
            if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                continue
            color = TILE_COLORS.get(ttype, C_BLACK)
            frame[py:py + CELL, px:px + CELL] = color

        # Draw keys (orange dot in center of tile)
        for (kx, ky) in g.remaining_keys:
            px, py = ox + kx * CELL, oy + ky * CELL
            if 0 <= px < 64 and 0 <= py < 64:
                # 2x2 orange center
                cx, cy = px + 1, py + 1
                frame[cy:cy+2, cx:cx+2] = C_ORANGE

        # Draw exit
        ex, ey = g.exit_pos
        px, py = ox + ex * CELL, oy + ey * CELL
        if 0 <= px < 64 and 0 <= py < 64:
            if g.keys_collected >= g.keys_total:
                # Exit open - gold
                frame[py:py + CELL, px:px + CELL] = C_GOLD
            else:
                # Exit locked - show as gold border with red center
                frame[py:py + CELL, px:px + CELL] = C_GOLD
                frame[py+1:py+3, px+1:px+3] = C_RED

        # Draw player (azure)
        pgx, pgy = g.player_pos
        px, py = ox + pgx * CELL, oy + pgy * CELL
        if 0 <= px < 64 and 0 <= py < 64:
            frame[py:py + CELL, px:px + CELL] = C_AZURE

        # HUD: key counter (top-left)
        # Show collected/total as colored dots
        hud_y = 0
        for i in range(g.keys_total):
            hx = 1 + i * 5
            if hx + 3 > 64:
                break
            if i < g.keys_collected:
                frame[hud_y:hud_y+2, hx:hx+3] = C_LIME  # collected
            else:
                frame[hud_y:hud_y+2, hx:hx+3] = C_ORANGE  # remaining

        return frame


# ============================================================================
# Game
# ============================================================================

class Cr01(ARCBaseGame):
    def __init__(self):
        self.display = Cr01Display(self)

        # State (properly set in on_set_level)
        self.grid = {}           # (gx,gy) -> tile type
        self.player_pos = (0, 0)
        self.remaining_keys = set()
        self.keys_collected = 0
        self.keys_total = 0
        self.exit_pos = (0, 0)
        self.teleporter_map = {} # (gx,gy) -> (dest_gx, dest_gy)
        self._offset_x = 0
        self._offset_y = 0
        self._cracked_stepped = set()  # cracked tiles that have been stepped off once

        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))

        super().__init__(
            "cr01",
            levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4],  # d-pad only
        )

    def on_set_level(self, level: Level) -> None:
        ldef = LEVELS[self.level_index]
        gw = ldef["grid_w"]
        gh = ldef["grid_h"]

        # Center grid in 64x64 frame, leaving room for HUD at top
        hud_height = 3  # reserve 3 pixels for HUD
        self._offset_x = (64 - gw * CELL) // 2
        self._offset_y = hud_height + (64 - hud_height - gh * CELL) // 2

        # Copy tile grid
        self.grid = dict(ldef["tiles"])

        # Player
        self.player_pos = ldef["player_start"]

        # Keys
        self.remaining_keys = set(ldef["keys"])
        self.keys_collected = 0
        self.keys_total = len(ldef["keys"])

        # Exit
        self.exit_pos = ldef["exit_pos"]

        # Teleporters
        self.teleporter_map = {}
        for (a, b) in ldef.get("teleporters", []):
            self.teleporter_map[a] = b
            self.teleporter_map[b] = a

        # Cracked tile tracking
        self._cracked_stepped = set()

    def step(self) -> None:
        aid = self.action.id.value

        # D-pad: 1=up, 2=down, 3=left, 4=right
        dx, dy = 0, 0
        if aid == 1:
            dy = -1
        elif aid == 2:
            dy = 1
        elif aid == 3:
            dx = -1
        elif aid == 4:
            dx = 1
        else:
            self.complete_action()
            return

        pgx, pgy = self.player_pos
        ngx, ngy = pgx + dx, pgy + dy

        # Check if target is a valid tile (not abyss, not out of bounds)
        if (ngx, ngy) not in self.grid or self.grid[(ngx, ngy)] == T_ABYSS:
            # Can't move there - it's abyss or doesn't exist
            self.complete_action()
            return

        # Valid move - process departure from current tile
        old_pos = (pgx, pgy)

        # Move player to new position
        self.player_pos = (ngx, ngy)

        # Handle tile the player LEFT (crumble logic)
        # Don't crumble if it's a sturdy tile
        old_tile = self.grid.get(old_pos, T_ABYSS)
        if old_tile == T_FLOOR:
            # Normal floor falls immediately when left
            self.grid[old_pos] = T_ABYSS
        elif old_tile == T_CRACKED:
            if old_pos in self._cracked_stepped:
                # Already cracked once - now it falls
                self.grid[old_pos] = T_ABYSS
                self._cracked_stepped.discard(old_pos)
            else:
                # First step off - becomes a normal floor (visually cracks more)
                self._cracked_stepped.add(old_pos)
                self.grid[old_pos] = T_FLOOR
        elif old_tile == T_TELEPORT:
            # Teleporter tiles also crumble when left
            self.grid[old_pos] = T_ABYSS
            # Also remove from teleporter map
            if old_pos in self.teleporter_map:
                dest = self.teleporter_map[old_pos]
                del self.teleporter_map[old_pos]
                if dest in self.teleporter_map:
                    del self.teleporter_map[dest]
        # T_STURDY: never crumbles, stays as is

        # Check if landed on a key
        if self.player_pos in self.remaining_keys:
            self.remaining_keys.remove(self.player_pos)
            self.keys_collected += 1

        # Check if landed on teleporter
        if self.player_pos in self.teleporter_map:
            dest = self.teleporter_map[self.player_pos]
            # Only teleport if destination exists and is not abyss
            if dest in self.grid and self.grid[dest] != T_ABYSS:
                # The teleporter tile we're on will crumble (handled above on next move)
                # Warp to destination
                self.player_pos = dest
                # Check if there's a key at the teleport destination
                if self.player_pos in self.remaining_keys:
                    self.remaining_keys.remove(self.player_pos)
                    self.keys_collected += 1

        # Check if landed on exit
        if self.player_pos == self.exit_pos:
            if self.keys_collected >= self.keys_total:
                # Win this level!
                self.next_level()
                self.complete_action()
                return

        # Check if player is now stuck (surrounded by abyss on all sides
        # and not on the exit with all keys). This is a lose condition.
        pgx, pgy = self.player_pos
        has_valid_move = False
        for ddx, ddy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            check = (pgx + ddx, pgy + ddy)
            if check in self.grid and self.grid[check] != T_ABYSS:
                has_valid_move = True
                break

        if not has_valid_move:
            # Player is stuck - but maybe they're on the exit?
            if self.player_pos == self.exit_pos and self.keys_collected >= self.keys_total:
                self.next_level()
                self.complete_action()
                return
            # Otherwise they're truly stuck
            self.lose()
            self.complete_action()
            return

        self.complete_action()
