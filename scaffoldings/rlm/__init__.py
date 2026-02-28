"""RLM (Recursive Language Model) scaffolding package."""

from scaffoldings.rlm.prompts import (
    RLM_SYSTEM_PROMPT,
    RLM_USER_PROMPT_FIRST,
    RLM_USER_PROMPT_CONTINUE,
    RLM_REPL_CODE_PATTERN,
    RLM_FINAL_PATTERN,
    RLM_FINAL_VAR_PATTERN,
)
from scaffoldings.rlm.repl import create_rlm_repl, rlm_execute_code, rlm_find_final
from scaffoldings.rlm.handler import handle_rlm_scaffolding
