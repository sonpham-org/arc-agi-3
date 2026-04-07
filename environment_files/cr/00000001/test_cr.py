#!/usr/bin/env python3
"""Smoke test for cr - Crumbling Route. Solves all 10 levels."""
import sys
sys.path.insert(0, 'environment_files/cr/00000001')
import cr
from arcengine.enums import ActionInput, GameAction, GameState

U = GameAction.ACTION1  # up
D = GameAction.ACTION2  # down
L = GameAction.ACTION3  # left
R = GameAction.ACTION4  # right

g = cr.Cr()

def A(a):
    return g.perform_action(ActionInput(id=a))

def play(moves, lvl):
    si = g.level_index
    for i, m in enumerate(moves):
        r = A(m)
        if r.state == GameState.WIN:
            print(f"L{lvl}: WIN after {i+1} steps")
            return True
        if r.state == GameState.GAME_OVER:
            print(f"L{lvl}: GAME OVER at step {i+1}, pos={g.player_pos}, k={g.keys_collected}/{g.keys_total}")
            return False
    if g.level_index > si:
        print(f"L{lvl}: OK (advanced to L{g.level_index+1}) in {len(moves)} steps")
        return True
    print(f"L{lvl}: STUCK pos={g.player_pos} keys={g.keys_collected}/{g.keys_total} rem={g.remaining_keys}")
    return False

results = []

# L1: 4x3, start(0,0), key(1,1), exit(3,2)
results.append(play([R, D, D, R, R], 1))

# L2: 5x3, start(0,0), keys(3,0),(1,2), exit(4,2)
results.append(play([D, D, R, R, R, U, U, R, D, D], 2))

# L3: 6x5, start(0,0), keys(3,1),(1,3),(3,4), exit(5,4)
results.append(play([D, D, R, D, D, R, R, U, U, U, R, R, D, D, D], 3))

# L4: 7x5, start(0,0), keys(6,0),(0,4),(6,1),(3,4), exit(6,4)
results.append(play([R,R,R,R,R,R, D,D, L,L,L,L,L,L, D,D, R,R,R,R,R,R], 4))

# L5: 6x4, start(0,0), keys(5,0),(0,3), exit(5,3)
results.append(play([D,D,D, R,R,R, U,U,U, R,R, D,D,D], 5))

# L6: 7x5, start(0,0), keys(6,0),(0,4),(6,4), exit(3,4)
results.append(play([D,D,D,D, R,R, U,U,U,U, R,R,R,R, D,D,D,D, L,L,L], 6))

# L7: 8x5, start(0,0), keys(0,4),(7,0), exit(7,4), tp(3,2)<->(5,2)
# Path: D*4(0,4)[key], R*3(3,4), U*2(3,2)[tp->5,2], U*2(5,0), R*2(7,0)[key], D*4(7,4)[exit]
results.append(play([D,D,D,D, R,R,R, U,U, U,U, R,R, D,D,D,D], 7))

# L8: 10x6, three islands, tp(2,0)<->(4,0) and tp(6,5)<->(8,0)
# keys(0,5),(4,5),(9,0), exit(9,5)
# Path: D*5(0,5)[key], R*2(2,5), U*5(2,0)[tp->4,0], D*5(4,5)[key],
#   R*2(6,5)[tp->8,0], R(9,0)[key], D*5(9,5)[exit]
results.append(play([
    D,D,D,D,D,       # (0,5)[key]
    R,R,               # (2,5)
    U,U,U,U,U,        # (2,0)[tp->4,0]
    D,D,D,D,D,        # (4,5)[key]
    R,R,               # (6,5)[tp->8,0]
    R,                  # (9,0)[key]
    D,D,D,D,D,        # (9,5)[exit]
], 8))

# L9: 10x7, keys(9,0),(5,3),(0,3),(0,6), exit(9,6)
# Pure S-shape: R*9(9,0)[key], D*3(9,3), L*4(5,3)[key], L*5(0,3)[key],
#   D*3(0,6)[key], R*9(9,6)[exit]
results.append(play([
    R,R,R,R,R,R,R,R,R,  # (9,0)[key]
    D,D,D,                # (9,3)
    L,L,L,L,              # (5,3)[key]
    L,L,L,L,L,            # (0,3)[key]
    D,D,D,                # (0,6)[key]
    R,R,R,R,R,R,R,R,R,   # (9,6)[exit]
], 9))

# L10: 10x8, keys(9,0),(0,2),(0,5),(9,5),(9,7), exit(4,7), tp(4,2)<->(4,4)
# Path: R*9(9,0)[key], D*2(9,2), L*9(0,2)[key], D*3(0,5)[key],
#   R*9(9,5)[key], D*2(9,7)[key], L*5(4,7)[exit]
results.append(play([
    R,R,R,R,R,R,R,R,R,  # (9,0)[key]
    D,D,                   # (9,2)
    L,L,L,L,L,L,L,L,L,  # (0,2)[key]
    D,D,D,                # (0,5)[key]
    R,R,R,R,R,R,R,R,R,  # (9,5)[key]
    D,D,                   # (9,7)[key]
    L,L,L,L,L,            # (4,7)[exit]
], 10))

print()
if all(results):
    print("ALL 10 LEVELS PASSED!")
    sys.exit(0)
else:
    failed = [i+1 for i, r in enumerate(results) if not r]
    print(f"FAILED levels: {failed}")
    sys.exit(1)
