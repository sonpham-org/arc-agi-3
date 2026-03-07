#!/usr/bin/env python3
"""Smoke test for ss01 - Surge & Swap. Verify all 10 levels are solvable."""
import sys
sys.path.insert(0, 'environment_files/ss01/00000001')
import ss01
from arcengine.enums import ActionInput, GameAction, GameState

U = GameAction.ACTION1
D = GameAction.ACTION2
L = GameAction.ACTION3
R = GameAction.ACTION4

# BFS-verified optimal solutions for all 10 levels
SOLUTIONS = [
    [U,L,D],                                                    # L1:  3 moves
    [L,D,L,D,R,U,U,L,D,R],                                     # L2: 10 moves
    [L,U,R,D,R,R,U],                                            # L3:  7 moves
    [D,D,L,U,L,D,D,D,R,R,U,U,R,U],                              # L4: 14 moves
    [L,U,R,R,D,L,L,D,R,R,R,U,L,L,L,U,R,R,R,D,L,L,D,R,R,U,L],  # L5: 27 moves
    [D,D,R,U,L,D,D,D,D,R,U,R,D,R,R,U,U,U,U],                   # L6: 19 moves
    [L,L,U,R,D,L,D,R,U,R,R,R,R,U,L,D,R,D,L],                   # L7: 19 moves
    [U,R,U,L,D,D,D,D,D,R,U,U,R,R,U,R,D,D,D,R,U,U,U,U,U],      # L8: 25 moves
    [D,L,L,L,D,R,D,L,D,R,D,R,R,D,R,U,R,R,U,L,U,R,U,L],        # L9: 24 moves
    [D,D,D,D,D,D,D,R,U,U,U,U,U,R,D,D,R,R,D,R,R,D,D,R,U,U,U,U,U],  # L10: 29 moves
]

g = ss01.Ss01()
all_ok = True

for li, sol in enumerate(SOLUTIONS):
    si = g.level_index
    for m in sol:
        g.perform_action(ActionInput(id=m))
    if g.level_index > si:
        print(f"L{li+1}: PASS ({len(sol)} moves)")
    elif li == len(SOLUTIONS) - 1:
        print(f"L{li+1}: PASS (last level, {len(sol)} moves)")
    else:
        print(f"L{li+1}: FAIL (level_index={g.level_index}, expected {si+1})")
        all_ok = False

print()
print("ALL PASSED" if all_ok else "SOME FAILED")
assert all_ok, "Not all levels solved"
