import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0
C_GREEN = 2
C_GRAY = 3
C_MID = 5
C_ORANGE = 7
C_AZURE = 8
C_GOLD = 11
C_WHITE = 15

# ── Level Definitions ──────────────────────────────────────────────────
# Coordinates are (x, y) where x=column, y=row, origin top-left.
# Border walls (x=0, x=w-1, y=0, y=h-1) are auto-generated.
# Snake list is [head, body1, body2, ...] from head to tail.

LEVELS = [
    # L1: 6x6, snake length 1, 1 food, no obstacles
    # Playable: (1,1)-(4,4). Snake at (1,1), food at (4,4), exit at (4,1).
    # Solution: RRRD DDD → right 3, down 3 to food, then up 3 to exit = ~6 moves
    {
        "name": "First Bite",
        "grid_w": 6, "grid_h": 6,
        "walls": [],
        "snake": [(1, 1)],
        "food": [(4, 4)],
        "exit": (4, 1),
    },
    # L2: 7x7, snake length 2, 2 food items
    # Playable: (1,1)-(5,5). Snake head at (1,1), body at (1,2).
    # Food at (3,1) and (5,5). Exit at (5,1).
    # Solution: RR(eat food at 3,1) RDDDD(down to 5,5: need to go to col5,row5)
    # From (3,1) after eating: go RRDDDD to (5,5), then UUUUR to exit
    {
        "name": "Double Snack",
        "grid_w": 7, "grid_h": 7,
        "walls": [],
        "snake": [(1, 1), (1, 2)],
        "food": [(3, 1), (5, 5)],
        "exit": (5, 1),
    },
    # L3: 7x7, snake length 2, 3 food, some walls
    # Playable: (1,1)-(5,5). Walls create a small barrier.
    # Snake at (1,3), body at (1,4). Food at (3,1), (5,3), (3,5). Exit at (5,1).
    # Wall at (3,3) blocks center.
    {
        "name": "Walled Garden",
        "grid_w": 7, "grid_h": 7,
        "walls": [(3, 3), (3, 4)],
        "snake": [(1, 3), (1, 4)],
        "food": [(3, 1), (5, 3), (3, 5)],
        "exit": (5, 1),
    },
    # L4: 8x8, snake length 3, 3 food, walls creating corridors
    # Playable: (1,1)-(6,6). Horizontal wall with gaps.
    {
        "name": "Corridor Run",
        "grid_w": 8, "grid_h": 8,
        "walls": [(2, 3), (3, 3), (4, 3), (5, 3),   # horizontal wall row 3, gap at x=1 and x=6
                  (2, 5), (3, 5), (4, 5), (5, 5)],   # horizontal wall row 5, gap at x=1 and x=6
        "snake": [(1, 1), (2, 1), (3, 1)],
        "food": [(6, 2), (1, 4), (6, 6)],
        "exit": (6, 1),
    },
    # L5: 8x8, snake length 3, 4 food, tight passages
    # Playable: (1,1)-(6,6). Vertical walls creating narrow passages.
    {
        "name": "Tight Squeeze",
        "grid_w": 8, "grid_h": 8,
        "walls": [(3, 1), (3, 2), (3, 3),             # vertical wall at x=3, gap at y=4
                  (5, 4), (5, 5), (5, 6)],             # vertical wall at x=5, gap at y=3
        "snake": [(1, 1), (1, 2), (1, 3)],
        "food": [(2, 5), (4, 2), (6, 1), (4, 6)],
        "exit": (6, 6),
    },
    # L6: 9x9, snake length 3, 4 food, maze-like
    # Playable: (1,1)-(7,7).
    {
        "name": "Garden Maze",
        "grid_w": 9, "grid_h": 9,
        "walls": [(2, 2), (3, 2), (4, 2),             # top horizontal
                  (6, 2), (7, 2),                       # top right
                  (2, 4), (3, 4), (4, 4),              # middle horizontal
                  (6, 4), (6, 5), (6, 6),              # right vertical
                  (2, 6), (3, 6), (4, 6)],             # bottom horizontal
        "snake": [(1, 1), (1, 2), (1, 3)],
        "food": [(5, 1), (7, 3), (5, 5), (1, 7)],
        "exit": (7, 7),
    },
    # L7: 9x9, snake length 4, 5 food, must plan path carefully
    # Playable: (1,1)-(7,7).
    {
        "name": "Serpent's Path",
        "grid_w": 9, "grid_h": 9,
        "walls": [(3, 2), (3, 3), (3, 4),             # vertical wall left
                  (5, 1), (5, 2), (5, 3),              # vertical wall right top
                  (5, 5), (5, 6), (5, 7),              # vertical wall right bottom
                  (2, 6), (3, 6)],                      # bottom-left horizontal
        "snake": [(1, 1), (2, 1), (2, 2), (2, 3)],
        "food": [(1, 5), (4, 4), (7, 1), (7, 5), (4, 7)],
        "exit": (7, 7),
    },
    # L8: 10x10, snake length 4, 5 food, complex maze
    # Playable: (1,1)-(8,8).
    {
        "name": "Labyrinth",
        "grid_w": 10, "grid_h": 10,
        "walls": [(3, 1), (3, 2), (3, 3),             # top-left vertical
                  (5, 3), (6, 3), (7, 3),              # middle horizontal
                  (5, 5), (5, 6), (5, 7),              # center vertical
                  (7, 5), (7, 6), (7, 7),              # right vertical
                  (2, 5), (3, 5),                       # left-center horizontal
                  (2, 7), (3, 7)],                      # bottom-left horizontal
        "snake": [(1, 1), (1, 2), (1, 3), (1, 4)],
        "food": [(2, 2), (8, 2), (4, 4), (8, 6), (1, 8)],
        "exit": (8, 8),
    },
    # L9: 10x10, snake length 4, 6 food, very tight
    # Playable: (1,1)-(8,8).
    {
        "name": "Snake Pit",
        "grid_w": 10, "grid_h": 10,
        "walls": [(3, 2), (4, 2), (5, 2),             # row 2 wall
                  (7, 2), (7, 3), (7, 4),              # right vertical top
                  (2, 4), (3, 4), (4, 4),              # row 4 wall left
                  (5, 6), (6, 6), (7, 6),              # row 6 wall right
                  (2, 6), (3, 6),                       # row 6 wall left
                  (3, 8), (4, 8), (5, 8)],             # row 8 wall
        "snake": [(1, 1), (2, 1), (3, 1), (4, 1)],
        "food": [(6, 1), (8, 5), (1, 5), (4, 3), (8, 7), (1, 8)],
        "exit": (8, 8),
    },
    # L10: 12x10, snake length 5, 7 food, grand maze
    # Playable: (1,1)-(10,8). Open layout with scattered walls.
    {
        "name": "Grand Constrictor",
        "grid_w": 12, "grid_h": 10,
        "walls": [(4, 2), (5, 2),                       # row 2 short wall
                  (8, 3), (9, 3),                       # row 3 right wall
                  (3, 4), (3, 5),                       # left vertical
                  (6, 5), (7, 5),                       # center horizontal
                  (5, 7), (6, 7),                       # bottom center wall
                  (9, 7), (9, 8)],                      # right vertical lower
        "snake": [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)],
        "food": [(7, 1), (10, 2), (1, 4), (5, 4), (10, 5), (8, 8), (1, 8)],
        "exit": (10, 8),
    },
]


class Cn01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        # Draw floor and walls
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.wall_set:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Draw food (smaller, centered in cell)
        for fx, fy in g.remaining_food:
            px, py = ox + fx * CELL, oy + fy * CELL
            frame[py + 1:py + 3, px + 1:px + 3] = C_ORANGE

        # Draw exit
        ex, ey = g.exit_pos
        px, py = ox + ex * CELL, oy + ey * CELL
        if len(g.remaining_food) == 0:
            frame[py:py + CELL, px:px + CELL] = C_GOLD
        else:
            frame[py:py + CELL, px:px + CELL] = C_GRAY

        # Draw snake body (tail first so head draws on top)
        for i in range(len(g.snake) - 1, -1, -1):
            sx, sy = g.snake[i]
            px, py = ox + sx * CELL, oy + sy * CELL
            color = C_AZURE if i == 0 else C_GREEN
            frame[py:py + CELL, px:px + CELL] = color

        return frame


class Cn01(ARCBaseGame):
    def __init__(self):
        self.display = Cn01Display(self)
        self.grid_w = 6
        self.grid_h = 6
        self.wall_set = set()
        self.snake = [(1, 1)]
        self.remaining_food = set()
        self.exit_pos = (4, 1)
        levels = [
            Level(sprites=[], grid_size=(64, 64), data=d, name=d["name"])
            for d in LEVELS
        ]
        super().__init__(
            "cn01",
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

        # Build wall set: explicit walls + border
        self.wall_set = set(tuple(w) for w in d["walls"])
        for x in range(self.grid_w):
            self.wall_set.add((x, 0))
            self.wall_set.add((x, self.grid_h - 1))
        for y in range(self.grid_h):
            self.wall_set.add((0, y))
            self.wall_set.add((self.grid_w - 1, y))

        self.snake = [tuple(s) for s in d["snake"]]
        self.remaining_food = set(tuple(f) for f in d["food"])
        self.exit_pos = tuple(d["exit"])

    def step(self):
        aid = self.action.id.value
        direction_map = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}
        delta = direction_map.get(aid)
        if delta is None:
            self.complete_action()
            return

        dx, dy = delta
        hx, hy = self.snake[0]
        nx, ny = hx + dx, hy + dy

        # Wall collision: block the move (no penalty)
        if (nx, ny) in self.wall_set:
            self.complete_action()
            return

        # Out of bounds: block the move
        if nx < 0 or nx >= self.grid_w or ny < 0 or ny >= self.grid_h:
            self.complete_action()
            return

        # Self-collision: check if new head hits any body segment
        # When not eating food, the tail will retract, so exclude last segment
        ate_food = (nx, ny) in self.remaining_food
        if ate_food:
            # Snake grows: all segments stay, check against all of them
            body_to_check = set(self.snake)
        else:
            # Tail retracts: exclude last segment from collision check
            body_to_check = set(self.snake[:-1])

        if (nx, ny) in body_to_check:
            self.lose()
            self.complete_action()
            return

        # Consume food if present
        if ate_food:
            self.remaining_food.discard((nx, ny))

        # Move snake: prepend new head
        new_snake = [(nx, ny)] + list(self.snake)
        if not ate_food:
            new_snake.pop()  # remove tail (snake doesn't grow)
        self.snake = new_snake

        # Check win: all food collected and standing on exit
        if (nx, ny) == self.exit_pos and len(self.remaining_food) == 0:
            self.next_level()
            self.complete_action()
            return

        self.complete_action()
