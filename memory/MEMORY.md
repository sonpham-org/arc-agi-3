# ARC-AGI-3 Agent — Hard Memory
# ─────────────────────────────────────────────────────────────────────────────
# This file is read at the start of every game and injected into the agent's
# context.  The agent (and the post-game reflector) can append new bullets here
# as it learns rules, strategies, and game-specific knowledge.
#
# Format:  one bullet per fact.  Keep bullets short (≤ 120 chars).
# Sections:  ## General  /  ## <game_id>  /  ## Strategies
# ─────────────────────────────────────────────────────────────────────────────

## General

### Action Mappings (universal across all games)
- ACTION1 = Move UP (or equivalent upward/north action)
- ACTION2 = Move RIGHT (or equivalent rightward/east action)
- ACTION3 = Move DOWN (or equivalent downward/south action)
- ACTION4 = Move LEFT (or equivalent westward/west action)
- ACTION5 = Context-dependent (cycle, toggle, interact, confirm — varies by game)
- ACTION6 = CLICK at (x, y) coordinates — used for selecting, placing, or interacting with specific cells
- ACTION7 = Context-dependent (secondary interact, rotate, swap — varies by game)
- ACTION0 = RESET — restarts the current level. Use only as last resort or help optimize the goal.

### Game Mechanics
- States: NOT_FINISHED (playing), WIN (all levels done), GAME_OVER (failed)
- Completing a level often triggers a grid reset — note what persists vs resets
- You can lose by running out of lives, energy, moves, or time-based counters

## Strategies

- The goal is to finish the game (WIN) in the fewest steps possible
- If no visible changes occur from an action, try a different action or approach
- Pay attention to color changes — they often signal progress or state transitions

## ls20
- The player is represented by white pixel (0) and there is a light gray companion (1).
- The game involves navigating a maze where dark gray (3) are paths and black are walls.
- ACTION4 does not result in player movement, suggesting it might be a 'stay' action or an attempt to move into an obstacle.
- ACTION2 moves the player by a fixed distance (e.g., 3 units in a cardinal direction).
- Player (0) and companion (1) move together. Companion is typically one step down and one step left relative to the player.
- Player (0) and companion (1) move in tandem or relative to each other. Maze navigation is key. Yellow bar (11) is a potential goal.
- Player (0) is at (31,21), Light Gray (1) at (32,20). Previous ACTION4s did not move player. RLE grid is source of truth for positions.
- Player is a 3x3 blue (9) block. Change map in rows 61-62 is not player movement, likely a status bar or other game element.
- The change map might not always reflect player movement directly, or there might be multiple moving entities. Player is a blue (9) object, likely 3x3 in shape, navigating a DarkGray (3) maze with Black (5) and VeryDarkGray (4) walls.

## ft09

## vc33

## ls20-cb3b57cc
