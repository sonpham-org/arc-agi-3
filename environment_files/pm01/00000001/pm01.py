# Potion Mixer - A sequence puzzle game
#
# Collect colored ingredients in the correct recipe order.
# D-pad to move (up/down/left/right). Stepping on the correct next
# ingredient collects it. Stepping on a wrong ingredient = lose.
# Collect all ingredients in recipe order to advance.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0
C_GREEN = 2
C_GRAY = 3
C_YELLOW = 4
C_MID = 5
C_ORANGE = 7
C_AZURE = 8
C_BLUE = 9
C_RED = 12
C_LIME = 14
C_WHITE = 15

INGR_COLORS = [C_RED, C_GREEN, C_BLUE, C_ORANGE, C_YELLOW]

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}


def _border(w, h):
    s = set()
    for x in range(w):
        s.add((x, 0))
        s.add((x, h - 1))
    for y in range(h):
        s.add((0, y))
        s.add((w - 1, y))
    return s


# Ingredient color indices:
# 0 = RED, 1 = GREEN, 2 = BLUE, 3 = ORANGE, 4 = YELLOW

LEVELS = [
    # L1: 5x5, 2 ingredients (RED then GREEN). Simple open grid.
    # Player at (2,2), RED at (1,1), GREEN at (3,3).
    # Path: left+up to (1,1)=RED, then right+down to (3,3)=GREEN.
    {
        "name": "Simple Brew",
        "grid_w": 5, "grid_h": 5,
        "walls": set(),
        "player": (2, 2),
        "recipe": [0, 1],
        "ingredients": [(1, 1, 0), (3, 3, 1)],
    },
    # L2: 6x6, 3 ingredients (RED, BLUE, GREEN). Open grid.
    # Player at (1,1). RED at (4,1), BLUE at (4,4), GREEN at (1,4).
    # Path: right to RED, down to BLUE, left to GREEN.
    {
        "name": "Three Step",
        "grid_w": 6, "grid_h": 6,
        "walls": set(),
        "player": (1, 1),
        "recipe": [0, 2, 1],
        "ingredients": [(4, 1, 0), (4, 4, 2), (1, 4, 1)],
    },
    # L3: 7x7, 3 ingredients with walls. Must route around walls.
    # Wall column at x=3 except gap at y=3.
    # Player at (1,3). RED at (1,1), GREEN at (5,1), BLUE at (5,5).
    # Must go up to RED, through gap to GREEN, then down to BLUE.
    {
        "name": "Wall Brew",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5)},
        "player": (1, 3),
        "recipe": [0, 1, 2],
        "ingredients": [(1, 1, 0), (5, 1, 1), (5, 5, 2)],
    },
    # L4: 7x7, 4 ingredients. Route carefully to avoid wrong ones.
    # Player at (1,1). Recipe: RED, BLUE, ORANGE, GREEN.
    # RED at (3,1), BLUE at (5,1), ORANGE at (5,5), GREEN at (1,5).
    # Clockwise path around edges. No blocking ingredients in the way.
    {
        "name": "Four Flavors",
        "grid_w": 7, "grid_h": 7,
        "walls": {(3, 3)},
        "player": (1, 1),
        "recipe": [0, 2, 3, 1],
        "ingredients": [(3, 1, 0), (5, 3, 2), (3, 5, 3), (1, 3, 1)],
    },
    # L5: 8x8, 4 ingredients, must plan path around obstacles.
    # Wall creates corridors. Recipe: GREEN, RED, YELLOW, BLUE.
    # Player at (1,1).
    {
        "name": "Corridor Mix",
        "grid_w": 8, "grid_h": 8,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 6),
                  (5, 2), (5, 3), (5, 4), (5, 6)},
        "player": (1, 3),
        "recipe": [1, 0, 4, 2],
        "ingredients": [(1, 1, 1), (4, 3, 0), (6, 1, 4), (6, 5, 2)],
    },
    # L6: 8x8, 5 ingredients, maze with corridors.
    # Recipe: RED, GREEN, BLUE, ORANGE, YELLOW.
    {
        "name": "Five Element",
        "grid_w": 8, "grid_h": 8,
        "walls": {(2, 2), (2, 3), (2, 5),
                  (4, 1), (4, 3), (4, 4), (4, 5),
                  (6, 2), (6, 3), (6, 5), (6, 6)},
        "player": (1, 1),
        "recipe": [0, 1, 2, 3, 4],
        "ingredients": [(3, 1, 0), (3, 6, 1), (5, 6, 2), (5, 1, 3), (1, 6, 4)],
    },
    # L7: 9x9, 5 ingredients, tight routing.
    # Recipe: BLUE, RED, GREEN, YELLOW, ORANGE.
    {
        "name": "Tight Brew",
        "grid_w": 9, "grid_h": 9,
        "walls": {(2, 1), (2, 2), (2, 3), (2, 5), (2, 6), (2, 7),
                  (4, 2), (4, 3), (4, 4), (4, 6), (4, 7),
                  (6, 1), (6, 2), (6, 3), (6, 5), (6, 6), (6, 7)},
        "player": (1, 4),
        "recipe": [2, 0, 1, 4, 3],
        "ingredients": [(1, 1, 2), (3, 1, 0), (3, 7, 1), (7, 7, 4), (7, 1, 3)],
    },
    # L8: 9x9, 6 ingredients.
    # Recipe: ORANGE, RED, GREEN, BLUE, YELLOW, RED.
    # Two RED ingredients - player must collect them in order.
    {
        "name": "Double Red",
        "grid_w": 9, "grid_h": 9,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 6), (3, 7),
                  (6, 2), (6, 3), (6, 4), (6, 5), (6, 7)},
        "player": (1, 3),
        "recipe": [3, 0, 1, 2, 4, 0],
        "ingredients": [
            (1, 1, 3), (2, 7, 0), (4, 7, 1),
            (4, 1, 2), (7, 1, 4), (7, 6, 0),
        ],
    },
    # L9: 10x10, 6 ingredients, complex maze.
    # Recipe: YELLOW, BLUE, RED, GREEN, ORANGE, YELLOW.
    {
        "name": "Maze Mixer",
        "grid_w": 10, "grid_h": 10,
        "walls": {(2, 1), (2, 2), (2, 3), (2, 5), (2, 6), (2, 7), (2, 8),
                  (4, 2), (4, 3), (4, 4), (4, 5), (4, 7), (4, 8),
                  (6, 1), (6, 2), (6, 3), (6, 5), (6, 6), (6, 8),
                  (8, 2), (8, 3), (8, 4), (8, 6), (8, 7), (8, 8)},
        "player": (1, 4),
        "recipe": [4, 2, 0, 1, 3, 4],
        "ingredients": [
            (1, 1, 4), (3, 1, 2), (5, 4, 0),
            (3, 8, 1), (7, 5, 3), (7, 1, 4),
        ],
    },
    # L10: 10x10, 7 ingredients, grand puzzle.
    # Recipe: RED, BLUE, GREEN, YELLOW, ORANGE, RED, GREEN.
    {
        "name": "Grand Potion",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 6), (3, 7), (3, 8),
                  (5, 1), (5, 2), (5, 3), (5, 5), (5, 6), (5, 8),
                  (7, 1), (7, 3), (7, 4), (7, 5), (7, 6), (7, 8)},
        "player": (1, 3),
        "recipe": [0, 2, 1, 4, 3, 0, 1],
        "ingredients": [
            (1, 1, 0), (4, 3, 2), (4, 8, 1),
            (6, 8, 4), (6, 4, 3), (8, 2, 0), (8, 7, 1),
        ],
    },
]


class Pm01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        # HUD height: 4 pixels for recipe display
        hud_h = 4
        ox = (64 - g.grid_w * CELL) // 2
        oy = hud_h + (64 - hud_h - g.grid_h * CELL) // 2

        # Recipe HUD at top
        total_w = len(g.recipe) * 6 - 2
        hx_start = max(0, (64 - total_w) // 2)
        for i, c in enumerate(g.recipe):
            hx = hx_start + i * 6
            if hx + 4 > 64:
                break
            if i < g.recipe_idx:
                frame[0:3, hx:hx + 4] = C_LIME
            else:
                frame[0:3, hx:hx + 4] = INGR_COLORS[c]

        # Grid floor
        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if py + CELL > 64 or px + CELL > 64:
                    continue
                if (gx, gy) in g.walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Ingredients
        for ix, iy, ic in g.remaining_ingredients:
            px, py = ox + ix * CELL, oy + iy * CELL
            if py + CELL > 64 or px + CELL > 64:
                continue
            frame[py:py + CELL, px:px + CELL] = INGR_COLORS[ic]
            # White dot in center to distinguish from floor
            cy, cx = py + CELL // 2, px + CELL // 2
            frame[cy - 1:cy + 1, cx - 1:cx + 1] = C_WHITE

        # Player
        ppx, ppy = ox + g.px * CELL, oy + g.py * CELL
        if ppy + CELL <= 64 and ppx + CELL <= 64:
            frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        return frame


class Pm01(ARCBaseGame):
    def __init__(self):
        self.display = Pm01Display(self)
        levels = []
        for d in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=d,
                name=d["name"],
            ))
        super().__init__(
            "pm01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.px, self.py = d["player"]
        self.recipe = list(d["recipe"])
        self.recipe_idx = 0
        self.remaining_ingredients = [list(i) for i in d["ingredients"]]

    def _ingredient_at(self, x, y):
        for i, (ix, iy, ic) in enumerate(self.remaining_ingredients):
            if ix == x and iy == y:
                return i
        return -1

    def step(self):
        aid = self.action.id.value
        if aid not in _DIR:
            self.complete_action()
            return

        dx, dy = _DIR[aid]
        nx, ny = self.px + dx, self.py + dy

        if (nx, ny) in self.walls:
            self.complete_action()
            return

        self.px, self.py = nx, ny

        # Check ingredient
        ii = self._ingredient_at(self.px, self.py)
        if ii >= 0:
            ix, iy, ic = self.remaining_ingredients[ii]
            if self.recipe_idx < len(self.recipe) and ic == self.recipe[self.recipe_idx]:
                # Correct ingredient collected
                self.remaining_ingredients.pop(ii)
                self.recipe_idx += 1
                if self.recipe_idx >= len(self.recipe):
                    self.next_level()
                    self.complete_action()
                    return
            else:
                # Wrong ingredient
                self.lose()
                self.complete_action()
                return

        self.complete_action()
