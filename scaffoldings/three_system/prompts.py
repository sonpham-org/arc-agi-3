"""Unified prompt templates for the Three-System scaffolding (CLI + web).

Note: ARC_AGI3_DESCRIPTION is NOT imported here to avoid circular imports.
Callers must prepend it to PLANNER_SYSTEM_PROMPT_BODY when building prompts.
All prompts are loaded from prompts/three_system/*.txt files.
"""

from pathlib import Path

_PROMPT_DIR = Path(__file__).parent.parent.parent / "prompts" / "three_system"

# ═══════════════════════════════════════════════════════════════════════════
# PLANNER PROMPTS
# ═══════════════════════════════════════════════════════════════════════════

# Prepend ARC_AGI3_DESCRIPTION + "\n\n" to this when building the full prompt
PLANNER_SYSTEM_PROMPT_BODY = (_PROMPT_DIR / "planner_system.txt").read_text()

# Variant without World Model (for 2-System scaffolding)
PLANNER_SYSTEM_PROMPT_BODY_NO_WM = (_PROMPT_DIR / "planner_system_no_wm.txt").read_text()

PLANNER_CONTEXT_TEMPLATE_NO_WM = (_PROMPT_DIR / "planner_context_no_wm.txt").read_text()

PLANNER_CONTEXT_TEMPLATE = (_PROMPT_DIR / "planner_context.txt").read_text()


# ═══════════════════════════════════════════════════════════════════════════
# WORLD MODEL PROMPTS
# ═══════════════════════════════════════════════════════════════════════════

WORLD_MODEL_SYSTEM_PROMPT = (_PROMPT_DIR / "wm_system.txt").read_text()

WORLD_MODEL_CONTEXT_TEMPLATE = (_PROMPT_DIR / "wm_context.txt").read_text()


# ═══════════════════════════════════════════════════════════════════════════
# MONITOR PROMPTS
# ═══════════════════════════════════════════════════════════════════════════

MONITOR_PROMPT_TEMPLATE = (_PROMPT_DIR / "monitor.txt").read_text()
