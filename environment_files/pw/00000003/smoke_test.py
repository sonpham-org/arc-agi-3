# Author: Claude Opus 4.7 (1M context)
# Date: 2026-04-29 10:15
# PURPOSE: Mandatory smoke test for pw01 v3 (thermostat + heat mechanic).
#   Wins all 6 levels deterministically. Same strategy as v2: per
#   attempt, fresh Pw01() fast-forwarded to the target level, click N
#   times then idle. Thermostat is never touched (stays at 0), so the
#   v2 click counts apply unchanged.
# SRP/DRY check: Pass — game-specific test.

import sys
sys.path.insert(0, 'environment_files/pw/00000003')

import pw01
from arcengine.enums import ActionInput, GameAction


def fresh(level: int):
    g = pw01.Pw01()
    if level > 0:
        g.set_level(level)
    return g


def play_with_n_clicks(level: int, n_click: int, max_ticks: int = 400):
    g = fresh(level)
    for i in range(max_ticks):
        if g._state.name in ('WIN', 'GAME_OVER'):
            return g._state.name, i, g
        if g.level_index != level:
            return 'NEXT', i, g
        if i < n_click:
            g.perform_action(ActionInput(id=GameAction.ACTION6,
                                         data={'x': 10, 'y': 30}))
        else:
            g.perform_action(ActionInput(id=GameAction.ACTION7))
    return 'TIMEOUT', max_ticks, g


def find_winning_n(level: int, lo: int, hi: int, step: int = 2,
                   max_ticks: int = 400) -> int | None:
    """Return the first n in [lo, hi] (step) that wins this level, or None."""
    for n in range(lo, hi + 1, step):
        result, used, _g = play_with_n_clicks(level, n, max_ticks)
        if result in ('NEXT', 'WIN'):
            return n
    return None


def main():
    # Tee output to file so background runs capture results even if shell
    # redirection drops stdout.
    import os
    log_path = os.path.join(os.path.dirname(__file__), 'smoke_test.log')
    log = open(log_path, 'w')
    def out(s):
        print(s, flush=True)
        log.write(s + '\n')
        log.flush()

    # Per-level click-count search ranges, picked from the geometry of each
    # level. Search bands are conservative — first hit wins.
    bands = {
        0: (44, 70, 2),     # First Pour — known good ~46
        1: (80, 180, 5),    # To the Brim — nearly full; bigger range
        2: (60, 130, 5),    # Precision
        3: (80, 250, 5),    # Boiling Cup — needs heavy pour
        4: (80, 250, 5),    # Frozen Cup
        5: (80, 250, 5),    # Heat Gauntlet
    }

    found = {}
    for lvl in range(6):
        lo, hi, step = bands[lvl]
        # Levels 4-6 may need more ticks (heat dynamics are slow)
        max_ticks = 400 if lvl < 3 else 800
        n = find_winning_n(lvl, lo, hi, step, max_ticks=max_ticks)
        found[lvl] = n
        out(f'L{lvl+1} ({pw01.LEVEL_DATA[lvl]["name"]}): n_click = {n}')
        if n is None:
            out(f'  NO WINNING n IN RANGE [{lo},{hi}] step {step}')
            return 1

    # Final integration run: play all 6 levels back-to-back with the
    # discovered per-level click counts on a single game instance.
    out('')
    out('Final integration run (single game, all 6 levels):')
    g = pw01.Pw01()
    for lvl in range(6):
        n = found[lvl]
        # Click n times, then idle until level changes or terminal state.
        idle_budget = 400 if lvl < 3 else 800
        start_lvl = g.level_index
        # Click phase
        for _ in range(n):
            if g._state.name in ('WIN', 'GAME_OVER') or g.level_index != start_lvl:
                break
            g.perform_action(ActionInput(id=GameAction.ACTION6,
                                         data={'x': 10, 'y': 30}))
        # Idle phase
        for _ in range(idle_budget):
            if g._state.name in ('WIN', 'GAME_OVER') or g.level_index != start_lvl:
                break
            g.perform_action(ActionInput(id=GameAction.ACTION7))
        out(f'  L{lvl+1} -> level_index={g.level_index} state={g._state.name} '
            f'lives={g.lives}')

    out('')
    out(f'Final state: {g._state.name}')
    if g._state.name == 'WIN':
        out('SMOKE TEST PASSED (all 6 levels won)')
        log.close()
        return 0
    out(f'SMOKE TEST FAILED (final state {g._state.name})')
    log.close()
    return 1


if __name__ == '__main__':
    sys.exit(main())
