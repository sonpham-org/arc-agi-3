# Author: Claude Opus 4.7
# Date: 2026-05-06 12:00
# PURPOSE: Demon Lord (dl01) — 5-level d-pad sokoban-RPG. Player pushes light
#          crystals; each crystal emits a 4-cardinal beam that lights cells
#          until blocked by a wall, the grid edge, or another crystal. Lit
#          cells kill shadow demons. Final level: light all 3 sanctuary
#          shrines to make the Demon Lord vulnerable, then walk into him to
#          win. Walking into the invulnerable Lord kills the player.
#          Integrates with arcengine via ARCBaseGame; d-pad only (ACTION1-4).
# SRP/DRY check: Pass — no existing utility covers crystal-beam-lighting
#                sokoban rule. Pattern is novel for this codebase.

import numpy as np
from arcengine import ARCBaseGame, Camera, Level, RenderableUserDisplay

CELL = 4          # 4x4 px per logical cell
GRID_W = 16
GRID_H = 16

# ── ARC-3 palette indices ──
C_FLOOR_DARK   = 4   # VeryDarkGray (shadow floor)
C_FLOOR_LIT    = 11  # Yellow (lit floor)
C_WALL         = 3   # DarkGray
C_CRYSTAL      = 10  # LightBlue
C_CRYSTAL_CORE = 0   # White facet inside crystal
C_PLAYER       = 9   # Blue
C_DEMON_STAT   = 15  # Purple
C_DEMON_PATROL = 8   # Red
C_LORD_INVULN  = 13  # Maroon
C_LORD_VULN    = 6   # Magenta
C_SHRINE_OFF   = 2   # Gray
C_SHRINE_ON    = 14  # Green
C_EXIT         = 12  # Orange
C_BG           = 5   # Black

# Action id → (dx, dy). ACTION1..4 = UP, DOWN, LEFT, RIGHT (per CLAUDE.md).
DIR_DELTAS = {
    1: (0, -1),   # UP
    2: (0, 1),    # DOWN
    3: (-1, 0),   # LEFT
    4: (1, 0),    # RIGHT
}


# ============================================================================
# Level definitions
# ----------------------------------------------------------------------------
# Each level dict:
#   walls            — set of (x, y) interior walls (border auto-added)
#   crystals         — list of starting crystal positions
#   static_demons    — list of stationary demon positions
#   patrol_demons    — list of {"path": [(x,y), ...], "start_idx": int}
#                      patrol cycles through path one cell per turn-advance
#   shrines          — list of shadow-shrine positions (Lord level only)
#   exit_pos         — (x, y) walkable exit, or None on Lord level
#   demon_lord       — (x, y) of the Lord, or None
#   player_start     — (x, y)
#   turn_limit       — hard cap; exceeding ends the level as a loss
# ============================================================================

LEVELS = [
    # ── Level 1: "First Light" ───────────────────────────────────────────────
    # Crystal pre-aligned with demon (col 4). Light kills the demon at level
    # start; player just walks to the exit. Tutorial: see what beams do.
    {
        "name": "First Light",
        "walls": set(),
        "crystals": [(4, 14)],
        "static_demons": [(4, 3)],
        "patrol_demons": [],
        "shrines": [],
        "exit_pos": (14, 14),
        "demon_lord": None,
        "player_start": (1, 14),
        "turn_limit": 30,
    },

    # ── Level 2: "Push It" ───────────────────────────────────────────────────
    # Crystal off-column (5,14). Player must push it left to col 4 to kill
    # the demon, then walk to the exit. Teaches sokoban push.
    {
        "name": "Push It",
        "walls": set(),
        "crystals": [(5, 14)],
        "static_demons": [(4, 3)],
        "patrol_demons": [],
        "shrines": [],
        "exit_pos": (14, 14),
        "demon_lord": None,
        "player_start": (1, 14),
        "turn_limit": 35,
    },

    # ── Level 3: "Two Targets" ──────────────────────────────────────────────
    # Two crystals, two demons. Crystals start in cols 3 and 12 (no demons
    # there). Push crystal A to col 5, crystal B to col 10.
    {
        "name": "Two Targets",
        "walls": set(),
        "crystals": [(3, 14), (12, 14)],
        "static_demons": [(5, 5), (10, 5)],
        "patrol_demons": [],
        "shrines": [],
        "exit_pos": (14, 14),
        "demon_lord": None,
        "player_start": (1, 14),
        "turn_limit": 50,
    },

    # ── Level 4: "Watchman" ─────────────────────────────────────────────────
    # Patrol demon walks col 8 rows 4-7. Static demon at (10, 7). Two crystals
    # in row 14. Exit moved to (14, 1) so player must traverse upward.
    {
        "name": "Watchman",
        "walls": set(),
        "crystals": [(4, 14), (12, 14)],
        "static_demons": [(10, 7)],
        "patrol_demons": [
            {
                "path": [(8, 4), (8, 5), (8, 6), (8, 7), (8, 6), (8, 5)],
                "start_idx": 0,
            },
        ],
        "shrines": [],
        "exit_pos": (14, 1),
        "demon_lord": None,
        "player_start": (1, 14),
        "turn_limit": 80,
    },

    # ── Level 5: "The Demon Lord" (boss) ────────────────────────────────────
    # Sanctuary U-shape (open south at (8,6)) houses the Lord at (8,5).
    # Three shrines at (3,7), (13,7), (8,9). Three crystals at (5,11), (10,11),
    # (8,13). Push crystal A LEFT to col 3, crystal B RIGHT to col 13; crystal
    # C at (8,13) already lights shrine (8,9). Then walk via col 7 (avoiding
    # col 8 which has crystal C) up to (7,7), right into (8,7), up through the
    # opening at (8,6), and into the now-vulnerable Lord at (8,5).
    {
        "name": "The Demon Lord",
        "walls": {
            # Sanctuary U-shape — opening at (8, 6)
            (7, 4), (8, 4), (9, 4),
            (7, 5),         (9, 5),
            (7, 6),         (9, 6),
        },
        "crystals": [(5, 11), (10, 11), (8, 13)],
        "static_demons": [],
        "patrol_demons": [],
        "shrines": [(3, 7), (13, 7), (8, 9)],
        "exit_pos": None,           # win = walk into vulnerable Lord
        "demon_lord": (8, 5),
        "player_start": (1, 14),
        "turn_limit": 100,
    },
]


# ============================================================================
# Display
# ============================================================================

class Dl01Display(RenderableUserDisplay):
    def __init__(self, game):
        self.game = game

    def render_interface(self, frame: np.ndarray) -> np.ndarray:
        g = self.game
        frame[:, :] = C_BG

        # 1. Floor / wall / exit / shrine — full 4x4 cells, in z-order
        for gy in range(GRID_H):
            for gx in range(GRID_W):
                px, py = gx * CELL, gy * CELL

                # Wall takes precedence over floor
                if (gx, gy) in g._all_walls:
                    color = C_WALL
                elif (gx, gy) in g._lit_cells:
                    color = C_FLOOR_LIT
                else:
                    color = C_FLOOR_DARK
                frame[py:py + CELL, px:px + CELL] = color

        # 2. Exit (overrides floor)
        if g._exit_pos is not None:
            ex, ey = g._exit_pos
            px, py = ex * CELL, ey * CELL
            frame[py:py + CELL, px:px + CELL] = C_EXIT

        # 3. Shrines (overrides floor; renders as full cell)
        for shrine_pos, state in g._shrines.items():
            sx, sy = shrine_pos
            px, py = sx * CELL, sy * CELL
            color = C_SHRINE_ON if state["lit"] else C_SHRINE_OFF
            frame[py:py + CELL, px:px + CELL] = color

        # 4. Crystals — 2x2 centered (1px border shows cell beneath, so a
        #    crystal sitting on a shrine still shows the shrine ring).
        for cx, cy in g._crystals:
            px, py = cx * CELL, cy * CELL
            frame[py + 1:py + 3, px + 1:px + 3] = C_CRYSTAL
            # Single-pixel core for visual texture
            frame[py + 1, px + 1] = C_CRYSTAL_CORE

        # 5. Static demons (alive only) — full cell
        for pos, state in g._static_demons.items():
            if not state["alive"]:
                continue
            dx, dy = pos
            px, py = dx * CELL, dy * CELL
            frame[py:py + CELL, px:px + CELL] = C_DEMON_STAT

        # 6. Patrol demons (alive only) — full cell
        for d in g._patrol_demons:
            if not d["alive"]:
                continue
            dx, dy = d["pos"]
            px, py = dx * CELL, dy * CELL
            frame[py:py + CELL, px:px + CELL] = C_DEMON_PATROL

        # 7. Demon Lord — full cell, color flips when vulnerable
        if g._demon_lord is not None:
            lx, ly = g._demon_lord["pos"]
            px, py = lx * CELL, ly * CELL
            color = C_LORD_VULN if g._demon_lord["vulnerable"] else C_LORD_INVULN
            frame[py:py + CELL, px:px + CELL] = color

        # 8. Player — full cell, on top of everything
        ppx, ppy = g._player
        px, py = ppx * CELL, ppy * CELL
        frame[py:py + CELL, px:px + CELL] = C_PLAYER

        return frame


# ============================================================================
# Game
# ============================================================================

class Dl01(ARCBaseGame):
    def __init__(self):
        self.display = Dl01Display(self)

        # State (populated in on_set_level)
        self._player = (0, 0)
        self._crystals = set()
        self._all_walls = set()
        self._static_demons = {}      # {(x,y): {"alive": bool}}
        self._patrol_demons = []      # [{"pos","path","idx","alive"}]
        self._shrines = {}            # {(x,y): {"lit": bool}}
        self._exit_pos = None
        self._demon_lord = None       # {"pos","vulnerable"} or None
        self._lit_cells = set()
        self._turn = 0
        self._turn_limit = 30

        levels = []
        for ldef in LEVELS:
            levels.append(Level(
                sprites=[],
                grid_size=(64, 64),
                data=ldef,
                name=ldef["name"],
            ))

        super().__init__(
            "dl",
            levels,
            Camera(0, 0, 64, 64, C_BG, C_BG, [self.display]),
            False,
            len(levels),
            [1, 2, 3, 4],
        )

    # ────────────────────────────────────────────────────────────────────────
    # Level setup
    # ────────────────────────────────────────────────────────────────────────

    def on_set_level(self, level: Level) -> None:
        ldef = LEVELS[self.level_index]

        # Border walls are always present
        border = set()
        for x in range(GRID_W):
            border.add((x, 0))
            border.add((x, GRID_H - 1))
        for y in range(GRID_H):
            border.add((0, y))
            border.add((GRID_W - 1, y))
        self._all_walls = border | set(ldef["walls"])

        self._crystals = set(ldef["crystals"])
        self._static_demons = {pos: {"alive": True} for pos in ldef["static_demons"]}

        self._patrol_demons = []
        for pdef in ldef["patrol_demons"]:
            path = list(pdef["path"])
            start_idx = pdef.get("start_idx", 0)
            self._patrol_demons.append({
                "pos": path[start_idx],
                "path": path,
                "idx": start_idx,
                "alive": True,
            })

        self._shrines = {pos: {"lit": False} for pos in ldef["shrines"]}
        self._exit_pos = ldef["exit_pos"]

        if ldef["demon_lord"] is not None:
            self._demon_lord = {"pos": ldef["demon_lord"], "vulnerable": False}
        else:
            self._demon_lord = None

        self._player = ldef["player_start"]
        self._turn = 0
        self._turn_limit = ldef["turn_limit"]

        # Initial lighting + cascading state updates (so demons sitting in a
        # beam at level start die immediately, shrines reflect initial beams).
        self._recompute_lighting()
        self._kill_static_demons_in_light()
        self._kill_patrol_demons_in_light()
        self._update_shrines()
        self._update_lord()

    # ────────────────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────────────────

    def _in_bounds(self, pos):
        x, y = pos
        return 0 <= x < GRID_W and 0 <= y < GRID_H

    def _recompute_lighting(self):
        """Cast 4-cardinal beams from each crystal. Beams stop at walls,
        edges, or other crystals. Crystal does NOT light its own cell.
        Beams pass through demons, the Lord, the player, shrines, exits."""
        self._lit_cells = set()
        for cx, cy in self._crystals:
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                x, y = cx + dx, cy + dy
                while self._in_bounds((x, y)):
                    if (x, y) in self._all_walls:
                        break
                    if (x, y) in self._crystals:
                        break
                    self._lit_cells.add((x, y))
                    x += dx
                    y += dy

    def _kill_static_demons_in_light(self):
        for pos, state in self._static_demons.items():
            if state["alive"] and pos in self._lit_cells:
                state["alive"] = False

    def _kill_patrol_demons_in_light(self):
        for d in self._patrol_demons:
            if d["alive"] and d["pos"] in self._lit_cells:
                d["alive"] = False

    def _patrol_blocker_at(self, pos, exclude=None):
        """Return True if some live patrol demon (other than `exclude`) is at pos."""
        for d in self._patrol_demons:
            if d is exclude or not d["alive"]:
                continue
            if d["pos"] == pos:
                return True
        return False

    def _move_patrol_demons(self):
        """Advance each living patrol demon one cell along its path. If a
        demon would step onto a wall, crystal, other live demon, the Lord,
        or a live static demon, it waits one turn (no move, no idx change).
        Returns True if any patrol demon ended its move on the player cell."""
        for d in self._patrol_demons:
            if not d["alive"]:
                continue
            next_idx = (d["idx"] + 1) % len(d["path"])
            next_pos = d["path"][next_idx]

            blocked = False
            if next_pos in self._all_walls:
                blocked = True
            elif next_pos in self._crystals:
                blocked = True
            elif self._patrol_blocker_at(next_pos, exclude=d):
                blocked = True
            elif (next_pos in self._static_demons
                  and self._static_demons[next_pos]["alive"]):
                blocked = True
            elif (self._demon_lord is not None
                  and self._demon_lord["pos"] == next_pos):
                blocked = True

            if blocked:
                continue  # wait this turn; idx unchanged

            d["pos"] = next_pos
            d["idx"] = next_idx
            if next_pos == self._player:
                return True
        return False

    def _update_shrines(self):
        for pos, state in self._shrines.items():
            state["lit"] = pos in self._lit_cells

    def _update_lord(self):
        if self._demon_lord is None:
            return
        if not self._shrines:
            self._demon_lord["vulnerable"] = False
            return
        self._demon_lord["vulnerable"] = all(
            state["lit"] for state in self._shrines.values()
        )

    def _check_level_win(self):
        """For exit-based levels: all enemies dead AND player on exit.
        For the Lord level: handled directly in step() on Lord-cell entry."""
        if self._exit_pos is None:
            return False
        if self._player != self._exit_pos:
            return False
        for state in self._static_demons.values():
            if state["alive"]:
                return False
        for d in self._patrol_demons:
            if d["alive"]:
                return False
        return True

    # ────────────────────────────────────────────────────────────────────────
    # Step
    # ────────────────────────────────────────────────────────────────────────

    def step(self) -> None:
        aid = self.action.id.value

        if aid not in DIR_DELTAS:
            self.complete_action()
            return

        dx, dy = DIR_DELTAS[aid]
        px, py = self._player
        target = (px + dx, py + dy)

        # Out of bounds / wall: no-op (no turn advance)
        if not self._in_bounds(target) or target in self._all_walls:
            self.complete_action()
            return

        # Demon Lord cell: vulnerable → win, invulnerable → die
        if self._demon_lord is not None and target == self._demon_lord["pos"]:
            self._player = target
            if self._demon_lord["vulnerable"]:
                self.next_level()
            else:
                self.lose()
            self.complete_action()
            return

        # Live static demon: blocks (no-op, no turn)
        if (target in self._static_demons
                and self._static_demons[target]["alive"]):
            self.complete_action()
            return

        # Live patrol demon: blocks
        if self._patrol_blocker_at(target):
            self.complete_action()
            return

        # Crystal: try push
        if target in self._crystals:
            push_target = (target[0] + dx, target[1] + dy)
            push_blocked = (
                not self._in_bounds(push_target)
                or push_target in self._all_walls
                or push_target in self._crystals
                or (push_target in self._static_demons
                    and self._static_demons[push_target]["alive"])
                or self._patrol_blocker_at(push_target)
                or (self._demon_lord is not None
                    and self._demon_lord["pos"] == push_target)
            )
            if push_blocked:
                self.complete_action()
                return

            # Move crystal, then player into vacated cell
            self._crystals.discard(target)
            self._crystals.add(push_target)
            self._player = target
        else:
            # Plain walk (floor / lit shrine / exit / dead-demon cell)
            self._player = target

        # ── Turn advance ──
        self._recompute_lighting()
        self._kill_static_demons_in_light()

        if self._move_patrol_demons():
            # Patrol demon stepped onto player → death
            self.lose()
            self.complete_action()
            return

        # Patrol demon may have stepped into a beam during its move
        self._kill_patrol_demons_in_light()

        self._update_shrines()
        self._update_lord()

        self._turn += 1

        if self._check_level_win():
            self.next_level()
            self.complete_action()
            return

        if self._turn >= self._turn_limit:
            self.lose()
            self.complete_action()
            return

        self.complete_action()
