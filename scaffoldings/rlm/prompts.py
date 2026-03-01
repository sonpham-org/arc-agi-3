"""RLM prompt templates and regex patterns."""

import re
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent.parent.parent / "prompts" / "rlm"
_RLM_SYSTEM_PROMPT_TEMPLATE = (_PROMPT_DIR / "system_prompt.txt").read_text()


def build_rlm_system_prompt(planning_horizon: int = 1) -> str:
    """Build the RLM system prompt with planning horizon."""
    if planning_horizon > 1:
        plan_instructions = (
            f"For multi-step plans (up to {planning_horizon} steps ahead):\n"
            f"  FINAL({{\"plan\": [{{\"action\": <int>, \"observation\": \"...\"}}, ...], \"reasoning\": \"...\"}})\n"
            f"Plan up to {planning_horizon} steps ahead if the next moves are obvious.\n\n"
        )
    else:
        plan_instructions = ""
    return _RLM_SYSTEM_PROMPT_TEMPLATE.format(plan_instructions=plan_instructions)


# Default for backward compatibility
RLM_SYSTEM_PROMPT = build_rlm_system_prompt(1)

RLM_USER_PROMPT_FIRST = (_PROMPT_DIR / "user_first.txt").read_text()

RLM_USER_PROMPT_CONTINUE = (_PROMPT_DIR / "user_continue.txt").read_text()

# RLM REPL sessions — separate from tool sessions, include llm_query etc.
RLM_REPL_CODE_PATTERN = re.compile(r"```repl\s*\n(.*?)\n```", re.DOTALL)
RLM_FINAL_PATTERN = re.compile(r"^\s*FINAL\((.+)\)\s*$", re.MULTILINE | re.DOTALL)
RLM_FINAL_VAR_PATTERN = re.compile(r"^\s*FINAL_VAR\((\w+)\)", re.MULTILINE)
