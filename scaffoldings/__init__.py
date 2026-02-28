"""Scaffolding registry — maps scaffolding names to game loop functions."""

from scaffoldings.three_system.game_loop import play_game_scaffold

SCAFFOLDING_REGISTRY = {
    "three_system": play_game_scaffold,
    # "rlm": play_game_rlm,  # future
}
