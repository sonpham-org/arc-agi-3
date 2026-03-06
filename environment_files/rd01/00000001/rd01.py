# River Diverter - A flow-routing pipe puzzle
#
# D-pad (1-4) moves cursor. ACTION5 cycles pipe type at cursor position.
# Direct water from the source to the drain by placing/rotating pipes.
# Water flows automatically through connected pipes.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4

# ARC-AGI-3 colour indices
C_BLACK = 0
C_GRAY = 3
C_MID = 5
C_AZURE = 8
C_BLUE = 9
C_GOLD = 11
C_RED = 12
C_LIME = 14
C_WHITE = 15

# Pipe types
P_EMPTY = 0
P_HORIZ = 1   # connects left-right
P_VERT = 2    # connects up-down
P_TL = 3      # connects up-left
P_TR = 4      # connects up-right
P_BL = 5      # connects down-left
P_BR = 6      # connects down-right

PIPE_CYCLE = [P_EMPTY, P_HORIZ, P_VERT, P_TL, P_TR, P_BL, P_BR]

# Connections: which directions each pipe type connects
# Directions are (dx, dy) offsets
PIPE_CONN = {
    P_HORIZ: {(-1, 0), (1, 0)},    # left, right
    P_VERT:  {(0, -1), (0, 1)},    # up, down
    P_TL:    {(0, -1), (-1, 0)},   # up, left
    P_TR:    {(0, -1), (1, 0)},    # up, right
    P_BL:    {(0, 1), (-1, 0)},    # down, left
    P_BR:    {(0, 1), (1, 0)},     # down, right
}

# =====================================================================
# Level definitions
#
# Each level has:
#   grid_w, grid_h: dimensions (border cells are auto-walled)
#   source: (x, y, flow_dx, flow_dy) - position on border, initial flow dir
#   drain: (x, y) - position on border (or adjacent to border)
#   fixed_pipes: {(x,y): pipe_type} - pre-placed, cannot be changed
#   placeable: {(x,y), ...} - cells where player can place pipes
#   walls: set of (x,y) - interior walls (border added automatically)
#
# Solution comments show the correct pipe placements for verification.
# Water trace: source flows into first interior cell, follows pipe
# connections until it reaches drain or is blocked.
# =====================================================================

LEVELS = [
    # ------------------------------------------------------------------
    # L1: "Straight Shot" (7x7)
    # Source left at (0,3) flowing right, drain right at (6,3).
    # Player places 5 horizontal pipes in a straight line.
    # Solution: (1,3)=H, (2,3)=H, (3,3)=H, (4,3)=H, (5,3)=H
    # Water: (1,3)->right->(2,3)->right->(3,3)->right->(4,3)->right->(5,3)->right->(6,3)=drain
    # ------------------------------------------------------------------
    {
        "name": "Straight Shot",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "source": (0, 3, 1, 0),
        "drain": (6, 3),
        "fixed_pipes": {},
        "placeable": {(1, 3), (2, 3), (3, 3), (4, 3), (5, 3)},
    },

    # ------------------------------------------------------------------
    # L2: "First Turn" (7x7)
    # Source top at (3,0) flowing down, drain right at (6,3).
    # Need to go down then turn right.
    # Solution: (3,1)=V, (3,2)=V, (3,3)=BR, (4,3)=H, (5,3)=H
    # Water: (3,1)->down->(3,2)->down->(3,3) BR exits right->(4,3)->right->(5,3)->right->(6,3)=drain
    # BR connects down+right. from_dir at (3,3) is (0,-1)="came from up".
    # BR has {(0,1),(1,0)}. from_dir (0,-1) not in BR! Need a pipe that
    # connects up and right = P_TR {(0,-1),(1,0)}.
    # Corrected: (3,3)=TR
    # TR has {(0,-1),(1,0)}. from_dir=(0,-1) is in TR. Exit=(1,0). Correct!
    # ------------------------------------------------------------------
    {
        "name": "First Turn",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "source": (3, 0, 0, 1),
        "drain": (6, 3),
        "fixed_pipes": {},
        "placeable": {(3, 1), (3, 2), (3, 3), (4, 3), (5, 3)},
    },

    # ------------------------------------------------------------------
    # L3: "Double Bend" (7x7)
    # Source left at (0,1) flowing right, drain bottom at (5,6) flowing down.
    # Route: right along row 1, turn down at (5,1), down to (5,5), into drain.
    # Solution: (1,1)=H, (2,1)=H, (3,1)=H, (4,1)=H, (5,1)=TR (connects
    #   up+right... no, need to go right then turn down.
    #   from_dir at (5,1) is (-1,0)="came from left".
    #   Need pipe connecting left+down = P_BL {(0,1),(-1,0)}.
    #   BL: from_dir (-1,0) in BL? Yes! Exit = (0,1) = down.
    # Then: (5,2)=V, (5,3)=V, (5,4)=V, (5,5)=V -> down to (5,6)=drain
    # ------------------------------------------------------------------
    {
        "name": "Double Bend",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "source": (0, 1, 1, 0),
        "drain": (5, 6),
        "fixed_pipes": {},
        "placeable": {
            (1, 1), (2, 1), (3, 1), (4, 1), (5, 1),
            (5, 2), (5, 3), (5, 4), (5, 5),
        },
    },

    # ------------------------------------------------------------------
    # L4: "Gap Fill" (7x7)
    # Source left at (0,3) flowing right, drain right at (6,3).
    # Some pipes pre-placed, player fills gaps.
    # Fixed: (1,3)=H, (3,3)=H, (5,3)=H
    # Player places: (2,3)=H, (4,3)=H
    # Water: straight horizontal line.
    # ------------------------------------------------------------------
    {
        "name": "Gap Fill",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "source": (0, 3, 1, 0),
        "drain": (6, 3),
        "fixed_pipes": {(1, 3): P_HORIZ, (3, 3): P_HORIZ, (5, 3): P_HORIZ},
        "placeable": {(2, 3), (4, 3)},
    },

    # ------------------------------------------------------------------
    # L5: "Wall Dodge" (9x7)
    # Source left at (0,3) flowing right, drain right at (8,3).
    # Wall at (4,3) blocks straight path. Must go around.
    # Route: right to (3,3), up to (3,2), right across (4,2)-(5,2),
    #   down at (5,2) to (5,3), right to drain.
    # Solution:
    #   (1,3)=H  from_dir=(-1,0), exit=(1,0)
    #   (2,3)=H  from_dir=(-1,0), exit=(1,0)
    #   (3,3)=TR from_dir=(-1,0)... TR has {(0,-1),(1,0)}.
    #     (-1,0) not in TR! Need left+up = P_TL {(0,-1),(-1,0)}.
    #     TL: from (-1,0) in TL? Yes! Exit=(0,-1)=up.
    #   (3,2)=TR from_dir=(0,1)="came from below". TR has {(0,-1),(1,0)}.
    #     (0,1) not in TR! Need down+right = P_BR {(0,1),(1,0)}.
    #     BR: from (0,1) in BR? Yes! Exit=(1,0)=right.
    #   (4,2)=H  from_dir=(-1,0), exit=(1,0)
    #   (5,2)=BL from_dir=(-1,0). BL has {(0,1),(-1,0)}.
    #     from (-1,0) in BL? Yes! Exit=(0,1)=down.
    #   (5,3)=TR from_dir=(0,-1)="came from above". TR has {(0,-1),(1,0)}.
    #     (0,-1) not in TR! Wait - from_dir is the direction we came FROM,
    #     which is the REVERSE of travel. We traveled down to reach (5,3),
    #     so from_dir = (0,-1) (came from up). TR needs (0,-1) in conns.
    #     TR = {(0,-1),(1,0)}. Yes (0,-1) is in TR! Exit=(1,0)=right.
    #   Wait, that's wrong. Let me re-trace.
    #   Water at (5,2) exits down via BL, goes to (5,3).
    #   from_dir at (5,3) = -exit_dir = -(0,1) = (0,-1). So from_dir=(0,-1).
    #   TR has {(0,-1),(1,0)}. (0,-1) in TR? Yes! Exit = (1,0) = right.
    #   (6,3)=H  from_dir=(-1,0), exit=(1,0)
    #   (7,3)=H  from_dir=(-1,0), exit=(1,0) -> (8,3)=drain
    # ------------------------------------------------------------------
    {
        "name": "Wall Dodge",
        "grid_w": 9, "grid_h": 7,
        "walls": {(4, 3)},
        "source": (0, 3, 1, 0),
        "drain": (8, 3),
        "fixed_pipes": {},
        "placeable": {
            (1, 3), (2, 3), (3, 3),
            (3, 2), (4, 2), (5, 2),
            (5, 3), (6, 3), (7, 3),
        },
    },

    # ------------------------------------------------------------------
    # L6: "S-Curve" (9x9)
    # Source left at (0,2) flowing right, drain right at (8,6).
    # Route: right along row 2, down, right along row 4, down, right along row 6.
    # Solution:
    #   (1,2)=H, (2,2)=H, (3,2)=H, (4,2)=H, (5,2)=BL
    #     BL at (5,2): from (-1,0), exit (0,1)=down
    #   (5,3)=V, (5,4)=BR
    #     BR at (5,4): from (0,-1), exit (1,0)=right
    #     Wait: V at (5,3): from (0,-1) (came from up). V={(0,-1),(0,1)}.
    #     (0,-1) in V? Yes. Exit=(0,1)=down.
    #     BR at (5,4): from_dir=(0,-1). BR={(0,1),(1,0)}. (0,-1) not in BR!
    #     Need up+right = P_TR. TR={(0,-1),(1,0)}. (0,-1) in TR? Yes! Exit=(1,0).
    #   Correction: (5,4)=TR
    #   (6,4)=H, (7,4)=BL
    #     BL at (7,4): from (-1,0), exit (0,1)=down
    #   (7,5)=V, (7,6)=TR
    #     Wait, need to reach drain at (8,6). So from (7,6), exit right to (8,6).
    #     TR at (7,6): from (0,-1). TR={(0,-1),(1,0)}. Yes! Exit=(1,0)=right to (8,6)=drain.
    #   Wait, but (7,5) V: from_dir=(0,-1). V={(0,-1),(0,1)}. Yes. Exit=(0,1)=down.
    #   (7,6): from_dir=(0,-1). TR={(0,-1),(1,0)}. Yes! Exit right. Drain at (8,6). Correct!
    #
    # Actually let me simplify. Let me make it go:
    # right r2 -> down -> right r6 to drain. Two turns only but longer.
    # (1,2)=H, (2,2)=H, (3,2)=BL
    #   BL: from (-1,0), exit (0,1)=down
    # (3,3)=V, (3,4)=V, (3,5)=V, (3,6)=TR
    #   TR at (3,6): from (0,-1), exit (1,0)=right
    # (4,6)=H, (5,6)=H, (6,6)=H, (7,6)=H -> (8,6)=drain
    #   Wait, (7,6) exits right to (8,6). But drain is on the border at x=8.
    #   Grid is 9 wide so border is at x=0 and x=8. (8,6) is border. Drain there.
    #   H at (7,6): from (-1,0), exit (1,0) -> (8,6)=drain. Correct!
    # ------------------------------------------------------------------
    {
        "name": "S-Curve",
        "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "source": (0, 2, 1, 0),
        "drain": (8, 6),
        "fixed_pipes": {},
        "placeable": {
            (1, 2), (2, 2), (3, 2),
            (3, 3), (3, 4), (3, 5), (3, 6),
            (4, 6), (5, 6), (6, 6), (7, 6),
        },
    },

    # ------------------------------------------------------------------
    # L7: "Maze Run" (9x9)
    # Source top at (1,0) flowing down, drain bottom at (7,8).
    # Walls create a maze. Route with multiple turns.
    # Walls block direct paths.
    # Route: down from (1,1), right, down, right, down to drain.
    # Solution:
    #   (1,1)=BR from (0,-1)="from up". BR={(0,1),(1,0)}. (0,-1) NOT in BR!
    #   Need up+right or up+down. Since we go down first then turn:
    #   (1,1)=V, (1,2)=V, (1,3)=TR
    #     TR at (1,3): from (0,-1). TR={(0,-1),(1,0)}. Yes! Exit=(1,0)=right.
    #   (2,3)=H, (3,3)=H, (4,3)=BL
    #     BL at (4,3): from (-1,0). BL={(0,1),(-1,0)}. Yes! Exit=(0,1)=down.
    #   (4,4)=V, (4,5)=TR
    #     TR at (4,5): from (0,-1). TR={(0,-1),(1,0)}. Yes! Exit=(1,0)=right.
    #   (5,5)=H, (6,5)=H, (7,5)=BL
    #     BL at (7,5): from (-1,0). BL={(0,1),(-1,0)}. Yes! Exit=(0,1)=down.
    #   (7,6)=V, (7,7)=V -> exits down to (7,8)=drain. Correct!
    #
    # Walls: block shortcuts
    # ------------------------------------------------------------------
    {
        "name": "Maze Run",
        "grid_w": 9, "grid_h": 9,
        "walls": {
            (2, 1), (3, 1), (4, 1), (5, 1),
            (2, 2),
            (1, 4), (2, 4), (3, 4),
            (5, 4),
            (5, 6), (6, 6),
            (6, 7),
        },
        "source": (1, 0, 0, 1),
        "drain": (7, 8),
        "fixed_pipes": {},
        "placeable": {
            (1, 1), (1, 2), (1, 3),
            (2, 3), (3, 3), (4, 3),
            (4, 4), (4, 5),
            (5, 5), (6, 5), (7, 5),
            (7, 6), (7, 7),
        },
    },

    # ------------------------------------------------------------------
    # L8: "Guided Path" (9x9)
    # Source left at (0,2) flowing right, drain right at (8,6).
    # Fixed pipes guide part of the route; player fills the rest.
    # Fixed: (1,2)=H, (2,2)=H, (3,2)=BL (goes down)
    #   BL at (3,2): from (-1,0). BL={(0,1),(-1,0)}. Yes! Exit=(0,1)=down.
    # Fixed: (3,3)=V, (3,4)=TR (goes right)
    #   TR at (3,4): from (0,-1). TR={(0,-1),(1,0)}. Yes! Exit=(1,0)=right.
    # Player: (4,4)=H, (5,4)=H, (6,4)=BL
    #   BL at (6,4): from (-1,0). BL={(0,1),(-1,0)}. Yes! Exit=(0,1)=down.
    # Player: (6,5)=V, (6,6)=TR
    #   TR at (6,6): from (0,-1). TR={(0,-1),(1,0)}. Yes! Exit=(1,0)=right.
    # Player: (7,6)=H -> (8,6)=drain. Correct!
    # ------------------------------------------------------------------
    {
        "name": "Guided Path",
        "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "source": (0, 2, 1, 0),
        "drain": (8, 6),
        "fixed_pipes": {
            (1, 2): P_HORIZ,
            (2, 2): P_HORIZ,
            (3, 2): P_BL,
            (3, 3): P_VERT,
            (3, 4): P_TR,
        },
        "placeable": {
            (4, 4), (5, 4), (6, 4),
            (6, 5), (6, 6),
            (7, 6),
        },
    },

    # ------------------------------------------------------------------
    # L9: "Tight Squeeze" (9x9)
    # Source top at (4,0) flowing down, drain bottom at (4,8).
    # Walls block column 4 rows 3-4, forcing a detour right then back.
    # Route: down col 4 to (4,2), turn right, go down col 6, turn left,
    #   back to col 4, then down to drain.
    # Solution:
    #   (4,1)=V  from (0,-1). V={(0,-1),(0,1)}. Exit=(0,1)=down.
    #   (4,2)=TR from (0,-1). TR={(0,-1),(1,0)}. Exit=(1,0)=right.
    #   (5,2)=H  from (-1,0). H={(-1,0),(1,0)}. Exit=(1,0)=right.
    #   (6,2)=BL from (-1,0). BL={(0,1),(-1,0)}. Exit=(0,1)=down.
    #   (6,3)=V  from (0,-1). V={(0,-1),(0,1)}. Exit=(0,1)=down.
    #   (6,4)=V  from (0,-1). V={(0,-1),(0,1)}. Exit=(0,1)=down.
    #   (6,5)=TL from (0,-1). TL={(0,-1),(-1,0)}. Exit=(-1,0)=left.
    #   (5,5)=H  from (1,0). H={(-1,0),(1,0)}. Exit=(-1,0)=left.
    #   (4,5)=BR from (1,0). BR={(0,1),(1,0)}. Exit=(0,1)=down.
    #   (4,6)=V  from (0,-1). V={(0,-1),(0,1)}. Exit=(0,1)=down.
    #   (4,7)=V  from (0,-1). V={(0,-1),(0,1)}. Exit=(0,1)=down -> (4,8)=drain.
    #
    # Walls: (4,3),(4,4) block straight path. (3,2),(3,3) prevent left shortcuts.
    # ------------------------------------------------------------------
    {
        "name": "Tight Squeeze",
        "grid_w": 9, "grid_h": 9,
        "walls": {
            (4, 3), (4, 4),
            (3, 2), (3, 3),
            (5, 4),
        },
        "source": (4, 0, 0, 1),
        "drain": (4, 8),
        "fixed_pipes": {},
        "placeable": {
            (4, 1), (4, 2),
            (5, 2), (6, 2),
            (6, 3), (6, 4), (6, 5),
            (5, 5), (4, 5),
            (4, 6), (4, 7),
        },
    },

    # ------------------------------------------------------------------
    # L10: "Grand Puzzle" (11x11)
    # Source top-left at (0,3) flowing right, drain bottom-right at (10,7).
    # Multiple walls and pre-placed pipes. Complex route.
    # Route: right along row 3, turn down at (5,3), down to (5,5),
    #   turn right at (5,5), right to (7,5), turn down at (7,5),
    #   down to (7,7), turn right to drain.
    # Solution:
    #   (1,3)=H, (2,3)=H from (-1,0), exit (1,0)
    #   (3,3)=H (fixed)
    #   (4,3)=H, (5,3)=BL
    #     BL at (5,3): from (-1,0). BL={(0,1),(-1,0)}. Yes! Exit=(0,1)=down.
    #   (5,4)=V (fixed)
    #   (5,5)=TR from (0,-1). TR={(0,-1),(1,0)}. Yes! Exit=(1,0)=right.
    #   (6,5)=H (fixed)
    #   (7,5)=BL from (-1,0). BL={(0,1),(-1,0)}. Yes! Exit=(0,1)=down.
    #   (7,6)=V
    #   (7,7)=TR from (0,-1). TR={(0,-1),(1,0)}. Yes! Exit=(1,0)=right.
    #   (8,7)=H, (9,7)=H -> (10,7)=drain. Correct!
    # ------------------------------------------------------------------
    {
        "name": "Grand Puzzle",
        "grid_w": 11, "grid_h": 11,
        "walls": {
            (3, 4), (4, 4),
            (6, 3), (6, 4),
            (4, 5), (4, 6),
            (8, 5), (8, 6),
            (6, 7), (6, 8),
            (3, 6), (3, 7),
        },
        "source": (0, 3, 1, 0),
        "drain": (10, 7),
        "fixed_pipes": {
            (3, 3): P_HORIZ,
            (5, 4): P_VERT,
            (6, 5): P_HORIZ,
        },
        "placeable": {
            (1, 3), (2, 3), (4, 3), (5, 3),
            (5, 5),
            (7, 5), (7, 6), (7, 7),
            (8, 7), (9, 7),
        },
    },
]


class Rd01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        # Draw grid cells (empty/walls)
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                    continue
                if (gx, gy) in g.walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Draw pipes
        for (px_g, py_g), ptype in g.pipes.items():
            if ptype == P_EMPTY:
                continue
            px, py = ox + px_g * CELL, oy + py_g * CELL
            if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                continue
            c = C_BLUE if (px_g, py_g) in g.water_cells else C_GRAY
            # Fixed pipes get a slightly different shade when not watered
            if (px_g, py_g) in g.fixed_pipes and (px_g, py_g) not in g.water_cells:
                c = C_AZURE
            conns = PIPE_CONN.get(ptype, set())
            # Draw center hub
            frame[py + 1:py + 3, px + 1:px + 3] = c
            # Draw connection arms
            for cdx, cdy in conns:
                if cdx == -1:
                    frame[py + 1:py + 3, px:px + 1] = c
                if cdx == 1:
                    frame[py + 1:py + 3, px + 3:px + 4] = c
                if cdy == -1:
                    frame[py:py + 1, px + 1:px + 3] = c
                if cdy == 1:
                    frame[py + 3:py + 4, px + 1:px + 3] = c

        # Draw source
        sx, sy, _, _ = g.source
        px, py = ox + sx * CELL, oy + sy * CELL
        if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
            frame[py:py + CELL, px:px + CELL] = C_RED

        # Draw drain
        dx_g, dy_g = g.drain
        px, py = ox + dx_g * CELL, oy + dy_g * CELL
        if 0 <= px and px + CELL <= 64 and 0 <= py and py + CELL <= 64:
            frame[py:py + CELL, px:px + CELL] = C_GOLD

        # Draw cursor (lime border outline)
        cx, cy = g.cursor_x, g.cursor_y
        px, py = ox + cx * CELL, oy + cy * CELL
        for i in range(CELL):
            if 0 <= py + i < 64 and 0 <= px < 64:
                frame[py + i, px] = C_LIME
            if 0 <= py + i < 64 and 0 <= px + CELL - 1 < 64:
                frame[py + i, px + CELL - 1] = C_LIME
            if 0 <= px + i < 64 and 0 <= py < 64:
                frame[py, px + i] = C_LIME
            if 0 <= px + i < 64 and 0 <= py + CELL - 1 < 64:
                frame[py + CELL - 1, px + i] = C_LIME

        return frame


class Rd01(ARCBaseGame):
    def __init__(self):
        self.display = Rd01Display(self)
        levels = []
        for d in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=d,
                name=d["name"],
            ))
        super().__init__(
            "rd01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4, 5],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]

        # Build wall set: border + interior walls
        self.walls = set()
        for x in range(self.grid_w):
            self.walls.add((x, 0))
            self.walls.add((x, self.grid_h - 1))
        for y in range(self.grid_h):
            self.walls.add((0, y))
            self.walls.add((self.grid_w - 1, y))
        # Add interior walls from level data
        for w in d.get("walls", set()):
            self.walls.add(w)

        # Remove source and drain from walls (they sit on the border)
        self.source = d["source"]
        self.drain = d["drain"]
        self.walls.discard((self.source[0], self.source[1]))
        self.walls.discard(self.drain)

        self.fixed_pipes = dict(d.get("fixed_pipes", {}))
        self.placeable = set(d.get("placeable", set()))

        # Initialize pipes with fixed pipes
        self.pipes = dict(self.fixed_pipes)

        # Place cursor at first placeable cell (sorted for determinism)
        if self.placeable:
            start = sorted(self.placeable)[0]
            self.cursor_x, self.cursor_y = start
        else:
            self.cursor_x, self.cursor_y = 1, 1

        self.water_cells = set()
        self._trace_water()

    def _trace_water(self):
        """Trace water flow from source through connected pipes."""
        self.water_cells = set()
        sx, sy, fdx, fdy = self.source
        x, y = sx + fdx, sy + fdy
        from_dir = (-fdx, -fdy)
        visited = set()

        while True:
            if (x, y) in visited:
                break
            if x < 0 or y < 0 or x >= self.grid_w or y >= self.grid_h:
                break
            if (x, y) in self.walls:
                break

            # Check if this is the drain (water reached it via pipe connection)
            if (x, y) == self.drain:
                self.water_cells.add((x, y))
                break

            ptype = self.pipes.get((x, y), P_EMPTY)
            if ptype == P_EMPTY:
                break

            conns = PIPE_CONN.get(ptype, set())
            if from_dir not in conns:
                break

            visited.add((x, y))
            self.water_cells.add((x, y))

            # Find exit direction (the other connection)
            exit_dirs = conns - {from_dir}
            if not exit_dirs:
                break

            edx, edy = next(iter(exit_dirs))
            x, y = x + edx, y + edy
            from_dir = (-edx, -edy)

    def _check_win(self):
        """Check if water has reached the drain."""
        return self.drain in self.water_cells

    def step(self):
        aid = self.action.id.value

        if aid in (1, 2, 3, 4):
            # Move cursor
            dx, dy = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}[aid]
            nx, ny = self.cursor_x + dx, self.cursor_y + dy
            # Allow cursor movement within interior cells (not on border walls)
            if 1 <= nx <= self.grid_w - 2 and 1 <= ny <= self.grid_h - 2:
                if (nx, ny) not in self.walls:
                    self.cursor_x, self.cursor_y = nx, ny
            self.complete_action()
            return

        if aid == 5:
            # Cycle pipe type at cursor position
            pos = (self.cursor_x, self.cursor_y)
            if pos in self.placeable and pos not in self.fixed_pipes:
                cur = self.pipes.get(pos, P_EMPTY)
                ci = PIPE_CYCLE.index(cur)
                new_type = PIPE_CYCLE[(ci + 1) % len(PIPE_CYCLE)]
                if new_type == P_EMPTY:
                    self.pipes.pop(pos, None)
                else:
                    self.pipes[pos] = new_type
                self._trace_water()
                if self._check_win():
                    self.next_level()
            self.complete_action()
            return

        self.complete_action()
