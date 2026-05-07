# Author: Claude Opus 4.7
# Date: 2026-05-07 10:00
# PURPOSE: Demon Lord (dl01) — 5-level d-pad sokoban-RPG. Player pushes light
#          crystals; each crystal emits a 4-cardinal beam that lights cells
#          until blocked by a wall, the grid edge, or another crystal. Lit
#          cells kill shadow demons. A pink Demon General hunts the player
#          via BFS shortest-path on every level — dormant for the first 2
#          player moves, then chases one cell per turn; killable by light,
#          deadly on contact, blocks player walks and crystal pushes.
#          Final level: light all 3 sanctuary shrines to make the Demon
#          Lord vulnerable, then walk into him to win. Walking into the
#          invulnerable Lord kills the player.
#          Integrates with arcengine via ARCBaseGame; d-pad only (ACTION1-4).
# SRP/DRY check: Pass — no existing utility covers crystal-beam-lighting
#                sokoban rule. BFS pathfinder is one-off, kept inline.

from collections import deque

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
C_GENERAL      = 7   # LightMagenta — Demon General (chasing enemy)
C_SHRINE_OFF   = 2   # Gray
C_SHRINE_ON    = 14  # Green
C_EXIT         = 12  # Orange
C_BG           = 5   # Black

# Demon General activates after this many successful player moves (turns).
# 2 → general is dormant on player's first 2 actions, chases from action 3 on.
GENERAL_DORMANT_TURNS = 2

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
#   demon_general    — (x, y) starting cell of the chasing Demon General,
#                      or None if absent. Dormant for the first
#                      GENERAL_DORMANT_TURNS player moves, then BFS-chases.
#   player_start     — (x, y)
#   turn_limit       — hard cap; exceeding ends the level as a loss
# ============================================================================

LEVELS = [
    # ── Level 1: "First Light" ───────────────────────────────────────────────
    # Crystal pre-aligned with demon (col 4). Light kills the demon at level
    # start; player just walks to the exit. The Demon General starts at the
    # opposite corner — dormant 2 turns then chases via BFS.
    {
        "name": "First Light",
        "walls": set(),
        "crystals": [(4, 14)],
        "static_demons": [(4, 3)],
        "patrol_demons": [],
        "shrines": [],
        "exit_pos": (14, 14),
        "demon_lord": None,
        "demon_general": (1, 1),
        "player_start": (1, 14),
        "turn_limit": 45,
    },

    # ── Level 2: "Push It" ───────────────────────────────────────────────────
    # Crystal off-column (5,14). Player must push it left to col 4 to kill
    # the demon, then walk to the exit. Teaches sokoban push under chase
    # pressure.
    {
        "name": "Push It",
        "walls": set(),
        "crystals": [(5, 14)],
        "static_demons": [(4, 3)],
        "patrol_demons": [],
        "shrines": [],
        "exit_pos": (14, 14),
        "demon_lord": None,
        "demon_general": (1, 1),
        "player_start": (1, 14),
        "turn_limit": 55,
    },

    # ── Level 3: "Two Targets" ──────────────────────────────────────────────
    # Two crystals, two demons. Push crystal A to col 5, crystal B to col 10.
    {
        "name": "Two Targets",
        "walls": set(),
        "crystals": [(3, 14), (12, 14)],
        "static_demons": [(5, 5), (10, 5)],
        "patrol_demons": [],
        "shrines": [],
        "exit_pos": (14, 14),
        "demon_lord": None,
        "demon_general": (1, 1),
        "player_start": (1, 14),
        "turn_limit": 70,
    },

    # ── Level 4: "Watchman" ─────────────────────────────────────────────────
    # Patrol demon walks col 8 rows 4-7. Static demon at (10, 7). Two crystals
    # in row 14. Exit at (14, 1) (so the General can't be there — starts at
    # (1, 1) instead).
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
        # (14, 14) would die at level start — sits in the right-beam from
        # crystal (12, 14). One row up keeps it in shadow on turn 0.
        "demon_general": (14, 13),
        "player_start": (1, 14),
        "turn_limit": 110,
    },

    # ── Level 5: "The Demon Lord" (boss) ────────────────────────────────────
    # Sanctuary U-shape (open south at (8,6)) houses the Lord at (8,5).
    # Three shrines at (3,7), (13,7), (8,9). Three crystals at (5,11), (10,11),
    # (8,13). The General lurks at (14, 14) — far from the player's eventual
    # path through col 7 to the Lord, but close enough to demand caution.
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
        "demon_general": (14, 14),
        "player_start": (1, 14),
        "turn_limit": 140,
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

        # 7b. Demon General (alive only) — full cell. Pink/LightMagenta
        # signals the elite chasing enemy.
        if g._demon_general is not None and g._demon_general["alive"]:
            gx, gy = g._demon_general["pos"]
            px, py = gx * CELL, gy * CELL
            frame[py:py + CELL, px:px + CELL] = C_GENERAL

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
        self._demon_general = None    # {"pos","alive"} or None
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

        gen_pos = ldef.get("demon_general")
        if gen_pos is not None:
            self._demon_general = {"pos": gen_pos, "alive": True}
        else:
            self._demon_general = None

        self._player = ldef["player_start"]
        self._turn = 0
        self._turn_limit = ldef["turn_limit"]

        # Initial lighting + cascading state updates (so demons sitting in a
        # beam at level start die immediately, shrines reflect initial beams).
        self._recompute_lighting()
        self._kill_static_demons_in_light()
        self._kill_patrol_demons_in_light()
        self._kill_general_in_light()
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

    def _general_alive(self):
        return self._demon_general is not None and self._demon_general["alive"]

    def _general_blocker_at(self, pos):
        return self._general_alive() and self._demon_general["pos"] == pos

    def _kill_general_in_light(self):
        if self._general_alive() and self._demon_general["pos"] in self._lit_cells:
            self._demon_general["alive"] = False

    def _general_bfs_next(self):
        """BFS from the General's cell toward the player. Returns the next
        cell to step into, or None if the General has no path or already
        co-locates with the player. Blockers excluded from traversal:
        walls, crystals, live static/patrol demons, the Demon Lord. The
        player cell itself IS reachable as the goal — that step kills the
        player."""
        if not self._general_alive():
            return None
        start = self._demon_general["pos"]
        goal = self._player
        if start == goal:
            return None

        parents = {start: None}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            if node == goal:
                break
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                nxt = (node[0] + dx, node[1] + dy)
                if nxt in parents:
                    continue
                if not self._in_bounds(nxt):
                    continue
                if nxt in self._all_walls:
                    continue
                if nxt in self._crystals:
                    continue
                if nxt != goal:
                    if (nxt in self._static_demons
                            and self._static_demons[nxt]["alive"]):
                        continue
                    if self._patrol_blocker_at(nxt):
                        continue
                    if (self._demon_lord is not None
                            and self._demon_lord["pos"] == nxt):
                        continue
                parents[nxt] = node
                queue.append(nxt)

        if goal not in parents:
            return None
        # Walk the parent chain back to the cell adjacent to start
        cur = goal
        while parents[cur] != start:
            cur = parents[cur]
        return cur

    def _move_general(self):
        """Advance the General one BFS step toward the player if it is
        active. Returns True if the General stepped onto the player (death)."""
        if not self._general_alive():
            return False
        if self._turn < GENERAL_DORMANT_TURNS:
            return False
        nxt = self._general_bfs_next()
        if nxt is None:
            return False
        self._demon_general["pos"] = nxt
        return nxt == self._player

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
        """For exit-based levels: all required enemies dead AND player on
        exit. The Demon General is a perpetual hazard, not a kill target —
        leaving it alive is fine; it just keeps chasing. For the Lord level:
        win is handled directly in step() on Lord-cell entry."""
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

        # Live Demon General: blocks player walking (it kills the player only
        # when IT steps onto the player, not the other way around — symmetric
        # with the patrol-demon rule).
        if self._general_blocker_at(target):
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
                or self._general_blocker_at(push_target)
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

        # Demon General chases AFTER patrol demons (so it sees up-to-date
        # blockers). Activation gate uses pre-increment self._turn — the
        # general first acts on the player's (GENERAL_DORMANT_TURNS+1)th move.
        if self._move_general():
            self.lose()
            self.complete_action()
            return
        self._kill_general_in_light()

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
