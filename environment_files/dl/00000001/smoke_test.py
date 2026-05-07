# Author: Claude Opus 4.7
# Date: 2026-05-06 12:00
# PURPOSE: Mandatory smoke test for dl01 — drives the game with d-pad
#          actions and asserts WIN at the end of all 5 levels. Per
#          CLAUDE.md "Mandatory Smoke Test" requirement.
# SRP/DRY check: Pass — smoke tests are per-game; no shared utility.

import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dl01  # noqa: E402
from arcengine.enums import ActionInput, GameAction, GameState  # noqa: E402


UP, DOWN, LEFT, RIGHT = (
    GameAction.ACTION1,
    GameAction.ACTION2,
    GameAction.ACTION3,
    GameAction.ACTION4,
)


def main():
    g = dl01.Dl01()

    def A(action):
        g.perform_action(ActionInput(id=action))

    def repeat(action, n):
        for _ in range(n):
            A(action)

    def banner(msg):
        gen = g._demon_general
        gen_str = (f"general@{gen['pos']}{'A' if gen['alive'] else 'D'}"
                   if gen else "no-general")
        print(f"  -> {msg}: state={g._state.name}, level={g.level_index}, "
              f"player={g._player}, turn={g._turn}, {gen_str}")

    print("Level 1 — First Light")
    # Crystal already aligned with demon → demon dies at start.
    # Walk around the crystal to the exit at (14, 14).
    A(UP)            # (1,14)→(1,13)
    repeat(RIGHT, 13)  # (1,13)→(14,13)
    A(DOWN)          # (14,13)→(14,14) exit
    banner("after L1")
    assert g.level_index == 1, f"Expected level 1, got {g.level_index}"

    print("Level 2 — Push It")
    # Crystal at (5,14); push it LEFT to (4,14) to align with demon.
    A(UP)            # (1,14)→(1,13)
    repeat(RIGHT, 5) # (1,13)→(6,13)
    A(DOWN)          # (6,13)→(6,14)
    A(LEFT)          # push (5,14)→(4,14), player→(5,14); demon dies
    A(UP)            # (5,14)→(5,13)
    repeat(RIGHT, 9) # (5,13)→(14,13)
    A(DOWN)          # (14,13)→(14,14) exit
    banner("after L2")
    assert g.level_index == 2

    print("Level 3 — Two Targets")
    # Push crystal A from (3,14) to (5,14): 3 RIGHTs from (1,14) push it.
    repeat(RIGHT, 3)  # (1,14)→(2,14)→push 3→4 player(3,14)→push 4→5 player(4,14)
    A(UP)             # (4,14)→(4,13)
    repeat(RIGHT, 9)  # (4,13)→(13,13)
    A(DOWN)           # (13,13)→(13,14)
    repeat(LEFT, 2)   # push B (12,14)→(11,14) player(12,14); push 11→10 player(11,14)
    repeat(RIGHT, 3)  # (11,14)→(12)→(13)→(14,14) exit
    banner("after L3")
    assert g.level_index == 3

    print("Level 4 — Watchman")
    # Push crystal A all the way to col 8 (kills patrol demon when beam hits col 8).
    repeat(RIGHT, 6)  # (1,14)→(2)→(3)→push (4→5)/(4)→push 5→6/(5)→push 6→7/(6)→push 7→8/(7)
    # Detour around crystal A to push crystal B LEFT 2.
    A(UP)             # (7,14)→(7,13)
    repeat(RIGHT, 6)  # (7,13)→(13,13)
    A(DOWN)           # (13,13)→(13,14)
    repeat(LEFT, 2)   # push B (12,14)→(11,14)/(12); push 11→10/(11); kills static (10,7)
    # Walk to exit at (14, 1).
    repeat(UP, 13)    # (11,14)→(11,1)
    repeat(RIGHT, 3)  # (11,1)→(12)→(13)→(14,1) exit
    banner("after L4")
    assert g.level_index == 4

    print("Level 5 — The Demon Lord")
    # Push crystal A from (5,11) LEFT 2 to (3,11) → lights shrine (3,7).
    repeat(UP, 3)     # (1,14)→(1,11)
    repeat(RIGHT, 3)  # (1,11)→(4,11)
    A(UP)             # (4,11)→(4,10)
    repeat(RIGHT, 2)  # (4,10)→(6,10)
    A(DOWN)           # (6,10)→(6,11)
    repeat(LEFT, 2)   # push (5,11)→(4,11)/(5); push (4,11)→(3,11)/(4)
    # Push crystal B from (10,11) RIGHT 3 to (13,11) → lights shrine (13,7).
    repeat(RIGHT, 5)  # (4,11)→(5)→(6)→(7)→(8)→(9,11)
    repeat(RIGHT, 3)  # push (10→11)/(10); push (11→12)/(11); push (12→13)/(12,11)
    # Walk to vulnerable Lord at (8,5) via col 7.
    repeat(LEFT, 5)   # (12,11)→(11)→(10)→(9)→(8)→(7,11)
    repeat(UP, 4)     # (7,11)→(7,10)→(7,9)→(7,8)→(7,7)
    A(RIGHT)          # (7,7)→(8,7)
    repeat(UP, 2)     # (8,7)→(8,6)→(8,5) Lord vulnerable → WIN
    banner("after L5")

    assert g._state == GameState.WIN, f"Expected WIN, got {g._state.name}"
    print("\nALL 5 LEVELS WON")


if __name__ == "__main__":
    main()
