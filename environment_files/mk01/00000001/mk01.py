# Morph Knight - A chess-themed puzzle game where capturing pieces changes your movement
#
# Click to move. Capture enemy pieces to absorb their movement type.
# Avoid patrolling guards (pink). Reach the gold goal to complete each level.
# Click your own square to wait (guards still move).

import numpy as np
from typing import List, Dict, Tuple, Optional

from arcengine import (
    ARCBaseGame,
    Camera,
    Level,
    RenderableUserDisplay,
    Sprite,
)

# --- Colors ---
C_BLACK = 0
C_GRAY = 3
C_MID = 5
C_PINK = 6
C_AZURE = 8
C_GOLD = 11
C_RED = 12
C_LIME = 14
C_WHITE = 15

# --- Piece types ---
KING = 0
ROOK = 1
BISHOP = 2
KNIGHT = 3

PIECE_PIXELS = {
    KING: [
        [-1, -1,  0, -1, -1],
        [-1,  0,  0,  0, -1],
        [ 0,  0,  0,  0,  0],
        [-1,  0,  0,  0, -1],
        [-1,  0,  0,  0, -1],
    ],
    ROOK: [
        [ 0, -1,  0, -1,  0],
        [ 0,  0,  0,  0,  0],
        [-1,  0,  0,  0, -1],
        [-1,  0,  0,  0, -1],
        [ 0,  0,  0,  0,  0],
    ],
    BISHOP: [
        [-1, -1,  0, -1, -1],
        [-1,  0,  0,  0, -1],
        [-1,  0,  0,  0, -1],
        [ 0,  0,  0,  0,  0],
        [-1,  0,  0,  0, -1],
    ],
    KNIGHT: [
        [-1,  0,  0, -1, -1],
        [ 0,  0,  0,  0, -1],
        [-1,  0,  0,  0, -1],
        [-1, -1,  0,  0, -1],
        [-1,  0,  0,  0,  0],
    ],
}

# Guard sprite (pawn shape)
GUARD_PIXELS = [
    [-1, -1,  0, -1, -1],
    [-1,  0,  0,  0, -1],
    [-1, -1,  0, -1, -1],
    [-1,  0,  0,  0, -1],
    [ 0,  0,  0,  0,  0],
]

CELL = 5


def _recolor(pixels, color):
    return [[color if p == 0 else p for p in row] for row in pixels]


def _make_board(grid_w, grid_h, walls, ox, oy):
    sprites = []
    for gy in range(grid_h):
        for gx in range(grid_w):
            px, py = ox + gx * CELL, oy + gy * CELL
            if (gx, gy) in walls:
                pix = [[C_BLACK] * CELL for _ in range(CELL)]
                sprites.append(Sprite(pixels=pix, name=f"w_{gx}_{gy}",
                                      x=px, y=py, layer=-5, visible=True, collidable=False))
            else:
                c = C_WHITE if (gx + gy) % 2 == 0 else C_MID
                pix = [[c] * CELL for _ in range(CELL)]
                sprites.append(Sprite(pixels=pix, name=f"f_{gx}_{gy}",
                                      x=px, y=py, layer=-10, visible=True, collidable=False))
    return sprites


def _make_piece(piece_type, color, gx, gy, ox, oy, tags):
    pix = _recolor(PIECE_PIXELS[piece_type], color)
    return Sprite(pixels=pix, name=tags[0], x=ox + gx * CELL, y=oy + gy * CELL,
                  layer=5, visible=True, collidable=False, tags=tags)


def _make_guard(idx, gx, gy, ox, oy):
    pix = _recolor(GUARD_PIXELS, C_PINK)
    return Sprite(pixels=pix, name=f"guard_{idx}",
                  x=ox + gx * CELL, y=oy + gy * CELL,
                  layer=6, visible=True, collidable=False, tags=[f"guard_{idx}", "guard"])


def _make_goal(gx, gy, ox, oy):
    pix = [
        [-1, C_GOLD, C_GOLD, C_GOLD, -1],
        [C_GOLD, C_GOLD, C_GOLD, C_GOLD, C_GOLD],
        [C_GOLD, C_GOLD, C_GOLD, C_GOLD, C_GOLD],
        [C_GOLD, C_GOLD, C_GOLD, C_GOLD, C_GOLD],
        [-1, C_GOLD, C_GOLD, C_GOLD, -1],
    ]
    return Sprite(pixels=pix, name="goal", x=ox + gx * CELL, y=oy + gy * CELL,
                  layer=-2, visible=True, collidable=False, tags=["goal"])


# =============================================================================
# Level definitions
# guards: list of {gx, gy, dx, dy} — each guard bounces off walls
# =============================================================================

def _border(w, h):
    return ({(x, 0) for x in range(w)} | {(x, h - 1) for x in range(w)} |
            {(0, y) for y in range(h)} | {(w - 1, y) for y in range(h)})


LEVELS = [
    # --- Phase 1: Pure piece mechanics (no guards) ---

    # L1: Tutorial — capture rook, click to goal
    {
        "name": "Capture",
        "grid_w": 6, "grid_h": 6,
        "walls": _border(6, 6),
        "enemies": [(ROOK, 3, 1)],
        "player_start": (1, 1),
        "goal_pos": (3, 4),
        "guards": [],
    },
    # L2: Must become bishop for diagonal-only goal
    {
        "name": "Fork",
        "grid_w": 8, "grid_h": 8,
        "walls": _border(8, 8) | {(5, 6), (6, 5)},
        "enemies": [(ROOK, 1, 3), (BISHOP, 3, 3)],
        "player_start": (1, 1),
        "goal_pos": (6, 6),
        "guards": [],
    },
    # L3: Rook to cross, then knight to jump wall
    {
        "name": "Sequence",
        "grid_w": 10, "grid_h": 6,
        "walls": _border(10, 6) | {(5, 1), (5, 2), (5, 3)},
        "enemies": [(ROOK, 2, 2), (KNIGHT, 4, 1)],
        "player_start": (1, 1),
        "goal_pos": (8, 1),
        "guards": [],
    },
    # L4: Pure knight navigation
    {
        "name": "Knight's Gambit",
        "grid_w": 9, "grid_h": 9,
        "walls": _border(9, 9) | {(4, 4), (6, 6)},
        "enemies": [(KNIGHT, 1, 2)],
        "player_start": (1, 1),
        "goal_pos": (7, 7),
        "guards": [],
    },
    # L5: Chain captures king→rook→bishop→knight→goal
    {
        "name": "Gauntlet",
        "grid_w": 12, "grid_h": 7,
        "walls": _border(12, 7) | {(4, 1), (4, 2), (4, 4), (4, 5)},
        "enemies": [(ROOK, 2, 3), (BISHOP, 6, 3), (KNIGHT, 8, 5)],
        "player_start": (1, 3),
        "goal_pos": (10, 4),
        "guards": [],
    },

    # --- Phase 2: Moving guards ---

    # L6: One guard patrols column, blocks rook slide
    {
        "name": "Sentry",
        "grid_w": 8, "grid_h": 6,
        "walls": _border(8, 6),
        "enemies": [(ROOK, 3, 3)],
        "player_start": (1, 3),
        "goal_pos": (6, 3),
        "guards": [{"gx": 5, "gy": 1, "dx": 0, "dy": 1}],
    },
    # L7: Two guards out of sync — must wait for both to clear
    {
        "name": "Crossfire",
        "grid_w": 10, "grid_h": 6,
        "walls": _border(10, 6),
        "enemies": [(ROOK, 3, 3)],
        "player_start": (1, 3),
        "goal_pos": (8, 3),
        "guards": [{"gx": 5, "gy": 2, "dx": 0, "dy": 1},
                    {"gx": 7, "gy": 1, "dx": 0, "dy": 1}],
    },
    # L8: Guard blocks capture chain — rook then bishop with timing
    {
        "name": "Guarded Capture",
        "grid_w": 8, "grid_h": 8,
        "walls": _border(8, 8) | {(5, 6), (6, 5)},
        "enemies": [(ROOK, 1, 4), (BISHOP, 4, 4)],
        "player_start": (1, 1),
        "goal_pos": (6, 6),
        "guards": [{"gx": 3, "gy": 1, "dx": 0, "dy": 1}],
    },
    # L9: Knight maze with guard patrol
    {
        "name": "Knight's Escape",
        "grid_w": 9, "grid_h": 9,
        "walls": _border(9, 9) | {(4, 4), (6, 6)},
        "enemies": [(KNIGHT, 2, 3)],
        "player_start": (1, 1),
        "goal_pos": (7, 7),
        "guards": [{"gx": 5, "gy": 4, "dx": 0, "dy": -1}],
    },
    # L10: Grand finale — chain captures + two guards
    # Rook through gap(4,3) → bishop → diag to knight(7,2) → jump through gap(8,4) → goal
    {
        "name": "Grandmaster",
        "grid_w": 12, "grid_h": 8,
        "walls": _border(12, 8) | {(4, 1), (4, 2), (4, 4), (4, 5), (4, 6),
                                    (8, 1), (8, 2), (8, 3), (8, 5), (8, 6)},
        "enemies": [(ROOK, 2, 3), (BISHOP, 6, 3), (KNIGHT, 7, 2)],
        "player_start": (1, 3),
        "goal_pos": (10, 5),
        "guards": [{"gx": 5, "gy": 2, "dx": 0, "dy": 1},
                    {"gx": 9, "gy": 1, "dx": 0, "dy": 1}],
    },
]

# =============================================================================
# Display
# =============================================================================

class Display(RenderableUserDisplay):
    def __init__(self):
        super().__init__()
        self.piece_type = KING

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        f = frame.copy()
        c = C_AZURE
        if self.piece_type == KING:
            f[0, 1] = c; f[1, 0] = c; f[1, 1] = c; f[1, 2] = c
        elif self.piece_type == ROOK:
            f[0, 0] = c; f[0, 2] = c; f[1, 0] = c; f[1, 1] = c; f[1, 2] = c
        elif self.piece_type == BISHOP:
            f[0, 1] = c; f[1, 0] = c; f[1, 1] = c; f[1, 2] = c
        elif self.piece_type == KNIGHT:
            f[0, 0] = c; f[0, 1] = c; f[1, 0] = c
        return f


# =============================================================================
# Game
# =============================================================================

class Mk01(ARCBaseGame):
    def __init__(self):
        self.display = Display()
        levels = []

        for ldef in LEVELS:
            gw, gh = ldef["grid_w"], ldef["grid_h"]
            ox = (64 - gw * CELL) // 2
            oy = (64 - gh * CELL) // 2

            board = _make_board(gw, gh, ldef["walls"], ox, oy)
            enemies = []
            for i, (ptype, ex, ey) in enumerate(ldef["enemies"]):
                enemies.append(_make_piece(ptype, C_RED, ex, ey, ox, oy,
                                           tags=[f"enemy_{i}", "enemy", f"ptype_{ptype}"]))
            guard_sprites = []
            for i, gd in enumerate(ldef["guards"]):
                guard_sprites.append(_make_guard(i, gd["gx"], gd["gy"], ox, oy))

            sx, sy = ldef["player_start"]
            player = _make_piece(KING, C_AZURE, sx, sy, ox, oy, tags=["player"])
            gx, gy = ldef["goal_pos"]
            goal = _make_goal(gx, gy, ox, oy)

            levels.append(Level(
                sprites=board + [goal] + enemies + guard_sprites + [player],
                grid_size=(64, 64),
                data={"grid_w": gw, "grid_h": gh, "ox": ox, "oy": oy,
                      "walls": ldef["walls"],
                      "guard_defs": ldef["guards"]},
                name=ldef["name"],
            ))

        super().__init__(
            "mk01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [6],
        )
        self.piece_type = KING
        self._valid_moves = {}
        self._guard_state = []  # list of [(gx, gy), (dx, dy)]
        self._init_level()

    # --- Coordinate helpers ---

    def _g2p(self, gx, gy):
        ox, oy = self.current_level.get_data("ox"), self.current_level.get_data("oy")
        return ox + gx * CELL, oy + gy * CELL

    def _p2g(self, px, py):
        ox, oy = self.current_level.get_data("ox"), self.current_level.get_data("oy")
        return (px - ox) // CELL, (py - oy) // CELL

    # --- Board queries ---

    def _is_wall(self, gx, gy):
        gw = self.current_level.get_data("grid_w")
        gh = self.current_level.get_data("grid_h")
        if gx < 0 or gy < 0 or gx >= gw or gy >= gh:
            return True
        return (gx, gy) in self.current_level.get_data("walls")

    def _is_blocked(self, gx, gy):
        """Wall or guard at position."""
        if self._is_wall(gx, gy):
            return True
        for (ggx, ggy), _ in self._guard_state:
            if ggx == gx and ggy == gy:
                return True
        return False

    def _is_goal(self, gx, gy):
        goal = self.current_level.get_sprites_by_tag("goal")[0]
        return (gx, gy) == self._p2g(goal.x, goal.y)

    def _enemy_at(self, gx, gy):
        px, py = self._g2p(gx, gy)
        for s in self.current_level.get_sprites_by_tag("enemy"):
            if s.x == px and s.y == py and s.is_visible:
                for tag in s.tags:
                    if tag.startswith("ptype_"):
                        return s, int(tag.split("_")[1])
        return None

    # --- Valid moves ---

    def _get_valid_moves(self):
        player = self.current_level.get_sprites_by_tag("player")[0]
        pgx, pgy = self._p2g(player.x, player.y)
        moves = {}

        if self.piece_type == KING:
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                nx, ny = pgx + dx, pgy + dy
                if not self._is_blocked(nx, ny):
                    moves[(nx, ny)] = self._enemy_at(nx, ny) is not None

        elif self.piece_type == ROOK:
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                cx, cy = pgx, pgy
                while True:
                    cx, cy = cx + dx, cy + dy
                    if self._is_blocked(cx, cy):
                        break
                    is_cap = self._enemy_at(cx, cy) is not None
                    moves[(cx, cy)] = is_cap
                    if is_cap:
                        break

        elif self.piece_type == BISHOP:
            for dx, dy in [(-1, -1), (1, 1), (-1, 1), (1, -1)]:
                cx, cy = pgx, pgy
                while True:
                    cx, cy = cx + dx, cy + dy
                    if self._is_blocked(cx, cy):
                        break
                    is_cap = self._enemy_at(cx, cy) is not None
                    moves[(cx, cy)] = is_cap
                    if is_cap:
                        break

        elif self.piece_type == KNIGHT:
            for dx, dy in [(-1, -2), (1, -2), (-1, 2), (1, 2),
                           (-2, -1), (-2, 1), (2, -1), (2, 1)]:
                nx, ny = pgx + dx, pgy + dy
                if not self._is_blocked(nx, ny):
                    moves[(nx, ny)] = self._enemy_at(nx, ny) is not None

        return moves

    # --- Guards ---

    def _init_guards(self):
        guard_defs = self.current_level.get_data("guard_defs")
        self._guard_state = []
        for gd in guard_defs:
            self._guard_state.append([(gd["gx"], gd["gy"]),
                                      (gd["dx"], gd["dy"])])

    def _move_guards(self):
        """Move all guards one step. Bounce off walls."""
        for i, (pos, direction) in enumerate(self._guard_state):
            gx, gy = pos
            dx, dy = direction
            nx, ny = gx + dx, gy + dy
            if self._is_wall(nx, ny):
                # Bounce: reverse direction, stay put
                self._guard_state[i][1] = (-dx, -dy)
            else:
                self._guard_state[i][0] = (nx, ny)
                # Update sprite position
                guard_sprites = self.current_level.get_sprites_by_tag(f"guard_{i}")
                if guard_sprites:
                    guard_sprites[0].set_position(*self._g2p(nx, ny))

    def _check_guard_collision(self):
        """Check if any guard is on the player's square."""
        player = self.current_level.get_sprites_by_tag("player")[0]
        pgx, pgy = self._p2g(player.x, player.y)
        for (gx, gy), _ in self._guard_state:
            if gx == pgx and gy == pgy:
                return True
        return False

    # --- Piece management ---

    def _set_piece(self, ptype):
        self.piece_type = ptype
        self.display.piece_type = ptype
        player = self.current_level.get_sprites_by_tag("player")[0]
        player.pixels = np.array(_recolor(PIECE_PIXELS[ptype], C_AZURE), dtype=np.int8)

    # --- Level management ---

    def _init_level(self):
        self.piece_type = KING
        self.display.piece_type = KING
        self._init_guards()
        self._valid_moves = self._get_valid_moves()

    def on_set_level(self, level):
        self._init_level()

    # --- Main game loop ---

    def step(self) -> None:
        if self.action.id.value != 6:
            self.complete_action()
            return

        cx = self.action.data.get("x", 0)
        cy = self.action.data.get("y", 0)
        ox = self.current_level.get_data("ox")
        oy = self.current_level.get_data("oy")
        gx = (cx - ox) // CELL
        gy = (cy - oy) // CELL

        # Check if clicking own square (wait)
        player = self.current_level.get_sprites_by_tag("player")[0]
        pgx, pgy = self._p2g(player.x, player.y)
        is_wait = (gx == pgx and gy == pgy)

        if not is_wait and (gx, gy) not in self._valid_moves:
            self.complete_action()
            return

        # Execute move (skip if waiting)
        if not is_wait:
            is_cap = self._valid_moves.get((gx, gy), False)
            if is_cap:
                enemy = self._enemy_at(gx, gy)
                if enemy:
                    enemy[0].set_visible(False)
                    self._set_piece(enemy[1])
            player.set_position(*self._g2p(gx, gy))

        # Check win before guards move
        if not is_wait and self._is_goal(gx, gy):
            self.next_level()
            self.complete_action()
            return

        # Move guards and check collision
        self._move_guards()
        if self._check_guard_collision():
            self.lose()
            self.complete_action()
            return

        self._valid_moves = self._get_valid_moves()
        self.complete_action()
