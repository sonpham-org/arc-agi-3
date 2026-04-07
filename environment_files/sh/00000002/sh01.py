# Stealth Hunter - Sneak behind or beside guards and eliminate them
#
# D-pad to move. Guards have directional vision cones.
# Kill a guard by stepping onto them from behind OR from the side.
# Only a frontal approach (walking into their face) gets you killed.
# Getting spotted = game over. Guards with guns shoot on sight.
# Dark areas hide you from normal guards (but not flashlight guards).
# Collect keys to open locked doors.
# Guards take 3 steps to rotate 90 degrees (no vision during rotation).
#
# Progressive difficulty:
#   L1: Single guard basics
#   L2: Two guards
#   L3: Two guards with walls
#   L4: Three guards
#   L5: Key to unlock
#   L6: Dark hiding area
#   L7: Larger map, multiple rooms
#   L8: Finale - large map, many enemies

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4  # 4x4 pixels per cell

# ARC-3 palette colors
C_BLACK  = 5   # walls / dark zones
C_BLUE   = 9   # player head
C_RED    = 8   # guard facing indicator / alert
C_GREEN  = 14  # exit / door open
C_YELLOW = 11  # key / flashlight beam
C_GRAY   = 2   # floor
C_PINK   = 6   # armed guard body
C_ORANGE = 12  # guard body
C_AZURE  = 10  # player body
C_MAROON = 13  # locked door
C_DKGRAY = 3   # dark floor
C_GOLD   = 11  # flashlight guard body
C_LTRED  = 7   # vision cone hint (LightMagenta)
C_PURPLE = 15  # killed guard marker
C_LIME   = 14  # exit open
C_WHITE  = 0   # HUD / door frame

# Tile types
T_EMPTY = 0   # wall / void
T_FLOOR = 1
T_WALL  = 2
T_DARK  = 3   # dark floor (hides from normal guards)
T_EXIT  = 4
T_DOOR  = 5   # locked door (needs key)

# Guard types
G_NORMAL     = 0  # patrols, kills on contact if spotted
G_ARMED      = 1  # shoots on sight (instant kill from any visible distance)
G_FLASHLIGHT = 2  # can see through dark zones

# Directions: 0=up, 1=down, 2=left, 3=right
DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT = 0, 1, 2, 3
DIR_DELTAS = {DIR_UP: (0, -1), DIR_DOWN: (0, 1), DIR_LEFT: (-1, 0), DIR_RIGHT: (1, 0)}
DIR_OPPOSITE = {DIR_UP: DIR_DOWN, DIR_DOWN: DIR_UP, DIR_LEFT: DIR_RIGHT, DIR_RIGHT: DIR_LEFT}

# Kill from behind or side: only frontal approach is fatal.
# "Frontal" = player's movement direction == opposite of guard's facing.
# e.g., guard faces UP, player moves DOWN (walking into guard's face) = frontal = death.
# Guard faces UP, player moves UP (from below = behind) or LEFT/RIGHT (side) = kill.


def bresenham_line(x0, y0, x1, y1):
    """Bresenham's line algorithm. Returns list of (x,y) points."""
    points = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return points


def has_line_of_sight(grid, x0, y0, x1, y1, see_through_dark=False):
    """Check if there's unobstructed line of sight between two points.
    Uses Bresenham's line. Walls block. Dark tiles block unless see_through_dark."""
    points = bresenham_line(x0, y0, x1, y1)
    for px, py in points[1:]:  # skip the starting point
        if px == x1 and py == y1:
            return True  # reached target
        tile = grid.get((px, py), T_EMPTY)
        if tile == T_EMPTY or tile == T_WALL:
            return False
        if tile == T_DARK and not see_through_dark:
            return False
        if tile == T_DOOR:
            return False  # closed doors block sight
    return True


def get_vision_cells(grid, gx, gy, facing, vision_range, see_through_dark=False):
    """Get all cells a guard can see given position, facing, and range.
    Vision is a cone: the forward direction + diagonals spreading out."""
    visible = set()
    dx, dy = DIR_DELTAS[facing]

    for dist in range(1, vision_range + 1):
        # Forward line
        tx, ty = gx + dx * dist, gy + dy * dist
        if has_line_of_sight(grid, gx, gy, tx, ty, see_through_dark):
            visible.add((tx, ty))

        # Spread: narrow cone, ~30 degrees
        spread = dist // 2  # 0 at dist 1, 1 at dist 2-3, 2 at dist 4-5
        if dx == 0:  # facing up/down, spread along x
            for s in range(1, spread + 1):
                for sx in [s, -s]:
                    cx = gx + sx
                    cy = gy + dy * dist
                    if has_line_of_sight(grid, gx, gy, cx, cy, see_through_dark):
                        visible.add((cx, cy))
        else:  # facing left/right, spread along y
            for s in range(1, spread + 1):
                for sy in [s, -s]:
                    cx = gx + dx * dist
                    cy = gy + sy
                    if has_line_of_sight(grid, gx, gy, cx, cy, see_through_dark):
                        visible.add((cx, cy))

    return visible


# ============================================================================
# Level definitions
# ============================================================================
# Each level:
#   grid: dict of (x,y) -> tile_type
#   grid_w, grid_h: dimensions
#   player_start: (x, y)
#   exit_pos: (x, y)
#   guards: list of (x, y, facing, guard_type, patrol_list, vision_range)
#     patrol_list: list of directions the guard cycles through each turn
#     vision_range: how far they can see
#   keys: list of (x, y)
#   doors: list of (x, y)

def make_rect(x, y, w, h, tile=T_FLOOR):
    """Helper: make a rectangular room of floor tiles."""
    tiles = {}
    for gx in range(x, x + w):
        for gy in range(y, y + h):
            tiles[(gx, gy)] = tile
    return tiles

def make_walls_border(tiles):
    """Add wall tiles around the border of existing floor tiles."""
    walls = {}
    for (x, y) in list(tiles.keys()):
        for dx, dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1),(-1,1),(1,1)]:
            nb = (x+dx, y+dy)
            if nb not in tiles:
                walls[nb] = T_WALL
    tiles.update(walls)
    return tiles


LEVELS = [
    # Level 1: "First Blood" - 1 enemy
    # One guard facing right. Walk up from behind or side to kill.
    {
        "name": "First Blood",
        "grid_w": 8, "grid_h": 6,
        "grid": {
            **{(x,y): T_FLOOR for x in range(1,7) for y in range(1,5)},
            **{(x,0): T_WALL for x in range(8)},
            **{(x,5): T_WALL for x in range(8)},
            **{(0,y): T_WALL for y in range(6)},
            **{(7,y): T_WALL for y in range(6)},
        },
        "player_start": (1, 3),
        "exit_pos": (6, 1),
        "guards": [
            (4, 3, DIR_RIGHT, G_NORMAL, [], 3),
        ],
        "keys": [],
        "doors": [],
    },

    # Level 2: "Double Trouble" - 2 enemies
    # Two stationary guards. Kill both to exit.
    {
        "name": "Double Trouble",
        "grid_w": 9, "grid_h": 7,
        "grid": {
            **{(x,y): T_FLOOR for x in range(1,8) for y in range(1,6)},
            **{(x,0): T_WALL for x in range(9)},
            **{(x,6): T_WALL for x in range(9)},
            **{(0,y): T_WALL for y in range(7)},
            **{(8,y): T_WALL for y in range(7)},
        },
        "player_start": (1, 5),
        "exit_pos": (7, 1),
        "guards": [
            (3, 2, DIR_RIGHT, G_NORMAL, [], 3),
            (6, 4, DIR_LEFT, G_NORMAL, [], 3),
        ],
        "keys": [],
        "doors": [],
    },

    # Level 3: "Cover" - 2 enemies with walls
    # Two guards with wall cover between zones.
    # Guard1 faces RIGHT in top area. Guard2 rotates DOWN/RIGHT with 3-step turn.
    {
        "name": "Cover",
        "grid_w": 10, "grid_h": 8,
        "grid": {
            **{(x,y): T_FLOOR for x in range(1,9) for y in range(1,7)},
            **{(x,0): T_WALL for x in range(10)},
            **{(x,7): T_WALL for x in range(10)},
            **{(0,y): T_WALL for y in range(8)},
            **{(9,y): T_WALL for y in range(8)},
            # Horizontal wall divider with gap on right
            (2,4): T_WALL, (3,4): T_WALL, (4,4): T_WALL, (5,4): T_WALL, (6,4): T_WALL,
            # Vertical wall cover
            (4,2): T_WALL, (4,3): T_WALL,
        },
        "player_start": (1, 6),
        "exit_pos": (8, 1),
        "guards": [
            # Top-left guard, faces RIGHT, stationary
            (2, 2, DIR_RIGHT, G_NORMAL, [], 3),
            # Bottom-right guard, rotates between DOWN and RIGHT (3 steps per turn)
            (7, 5, DIR_DOWN, G_NORMAL, [DIR_RIGHT, DIR_DOWN], 3),
        ],
        "keys": [],
        "doors": [],
    },

    # Level 4: "Three's a Crowd" - 3 enemies
    # Three guards in a larger room with wall cover.
    {
        "name": "Three's a Crowd",
        "grid_w": 10, "grid_h": 8,
        "grid": {
            **{(x,y): T_FLOOR for x in range(1,9) for y in range(1,7)},
            **{(x,0): T_WALL for x in range(10)},
            **{(x,7): T_WALL for x in range(10)},
            **{(0,y): T_WALL for y in range(8)},
            **{(9,y): T_WALL for y in range(8)},
            # Wall pillars for cover
            (3,3): T_WALL, (3,4): T_WALL,
            (6,2): T_WALL, (6,3): T_WALL, (6,4): T_WALL, (6,5): T_WALL,
        },
        "player_start": (1, 6),
        "exit_pos": (8, 1),
        "guards": [
            # Guard 1: faces RIGHT in top-left
            (2, 2, DIR_RIGHT, G_NORMAL, [], 3),
            # Guard 2: faces UP in bottom-right, rotates UP/LEFT
            (7, 5, DIR_UP, G_NORMAL, [DIR_LEFT, DIR_UP], 3),
            # Guard 3: faces DOWN in center-right, stationary
            (5, 4, DIR_DOWN, G_NORMAL, [], 3),
        ],
        "keys": [],
        "doors": [],
    },

    # Level 5: "Locked Up" - Key to unlock
    # Key in bottom-left. Door blocks the path. One guard behind door.
    {
        "name": "Locked Up",
        "grid_w": 10, "grid_h": 7,
        "grid": {
            # Left room
            **{(x,y): T_FLOOR for x in range(1,4) for y in range(1,6)},
            # Right room
            **{(x,y): T_FLOOR for x in range(5,9) for y in range(1,6)},
            # Door
            (4, 3): T_DOOR,
            # Walls
            **{(x,0): T_WALL for x in range(10)},
            **{(x,6): T_WALL for x in range(10)},
            **{(0,y): T_WALL for y in range(7)},
            **{(9,y): T_WALL for y in range(7)},
            # Dividing wall
            (4,1): T_WALL, (4,2): T_WALL, (4,4): T_WALL, (4,5): T_WALL,
        },
        "player_start": (1, 1),
        "exit_pos": (8, 1),
        "guards": [
            # Guard faces RIGHT in right room
            (6, 3, DIR_RIGHT, G_NORMAL, [], 3),
        ],
        "keys": [(1, 5)],
        "doors": [(4, 3)],
    },

    # Level 6: "Shadow Zone" - Dark area for hiding
    # Dark corridor through center. Guards can't see into dark.
    # Sneak through darkness to get behind guards.
    {
        "name": "Shadow Zone",
        "grid_w": 10, "grid_h": 8,
        "grid": {
            **{(x,y): T_FLOOR for x in range(1,9) for y in range(1,7)},
            **{(x,0): T_WALL for x in range(10)},
            **{(x,7): T_WALL for x in range(10)},
            **{(0,y): T_WALL for y in range(8)},
            **{(9,y): T_WALL for y in range(8)},
            # Large dark zone in center
            **{(x,y): T_DARK for x in range(3,7) for y in range(2,6)},
        },
        "player_start": (1, 6),
        "exit_pos": (8, 1),
        "guards": [
            # Guard faces RIGHT, vision blocked by dark
            (2, 2, DIR_RIGHT, G_NORMAL, [], 4),
            # Guard faces LEFT, vision blocked by dark
            (7, 5, DIR_LEFT, G_NORMAL, [], 4),
        ],
        "keys": [],
        "doors": [],
    },

    # Level 7: "The Compound" - Larger map, multiple rooms
    # Three rooms connected by corridors. Guards in each room.
    {
        "name": "The Compound",
        "grid_w": 14, "grid_h": 10,
        "grid": {
            # Room 1 (top-left): 4x4 floor
            **{(x,y): T_FLOOR for x in range(1,5) for y in range(1,5)},
            # Room 2 (top-right): 4x4 floor
            **{(x,y): T_FLOOR for x in range(9,13) for y in range(1,5)},
            # Room 3 (bottom-center): 6x3 floor
            **{(x,y): T_FLOOR for x in range(4,10) for y in range(6,9)},
            # Corridor: room1 to room3
            (4,5): T_FLOOR, (4,6): T_FLOOR,
            (3,5): T_FLOOR,
            # Corridor: room2 to room3
            (9,5): T_FLOOR, (9,6): T_FLOOR,
            (10,5): T_FLOOR,
            # Corridor: room1 to room2
            **{(x,3): T_FLOOR for x in range(5,9)},
            # Outer walls
            **{(x,0): T_WALL for x in range(14)},
            **{(x,9): T_WALL for x in range(14)},
            **{(0,y): T_WALL for y in range(10)},
            **{(13,y): T_WALL for y in range(10)},
            # Room 1 walls
            (5,1): T_WALL, (5,2): T_WALL, (5,4): T_WALL,
            (1,5): T_WALL, (2,5): T_WALL,
            # Room 2 walls
            (8,1): T_WALL, (8,2): T_WALL, (8,4): T_WALL,
            (11,5): T_WALL, (12,5): T_WALL,
            # Room 3 walls
            (3,6): T_WALL, (3,7): T_WALL, (3,8): T_WALL,
            (10,6): T_WALL, (10,7): T_WALL, (10,8): T_WALL,
            # Corridor walls
            (5,5): T_WALL, (6,5): T_WALL, (7,5): T_WALL, (8,5): T_WALL,
            (5,2): T_WALL, (5,4): T_WALL,
            (8,2): T_WALL, (8,4): T_WALL,
        },
        "player_start": (1, 4),
        "exit_pos": (12, 1),
        "guards": [
            # Room 1: guard faces RIGHT
            (3, 2, DIR_RIGHT, G_NORMAL, [], 3),
            # Room 3: guard rotates DOWN/RIGHT
            (7, 7, DIR_DOWN, G_NORMAL, [DIR_RIGHT, DIR_DOWN], 3),
            # Corridor: guard faces DOWN between rooms
            (6, 3, DIR_DOWN, G_NORMAL, [], 2),
        ],
        "keys": [],
        "doors": [],
    },

    # Level 8: "The Gauntlet" - Finale: large map, many enemies
    # Multiple rooms, dark areas, key/door, 5 guards.
    {
        "name": "The Gauntlet",
        "grid_w": 15, "grid_h": 12,
        "grid": {
            # Room A (start, bottom-left): 4x4
            **{(x,y): T_FLOOR for x in range(1,5) for y in range(7,11)},
            # Room B (center): 5x4 with dark zone
            **{(x,y): T_FLOOR for x in range(5,10) for y in range(5,9)},
            **{(x,y): T_DARK for x in range(6,9) for y in range(6,8)},
            # Room C (top-left): 4x3
            **{(x,y): T_FLOOR for x in range(1,5) for y in range(1,4)},
            # Room D (top-right): 4x3
            **{(x,y): T_FLOOR for x in range(10,14) for y in range(1,4)},
            # Room E (bottom-right): 4x4 with dark entrance
            **{(x,y): T_FLOOR for x in range(10,14) for y in range(7,11)},
            # Dark tiles hide player entering Room E from G5's UP vision
            (12,7): T_DARK, (12,8): T_DARK,
            # Corridor A->B (right from room A)
            (5,8): T_FLOOR, (5,9): T_FLOOR,
            # Corridor A->C (up from room A)
            (2,4): T_FLOOR, (2,5): T_FLOOR, (2,6): T_FLOOR,
            # Corridor B->D (up-right from room B)
            **{(x,4): T_FLOOR for x in range(7,11)},
            (10,4): T_FLOOR, (10,5): T_FLOOR, (10,6): T_FLOOR,
            # Corridor D->E (down from room D)
            (12,4): T_FLOOR, (12,5): T_FLOOR, (12,6): T_FLOOR,
            # Door between C and D
            (5,2): T_DOOR,
            # Corridor C->door
            **{(x,2): T_FLOOR for x in range(5,10)},
            (9,2): T_FLOOR,
            # Outer walls
            **{(x,0): T_WALL for x in range(15)},
            **{(x,11): T_WALL for x in range(15)},
            **{(0,y): T_WALL for y in range(12)},
            **{(14,y): T_WALL for y in range(12)},
            # Room A walls (top + right, with gaps for corridors)
            (1,6): T_WALL, (3,6): T_WALL, (4,6): T_WALL,
            (5,7): T_WALL, (5,10): T_WALL,
            # Room C walls (bottom + right, with corridor gap)
            (1,4): T_WALL, (3,4): T_WALL, (4,4): T_WALL,
            (5,1): T_WALL, (5,3): T_WALL,
            # Room B walls
            (5,5): T_WALL, (5,6): T_WALL,
            (10,5): T_WALL, (10,8): T_WALL,
            (6,9): T_WALL, (7,9): T_WALL, (8,9): T_WALL, (9,9): T_WALL,
            # Room D walls
            (9,1): T_WALL, (9,3): T_WALL,
            (11,4): T_WALL, (13,4): T_WALL,
            # Room E walls
            (10,7): T_WALL, (10,10): T_WALL,
            (11,6): T_WALL, (13,6): T_WALL,
        },
        "player_start": (1, 10),
        "exit_pos": (13, 1),
        "guards": [
            # Room A: guard faces UP
            (3, 8, DIR_UP, G_NORMAL, [], 3),
            # Room B: guard faces LEFT, rotates LEFT/DOWN
            (6, 8, DIR_LEFT, G_NORMAL, [DIR_DOWN, DIR_LEFT], 3),
            # Room C: guard faces DOWN, guards the key
            (3, 2, DIR_DOWN, G_NORMAL, [], 1),
            # Room D: guard faces LEFT, rotates LEFT/UP
            (11, 2, DIR_LEFT, G_NORMAL, [DIR_UP, DIR_LEFT], 3),
            # Room E: guard faces UP, stationary
            (12, 9, DIR_UP, G_NORMAL, [], 3),
        ],
        "keys": [(1, 1)],
        "doors": [(5, 2)],
    },
]


# ============================================================================
# Display
# ============================================================================

class Sh02Display(RenderableUserDisplay):
    def __init__(self, game: "Sh01"):
        self.game = game

    def _draw_person(self, frame, px, py, facing, body_color, head_color):
        """Draw a 4x4 person sprite with directional head.
        Body is 3x2, head is 1 pixel pointing in facing direction.

        The shape (facing UP):
          .X..
          XXX.
          XXX.
          ....

        Facing RIGHT:
          .XX.
          .XXX
          .XX.
          ....

        Facing DOWN:
          XXX.
          XXX.
          .X..
          ....

        Facing LEFT:
          XX..
          XXX.
          XX..
          ....
        """
        if facing == DIR_UP:
            # Head on top center
            frame[py, px+1] = head_color
            frame[py+1, px:px+3] = body_color
            frame[py+2, px:px+3] = body_color
        elif facing == DIR_DOWN:
            # Head on bottom center
            frame[py, px:px+3] = body_color
            frame[py+1, px:px+3] = body_color
            frame[py+2, px+1] = head_color
        elif facing == DIR_LEFT:
            # Head on left center
            frame[py, px:px+2] = body_color
            frame[py+1, px:px+3] = body_color
            frame[py+2, px:px+2] = body_color
            frame[py+1, px] = head_color  # override leftmost mid with head
            # Actually let's redo: head sticks out left
            frame[py, px+1:px+3] = body_color
            frame[py+1, px:px+3] = body_color
            frame[py+2, px+1:px+3] = body_color
            frame[py+1, px] = head_color
        elif facing == DIR_RIGHT:
            # Head on right center
            frame[py, px:px+2] = body_color
            frame[py+1, px:px+3] = body_color
            frame[py+2, px:px+2] = body_color
            frame[py+1, px+2] = head_color  # override rightmost mid with head
            # Actually redo for consistency:
            frame[py, px:px+2] = body_color
            frame[py+1, px:px+3] = body_color
            frame[py+2, px:px+2] = body_color
            frame[py+1, px+2] = head_color

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        ox, oy = g._offset_x, g._offset_y

        # Clear
        frame[:, :] = C_BLACK

        # Draw tiles
        for (gx, gy), tile in g.grid.items():
            px, py = ox + gx * CELL, oy + gy * CELL
            if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                continue
            if tile == T_FLOOR:
                frame[py:py+CELL, px:px+CELL] = C_GRAY
                # Subtle grid lines
                frame[py+CELL-1, px:px+CELL] = C_GRAY - 1 if C_GRAY > 0 else C_GRAY
            elif tile == T_WALL:
                frame[py:py+CELL, px:px+CELL] = C_BLACK
                # Wall texture: slight highlight on top-left
                frame[py, px:px+CELL] = C_DKGRAY  # dark gray top edge
                frame[py:py+CELL, px] = C_DKGRAY
            elif tile == T_DARK:
                # Dark floor - very dark
                frame[py:py+CELL, px:px+CELL] = C_DKGRAY
                # Subtle checkerboard to show it's floor
                frame[py, px] = C_BLACK
                frame[py+2, px+2] = C_BLACK
            elif tile == T_EXIT:
                frame[py:py+CELL, px:px+CELL] = C_LIME
            elif tile == T_DOOR:
                if g.doors_open:
                    frame[py:py+CELL, px:px+CELL] = C_GREEN
                else:
                    frame[py:py+CELL, px:px+CELL] = C_MAROON
                    frame[py+1:py+3, px+1:px+3] = C_YELLOW  # keyhole

        # Draw vision cones (subtle red tint on visible cells)
        for cell in g.all_vision_cells:
            gx, gy = cell
            px, py = ox + gx * CELL, oy + gy * CELL
            if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                continue
            tile = g.grid.get(cell, T_EMPTY)
            if tile in (T_FLOOR, T_DARK):
                # Tint: draw red dots at corners to show danger
                frame[py, px] = C_LTRED
                frame[py, px+CELL-1] = C_LTRED

        # Draw exit
        ex, ey = g.exit_pos
        px, py = ox + ex * CELL, oy + ey * CELL
        if 0 <= px < 64 and 0 <= py < 64:
            frame[py:py+CELL, px:px+CELL] = C_LIME

        # Draw keys
        for (kx, ky) in g.remaining_keys:
            px, py = ox + kx * CELL, oy + ky * CELL
            if 0 <= px < 64 and 0 <= py < 64:
                # Small key shape
                frame[py+1, px+1:px+3] = C_YELLOW
                frame[py+2, px+2] = C_YELLOW

        # Draw killed guards (X marks)
        for (kx, ky) in g.killed_positions:
            px, py = ox + kx * CELL, oy + ky * CELL
            if 0 <= px < 64 and 0 <= py < 64:
                frame[py, px] = C_PURPLE
                frame[py+2, px+2] = C_PURPLE
                frame[py, px+2] = C_PURPLE
                frame[py+2, px] = C_PURPLE

        # Draw guards
        for guard in g.guards:
            if not guard["alive"]:
                continue
            gx, gy = guard["x"], guard["y"]
            px, py = ox + gx * CELL, oy + gy * CELL
            if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                continue
            gtype = guard["type"]
            if gtype == G_ARMED:
                body_color = C_PINK
            elif gtype == G_FLASHLIGHT:
                body_color = C_GOLD
            else:
                body_color = C_ORANGE
            self._draw_person(frame, px, py, guard["facing"], body_color, C_RED)

        # Draw player
        ppx, ppy = g.player_pos
        px, py = ox + ppx * CELL, oy + ppy * CELL
        if 0 <= px < 64 and 0 <= py < 64:
            self._draw_person(frame, px, py, g.player_facing, C_AZURE, C_BLUE)

        # HUD: top row - key count and guard count
        hud_y = 0
        # Keys remaining
        for i in range(g.keys_total):
            hx = 1 + i * 4
            if hx + 2 > 64:
                break
            if i < g.keys_collected:
                frame[hud_y, hx:hx+2] = C_LIME
            else:
                frame[hud_y, hx:hx+2] = C_YELLOW

        # Guards remaining (right side)
        alive_guards = sum(1 for guard in g.guards if guard["alive"])
        for i in range(len(g.guards)):
            hx = 62 - i * 4
            if hx < 0:
                break
            if i < alive_guards:
                frame[hud_y, hx:hx+2] = C_RED
            else:
                frame[hud_y, hx:hx+2] = C_PURPLE

        return frame


# ============================================================================
# Game
# ============================================================================

class Sh01(ARCBaseGame):
    def __init__(self):
        self.display = Sh02Display(self)

        # State
        self.grid = {}
        self.player_pos = (0, 0)
        self.player_facing = DIR_DOWN
        self.exit_pos = (0, 0)
        self.guards = []
        self.remaining_keys = set()
        self.keys_collected = 0
        self.keys_total = 0
        self.doors_open = False
        self.door_positions = set()
        self.killed_positions = set()
        self.all_vision_cells = set()
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
            "sh",
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

        self._offset_x = (64 - gw * CELL) // 2
        self._offset_y = 2 + (64 - 2 - gh * CELL) // 2  # 2px HUD

        self.grid = dict(ldef["grid"])
        self.player_pos = ldef["player_start"]
        self.player_facing = DIR_DOWN
        self.exit_pos = ldef["exit_pos"]

        # Set exit tile
        self.grid[self.exit_pos] = T_EXIT

        # Guards
        self.guards = []
        for gdef in ldef["guards"]:
            x, y, facing, gtype, patrol, vrange = gdef
            self.guards.append({
                "x": x, "y": y,
                "facing": facing,
                "type": gtype,
                "patrol": list(patrol),
                "patrol_idx": 0,
                "vision_range": vrange,
                "alive": True,
                "rotate_timer": 0,
                "rotate_target": facing,
            })

        # Keys
        self.remaining_keys = set(ldef["keys"])
        self.keys_collected = 0
        self.keys_total = len(ldef["keys"])

        # Doors
        self.door_positions = set(ldef["doors"])
        self.doors_open = self.keys_total == 0  # open if no keys needed

        self.killed_positions = set()

        # Calculate initial vision
        self._update_vision()

    def _update_vision(self):
        """Recalculate all guards' vision cones."""
        self.all_vision_cells = set()
        for guard in self.guards:
            if not guard["alive"]:
                continue
            # No vision while rotating (facing is between directions)
            if guard["rotate_timer"] > 0:
                guard["vision"] = set()
                continue
            see_dark = guard["type"] == G_FLASHLIGHT
            cells = get_vision_cells(
                self.grid, guard["x"], guard["y"],
                guard["facing"], guard["vision_range"],
                see_through_dark=see_dark
            )
            guard["vision"] = cells
            self.all_vision_cells |= cells

    def _is_player_in_dark(self):
        """Check if player is standing on a dark tile."""
        return self.grid.get(self.player_pos, T_EMPTY) == T_DARK

    def _check_detection(self):
        """Check if any guard can see the player. Returns True if detected."""
        px, py = self.player_pos
        for guard in self.guards:
            if not guard["alive"]:
                continue
            if self.player_pos in guard.get("vision", set()):
                # Player is in vision cone
                # But dark tiles hide from non-flashlight guards
                if self._is_player_in_dark() and guard["type"] != G_FLASHLIGHT:
                    continue
                return True
        return False

    def _move_guards(self):
        """Move patrolling guards one step in their patrol cycle.
        Rotation takes 3 steps (no vision during rotation)."""
        for guard in self.guards:
            if not guard["alive"]:
                continue

            # Handle ongoing rotation
            if guard["rotate_timer"] > 0:
                guard["rotate_timer"] -= 1
                if guard["rotate_timer"] == 0:
                    guard["facing"] = guard["rotate_target"]
                continue  # no movement or patrol during rotation

            if not guard["patrol"]:
                continue

            # Get next direction in patrol
            new_facing = guard["patrol"][guard["patrol_idx"]]
            guard["patrol_idx"] = (guard["patrol_idx"] + 1) % len(guard["patrol"])

            # If direction changes, start a 3-step rotation
            if new_facing != guard["facing"]:
                guard["rotate_target"] = new_facing
                guard["rotate_timer"] = 3
                continue  # rotation starts, no movement this step

            # Same direction: move forward
            dx, dy = DIR_DELTAS[new_facing]
            nx, ny = guard["x"] + dx, guard["y"] + dy
            tile = self.grid.get((nx, ny), T_EMPTY)

            # Guards don't walk into walls, doors, other guards, or off map
            can_move = tile in (T_FLOOR, T_DARK, T_EXIT)
            if can_move:
                # Check no other guard at destination
                for other in self.guards:
                    if other is guard or not other["alive"]:
                        continue
                    if other["x"] == nx and other["y"] == ny:
                        can_move = False
                        break
                # Don't walk into player
                if (nx, ny) == self.player_pos:
                    can_move = False

            if can_move:
                guard["x"] = nx
                guard["y"] = ny

    def step(self) -> None:
        aid = self.action.id.value

        dx, dy = 0, 0
        if aid == 1:
            dy = -1  # up
        elif aid == 2:
            dy = 1   # down
        elif aid == 3:
            dx = -1  # left
        elif aid == 4:
            dx = 1   # right
        else:
            self.complete_action()
            return

        # Update player facing
        if dy == -1:
            self.player_facing = DIR_UP
        elif dy == 1:
            self.player_facing = DIR_DOWN
        elif dx == -1:
            self.player_facing = DIR_LEFT
        elif dx == 1:
            self.player_facing = DIR_RIGHT

        px, py = self.player_pos
        nx, ny = px + dx, py + dy

        # Check target tile
        target_tile = self.grid.get((nx, ny), T_EMPTY)

        # Check if there's a guard at destination
        target_guard = None
        for guard in self.guards:
            if guard["alive"] and guard["x"] == nx and guard["y"] == ny:
                target_guard = guard
                break

        if target_guard is not None:
            # Attempting to step onto a guard
            # Kill from behind or side: only frontal approach is fatal.
            # "Frontal" = walking into the direction the guard is looking at
            # = player's facing == opposite of guard's facing
            frontal = (self.player_facing == DIR_OPPOSITE[target_guard["facing"]])
            if not frontal:
                # Stealth kill from behind or side!
                target_guard["alive"] = False
                self.killed_positions.add((nx, ny))
                self.player_pos = (nx, ny)
            else:
                # Frontal approach = detected = death
                self.lose()
                self.complete_action()
                return
        elif target_tile in (T_FLOOR, T_DARK, T_EXIT):
            self.player_pos = (nx, ny)
        elif target_tile == T_DOOR:
            if self.doors_open:
                self.player_pos = (nx, ny)
            # else: can't pass, player stays put (but turn still passes)
        # else: wall or empty - can't move (but turn still passes)

        # Pick up key
        if self.player_pos in self.remaining_keys:
            self.remaining_keys.remove(self.player_pos)
            self.keys_collected += 1
            if self.keys_collected >= self.keys_total:
                self.doors_open = True
                # Convert door tiles to floor
                for dpos in self.door_positions:
                    self.grid[dpos] = T_FLOOR

        # Check exit
        if self.player_pos == self.exit_pos:
            # Must kill all guards to exit
            all_dead = all(not g["alive"] for g in self.guards)
            if all_dead:
                self.next_level()
                self.complete_action()
                return

        # Guards move AFTER player
        self._move_guards()

        # Recalculate vision after guards move
        self._update_vision()

        # Check if player is now detected
        if self._check_detection():
            self.lose()
            self.complete_action()
            return

        self.complete_action()
