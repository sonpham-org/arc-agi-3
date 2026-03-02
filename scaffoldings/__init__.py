"""Scaffolding registry — maps scaffolding names to game loop functions."""

from scaffoldings.three_system.game_loop import play_game_scaffold
from scaffoldings.agent_spawn.game_loop import play_game_agent_spawn

SCAFFOLDING_REGISTRY = {
    "three_system": play_game_scaffold,
    "agent_spawn": play_game_agent_spawn,
}
