# Light Bender - A beam-reflection puzzle game
#
# D-pad (1-4) moves cursor. ACTION5 cycles mirror state on placeable cells:
# empty -> "/" mirror -> "\" mirror -> empty.
# A light source fires a beam; mirrors redirect it. Win when beam reaches target.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4

# Colors (ARC-3 palette — dark theme)
C_BLACK  = 5   # Black — background / abyss
C_FLOOR  = 4   # VeryDarkGray — floor tiles
C_WALL   = 3   # DarkGray — border & interior walls
C_GRAY   = 3   # DarkGray — fixed mirror bg, placeable dots
C_YELLOW = 11  # Yellow — backslash player mirror
C_ORANGE = 12  # Orange — slash player mirror
C_AZURE  = 10  # LightBlue — beam
C_GOLD   = 11  # Yellow — target
C_RED    = 8   # Red — source
C_LIME   = 14  # Green — cursor
C_WHITE  = 0   # White — mirror line pattern

# Mirror types
M_EMPTY = 0
M_SLASH = 1       # "/"
M_BACKSLASH = 2   # "\"

# Reflection maps
# "/" reflects: right->up, up->right, left->down, down->left
SLASH_REFLECT = {
    (1, 0): (0, -1),
    (-1, 0): (0, 1),
    (0, 1): (-1, 0),
    (0, -1): (1, 0),
}
# "\" reflects: right->down, down->right, left->up, up->left
BACKSLASH_REFLECT = {
    (1, 0): (0, 1),
    (-1, 0): (0, -1),
    (0, 1): (1, 0),
    (0, -1): (-1, 0),
}

# ============================================================================
# Level definitions
#
# source: (x, y, dx, dy) - beam origin and initial direction
# target: (x, y) - cell the beam must reach to win
# walls: set of (x, y) - interior wall cells that block beam
# fixed_mirrors: dict of (x, y) -> M_SLASH or M_BACKSLASH - pre-placed mirrors
# placeable: set of (x, y) - cells where player can place/cycle mirrors
# cursor_start: (x, y) - initial cursor position
# ============================================================================

LEVELS = [
    # L1: "First Bend" - Tutorial. One mirror to redirect beam down.
    # Source left (0,3) right, target bottom (3,6).
    # Solution: \ at (3,3)
    {
        "name": "First Bend",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "source": (0, 3, 1, 0),
        "target": (3, 6),
        "fixed_mirrors": {},
        "placeable": {(3, 3)},
        "cursor_start": (3, 3),
    },

    # L2: "Simple Bend" - One \ mirror to redirect beam down.
    # Source left (0,2) right, target bottom (3,6).
    # Solution: \ at (3,2)
    {
        "name": "Simple Bend",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "source": (0, 2, 1, 0),
        "target": (3, 6),
        "fixed_mirrors": {},
        "placeable": {(3, 2)},
        "cursor_start": (3, 2),
    },

    # L3: "Two Turns" - Two mirrors to route beam.
    # Source top (1,0) down, target bottom (5,7).
    # Solution: \ at (1,3), \ at (5,3)
    {
        "name": "Two Turns",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "source": (1, 0, 0, 1),
        "target": (5, 7),
        "fixed_mirrors": {},
        "placeable": {(1, 3), (5, 3)},
        "cursor_start": (1, 3),
    },

    # L4: "Fixed Guide" - One fixed mirror + one player mirror.
    # Source left (0,2) right, target right (7,5).
    # Fixed \ at (4,2). Player places \ at (4,5).
    {
        "name": "Fixed Guide",
        "grid_w": 8, "grid_h": 8,
        "walls": set(),
        "source": (0, 2, 1, 0),
        "target": (7, 5),
        "fixed_mirrors": {(4, 2): M_BACKSLASH},
        "placeable": {(4, 5)},
        "cursor_start": (4, 5),
    },

    # L5: "Triple Bounce" - Three mirrors in a zigzag.
    # Source left (0,1) right, target bottom (4,8).
    # Solution: \ at (2,1), \ at (2,3), \ at (4,3)
    {
        "name": "Triple Bounce",
        "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "source": (0, 1, 1, 0),
        "target": (4, 8),
        "fixed_mirrors": {},
        "placeable": {(2, 1), (2, 3), (4, 3)},
        "cursor_start": (2, 1),
    },

    # L6: "Wall Detour" - Walls block straight path, must route around.
    # Source left (0,4) right, target right (8,2). Walls at col 4 rows 3-5.
    # Solution: / at (3,4), / at (3,1), \ at (7,1), \ at (7,2)
    {
        "name": "Wall Detour",
        "grid_w": 9, "grid_h": 9,
        "walls": {(4, 3), (4, 4), (4, 5)},
        "source": (0, 4, 1, 0),
        "target": (8, 2),
        "fixed_mirrors": {},
        "placeable": {(3, 4), (3, 1), (7, 1), (7, 2)},
        "cursor_start": (3, 4),
    },

    # L7: "Zigzag" - Four mirrors in a staircase pattern.
    # Source left (0,1) right, target right (9,8).
    # Solution: \ at (3,1), \ at (3,4), \ at (6,4), \ at (6,8)
    {
        "name": "Zigzag",
        "grid_w": 10, "grid_h": 10,
        "walls": set(),
        "source": (0, 1, 1, 0),
        "target": (9, 8),
        "fixed_mirrors": {},
        "placeable": {(3, 1), (3, 4), (6, 4), (6, 8)},
        "cursor_start": (3, 1),
    },

    # L8: "Fixed Maze" - Two fixed + two player mirrors.
    # Source left (0,2) right, target right (9,7).
    # Fixed: \ at (3,2), \ at (3,5). Player: \ at (6,5), \ at (6,7).
    {
        "name": "Fixed Maze",
        "grid_w": 10, "grid_h": 10,
        "walls": set(),
        "source": (0, 2, 1, 0),
        "target": (9, 7),
        "fixed_mirrors": {(3, 2): M_BACKSLASH, (3, 5): M_BACKSLASH},
        "placeable": {(6, 5), (6, 7)},
        "cursor_start": (6, 5),
    },

    # L9: "Periscope" - Mix of / and \ mirrors around walls.
    # Source left (0,4) right, target right (9,2). Walls at col 5 rows 3-5.
    # Solution: / at (3,4), / at (3,1), \ at (7,1), \ at (7,2)
    {
        "name": "Periscope",
        "grid_w": 10, "grid_h": 10,
        "walls": {(5, 3), (5, 4), (5, 5)},
        "source": (0, 4, 1, 0),
        "target": (9, 2),
        "fixed_mirrors": {},
        "placeable": {(3, 4), (3, 1), (7, 1), (7, 2)},
        "cursor_start": (3, 4),
    },

    # L10: "Grand Puzzle" - Five mirrors with wall obstacles.
    # Source top (2,0) down, target right (11,7).
    # Walls at (5,2),(5,3),(6,2),(6,3),(7,2),(7,3) block direct routing.
    # Solution: \ at (2,3), / at (4,3), / at (4,1), \ at (8,1), \ at (8,7)
    {
        "name": "Grand Puzzle",
        "grid_w": 12, "grid_h": 10,
        "walls": {(5, 2), (5, 3), (6, 2), (6, 3), (7, 2), (7, 3)},
        "source": (2, 0, 0, 1),
        "target": (11, 7),
        "fixed_mirrors": {},
        "placeable": {(2, 3), (4, 3), (4, 1), (8, 1), (8, 7)},
        "cursor_start": (2, 3),
    },
]


# ============================================================================
# Display
# ============================================================================

class Lb01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        # Draw grid cells
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.border_walls:
                    frame[py:py + CELL, px:px + CELL] = C_WALL
                elif (gx, gy) in g.interior_walls:
                    frame[py:py + CELL, px:px + CELL] = C_WALL
                else:
                    frame[py:py + CELL, px:px + CELL] = C_FLOOR

        # Draw source
        sx, sy = g.source[0], g.source[1]
        spx, spy = ox + sx * CELL, oy + sy * CELL
        frame[spy:spy + CELL, spx:spx + CELL] = C_RED

        # Draw target
        tx, ty = g.target
        tpx, tpy = ox + tx * CELL, oy + ty * CELL
        frame[tpy:tpy + CELL, tpx:tpx + CELL] = C_GOLD

        # Draw placeable cell markers (subtle dot in center)
        for (plx, ply) in g.placeable:
            if (plx, ply) not in g.mirrors:
                ppx, ppy = ox + plx * CELL, oy + ply * CELL
                # Small center dot to indicate placeable
                cx, cy = ppx + CELL // 2, ppy + CELL // 2
                if 0 <= cy < 64 and 0 <= cx < 64:
                    frame[cy, cx] = C_GRAY

        # Draw mirrors
        for (mx, my), mtype in g.mirrors.items():
            mpx, mpy = ox + mx * CELL, oy + my * CELL
            if (mx, my) in g.fixed_mirrors:
                # Fixed mirror: gray background
                frame[mpy:mpy + CELL, mpx:mpx + CELL] = C_GRAY
            else:
                # Player mirror: orange for /, yellow for backslash
                color = C_ORANGE if mtype == M_SLASH else C_YELLOW
                frame[mpy:mpy + CELL, mpx:mpx + CELL] = color
            # Draw slash/backslash pattern on mirror
            for i in range(CELL):
                if mtype == M_SLASH:
                    # "/" pattern: bottom-left to top-right
                    r = mpy + (CELL - 1 - i)
                    c = mpx + i
                else:
                    # "\" pattern: top-left to bottom-right
                    r = mpy + i
                    c = mpx + i
                if 0 <= r < 64 and 0 <= c < 64:
                    frame[r, c] = C_WHITE

        # Draw beam path
        for (bx, by) in g.beam_path:
            # Skip drawing beam on source and mirror cells (they have their own colors)
            if (bx, by) == (g.source[0], g.source[1]):
                continue
            if (bx, by) in g.mirrors:
                continue
            bpx, bpy = ox + bx * CELL, oy + by * CELL
            # Draw beam as center 2x2
            r0, r1 = bpy + 1, bpy + 3
            c0, c1 = bpx + 1, bpx + 3
            if r0 >= 0 and c0 >= 0 and r1 <= 64 and c1 <= 64:
                frame[r0:r1, c0:c1] = C_AZURE

        # Draw beam on target if hit (gold with azure center)
        if g.target in g.beam_path:
            tpx2, tpy2 = ox + tx * CELL, oy + ty * CELL
            frame[tpy2:tpy2 + CELL, tpx2:tpx2 + CELL] = C_GOLD
            frame[tpy2 + 1:tpy2 + 3, tpx2 + 1:tpx2 + 3] = C_AZURE

        # Draw cursor border (lime outline)
        cx_pos, cy_pos = g.cursor_x, g.cursor_y
        cpx, cpy = ox + cx_pos * CELL, oy + cy_pos * CELL
        for i in range(CELL):
            # Top edge
            r, c = cpy, cpx + i
            if 0 <= r < 64 and 0 <= c < 64:
                frame[r, c] = C_LIME
            # Bottom edge
            r = cpy + CELL - 1
            if 0 <= r < 64 and 0 <= c < 64:
                frame[r, c] = C_LIME
            # Left edge
            r, c = cpy + i, cpx
            if 0 <= r < 64 and 0 <= c < 64:
                frame[r, c] = C_LIME
            # Right edge
            c = cpx + CELL - 1
            if 0 <= r < 64 and 0 <= c < 64:
                frame[r, c] = C_LIME

        # Level progress bar at top
        n = len(LEVELS)
        bar_w = 64 // n
        for li in range(n):
            color = C_AZURE if li < g.level_index else (C_GOLD if li == g.level_index else C_GRAY)
            c0 = li * bar_w
            c1 = min(64, c0 + bar_w - 1)
            frame[0:2, c0:c1] = color

        return frame


# ============================================================================
# Game
# ============================================================================

class Lb01(ARCBaseGame):
    def __init__(self):
        self.display = Lb01Display(self)
        levels = []
        for d in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=d,
                name=d["name"],
            ))
        super().__init__(
            "lb01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4, 5],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]

        # Build border walls
        self.border_walls = set()
        for x in range(self.grid_w):
            self.border_walls.add((x, 0))
            self.border_walls.add((x, self.grid_h - 1))
        for y in range(self.grid_h):
            self.border_walls.add((0, y))
            self.border_walls.add((self.grid_w - 1, y))

        # Remove source and target from border walls so beam can reach them
        src = (d["source"][0], d["source"][1])
        self.border_walls.discard(src)
        self.border_walls.discard(d["target"])

        # Interior walls (obstacles)
        self.interior_walls = set(d.get("walls", set()))

        self.source = d["source"]
        self.target = tuple(d["target"])
        self.fixed_mirrors = dict(d.get("fixed_mirrors", {}))
        self.placeable = set(d.get("placeable", set()))

        # Active mirrors = fixed + player-placed
        self.mirrors = dict(self.fixed_mirrors)

        # Cursor
        cs = d.get("cursor_start", (1, 1))
        self.cursor_x, self.cursor_y = cs

        # Trace initial beam
        self.beam_path = []
        self._trace_beam()

    def _trace_beam(self):
        """Trace beam from source, reflecting off mirrors, stopping at walls."""
        sx, sy, dx, dy = self.source
        x, y = sx + dx, sy + dy
        self.beam_path = []
        visited = set()
        # Combine all blocking walls
        all_walls = self.border_walls | self.interior_walls

        while True:
            if (x, y) in visited:
                break  # infinite loop guard
            if (x, y) in all_walls:
                break
            if x < 0 or y < 0 or x >= self.grid_w or y >= self.grid_h:
                break
            visited.add((x, y))
            self.beam_path.append((x, y))
            if (x, y) == self.target:
                break  # hit target
            if (x, y) in self.mirrors:
                mtype = self.mirrors[(x, y)]
                if mtype == M_SLASH:
                    new = SLASH_REFLECT.get((dx, dy))
                else:
                    new = BACKSLASH_REFLECT.get((dx, dy))
                if new is None:
                    break
                dx, dy = new
            x, y = x + dx, y + dy

    def _check_win(self):
        return self.target in self.beam_path

    def step(self):
        aid = self.action.id.value

        if aid in (1, 2, 3, 4):
            # D-pad: move cursor
            ddx, ddy = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}[aid]
            nx, ny = self.cursor_x + ddx, self.cursor_y + ddy
            # Allow cursor on any interior cell (not border walls)
            if 1 <= nx <= self.grid_w - 2 and 1 <= ny <= self.grid_h - 2:
                self.cursor_x, self.cursor_y = nx, ny
        elif aid == 5:
            # Cycle mirror on current cell if it's placeable
            pos = (self.cursor_x, self.cursor_y)
            if pos in self.placeable and pos not in self.fixed_mirrors:
                if pos not in self.mirrors:
                    # empty -> /
                    self.mirrors[pos] = M_SLASH
                elif self.mirrors[pos] == M_SLASH:
                    # / -> backslash
                    self.mirrors[pos] = M_BACKSLASH
                else:
                    # backslash -> empty
                    del self.mirrors[pos]
                # Re-trace beam after mirror change
                self._trace_beam()
                if self._check_win():
                    self.next_level()

        self.complete_action()
