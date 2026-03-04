"""
td01 – Tower Defense  (ARC-AGI-3 game)

Controls
--------
ACTION1 (^): Move cursor up
ACTION2 (v): Move cursor down
ACTION3 (<): Move cursor left
ACTION4 (>): Move cursor right
ACTION5    : Place tower at cursor (costs 50 money)

Goal: Survive 10 waves of 10 enemies each.
- Start with 100 money; tower costs 50, each kill earns 25.
- Enemies march from the gate along the path to the castle.
- Castle has 10 HP; each enemy that reaches it deals 1 damage.
- Place towers on green cells to auto-attack enemies in range.
- Three levels with increasingly complex paths.
"""

import math

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

GL = 32   # logical grid size → 64×64 pixel frame (2×2 per cell)

# ── Colour palette ───────────────────────────────────────────────────────────
#  0=black  1=dark-blue  2=green   3=dark-gray  4=yellow   5=gray
#  6=pink   7=orange     8=azure   9=blue      11=bright-yellow
# 12=red   14=lime       15=white

GRASS_C     = 2    # green – placeable field
PATH_C      = 3    # dark-gray – enemy road
GATE_C      = 14   # lime – enemy spawn point
CASTLE_C    = 9    # blue – player castle
TOWER_C     = 7    # orange – tower base
TOWER_TOP_C = 11   # bright-yellow – tower tip pixel
ENEMY_C     = 12   # red – enemy
CURSOR_C    = 15   # white – valid placement cursor
CURSOR_NO_C = 5    # gray – invalid placement cursor
MONEY_C     = 11   # bright-yellow – HUD money
HP_C        = 12   # red – HUD castle HP
WAVE_C      = 8    # azure – HUD wave dots

# ── Game constants ────────────────────────────────────────────────────────────
TOWER_RANGE      = 5.0   # Euclidean attack range in cells
TOWER_COST       = 50
KILL_REWARD      = 25
WAVES_PER_LEVEL  = 10
ENEMIES_PER_WAVE = 10
SPAWN_INTERVAL   = 6    # steps between enemy spawns within a wave
ENEMY_MOVE_EVERY = 2    # enemies advance 1 cell every N player steps


# ── Path builder ─────────────────────────────────────────────────────────────

def _seg(x0, y0, x1, y1):
    """Axis-aligned segment from (x0,y0) to (x1,y1), both endpoints inclusive."""
    pts = []
    if x0 == x1:
        step = 1 if y1 >= y0 else -1
        for y in range(y0, y1 + step, step):
            pts.append((x0, y))
    else:
        step = 1 if x1 >= x0 else -1
        for x in range(x0, x1 + step, step):
            pts.append((x, y0))
    return pts


def _build_path(*waypoints):
    """Connect waypoints into a deduped axis-aligned path."""
    full = []
    for i in range(len(waypoints) - 1):
        seg = _seg(*waypoints[i], *waypoints[i + 1])
        if full:
            seg = seg[1:]   # drop duplicate junction point
        full.extend(seg)
    return full


# ── Hardcoded level paths ─────────────────────────────────────────────────────

# Level 1 – Crescent Bay: U-shape
_PATH1 = _build_path(
    (0, 8), (14, 8), (14, 22), (28, 22), (28, 8), (31, 8)
)

# Level 2 – River Bend: S-curve
_PATH2 = _build_path(
    (0, 4), (8, 4), (8, 14), (22, 14), (22, 24), (31, 24)
)

# Level 3 – Serpentine: tight zigzag
_PATH3 = _build_path(
    (0, 28), (6, 28), (6, 4), (16, 4), (16, 20), (24, 20), (24, 10), (31, 10)
)

_LEVELS = [
    {"name": "Crescent Bay", "path": _PATH1, "enemy_hp": 1, "prep_time": 20},
    {"name": "River Bend",   "path": _PATH2, "enemy_hp": 2, "prep_time": 15},
    {"name": "Serpentine",   "path": _PATH3, "enemy_hp": 3, "prep_time": 15},
]

levels = [
    Level(sprites=[], grid_size=(64, 64), name=d["name"], data=d)
    for d in _LEVELS
]


# ── Render helper ─────────────────────────────────────────────────────────────

def _fill(frame, lx, ly, color):
    px, py = lx * 2, ly * 2
    if 0 <= px < 63 and 0 <= py < 63:
        frame[py:py + 2, px:px + 2] = color


# ── Display ───────────────────────────────────────────────────────────────────

class Td01Display(RenderableUserDisplay):
    def __init__(self, game: "Td01"):
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        path = g.path

        # ── Background: grass ────────────────────────────────────────────────
        frame[:, :] = GRASS_C

        # ── Path ──────────────────────────────────────────────────────────────
        for (px, py) in path:
            _fill(frame, px, py, PATH_C)

        # ── Gate & Castle ─────────────────────────────────────────────────────
        gx, gy = path[0]
        ex, ey = path[-1]
        _fill(frame, gx, gy, GATE_C)
        _fill(frame, ex, ey, CASTLE_C)

        # ── Towers ────────────────────────────────────────────────────────────
        for (tx, ty) in g.towers:
            _fill(frame, tx, ty, TOWER_C)
            # bright tip on top-right pixel of the tower
            frame[ty * 2, tx * 2 + 1] = TOWER_TOP_C

        # ── Enemies ───────────────────────────────────────────────────────────
        for e in g.enemies:
            ep = path[e["idx"]]
            _fill(frame, ep[0], ep[1], ENEMY_C)

        # ── Cursor (blinks every 4 steps) ────────────────────────────────────
        if (g.step_count // 4) % 2 == 0:
            cc = CURSOR_NO_C if g._cursor_invalid() else CURSOR_C
            _fill(frame, g.cursor[0], g.cursor[1], cc)

        # ── HUD: money bar (top-left, rows 0-1) ──────────────────────────────
        frame[0:2, 0:50] = 1   # dark-blue track
        blocks = min(g.money // KILL_REWARD, 12)   # 1 block = 25 money, max 12
        for i in range(blocks):
            frame[0:2, 1 + i * 4: 1 + i * 4 + 3] = MONEY_C

        # ── HUD: wave counter (top-right, rows 0-1, cols 52-63) ──────────────
        frame[0:2, 52:64] = 1
        for i in range(WAVES_PER_LEVEL):
            col = WAVE_C if i < g.wave else 1
            c = 53 + i
            if c < 64:
                frame[0:2, c] = col

        # ── HUD: castle HP (bottom, rows 62-63) ──────────────────────────────
        frame[62:64, 0:64] = 1   # dark-blue track
        for i in range(g.castle_hp):
            frame[62:64, 1 + i * 6: 1 + i * 6 + 4] = HP_C

        # ── HUD: PREP countdown bar (rows 0-1, overwrites center) ────────────
        if g.between_wave_timer > 0:
            d = _LEVELS[g.level_index]
            frac = g.between_wave_timer / d["prep_time"]
            bar = round(44 * frac)
            frame[0:2, 10:54] = 1          # clear center of top strip
            if bar > 0:
                frame[0:2, 10:10 + bar] = 4   # yellow countdown

        return frame


# ── Game ──────────────────────────────────────────────────────────────────────

class Td01(ARCBaseGame):
    def __init__(self):
        self.display = Td01Display(self)

        # Mutable state – will be properly set by on_set_level
        self.path            = _PATH1
        self.path_set        = set(_PATH1)
        self.cursor          = (2, 2)
        self.towers          = []
        self.tower_set       = set()
        self.enemies         = []
        self.money           = 100
        self.castle_hp       = 10
        self.wave            = 0
        self.enemies_spawned = 0
        self.spawn_timer     = 0
        self.between_wave_timer = 20
        self.step_count      = 0
        self.enemy_hp_val    = 1

        super().__init__(
            "td01",
            levels,
            Camera(0, 0, 64, 64, GRASS_C, GRASS_C, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4, 5],
        )

    # ── Level setup ───────────────────────────────────────────────────────────

    def on_set_level(self, level: Level) -> None:
        d = _LEVELS[self.level_index]
        self.path            = d["path"]
        self.path_set        = set(d["path"])
        self.cursor          = (2, 2)
        self.towers          = []
        self.tower_set       = set()
        self.enemies         = []
        self.money           = 100
        self.castle_hp       = 10
        self.wave            = 0
        self.enemies_spawned = 0
        self.spawn_timer     = 0
        self.between_wave_timer = d["prep_time"]
        self.step_count      = 0
        self.enemy_hp_val    = d["enemy_hp"]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _cursor_invalid(self):
        return self.cursor in self.path_set or self.cursor in self.tower_set

    def _towers_shoot(self):
        """Each tower attacks the furthest-along enemy within range (1 damage)."""
        to_remove = []
        for (tx, ty) in self.towers:
            # Target furthest-along enemy (highest path index) in range
            target = None
            best_idx = -1
            for e in self.enemies:
                if e in to_remove:
                    continue
                ep = self.path[e["idx"]]
                dist = math.sqrt((tx - ep[0]) ** 2 + (ty - ep[1]) ** 2)
                if dist <= TOWER_RANGE and e["idx"] > best_idx:
                    best_idx = e["idx"]
                    target = e
            if target is not None:
                target["hp"] -= 1
                if target["hp"] <= 0:
                    to_remove.append(target)
                    self.money += KILL_REWARD
        for e in to_remove:
            if e in self.enemies:
                self.enemies.remove(e)

    def _move_enemies(self):
        """Advance every enemy one cell along the path."""
        reached = []
        for e in self.enemies:
            e["idx"] += 1
            if e["idx"] >= len(self.path):
                reached.append(e)
        for e in reached:
            self.enemies.remove(e)
            self.castle_hp -= 1

    def _try_spawn(self):
        """Spawn one enemy at the gate if the spawn timer allows."""
        if self.enemies_spawned >= ENEMIES_PER_WAVE:
            return
        if self.spawn_timer > 0:
            self.spawn_timer -= 1
            return
        self.enemies.append({"idx": 0, "hp": self.enemy_hp_val})
        self.enemies_spawned += 1
        self.spawn_timer = SPAWN_INTERVAL

    # ── Step ──────────────────────────────────────────────────────────────────

    def step(self) -> None:
        aid = self.action.id.value
        self.step_count += 1

        # ── Player action ──────────────────────────────────────────────────────
        cx, cy = self.cursor
        if aid == 1 and cy > 0:
            self.cursor = (cx, cy - 1)
        elif aid == 2 and cy < GL - 1:
            self.cursor = (cx, cy + 1)
        elif aid == 3 and cx > 0:
            self.cursor = (cx - 1, cy)
        elif aid == 4 and cx < GL - 1:
            self.cursor = (cx + 1, cy)
        elif aid == 5:
            if not self._cursor_invalid() and self.money >= TOWER_COST:
                self.towers.append((cx, cy))
                self.tower_set.add((cx, cy))
                self.money -= TOWER_COST

        # ── Prep phase: countdown before each wave ────────────────────────────
        if self.between_wave_timer > 0:
            self.between_wave_timer -= 1
            self.complete_action()
            return

        # ── Wave-active phase ─────────────────────────────────────────────────
        self._try_spawn()

        if self.step_count % ENEMY_MOVE_EVERY == 0:
            self._move_enemies()

        self._towers_shoot()

        # ── Check lose ────────────────────────────────────────────────────────
        if self.castle_hp <= 0:
            self.lose()
            self.complete_action()
            return

        # ── Check wave complete ───────────────────────────────────────────────
        if self.enemies_spawned >= ENEMIES_PER_WAVE and not self.enemies:
            self.wave += 1
            if self.wave >= WAVES_PER_LEVEL:
                # All 10 waves cleared
                if not self.is_last_level():
                    self.next_level()
                else:
                    self.win()
                self.complete_action()
                return
            # Begin prep for next wave
            self.enemies_spawned = 0
            self.spawn_timer = 0
            self.between_wave_timer = _LEVELS[self.level_index]["prep_time"]

        self.complete_action()
