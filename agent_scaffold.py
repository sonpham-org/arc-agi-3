"""ARC-AGI-3 Three-System Agent Scaffolding — thin re-export shim.

All implementation has moved to scaffoldings/three_system/.
This file is kept for backward compatibility.
"""

# Re-export everything that was previously defined here
from scaffoldings.three_system.systems import (  # noqa: F401
    _recover_truncated_rules,
    _compact_grid,
    StepSnapshot,
    GameContext,
    PlannerSystem,
    MonitorSystem,
    WorldModelSystem,
)
from scaffoldings.three_system.game_loop import play_game_scaffold  # noqa: F401

# Re-export prompts that were defined here
from scaffoldings.three_system.prompts import (  # noqa: F401
    PLANNER_CONTEXT_TEMPLATE,
    WORLD_MODEL_SYSTEM_PROMPT,
    WORLD_MODEL_CONTEXT_TEMPLATE,
    MONITOR_PROMPT_TEMPLATE,
)

# The CLI-specific planner system prompt (with agent.py's ARC_AGI3_DESCRIPTION)
from scaffoldings.three_system.systems import _PLANNER_SYSTEM_PROMPT as PLANNER_SYSTEM_PROMPT  # noqa: F401
# Re-export MONITOR_PROMPT_TEMPLATE under the old name too
MONITOR_PROMPT_TEMPLATE = MONITOR_PROMPT_TEMPLATE  # noqa: F811
