"""RLM prompt templates and regex patterns."""

import re

RLM_SYSTEM_PROMPT = """\
You are tasked with answering a query about a game environment. You can access, transform, \
and analyze the game context interactively in a REPL environment that can recursively query \
sub-LLMs. You will be queried iteratively until you provide a final answer.

The REPL environment is initialized with:
1. A `context` variable (dict) containing the full game state: grid, history, change_map, \
available_actions, levels_completed, win_levels, game_id, compact_context.
2. `llm_query(prompt) -> str` — fast single LLM call for analysis/reasoning.
3. `llm_query_batched(prompts) -> list[str]` — concurrent batch of llm_query calls.
4. `SHOW_VARS()` — lists all variables you've created in the REPL.
5. `print()` to view REPL output.

Write code in ```repl blocks (not ```python). Variables persist across iterations.

When you have determined the best action, call FINAL() with a JSON object:
  FINAL({"action": <int>, "reasoning": "...", "observation": "..."})

For multi-step plans:
  FINAL({"plan": [{"action": <int>, "observation": "..."}, ...], "reasoning": "..."})

Or use FINAL_VAR(variable_name) to return a variable containing the JSON.

IMPORTANT: The action must be one of the available_actions integers. \
Do NOT provide a final answer until you have analyzed the game state."""

RLM_USER_PROMPT_FIRST = """\
Your game context is stored in the `context` variable (dict). It contains:
- context['grid']: 2D list of color values (the current game board)
- context['available_actions']: list of valid action integers
- context['history']: recent move history
- context['change_map']: cells that changed since last action
- context['levels_completed']: current progress
- context['win_levels']: target levels to win
- context['compact_context']: summarized game knowledge (if available)

Think step-by-step about what to do using the REPL environment to analyze the game state \
and determine the best action. Start by examining the context."""

RLM_USER_PROMPT_CONTINUE = """\
Continue using the REPL environment to analyze the game context and determine your next action. \
Your next action:"""

# RLM REPL sessions — separate from tool sessions, include llm_query etc.
RLM_REPL_CODE_PATTERN = re.compile(r"```repl\s*\n(.*?)\n```", re.DOTALL)
RLM_FINAL_PATTERN = re.compile(r"^\s*FINAL\((.+)\)\s*$", re.MULTILINE | re.DOTALL)
RLM_FINAL_VAR_PATTERN = re.compile(r"^\s*FINAL_VAR\((\w+)\)", re.MULTILINE)
