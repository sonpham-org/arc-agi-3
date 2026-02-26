import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

# Logical grid: 32×32 cells, each rendered as 2×2 pixels → 64×64 output
GL = 32

# ARC-AGI-3 colour indices
# 0=black  1=dark-blue  2=green   3=dark-gray  4=yellow   5=gray
# 6=pink   7=orange     8=azure   9=blue       11=bright-yellow
# 12=red   14=lime      15=white

OCEAN_C   = 9    # blue sea
LAND_C    = 2    # green island
SHORE_C   = 4    # yellow sand (shoreline)
ROCK_C    = 5    # gray rocks
PORT_C    = 7    # orange port / dock
SHIP_C    = 15   # white ship hull
SAIL_C    = 15   # white sail
DECK_C    = 3    # dark deck
TREASURE_C = 11  # bright yellow chest
ENEMY_C   = 12   # red enemy ship
LIFE_C    = 12   # red (HUD lives)
PROGRESS_C = 11  # yellow (HUD progress)

# Map cell types
OCEAN = 0
LAND  = 1
ROCK  = 2

# Action → direction mapping  (matches universal standard: 1=up 2=right 3=down 4=left)
_DIR = {1: (0, -1), 2: (1, 0), 3: (0, 1), 4: (-1, 0)}

# Ship pixel art in logical coords (width=2, height=3), -1 = transparent
# Each logical cell → 2×2 screen pixels
SHIP_PIX = [
    [-1, SAIL_C],   # row 0: mast / sail
    [SHIP_C, SHIP_C],   # row 1: upper hull
    [DECK_C, DECK_C],   # row 2: keel
]
SHIP_LW, SHIP_LH = 2, 3  # logical dimensions


# ---------------------------------------------------------------------------
# Map helpers
# ---------------------------------------------------------------------------

def _make_map(islands, rocks):
    """Build a 32×32 int8 map with LAND ellipses and ROCK cells."""
    m = np.zeros((GL, GL), dtype=np.int8)
    for cx, cy, rx, ry in islands:
        for y in range(max(0, cy - ry), min(GL, cy + ry + 1)):
            for x in range(max(0, cx - rx), min(GL, cx + rx + 1)):
                if rx > 0 and ry > 0:
                    if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                        m[y, x] = LAND
    for x, y in rocks:
        if 0 <= x < GL and 0 <= y < GL:
            m[y, x] = ROCK
    return m


_MAP1 = _make_map(
    islands=[(10, 8, 4, 3), (22, 21, 3, 4)],
    rocks=[(17, 14), (18, 14), (17, 15)],
)
_MAP2 = _make_map(
    islands=[(8, 6, 3, 2), (23, 8, 2, 4), (15, 23, 5, 3)],
    rocks=[(12, 15), (13, 16), (21, 16), (26, 6)],
)
_MAP3 = _make_map(
    islands=[(6, 5, 2, 2), (18, 4, 3, 2), (27, 11, 2, 3),
             (9, 21, 2, 3), (23, 25, 3, 2), (15, 16, 2, 2)],
    rocks=[(14, 10), (15, 10), (10, 15), (24, 18), (20, 20)],
)

# Pre-compute shore mask for nicer rendering: land cell adjacent to ocean
def _shore_mask(m):
    s = np.zeros_like(m, dtype=bool)
    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        rolled = np.roll(m == OCEAN, (dy, dx), axis=(0, 1))
        s |= ((m == LAND) & rolled)
    return s


_SHORE1 = _shore_mask(_MAP1)
_SHORE2 = _shore_mask(_MAP2)
_SHORE3 = _shore_mask(_MAP3)

_LEVELS = [
    {
        "name":      "Caribbean Cove",
        "map":       _MAP1,
        "shore":     _SHORE1,
        "ship":      (2, 16),
        "treasures": [(28, 4), (28, 27), (4, 27)],
        "enemies":   [{"pos": [16, 5],  "dir": [1, 0]},
                     ],
        "lives":     3,
    },
    {
        "name":      "Skull Shoals",
        "map":       _MAP2,
        "shore":     _SHORE2,
        "ship":      (2, 16),
        "treasures": [(28, 4), (28, 28), (4, 28), (28, 16), (16, 28)],
        "enemies":   [{"pos": [16, 10], "dir": [0, 1]},
                      {"pos": [26, 22], "dir": [-1, 0]},
                     ],
        "lives":     3,
    },
    {
        "name":      "Dragon's Lair",
        "map":       _MAP3,
        "shore":     _SHORE3,
        "ship":      (2, 16),
        "treasures": [(29, 3), (29, 29), (3, 29), (29, 16),
                      (16, 29), (16, 2),  (3,  3)],
        "enemies":   [{"pos": [20, 8],  "dir": [1, 0]},
                      {"pos": [5,  25], "dir": [0, -1]},
                      {"pos": [26, 16], "dir": [0, 1]},
                     ],
        "lives":     3,
    },
]

levels = [
    Level(sprites=[], grid_size=(64, 64), name=d["name"], data=d)
    for d in _LEVELS
]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _fill(frame, lx, ly, color, lw=1, lh=1):
    """Fill a logical rect (lx, ly, lw, lh) with colour in 64×64 frame."""
    px, py = lx * 2, ly * 2
    frame[py:py + lh * 2, px:px + lw * 2] = color


def _draw_sprite(frame, lx, ly, pix):
    """Draw a sprite (list of rows, list of cols) at logical (lx, ly)."""
    for row, prow in enumerate(pix):
        for col, color in enumerate(prow):
            if color != -1:
                px = (lx + col) * 2
                py = (ly + row) * 2
                if 0 <= px < 63 and 0 <= py < 63:
                    frame[py:py + 2, px:px + 2] = color


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

class PiDisplay(RenderableUserDisplay):
    def __init__(self, game: "Pi01"):
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        m = g.game_map
        shore = g.shore_mask

        # ── Ocean base ───────────────────────────────────────────────────────
        frame[:, :] = OCEAN_C

        # ── Terrain ──────────────────────────────────────────────────────────
        for ly in range(GL):
            for lx in range(GL):
                cell = m[ly, lx]
                if cell == LAND:
                    color = SHORE_C if shore[ly, lx] else LAND_C
                    _fill(frame, lx, ly, color)
                elif cell == ROCK:
                    _fill(frame, lx, ly, ROCK_C)

        # ── Port marker (ship start) ──────────────────────────────────────────
        px0, py0 = g.ship_start
        _fill(frame, px0, py0, PORT_C, 1, 1)

        # ── Treasures ────────────────────────────────────────────────────────
        for (tx, ty) in g.treasures:
            _fill(frame, tx, ty, TREASURE_C)

        # ── Enemy ships ──────────────────────────────────────────────────────
        for e in g.enemies:
            ex, ey = int(e["pos"][0]), int(e["pos"][1])
            _fill(frame, ex, ey, ENEMY_C)

        # ── Player ship (blinks during invincibility) ─────────────────────────
        if not (g.invincible > 0 and g.invincible % 4 < 2):
            _draw_sprite(frame, g.sx, g.sy, SHIP_PIX)

        # ── HUD: lives (top-left, red squares) ───────────────────────────────
        for i in range(g.lives):
            frame[1:3, 1 + i * 5:1 + i * 5 + 3] = LIFE_C

        # ── HUD: treasure progress (top strip, yellow) ────────────────────────
        total = len(_LEVELS[g.level_index]["treasures"])
        collected = total - len(g.treasures)
        for i in range(total):
            color = PROGRESS_C if i < collected else 1   # yellow filled / dark unfilled
            frame[0:2, 24 + i * 5:24 + i * 5 + 3] = color

        return frame


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------

class Pi01(ARCBaseGame):
    def __init__(self):
        self.display = PiDisplay(self)

        # State – populated in on_set_level
        self.sx = 2
        self.sy = 16
        self.ship_start = (2, 16)
        self.game_map  = np.zeros((GL, GL), dtype=np.int8)
        self.shore_mask = np.zeros((GL, GL), dtype=bool)
        self.treasures = []
        self.enemies   = []
        self.lives     = 3
        self.invincible = 0
        self._step_count = 0

        super().__init__(
            "pi01",
            levels,
            Camera(0, 0, 64, 64, 0, 0, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4],   # up right down left
        )

    # ── Level setup ──────────────────────────────────────────────────────────

    def on_set_level(self, level: Level) -> None:
        d = _LEVELS[self.level_index]
        self.game_map   = d["map"]
        self.shore_mask = d["shore"]
        self.ship_start = d["ship"]
        self.sx, self.sy = d["ship"]
        self.treasures  = list(d["treasures"])
        self.enemies    = [{"pos": list(e["pos"]), "dir": list(e["dir"])}
                           for e in d["enemies"]]
        self.lives      = d["lives"]
        self.invincible = 0
        self._step_count = 0

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _blocked(self, lx: int, ly: int) -> bool:
        """True if any cell the ship would occupy is non-ocean."""
        for row in range(SHIP_LH):
            for col in range(SHIP_LW):
                cx, cy = lx + col, ly + row
                if cx < 0 or cx >= GL or cy < 0 or cy >= GL:
                    return True
                if self.game_map[cy, cx] != OCEAN:
                    return True
        return False

    def _move_enemies(self) -> None:
        """Advance each enemy ship one logical step, bouncing off terrain."""
        m = self.game_map
        for e in self.enemies:
            ex, ey = int(e["pos"][0]), int(e["pos"][1])
            dx, dy = e["dir"]
            nx, ny = ex + dx, ey + dy
            # Bounce if new position is out of bounds or on land/rock
            if (nx < 0 or nx >= GL or ny < 0 or ny >= GL or
                    m[ny, nx] not in (OCEAN,)):
                dx, dy = -dx, -dy
                nx, ny = ex + dx, ey + dy
                # If still blocked after bounce, try perpendicular
                if (nx < 0 or nx >= GL or ny < 0 or ny >= GL or
                        m[ny, nx] not in (OCEAN,)):
                    dx, dy = dy, dx   # 90° turn
                    nx, ny = ex + dx, ey + dy
                    if (nx < 0 or nx >= GL or ny < 0 or ny >= GL or
                            m[ny, nx] not in (OCEAN,)):
                        nx, ny = ex, ey   # stay put
            e["pos"] = [nx, ny]
            e["dir"] = [dx, dy]

    def _enemy_collision(self) -> bool:
        """True if any enemy overlaps the ship."""
        for e in self.enemies:
            ex, ey = int(e["pos"][0]), int(e["pos"][1])
            # Ship occupies lx ∈ [sx, sx+SHIP_LW), ly ∈ [sy, sy+SHIP_LH)
            if (self.sx < ex + 1 and self.sx + SHIP_LW > ex and
                    self.sy < ey + 1 and self.sy + SHIP_LH > ey):
                return True
        return False

    # ── Step ─────────────────────────────────────────────────────────────────

    def step(self) -> None:
        aid = self.action.id.value
        dx, dy = _DIR.get(aid, (0, 0))

        # Try to move
        nx, ny = self.sx + dx, self.sy + dy
        if not self._blocked(nx, ny):
            self.sx, self.sy = nx, ny

        # Check treasure pickup
        pos = (self.sx, self.sy)
        # Collect any treasure the ship overlaps (ship is 2 wide × 3 tall)
        collected = []
        for (tx, ty) in self.treasures:
            if (self.sx <= tx < self.sx + SHIP_LW and
                    self.sy <= ty < self.sy + SHIP_LH):
                collected.append((tx, ty))
        for t in collected:
            self.treasures.remove(t)

        # Move enemies every step
        self._move_enemies()
        self._step_count += 1

        # Enemy collision
        if self.invincible == 0 and self._enemy_collision():
            self.lives -= 1
            self.invincible = 12
            if self.lives <= 0:
                self.lose()
                self.complete_action()
                return

        # Invincibility tick
        if self.invincible > 0:
            self.invincible -= 1

        # Win condition: all treasure collected
        if not self.treasures:
            self.next_level()
            self.complete_action()
            return

        self.complete_action()
