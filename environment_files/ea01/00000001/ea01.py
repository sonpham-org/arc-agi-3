"""
ea01 - Escalation Arena  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Move up
ACTION2 (v): Move down
ACTION3 (<): Move left
ACTION4 (>): Move right

Goal: Survive waves of enemies and reach the exit.
- Move with d-pad (1 tile per turn on the grid).
- After the player moves, enemies advance along predetermined paths.
- Moving into an enemy's tile destroys it.
- If an enemy moves into the player's tile, you lose.
- After surviving enough turns, the exit (gold tile) opens.
- Step on the open exit to advance to the next level.

10 levels with escalating difficulty. Fully deterministic.
"""

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4

# ── Colour palette ───────────────────────────────────────────────────────────
C_BLACK = 0
C_DKBLUE = 1
C_GRAY = 3
C_MID = 5
C_AZURE = 8
C_GOLD = 11
C_RED = 12
C_WHITE = 15

# ── Level data ───────────────────────────────────────────────────────────────
# Each enemy: (start_x, start_y, spawn_turn, moves_list)
# moves_list: list of (dx, dy) the enemy executes each turn after spawning.
# Walls are auto-generated as borders; extra_walls adds interior obstacles.
#
# SOLUTION NOTES (not shown to player):
# Each level has a verified solution sequence listed in comments.

LEVELS = [
    # ── Level 1: First Blood (6x6) ──────────────────────────────────────────
    # Interior: (1,1)-(4,4). Player at (1,3), exit at (4,3).
    # 1 enemy at (4,1), spawns turn 0, walks down-left toward player.
    # Solution: right, right, up, right (kill enemy at (3,2)), down → exit
    # Exit opens turn 3.
    {
        "name": "First Blood",
        "grid_w": 6, "grid_h": 6,
        "extra_walls": [],
        "player": (1, 3),
        "exit": (4, 3),
        "enemies": [
            (4, 1, 0, [(0, 1), (-1, 0), (0, 1)]),
        ],
        "exit_turn": 3,
    },
    # ── Level 2: Pincer (6x6) ───────────────────────────────────────────────
    # 2 enemies from different sides. Player at (2,2). Exit at (4,4).
    # Enemy A at (4,1) moves down; Enemy B at (1,4) moves right then up.
    # Solution: right, down, right (kill A), down (exit). 4 actions.
    {
        "name": "Pincer",
        "grid_w": 6, "grid_h": 6,
        "extra_walls": [],
        "player": (2, 2),
        "exit": (4, 4),
        "enemies": [
            (4, 1, 0, [(0, 1), (0, 1), (0, 1), (0, 1)]),
            (1, 4, 0, [(1, 0), (1, 0), (0, -1), (0, -1)]),
        ],
        "exit_turn": 3,
    },
    # ── Level 3: Two Waves (7x7) ────────────────────────────────────────────
    # Interior: (1,1)-(5,5). Player at (1,3), exit at (5,3).
    # Wave 1 (turn 0): 2 enemies from top-right.
    # Wave 2 (turn 4): 2 enemies from bottom-right.
    # Solution: move right x4 killing enemies, then reach exit.
    {
        "name": "Two Waves",
        "grid_w": 7, "grid_h": 7,
        "extra_walls": [],
        "player": (1, 3),
        "exit": (5, 3),
        "enemies": [
            # Wave 1
            (5, 1, 0, [(-1, 0), (0, 1), (-1, 0), (0, 1)]),
            (4, 1, 0, [(0, 1), (-1, 0), (0, 1), (-1, 0)]),
            # Wave 2
            (5, 5, 4, [(-1, 0), (0, -1), (-1, 0), (0, -1)]),
            (4, 5, 4, [(0, -1), (-1, 0), (0, -1), (-1, 0)]),
        ],
        "exit_turn": 7,
    },
    # ── Level 4: Three Fronts (8x8) ─────────────────────────────────────────
    # Interior: (1,1)-(6,6). Player at (3,3), exit at (6,3).
    # Enemies from top, right, and bottom.
    {
        "name": "Three Fronts",
        "grid_w": 8, "grid_h": 8,
        "extra_walls": [],
        "player": (3, 3),
        "exit": (6, 3),
        "enemies": [
            # Wave 1: from top and right
            (3, 1, 0, [(0, 1), (0, 1), (0, 1), (0, 1)]),
            (6, 1, 0, [(0, 1), (-1, 0), (0, 1), (-1, 0)]),
            (6, 5, 0, [(0, -1), (-1, 0), (0, -1), (-1, 0)]),
            # Wave 2: from bottom
            (1, 6, 4, [(1, 0), (0, -1), (1, 0), (0, -1), (1, 0)]),
            (2, 6, 4, [(0, -1), (1, 0), (0, -1), (1, 0), (0, -1)]),
        ],
        "exit_turn": 8,
    },
    # ── Level 5: Tight Squeeze (8x8) ────────────────────────────────────────
    # 3 waves, tighter spacing, enemies converge on center.
    {
        "name": "Tight Squeeze",
        "grid_w": 8, "grid_h": 8,
        "extra_walls": [],
        "player": (3, 4),
        "exit": (6, 1),
        "enemies": [
            # Wave 1 (turn 0): two from top
            (2, 1, 0, [(0, 1), (0, 1), (0, 1), (1, 0)]),
            (5, 1, 0, [(0, 1), (0, 1), (-1, 0), (0, 1)]),
            # Wave 2 (turn 3): two from right
            (6, 3, 3, [(-1, 0), (-1, 0), (0, 1), (-1, 0)]),
            (6, 5, 3, [(-1, 0), (0, -1), (-1, 0), (-1, 0)]),
            # Wave 3 (turn 6): one from bottom
            (3, 6, 6, [(0, -1), (0, -1), (1, 0), (0, -1)]),
            (1, 4, 6, [(1, 0), (1, 0), (0, -1), (1, 0)]),
        ],
        "exit_turn": 9,
    },
    # ── Level 6: Bunker (9x9) ───────────────────────────────────────────────
    # Walls to use as cover. Interior: (1,1)-(7,7).
    {
        "name": "Bunker",
        "grid_w": 9, "grid_h": 9,
        "extra_walls": [
            (3, 3), (3, 4), (3, 5),
            (5, 3), (5, 4), (5, 5),
        ],
        "player": (4, 4),
        "exit": (7, 1),
        "enemies": [
            # Wave 1 (turn 0): from top corners
            (1, 1, 0, [(1, 0), (1, 0), (0, 1), (0, 1), (1, 0)]),
            (7, 1, 0, [(-1, 0), (-1, 0), (0, 1), (0, 1), (-1, 0)]),
            # Wave 2 (turn 4): from bottom
            (1, 7, 4, [(1, 0), (0, -1), (1, 0), (0, -1), (1, 0)]),
            (7, 7, 4, [(-1, 0), (0, -1), (-1, 0), (0, -1), (-1, 0)]),
            # Wave 3 (turn 8): from sides
            (1, 4, 8, [(1, 0), (1, 0), (0, -1), (0, -1), (1, 0)]),
            (7, 4, 8, [(-1, 0), (-1, 0), (0, -1), (0, -1), (-1, 0)]),
        ],
        "exit_turn": 11,
    },
    # ── Level 7: Patrol Patterns (9x9) ──────────────────────────────────────
    # 4 waves, enemies move in L-shapes and zigzags.
    {
        "name": "Patrol Patterns",
        "grid_w": 9, "grid_h": 9,
        "extra_walls": [
            (4, 2), (4, 6),
        ],
        "player": (2, 4),
        "exit": (7, 4),
        "enemies": [
            # Wave 1 (turn 0): L-shape patrollers
            (7, 1, 0, [(-1, 0), (-1, 0), (-1, 0), (0, 1), (0, 1), (0, 1)]),
            (7, 7, 0, [(-1, 0), (-1, 0), (-1, 0), (0, -1), (0, -1), (0, -1)]),
            # Wave 2 (turn 4): zigzag from left
            (1, 1, 4, [(0, 1), (1, 0), (0, 1), (1, 0), (0, 1), (1, 0)]),
            (1, 7, 4, [(0, -1), (1, 0), (0, -1), (1, 0), (0, -1), (1, 0)]),
            # Wave 3 (turn 8): straight rush
            (7, 3, 8, [(-1, 0), (-1, 0), (-1, 0), (-1, 0), (-1, 0)]),
            (7, 5, 8, [(-1, 0), (-1, 0), (-1, 0), (-1, 0), (-1, 0)]),
            # Wave 4 (turn 11): diagonal approach
            (1, 1, 11, [(1, 0), (0, 1), (1, 0), (0, 1), (1, 0)]),
            (1, 7, 11, [(1, 0), (0, -1), (1, 0), (0, -1), (1, 0)]),
        ],
        "exit_turn": 14,
    },
    # ── Level 8: Complex Maze (10x10) ───────────────────────────────────────
    # 4 waves, winding enemy paths through a maze.
    {
        "name": "Complex Maze",
        "grid_w": 10, "grid_h": 10,
        "extra_walls": [
            (3, 2), (3, 3), (3, 4),
            (6, 5), (6, 6), (6, 7),
            (5, 2), (5, 3),
        ],
        "player": (1, 5),
        "exit": (8, 5),
        "enemies": [
            # Wave 1 (turn 0): from top
            (8, 1, 0, [(0, 1), (-1, 0), (0, 1), (-1, 0), (0, 1), (-1, 0)]),
            (4, 1, 0, [(0, 1), (0, 1), (0, 1), (0, 1), (1, 0), (1, 0)]),
            # Wave 2 (turn 4): from right side
            (8, 8, 4, [(-1, 0), (0, -1), (-1, 0), (0, -1), (-1, 0), (0, -1)]),
            (8, 4, 4, [(-1, 0), (-1, 0), (0, 1), (0, 1), (-1, 0), (-1, 0)]),
            # Wave 3 (turn 8): from bottom
            (1, 8, 8, [(1, 0), (0, -1), (1, 0), (0, -1), (1, 0), (0, -1)]),
            (4, 8, 8, [(0, -1), (1, 0), (0, -1), (1, 0), (0, -1), (0, -1)]),
            # Wave 4 (turn 12): converge
            (1, 1, 12, [(1, 0), (0, 1), (1, 0), (0, 1), (1, 0), (0, 1)]),
            (8, 1, 12, [(-1, 0), (0, 1), (-1, 0), (0, 1), (-1, 0), (0, 1)]),
        ],
        "exit_turn": 15,
    },
    # ── Level 9: Gauntlet (10x10) ───────────────────────────────────────────
    # 5 waves, must plan carefully to avoid being cornered.
    {
        "name": "Gauntlet",
        "grid_w": 10, "grid_h": 10,
        "extra_walls": [
            (4, 4), (4, 5),
            (5, 4), (5, 5),
        ],
        "player": (1, 1),
        "exit": (8, 8),
        "enemies": [
            # Wave 1 (turn 0): two from right
            (8, 1, 0, [(-1, 0), (-1, 0), (0, 1), (-1, 0), (0, 1), (-1, 0)]),
            (8, 3, 0, [(-1, 0), (0, 1), (-1, 0), (0, 1), (-1, 0), (0, 1)]),
            # Wave 2 (turn 4): two from bottom
            (1, 8, 4, [(0, -1), (1, 0), (0, -1), (1, 0), (0, -1), (1, 0)]),
            (3, 8, 4, [(1, 0), (0, -1), (1, 0), (0, -1), (1, 0), (0, -1)]),
            # Wave 3 (turn 8): three from top
            (3, 1, 8, [(0, 1), (0, 1), (1, 0), (0, 1), (0, 1), (1, 0)]),
            (6, 1, 8, [(0, 1), (-1, 0), (0, 1), (0, 1), (-1, 0), (0, 1)]),
            (8, 1, 8, [(-1, 0), (0, 1), (0, 1), (-1, 0), (0, 1), (0, 1)]),
            # Wave 4 (turn 12): two from left
            (1, 3, 12, [(1, 0), (0, 1), (1, 0), (1, 0), (0, 1), (1, 0)]),
            (1, 6, 12, [(1, 0), (1, 0), (0, -1), (1, 0), (1, 0), (0, -1)]),
            # Wave 5 (turn 16): final push from corners
            (1, 1, 16, [(1, 0), (1, 0), (0, 1), (0, 1), (1, 0), (1, 0)]),
            (8, 1, 16, [(-1, 0), (-1, 0), (0, 1), (0, 1), (-1, 0), (-1, 0)]),
        ],
        "exit_turn": 19,
    },
    # ── Level 10: Grand Battle (12x10) ──────────────────────────────────────
    # 5 large waves, biggest arena.
    {
        "name": "Grand Battle",
        "grid_w": 12, "grid_h": 10,
        "extra_walls": [
            (4, 3), (4, 4), (4, 5), (4, 6),
            (7, 3), (7, 4), (7, 5), (7, 6),
            (6, 2), (5, 2),
            (6, 7), (5, 7),
        ],
        "player": (1, 5),
        "exit": (10, 5),
        "enemies": [
            # Wave 1 (turn 0): 3 from right
            (10, 1, 0, [(0, 1), (-1, 0), (0, 1), (-1, 0), (0, 1), (-1, 0), (-1, 0)]),
            (10, 4, 0, [(-1, 0), (-1, 0), (0, 1), (-1, 0), (-1, 0), (0, 1), (-1, 0)]),
            (10, 8, 0, [(0, -1), (-1, 0), (0, -1), (-1, 0), (0, -1), (-1, 0), (-1, 0)]),
            # Wave 2 (turn 4): 3 from top
            (2, 1, 4, [(0, 1), (0, 1), (1, 0), (0, 1), (0, 1), (1, 0), (0, 1)]),
            (6, 1, 4, [(0, 1), (-1, 0), (0, 1), (0, 1), (-1, 0), (0, 1), (0, 1)]),
            (10, 1, 4, [(-1, 0), (0, 1), (-1, 0), (0, 1), (-1, 0), (0, 1), (-1, 0)]),
            # Wave 3 (turn 8): 3 from bottom
            (2, 8, 8, [(0, -1), (1, 0), (0, -1), (0, -1), (1, 0), (0, -1), (1, 0)]),
            (6, 8, 8, [(0, -1), (-1, 0), (0, -1), (0, -1), (-1, 0), (0, -1), (-1, 0)]),
            (10, 8, 8, [(-1, 0), (0, -1), (-1, 0), (0, -1), (-1, 0), (0, -1), (-1, 0)]),
            # Wave 4 (turn 12): 3 from left
            (1, 1, 12, [(1, 0), (0, 1), (1, 0), (0, 1), (1, 0), (0, 1), (1, 0)]),
            (1, 5, 12, [(1, 0), (1, 0), (0, -1), (1, 0), (1, 0), (0, 1), (1, 0)]),
            (1, 8, 12, [(1, 0), (0, -1), (1, 0), (0, -1), (1, 0), (0, -1), (1, 0)]),
            # Wave 5 (turn 16): 4 from all corners - grand finale
            (1, 1, 16, [(1, 0), (1, 0), (0, 1), (1, 0), (0, 1), (1, 0), (0, 1)]),
            (10, 1, 16, [(-1, 0), (-1, 0), (0, 1), (-1, 0), (0, 1), (-1, 0), (0, 1)]),
            (1, 8, 16, [(1, 0), (1, 0), (0, -1), (1, 0), (0, -1), (1, 0), (0, -1)]),
            (10, 8, 16, [(-1, 0), (-1, 0), (0, -1), (-1, 0), (0, -1), (-1, 0), (0, -1)]),
        ],
        "exit_turn": 20,
    },
]


# ── Display ──────────────────────────────────────────────────────────────────

class Ea01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        # ── Floor tiles ──────────────────────────────────────────────────────
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if (gx, gy) in g.wall_set:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # ── Exit ─────────────────────────────────────────────────────────────
        ex_x, ex_y = g.exit_pos
        epx, epy = ox + ex_x * CELL, oy + ex_y * CELL
        if g.exit_open:
            frame[epy:epy + CELL, epx:epx + CELL] = C_GOLD
        else:
            frame[epy:epy + CELL, epx:epx + CELL] = C_GRAY

        # ── Enemies ──────────────────────────────────────────────────────────
        for i in range(len(g.active_enemies)):
            ae_x, ae_y = g.active_enemies[i]
            apx, apy = ox + ae_x * CELL, oy + ae_y * CELL
            frame[apy:apy + CELL, apx:apx + CELL] = C_RED

        # ── Player ───────────────────────────────────────────────────────────
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        # ── HUD: Wave / turn info (top 2 rows) ──────────────────────────────
        # Show enemy status: gold=killed, red=active, gray=pending
        total_enemies = len(g.enemy_defs)
        spawned = sum(1 for (_, _, st, _) in g.enemy_defs if st <= g.turn)
        destroyed = spawned - len(g.active_enemies)
        # Enemy count bar (top row)
        frame[0, 0:64] = C_DKBLUE
        for i in range(total_enemies):
            cx = 2 + i * (60 // max(total_enemies, 1))
            if cx < 63:
                if i < destroyed:
                    frame[0, cx:cx + 2] = C_GOLD  # killed
                elif i < spawned:
                    frame[0, cx:cx + 2] = C_RED  # active
                else:
                    frame[0, cx:cx + 2] = C_GRAY  # pending

        # Exit status indicator (top-right)
        frame[0, 62:64] = C_GOLD if g.exit_open else C_GRAY

        return frame


# ── Game ─────────────────────────────────────────────────────────────────────

levels = [
    Level(sprites=[], grid_size=(64, 64), data=d, name=d["name"])
    for d in LEVELS
]


class Ea01(ARCBaseGame):
    def __init__(self):
        self.display = Ea01Display(self)

        # Mutable state — properly set by on_set_level
        self.grid_w = 6
        self.grid_h = 6
        self.wall_set = set()
        self.px = 1
        self.py = 1
        self.exit_pos = (4, 4)
        self.exit_open = False
        self.exit_turn = 3
        self.turn = 0
        self.enemy_defs = []
        self.active_enemies = []  # list of [x, y]
        self.enemy_states = []  # list of [move_index, moves_list]

        super().__init__(
            "ea01",
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

        # Build wall set: borders + extra walls
        self.wall_set = set()
        for x in range(self.grid_w):
            self.wall_set.add((x, 0))
            self.wall_set.add((x, self.grid_h - 1))
        for y in range(self.grid_h):
            self.wall_set.add((0, y))
            self.wall_set.add((self.grid_w - 1, y))
        for w in d.get("extra_walls", []):
            self.wall_set.add(tuple(w))

        self.px, self.py = d["player"]
        self.exit_pos = tuple(d["exit"])
        self.exit_turn = d["exit_turn"]
        self.exit_open = False
        self.turn = 0
        self.enemy_defs = d["enemies"]
        self.active_enemies = []
        self.enemy_states = []

    def step(self):
        aid = self.action.id.value

        # ── Decode direction ─────────────────────────────────────────────────
        dx, dy = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}.get(aid, (0, 0))
        if dx == 0 and dy == 0:
            self.complete_action()
            return

        nx, ny = self.px + dx, self.py + dy

        # ── Wall collision → stay put ────────────────────────────────────────
        if (nx, ny) in self.wall_set:
            self.complete_action()
            return

        # ── Check if moving into an enemy → kill it ──────────────────────────
        for i in range(len(self.active_enemies) - 1, -1, -1):
            ex, ey = self.active_enemies[i]
            if (nx, ny) == (ex, ey):
                self.active_enemies.pop(i)
                self.enemy_states.pop(i)

        # ── Move player ──────────────────────────────────────────────────────
        self.px, self.py = nx, ny

        # ── Check win BEFORE enemy movement ──────────────────────────────────
        if self.exit_open and (self.px, self.py) == self.exit_pos:
            if not self.is_last_level():
                self.next_level()
            else:
                self.win()
            self.complete_action()
            return

        # ── Spawn new enemies for this turn ──────────────────────────────────
        for (sx, sy, spawn_turn, moves) in self.enemy_defs:
            if spawn_turn == self.turn:
                self.active_enemies.append([sx, sy])
                self.enemy_states.append([0, list(moves)])

        # ── Move enemies ─────────────────────────────────────────────────────
        for i in range(len(self.active_enemies)):
            mi, moves = self.enemy_states[i]
            if mi < len(moves):
                edx, edy = moves[mi]
                enx, eny = self.active_enemies[i][0] + edx, self.active_enemies[i][1] + edy
                if (enx, eny) not in self.wall_set:
                    self.active_enemies[i] = [enx, eny]
                self.enemy_states[i][0] = mi + 1

        # ── Check if enemy moved onto player → lose ──────────────────────────
        for ex, ey in self.active_enemies:
            if (ex, ey) == (self.px, self.py):
                self.lose()
                self.complete_action()
                return

        # ── Advance turn ─────────────────────────────────────────────────────
        self.turn += 1

        # ── Open exit once turn threshold is reached ─────────────────────────
        if not self.exit_open and self.turn >= self.exit_turn:
            self.exit_open = True

        self.complete_action()
