# Arbitrage Runner - Buy low, sell high across market stalls
#
# D-pad to move. Visit market stalls to buy goods cheap and sell them
# at other stalls for profit. Reach the target gold amount to win.
# Each stall has a fixed buy/sell price. Carry one good at a time.
# Step on a buy stall = buy (costs gold). Step on sell stall = sell (earns gold).

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4
C_BLACK = 0
C_MID = 5
C_AZURE = 8
C_GOLD = 11
C_WHITE = 15
C_RED = 12
C_GREEN = 2
C_ORANGE = 7
C_BLUE = 9
C_LIME = 14
C_GRAY = 3
C_YELLOW = 4

_DIR = {1: (0, -1), 2: (0, 1), 3: (-1, 0), 4: (1, 0)}

# Stall: (x, y, type, good_id, price)
# type: 0 = buy (player pays price to get good), 1 = sell (player gets price for good)
# good_id: which good (0, 1, 2...)

LEVELS = [
    # L1: Simple - buy for 1, sell for 3, need 5 gold (start with 1)
    {
        "name": "First Trade",
        "grid_w": 7, "grid_h": 7,
        "walls": set(),
        "player": (3, 3),
        "stalls": [
            (1, 3, 0, 0, 1),   # buy good0 for 1
            (5, 3, 1, 0, 3),   # sell good0 for 3
        ],
        "start_gold": 1,
        "target_gold": 5,
    },
    # L2: Two goods, different margins
    {
        "name": "Two Markets",
        "grid_w": 8, "grid_h": 7,
        "walls": set(),
        "player": (1, 3),
        "stalls": [
            (2, 1, 0, 0, 1),   # buy good0 for 1
            (6, 1, 1, 0, 3),   # sell good0 for 3
            (2, 5, 0, 1, 2),   # buy good1 for 2
            (6, 5, 1, 1, 5),   # sell good1 for 5
        ],
        "start_gold": 2,
        "target_gold": 8,
    },
    # L3: Need multiple trips
    {
        "name": "Repeat Customer",
        "grid_w": 8, "grid_h": 7,
        "walls": set(),
        "player": (1, 3),
        "stalls": [
            (1, 1, 0, 0, 1),
            (6, 1, 1, 0, 2),
            (1, 5, 0, 1, 1),
            (6, 5, 1, 1, 3),
        ],
        "start_gold": 2,
        "target_gold": 10,
    },
    # L4: Walls between markets
    {
        "name": "Walled Markets",
        "grid_w": 9, "grid_h": 8,
        "walls": {(4, 1), (4, 2), (4, 4), (4, 5), (4, 6)},
        "player": (1, 3),
        "stalls": [
            (2, 1, 0, 0, 1),
            (7, 1, 1, 0, 4),
            (2, 6, 0, 1, 2),
            (7, 6, 1, 1, 5),
        ],
        "start_gold": 2,
        "target_gold": 12,
    },
    # L5: Three goods
    {
        "name": "Triple Market",
        "grid_w": 10, "grid_h": 8,
        "walls": {(5, 1), (5, 2), (5, 4), (5, 5), (5, 6)},
        "player": (1, 3),
        "stalls": [
            (2, 1, 0, 0, 1), (8, 1, 1, 0, 3),
            (2, 3, 0, 1, 2), (8, 3, 1, 1, 5),
            (2, 6, 0, 2, 3), (8, 6, 1, 2, 7),
        ],
        "start_gold": 3,
        "target_gold": 15,
    },
    # L6: Must choose optimal routes
    {
        "name": "Optimal Route",
        "grid_w": 10, "grid_h": 9,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7),
                  (7, 2), (7, 3), (7, 5), (7, 6), (7, 7)},
        "player": (1, 4),
        "stalls": [
            (1, 1, 0, 0, 1), (5, 1, 1, 0, 3),
            (5, 7, 0, 1, 2), (8, 1, 1, 1, 6),
        ],
        "start_gold": 2,
        "target_gold": 14,
    },
    # L7: Maze with markets scattered
    {
        "name": "Market Maze",
        "grid_w": 10, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 3), (3, 5), (3, 6), (3, 8),
                  (6, 2), (6, 3), (6, 5), (6, 6), (6, 7), (6, 8)},
        "player": (1, 4),
        "stalls": [
            (1, 1, 0, 0, 1), (8, 1, 1, 0, 4),
            (4, 4, 0, 1, 2), (8, 8, 1, 1, 6),
        ],
        "start_gold": 2,
        "target_gold": 16,
    },
    # L8: Complex economy
    {
        "name": "Supply Chain",
        "grid_w": 11, "grid_h": 9,
        "walls": {(4, 1), (4, 2), (4, 4), (4, 5), (4, 7),
                  (7, 2), (7, 3), (7, 5), (7, 6), (7, 7)},
        "player": (1, 4),
        "stalls": [
            (1, 1, 0, 0, 1), (5, 1, 1, 0, 2),
            (1, 7, 0, 1, 2), (9, 7, 1, 1, 5),
            (5, 4, 0, 2, 3), (9, 1, 1, 2, 8),
        ],
        "start_gold": 3,
        "target_gold": 20,
    },
    # L9: Tight margins, many trips
    {
        "name": "Thin Margins",
        "grid_w": 11, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7), (3, 8),
                  (6, 2), (6, 3), (6, 5), (6, 6), (6, 8),
                  (9, 1), (9, 3), (9, 4), (9, 6), (9, 7), (9, 8)},
        "player": (1, 4),
        "stalls": [
            (1, 1, 0, 0, 1), (4, 1, 1, 0, 2),
            (1, 8, 0, 1, 1), (7, 1, 1, 1, 3),
            (4, 8, 0, 2, 2), (10, 4, 1, 2, 6),
        ],
        "start_gold": 2,
        "target_gold": 18,
    },
    # L10: Grand marketplace
    {
        "name": "Grand Bazaar",
        "grid_w": 12, "grid_h": 10,
        "walls": {(3, 1), (3, 2), (3, 4), (3, 5), (3, 7), (3, 8),
                  (6, 1), (6, 2), (6, 4), (6, 5), (6, 7), (6, 8),
                  (9, 2), (9, 3), (9, 5), (9, 6), (9, 8)},
        "player": (1, 4),
        "stalls": [
            (1, 1, 0, 0, 1), (7, 1, 1, 0, 3),
            (1, 8, 0, 1, 2), (10, 1, 1, 1, 6),
            (4, 3, 0, 2, 3), (10, 8, 1, 2, 8),
            (4, 6, 0, 0, 1), (7, 8, 1, 0, 4),
        ],
        "start_gold": 3,
        "target_gold": 25,
    },
]


def _border(w, h):
    s = set()
    for x in range(w):
        s.add((x, 0))
        s.add((x, h - 1))
    for y in range(h):
        s.add((0, y))
        s.add((w - 1, y))
    return s


GOOD_COLORS = [C_RED, C_GREEN, C_BLUE]


class Ar01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame):
        frame[:, :] = C_BLACK
        g = self.game
        ox = (64 - g.grid_w * CELL) // 2
        oy = (64 - g.grid_h * CELL) // 2

        for gy in range(g.grid_h):
            for gx in range(g.grid_w):
                px, py = ox + gx * CELL, oy + gy * CELL
                if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                    continue
                if (gx, gy) in g.walls:
                    frame[py:py + CELL, px:px + CELL] = C_WHITE
                else:
                    frame[py:py + CELL, px:px + CELL] = C_MID

        # Draw stalls
        for sx, sy, stype, good_id, price in g.stall_defs:
            px, py = ox + sx * CELL, oy + sy * CELL
            if px < 0 or py < 0 or px + CELL > 64 or py + CELL > 64:
                continue
            color = GOOD_COLORS[good_id % len(GOOD_COLORS)]
            frame[py:py + CELL, px:px + CELL] = color
            # Buy stalls have dark center, sell stalls have bright center
            if stype == 0:
                frame[py + 1:py + 3, px + 1:px + 3] = C_BLACK
            else:
                frame[py + 1:py + 3, px + 1:px + 3] = C_GOLD

        # Player
        ppx = ox + g.px * CELL
        ppy = oy + g.py * CELL
        if 0 <= ppx and ppx + CELL <= 64 and 0 <= ppy and ppy + CELL <= 64:
            if g.carrying is not None:
                frame[ppy:ppy + CELL, ppx:ppx + CELL] = GOOD_COLORS[g.carrying % len(GOOD_COLORS)]
                frame[ppy + 1:ppy + 3, ppx + 1:ppx + 3] = C_AZURE
            else:
                frame[ppy:ppy + CELL, ppx:ppx + CELL] = C_AZURE

        # HUD: gold counter
        gold_display = min(g.gold, 25)
        for i in range(gold_display):
            hx = 1 + i * 2
            if hx + 1 > 64:
                break
            frame[0:2, hx:hx + 1] = C_GOLD

        return frame


class Ar01(ARCBaseGame):
    def __init__(self):
        self.display = Ar01Display(self)
        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))
        super().__init__(
            "ar01", levels,
            Camera(0, 0, 64, 64, C_BLACK, C_BLACK, [self.display]),
            False, len(levels), [1, 2, 3, 4],
        )

    def on_set_level(self, level):
        d = LEVELS[self.level_index]
        self.grid_w = d["grid_w"]
        self.grid_h = d["grid_h"]
        self.walls = _border(d["grid_w"], d["grid_h"]) | set(d["walls"])
        self.px, self.py = d["player"]
        self.stall_defs = d["stalls"]
        self.stall_map = {}  # (x,y) -> (type, good_id, price)
        for sx, sy, stype, gid, price in d["stalls"]:
            self.stall_map[(sx, sy)] = (stype, gid, price)
        self.gold = d["start_gold"]
        self.target_gold = d["target_gold"]
        self.carrying = None  # good_id or None

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

        # Check stall interaction
        if (self.px, self.py) in self.stall_map:
            stype, gid, price = self.stall_map[(self.px, self.py)]
            if stype == 0 and self.carrying is None and self.gold >= price:
                # Buy
                self.gold -= price
                self.carrying = gid
            elif stype == 1 and self.carrying == gid:
                # Sell
                self.gold += price
                self.carrying = None

        # Check win
        if self.gold >= self.target_gold:
            self.next_level()

        self.complete_action()
