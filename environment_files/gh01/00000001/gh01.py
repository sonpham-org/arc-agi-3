"""
gh01 - Ghost Heist  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Move up
ACTION2 (v): Move down
ACTION3 (<): Move left
ACTION4 (>): Move right

A stealth puzzle. Steal the treasure and escape to the exit without being
seen by guards. Guards patrol fixed routes and see straight ahead for
several tiles (blocked by walls). Step on the treasure to pick it up,
then reach the exit to clear the level.

Fully deterministic - no random elements.
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# --- Colours (ARC palette) ---
C_BLACK  = 0
C_MID    = 5
C_PINK   = 6
C_ORANGE = 7
C_AZURE  = 8
C_GOLD   = 11
C_RED    = 12
C_LIME   = 14
C_WHITE  = 15

# Cell size in pixels
CELL = 4

# Direction map: action_id -> (dx, dy) in grid coords
_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

# ========================================================================
# Level definitions
# ========================================================================
# Each level:
#   grid_w, grid_h  - playfield dimensions (borders are auto-walled)
#   walls           - set of (x, y) interior wall positions
#   player          - (x, y) start position
#   treasure        - (x, y) treasure position
#   exit            - (x, y) exit position
#   guards          - list of (start_x, start_y, patrol_moves, vision_range)
#                     patrol_moves: list of (dx, dy), loops forever

LEVELS = [
    # L1: 7x7, 1 guard simple up-down patrol
    {
        "name": "Easy Grab",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (1, 5),
        "treasure": (5, 1),
        "exit": (1, 1),
        "guards": [
            (3, 3, [(0, -1), (0, -1), (0, 1), (0, 1)], 3),
        ],
    },
    # L2: 7x7, 1 guard, walls to hide behind
    {
        "name": "Wall Cover",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 2), (3, 3), (3, 4)},
        "player": (1, 5),
        "treasure": (5, 3),
        "exit": (1, 1),
        "guards": [
            (5, 1, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
        ],
    },
    # L3: 8x8, 2 guards
    {
        "name": "Double Watch",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "player": (1, 6),
        "treasure": (6, 1),
        "exit": (1, 1),
        "guards": [
            (3, 3, [(1, 0), (1, 0), (-1, 0), (-1, 0)], 3),
            (6, 4, [(0, -1), (0, -1), (0, 1), (0, 1)], 3),
        ],
    },
    # L4: 8x8, 2 guards, corridors with gaps
    {
        "name": "Corridor Run",
        "grid_w": 8, "grid_h": 8,
        "walls": {(4, 2), (4, 3), (4, 4)},
        "player": (1, 6),
        "treasure": (6, 1),
        "exit": (1, 1),
        "guards": [
            (3, 1, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (6, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
        ],
    },
    # L5: 9x9, 2 guards, treasure behind guards
    {
        "name": "Behind the Watch",
        "grid_w": 9, "grid_h": 9,
        "walls": {(4, 2), (4, 3), (4, 5), (4, 6)},
        "player": (1, 7),
        "treasure": (7, 4),
        "exit": (1, 1),
        "guards": [
            (3, 4, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
            (6, 3, [(0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1)], 3),
        ],
    },
    # L6: 9x9, 3 guards, must time movements
    {
        "name": "Timing Is Key",
        "grid_w": 9, "grid_h": 9,
        "walls": {(3, 3), (3, 4), (3, 5),
                  (6, 3), (6, 4), (6, 5)},
        "player": (1, 7),
        "treasure": (7, 1),
        "exit": (1, 1),
        "guards": [
            (2, 2, [(1, 0), (1, 0), (1, 0), (-1, 0), (-1, 0), (-1, 0)], 3),
            (5, 4, [(0, -1), (0, -1), (0, 1), (0, 1)], 3),
            (7, 5, [(0, 1), (0, 1), (0, -1), (0, -1)], 3),
        ],
    },
    # L7: 10x10, 3 guards, complex patrols
    {
        "name": "Complex Patrol",
        "grid_w": 10, "grid_h": 10,
        "walls": {(4, 2), (4, 3), (4, 4),
                  (6, 5), (6, 6), (6, 7)},
        "player": (1, 8),
        "treasure": (8, 1),
        "exit": (1, 1),
        "guards": [
            (3, 5, [(0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1)], 3),
            (5, 2, [(1, 0), (1, 0), (1, 0), (-1, 0), (-1, 0), (-1, 0)], 3),
            (8, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
        ],
    },
    # L8: 10x10, 4 guards, maze
    {
        "name": "The Maze",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 3), (3, 4), (3, 5),
                  (6, 4), (6, 5), (6, 6)},
        "player": (1, 8),
        "treasure": (8, 1),
        "exit": (1, 1),
        "guards": [
            (2, 2, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (5, 1, [(0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1)], 3),
            (5, 7, [(1, 0), (1, 0), (1, 0), (-1, 0), (-1, 0), (-1, 0)], 3),
            (8, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
        ],
    },
    # L9: 10x10, 4 guards, tight timing
    {
        "name": "Tight Timing",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 3), (3, 4), (3, 5),
                  (6, 2), (6, 3),
                  (6, 6), (6, 7)},
        "player": (1, 8),
        "treasure": (8, 1),
        "exit": (1, 1),
        "guards": [
            (2, 2, [(0, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (5, 1, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (7, 4, [(-1, 0), (1, 0)], 3),
            (8, 5, [(0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1)], 3),
        ],
    },
    # L10: 12x10, 5 guards, grand heist
    {
        "name": "Grand Heist",
        "grid_w": 12, "grid_h": 10,
        "walls": {(3, 2), (3, 3), (3, 4),
                  (5, 5), (5, 6), (5, 7),
                  (8, 2), (8, 3), (8, 4),
                  (10, 5), (10, 6), (10, 7)},
        "player": (1, 8),
        "treasure": (10, 1),
        "exit": (1, 1),
        "guards": [
            (2, 1, [(0, 1), (0, 1), (0, 1), (0, 1), (0, -1), (0, -1), (0, -1), (0, -1)], 3),
            (4, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
            (6, 2, [(1, 0), (1, 0), (-1, 0), (-1, 0)], 3),
            (9, 5, [(0, -1), (0, -1), (0, -1), (0, 1), (0, 1), (0, 1)], 3),
            (7, 8, [(1, 0), (1, 0), (1, 0), (-1, 0), (-1, 0), (-1, 0)], 3),
        ],
    },
]


def _border(w, h):
    """All border cells as a set."""
    s = set()
    for x in range(w):
        s.add((x, 0))
        s.add((x, h - 1))
    for y in range(h):
        s.add((0, y))
        s.add((w - 1, y))
    return s


# ========================================================================
# Display
# ========================================================================

class Gh01Display(RenderableUserDisplay):
    def __init__(self, game):
        super().__init__()
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        if not hasattr(g, 'grid_w'):
            return frame

        gw, gh = g.grid_w, g.grid_h
        ox = (64 - gw * CELL) // 2
        oy = (64 - gh * CELL) // 2

        frame[:, :] = C_BLACK

        # Draw floor and walls
        for gy in range(gh):
            for gx in range(gw):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Draw vision cones (before entities so they show as background)
        for vx, vy in g.vision_cells:
            px, py = ox + vx * CELL, oy + vy * CELL
            # Draw inner 2x2 pink marker on floor
            frame[py + 1:py + 3, px + 1:px + 3] = C_PINK

        # Draw treasure (if not picked up)
        if not g.has_treasure:
            tx, ty = g.treasure_pos
            px, py = ox + tx * CELL, oy + ty * CELL
            frame[py:py + CELL, px:px + CELL] = C_GOLD

        # Draw exit
        ex, ey = g.exit_pos
        px, py = ox + ex * CELL, oy + ey * CELL
        frame[py:py + CELL, px:px + CELL] = C_ORANGE

        # Draw guards
        for grd in g.guards:
            gx, gy = grd[0], grd[1]
            px, py = ox + gx * CELL, oy + gy * CELL
            frame[py:py + CELL, px:px + CELL] = C_RED

        # Draw player
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        c = C_LIME if g.has_treasure else C_AZURE
        frame[ppy:ppy + CELL, ppx:ppx + CELL] = c

        return frame


# ========================================================================
# Game
# ========================================================================

class Gh01(ARCBaseGame):
    def __init__(self):
        self.display = Gh01Display(self)

        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))

        super().__init__(
            "gh01",
            levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]

        # Build walls: border + interior
        self.walls = set()
        for x in range(self.grid_w):
            self.walls.add((x, 0))
            self.walls.add((x, self.grid_h - 1))
        for y in range(self.grid_h):
            self.walls.add((0, y))
            self.walls.add((self.grid_w - 1, y))
        self.walls |= set(d["walls"])

        # Player
        self.px, self.py = d["player"]

        # Treasure and exit
        self.treasure_pos = d["treasure"]
        self.exit_pos = d["exit"]
        self.has_treasure = False

        # Guards: [x, y, patrol_index, patrol_moves, face_dx, face_dy, vision_range]
        self.guards = []
        for gx, gy, patrol, vr in d["guards"]:
            fdx, fdy = patrol[0] if patrol else (0, 1)
            self.guards.append([gx, gy, 0, patrol, fdx, fdy, vr])

        # Compute initial vision
        self.vision_cells = set()
        self._update_vision()

    def _update_vision(self):
        """Recompute all guard vision cones."""
        self.vision_cells = set()
        for g in self.guards:
            gx, gy, _, _, fdx, fdy, vr = g
            for i in range(1, vr + 1):
                vx, vy = gx + fdx * i, gy + fdy * i
                if (vx, vy) in self.walls:
                    break
                self.vision_cells.add((vx, vy))

    def _player_detected(self):
        """Check if the player is in any guard's vision cone."""
        return (self.px, self.py) in self.vision_cells

    def step(self) -> None:
        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        # Can't walk into walls
        if (nx, ny) in self.walls:
            self.complete_action()
            return

        # Can't walk onto a guard
        for g in self.guards:
            if (nx, ny) == (g[0], g[1]):
                self.complete_action()
                return

        # Move player
        self.px, self.py = nx, ny

        # Pick up treasure
        if not self.has_treasure and (self.px, self.py) == self.treasure_pos:
            self.has_treasure = True

        # Check win: on exit with treasure
        if self.has_treasure and (self.px, self.py) == self.exit_pos:
            self.next_level()
            self.complete_action()
            return

        # Move guards along their patrol routes
        for g in self.guards:
            gx, gy, pi, patrol, fdx, fdy, vr = g
            if patrol:
                mdx, mdy = patrol[pi]
                ngx, ngy = gx + mdx, gy + mdy
                if (ngx, ngy) not in self.walls:
                    g[0], g[1] = ngx, ngy
                    g[4], g[5] = mdx, mdy  # update facing direction
                else:
                    # Can't move but still update facing
                    g[4], g[5] = mdx, mdy
                g[2] = (pi + 1) % len(patrol)

        # Recompute vision after guards move
        self._update_vision()

        # Check detection after guards move
        if self._player_detected():
            self.lose()
            self.complete_action()
            return

        # Check if a guard walked onto the player
        for g in self.guards:
            if (g[0], g[1]) == (self.px, self.py):
                self.lose()
                self.complete_action()
                return

        self.complete_action()
