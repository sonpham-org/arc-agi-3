#!/usr/bin/env python3
"""Difficulty analysis for Sneeze game.

Tests every possible starting person on every level to compute
the percentage of choices that lead to a win.

Usage:
    python test_difficulty.py
"""
import sys
sys.path.insert(0, '.')
import importlib
import sn
importlib.reload(sn)
from arcengine.enums import ActionInput, GameAction, GameState


def test_level(lvl_idx):
    ldef = sn.LEVELS[lvl_idx]
    g = sn.Sn()
    g.set_level(lvl_idx)
    total = len(g._people)
    clickable = 0
    winners = 0

    for si in range(total):
        g2 = sn.Sn()
        g2.set_level(lvl_idx)
        p = g2._people[si]
        if p['type'] in (sn.TYPE_DOCTOR, sn.TYPE_QUARAN):
            continue
        clickable += 1

        cx = int(p['x']) + 2
        cy = int(p['y']) + sn.HUD_H

        # perform_action runs the entire multi-frame simulation internally
        r = g2.perform_action(ActionInput(id=GameAction.ACTION6, data={'x': cx, 'y': cy}))

        # Win detection: level advanced (levels 1-6) or state is WIN (level 7)
        if g2.level_index != lvl_idx or r.state == GameState.WIN:
            winners += 1

    return clickable, winners


if __name__ == '__main__':
    targets = [80, 70, 60, 50, 40, 25, 10]
    print('Sneeze Game - Difficulty Analysis')
    print('=' * 65)

    for lvl_idx in range(len(sn.LEVELS)):
        ldef = sn.LEVELS[lvl_idx]
        clickable, winners = test_level(lvl_idx)
        pct = 100 * winners / clickable if clickable > 0 else 0
        target = targets[lvl_idx] if lvl_idx < len(targets) else '?'
        bar = '#' * int(pct / 5) + '.' * (20 - int(pct / 5))
        total = sum(c for _, c in ldef['type_counts'])
        print(f'L{lvl_idx+1} {ldef["name"]:20s} ({total:3d}p) [{bar}] {pct:4.0f}% (target ~{target}%)')

    print()
    print('Done!')
