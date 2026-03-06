"""
sp01 - Shatter Push  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Move up
ACTION2 (v): Move down
ACTION3 (<): Move left
ACTION4 (>): Move right

A top-down block-pushing puzzle. Push blocks into pits to fill them.
Push a block into a wall to shatter it into two smaller fragments that
slide perpendicular. Sticky blocks merge when pushed together.
Reach the goal after filling all pits.

Fully deterministic - no random elements.
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# --- Colours (ARC palette) ---
C_BLACK  = 0
C_DBLUE  = 1
C_GREEN  = 2
C_GRAY   = 3
C_YELLOW = 4
C_MID    = 5
C_PINK   = 6
C_ORANGE = 7
C_AZURE  = 8
C_BLUE   = 9
C_GOLD   = 11
C_RED    = 12
C_LIME   = 14
C_WHITE  = 15

# Cell size in pixels
CELL = 4

# Direction map: action_id -> (dx, dy) in grid coords
_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

# Perpendicular directions for shattering
_PERP = {
    (0, -1): [(-1, 0), (1, 0)],   # push up   -> fragments go left, right
    (0, 1):  [(-1, 0), (1, 0)],   # push down -> fragments go left, right
    (-1, 0): [(0, -1), (0, 1)],   # push left -> fragments go up, down
    (1, 0):  [(0, -1), (0, 1)],   # push right-> fragments go up, down
}

# Tile types
T_FLOOR = 0
T_WALL  = 1
T_PIT   = 2
T_GOAL  = 3

# Block types
B_NORMAL = 0   # size 2 - can shatter into 2 size-1 fragments
B_FRAG   = 1   # size 1 - fragment, fits small pits, can't shatter further
B_STICKY = 2   # size 2 - merges with adjacent sticky/normal when pushed into it
B_BIG    = 3   # size 3 - shatters into size-2 + size-1

# Pit sizes (what block size they accept: block.size >= pit.size to fill)
P_SMALL  = 1   # accepts any block
P_NORMAL = 2   # accepts normal/sticky/big blocks
P_BIG    = 3   # accepts big blocks only


# ========================================================================
# Level definitions
# ========================================================================
# Each level: grid dims, extra interior walls, player start, goal, blocks, pits.
# Border cells (x=0, x=w-1, y=0, y=h-1) are always walls.

LEVELS = [
    # L1: Tutorial - push one block into one pit, walk to goal.
    {
        "name": "First Push",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (1, 3),
        "goal": (5, 3),
        "blocks": [(3, 3, B_NORMAL)],
        "pits": [(4, 3, P_NORMAL)],
    },

    # L2: Two blocks, two pits from different directions.
    {
        "name": "Two Pits",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (1, 1),
        "goal": (5, 5),
        "blocks": [(3, 1, B_NORMAL), (1, 3, B_NORMAL)],
        "pits": [(5, 1, P_NORMAL), (1, 5, P_NORMAL)],
    },

    # L3: Push block right into east wall to shatter; fragments fill small pits.
    {
        "name": "Shatter",
        "grid_w": 8, "grid_h": 7,
        "walls": set(),
        "player": (1, 3),
        "goal": (6, 3),
        "blocks": [(4, 3, B_NORMAL)],
        "pits": [(6, 1, P_SMALL), (6, 5, P_SMALL)],
    },

    # L4: Push one block into pit, shatter the other against east wall.
    {
        "name": "Split Path",
        "grid_w": 9, "grid_h": 7,
        "walls": set(),
        "player": (1, 3),
        "goal": (7, 3),
        "blocks": [(3, 3, B_NORMAL), (5, 3, B_NORMAL)],
        "pits": [(4, 3, P_NORMAL), (7, 1, P_SMALL), (7, 5, P_SMALL)],
    },

    # L5: Push two sticky blocks together to merge, push into big pit.
    {
        "name": "Sticky Merge",
        "grid_w": 8, "grid_h": 7,
        "walls": set(),
        "player": (1, 3),
        "goal": (6, 3),
        "blocks": [(2, 3, B_STICKY), (4, 3, B_STICKY)],
        "pits": [(5, 3, P_BIG)],
    },

    # L6: Merge sticky blocks, shatter the merged BIG against east wall.
    {
        "name": "Fuse & Break",
        "grid_w": 9, "grid_h": 7,
        "walls": set(),
        "player": (1, 3),
        "goal": (7, 3),
        "blocks": [(3, 3, B_STICKY), (5, 3, B_STICKY)],
        "pits": [(7, 1, P_NORMAL), (7, 5, P_NORMAL)],
    },

    # L7: Two blocks on different rows, shatter each against east wall.
    {
        "name": "Double Shatter",
        "grid_w": 9, "grid_h": 9,
        "walls": set(),
        "player": (1, 4),
        "goal": (7, 4),
        "blocks": [(4, 2, B_NORMAL), (4, 6, B_NORMAL)],
        "pits": [(7, 1, P_SMALL), (7, 3, P_SMALL), (7, 5, P_SMALL), (7, 7, P_SMALL)],
    },

    # L8: Interior wall with gap; push block through pit, shatter second on far wall.
    {
        "name": "Chain React",
        "grid_w": 11, "grid_h": 9,
        "walls": {(5, 1), (5, 2), (5, 3), (5, 5), (5, 6), (5, 7)},
        "player": (1, 4),
        "goal": (9, 4),
        "blocks": [(3, 4, B_NORMAL), (7, 4, B_NORMAL)],
        "pits": [(5, 4, P_SMALL), (9, 2, P_SMALL), (9, 6, P_SMALL)],
    },

    # L9: Shatter one block against interior wall, push another through gap, shatter on far wall.
    {
        "name": "Precision",
        "grid_w": 11, "grid_h": 9,
        "walls": {(5, 1), (5, 2), (5, 3), (5, 5), (5, 6), (5, 7)},
        "player": (1, 4),
        "goal": (9, 4),
        "blocks": [(4, 2, B_NORMAL), (3, 4, B_NORMAL), (7, 4, B_NORMAL)],
        "pits": [(4, 1, P_SMALL), (4, 7, P_SMALL), (5, 4, P_SMALL),
                 (9, 2, P_SMALL), (9, 6, P_SMALL)],
    },

    # L10: Sticky merge + shatter + multiple pits across interior wall.
    {
        "name": "Grand Shatter",
        "grid_w": 13, "grid_h": 9,
        "walls": {(6, 1), (6, 2), (6, 3), (6, 5), (6, 6), (6, 7)},
        "player": (1, 4),
        "goal": (11, 4),
        "blocks": [(2, 4, B_STICKY), (4, 4, B_STICKY), (9, 4, B_NORMAL)],
        "pits": [(6, 4, P_BIG), (11, 2, P_SMALL), (11, 6, P_SMALL)],
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

class Display(RenderableUserDisplay):
    def __init__(self, game):
        super().__init__()
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        if not hasattr(g, 'grid'):
            return frame

        gw, gh = g.grid_w, g.grid_h
        ox = (64 - gw * CELL) // 2
        oy = (64 - gh * CELL) // 2

        frame[:, :] = C_BLACK

        # Tiles
        for gy in range(gh):
            for gx in range(gw):
                px, py = ox + gx * CELL, oy + gy * CELL
                tile = g.grid[gy][gx]
                if tile == T_WALL:
                    _fill(frame, px, py, C_GRAY)
                elif tile == T_PIT:
                    pit_size = g.pit_sizes.get((gx, gy), P_NORMAL)
                    col = C_DBLUE if pit_size == P_SMALL else (C_PINK if pit_size == P_BIG else C_BLUE)
                    _fill(frame, px, py, col)
                    _dot(frame, px, py, C_BLACK)
                elif tile == T_GOAL:
                    _fill(frame, px, py, C_GOLD)
                else:
                    _fill(frame, px, py, C_MID)

        # Blocks
        for bx, by, btype, bsize in g.blocks:
            px, py = ox + bx * CELL, oy + by * CELL
            if btype == B_STICKY:
                _fill(frame, px, py, C_ORANGE)
                _dot(frame, px, py, C_YELLOW)
            elif btype == B_FRAG:
                _fill(frame, px, py, C_LIME)
                _dot(frame, px, py, C_GREEN)
            elif btype == B_BIG:
                _fill(frame, px, py, C_RED)
                _dot(frame, px, py, C_ORANGE)
            else:
                _fill(frame, px, py, C_RED)
                _dot(frame, px, py, C_WHITE)

        # Player
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        _fill(frame, ppx, ppy, C_AZURE)
        _dot(frame, ppx, ppy, C_WHITE)

        return frame


def _fill(frame, px, py, color):
    """Fill a CELL x CELL block."""
    for dy in range(CELL):
        for dx in range(CELL):
            y, x = py + dy, px + dx
            if 0 <= y < 64 and 0 <= x < 64:
                frame[y, x] = color


def _dot(frame, px, py, color):
    """Draw a 2x2 dot in cell center."""
    cx, cy = px + CELL // 2, py + CELL // 2
    for dy in range(-1, 1):
        for dx in range(-1, 1):
            y, x = cy + dy, cx + dx
            if 0 <= y < 64 and 0 <= x < 64:
                frame[y, x] = color


# ========================================================================
# Game
# ========================================================================

class Sp01(ARCBaseGame):
    def __init__(self):
        self.display = Display(self)

        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))

        super().__init__(
            "sp01",
            levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4],
        )
        self._setup_level()

    def on_set_level(self, level):
        self._setup_level()

    def _setup_level(self):
        d = LEVELS[self.level_index]
        gw, gh = d["grid_w"], d["grid_h"]
        self.grid_w = gw
        self.grid_h = gh

        walls = _border(gw, gh) | d["walls"]
        self.grid = [[T_FLOOR] * gw for _ in range(gh)]
        for wx, wy in walls:
            if 0 <= wx < gw and 0 <= wy < gh:
                self.grid[wy][wx] = T_WALL

        gx, gy = d["goal"]
        self.grid[gy][gx] = T_GOAL
        self.goal_pos = (gx, gy)

        self.pit_sizes = {}
        for px_pos, py_pos, psize in d["pits"]:
            self.grid[py_pos][px_pos] = T_PIT
            self.pit_sizes[(px_pos, py_pos)] = psize

        self.px, self.py = d["player"]

        self.blocks = []
        for bx, by, btype in d["blocks"]:
            self.blocks.append([bx, by, btype, _block_size(btype)])

    # -- Queries ---

    def _is_wall(self, x, y):
        if x < 0 or y < 0 or x >= self.grid_w or y >= self.grid_h:
            return True
        return self.grid[y][x] == T_WALL

    def _block_at(self, x, y):
        for i, (bx, by, _bt, _bs) in enumerate(self.blocks):
            if bx == x and by == y:
                return i
        return -1

    def _is_pit(self, x, y):
        if x < 0 or y < 0 or x >= self.grid_w or y >= self.grid_h:
            return False
        return self.grid[y][x] == T_PIT

    def _all_pits_filled(self):
        for gy in range(self.grid_h):
            for gx in range(self.grid_w):
                if self.grid[gy][gx] == T_PIT:
                    return False
        return True

    # -- Push / shatter ---

    def _try_push_block(self, block_idx, dx, dy):
        bx, by, btype, bsize = self.blocks[block_idx]
        nx, ny = bx + dx, by + dy

        # Sticky merge
        other_idx = self._block_at(nx, ny)
        if other_idx >= 0:
            _obx, _oby, otype, osize = self.blocks[other_idx]
            if btype == B_STICKY and otype in (B_STICKY, B_NORMAL):
                new_size = bsize + osize
                new_type = B_BIG if new_size >= 3 else B_NORMAL
                for idx in sorted([block_idx, other_idx], reverse=True):
                    self.blocks.pop(idx)
                self.blocks.append([nx, ny, new_type, new_size])
                return True
            return False

        # Wall -> shatter
        if self._is_wall(nx, ny):
            return self._shatter_block(block_idx, dx, dy)

        # Pit -> fill (block consumed entirely if size >= pit size)
        if self._is_pit(nx, ny):
            pit_size = self.pit_sizes.get((nx, ny), P_NORMAL)
            if bsize >= pit_size:
                self.grid[ny][nx] = T_FLOOR
                del self.pit_sizes[(nx, ny)]
                self.blocks.pop(block_idx)
                return True
            else:
                # Too small to fill: block sits on the pit tile
                self.blocks[block_idx] = [nx, ny, btype, bsize]
                return True

        # Normal slide
        self.blocks[block_idx] = [nx, ny, btype, bsize]
        return True

    def _shatter_block(self, block_idx, dx, dy):
        bx, by, btype, bsize = self.blocks[block_idx]
        if bsize <= 1:
            return False  # fragments can't shatter

        self.blocks.pop(block_idx)
        perp_dirs = _PERP[(dx, dy)]
        frag_size = bsize // 2
        remainder = bsize - frag_size * 2

        for i, (pdx, pdy) in enumerate(perp_dirs):
            this_size = frag_size + (remainder if i == 0 else 0)
            if this_size <= 0:
                continue
            ftype = B_FRAG if this_size == 1 else B_NORMAL

            # Slide fragment from block's position in perpendicular direction
            final_x, final_y = bx, by
            cx, cy = bx + pdx, by + pdy
            consumed = False
            while True:
                if self._is_wall(cx, cy):
                    break
                if self._block_at(cx, cy) >= 0:
                    break
                if self._is_pit(cx, cy):
                    pit_size = self.pit_sizes.get((cx, cy), P_NORMAL)
                    if this_size >= pit_size:
                        self.grid[cy][cx] = T_FLOOR
                        del self.pit_sizes[(cx, cy)]
                        consumed = True
                        break
                    else:
                        final_x, final_y = cx, cy
                        break
                final_x, final_y = cx, cy
                cx, cy = cx + pdx, cy + pdy

            if not consumed:
                self.blocks.append([final_x, final_y, ftype, this_size])

        return True

    # -- Step ---

    def step(self) -> None:
        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        if self._is_wall(nx, ny):
            self.complete_action()
            return

        block_idx = self._block_at(nx, ny)
        if block_idx >= 0:
            if not self._try_push_block(block_idx, dx, dy):
                self.complete_action()
                return
            self.px, self.py = nx, ny
        elif self._is_pit(nx, ny):
            self.complete_action()
            return
        else:
            self.px, self.py = nx, ny

        if self._all_pits_filled() and (self.px, self.py) == self.goal_pos:
            self.next_level()

        self.complete_action()


def _block_size(btype):
    if btype == B_FRAG:
        return 1
    elif btype == B_BIG:
        return 3
    else:
        return 2  # B_NORMAL, B_STICKY
