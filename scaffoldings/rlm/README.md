# RLM (Recursive Language Model) Scaffolding

## Overview

The RLM scaffolding gives the LLM a REPL environment to iteratively analyze the game state and decide on actions. It supports recursive sub-LLM queries via `llm_query()` and batched queries via `llm_query_batched()`.

## Architecture

```
Web UI (index.html)
  │
  ▼ POST /api/llm
  │
server.py ─► _handle_rlm_scaffolding()
  │              │
  │              ▼  (dependency injection)
  │     scaffoldings/rlm/handler.py
  │         └── handle_rlm_scaffolding()
  │              ├── create_rlm_repl()     ← repl.py
  │              ├── rlm_execute_code()    ← repl.py
  │              └── rlm_find_final()      ← repl.py
  │
  └── prompts.py: RLM_SYSTEM_PROMPT, RLM_USER_PROMPT_*, regex patterns
```

## Files

| File | Purpose |
|------|---------|
| `prompts.py` | System/user prompt templates and regex patterns for parsing REPL blocks and FINAL() calls |
| `repl.py` | REPL environment creation (`create_rlm_repl`), code execution (`rlm_execute_code`), and final answer detection (`rlm_find_final`) |
| `handler.py` | Web UI handler that runs the full iteration loop: call LLM → extract code blocks → execute → check for FINAL → repeat |

## How It Works

1. **REPL Environment** is created with a `context` dict (grid, history, actions, etc.) and injected functions (`llm_query`, `SHOW_VARS`, `FINAL_VAR`)
2. **Iteration Loop** sends the conversation to the main model, which responds with `\`\`\`repl` code blocks
3. **Code Execution** runs each code block in a sandboxed namespace with a timeout
4. **Sub-LLM Calls** are available via `llm_query(prompt)` and `llm_query_batched(prompts)` for the LLM to delegate analysis
5. **Final Answer** is detected when the LLM writes `FINAL({json})` or `FINAL_VAR(variable_name)` outside a code block
6. The final JSON is parsed and returned in the standard response format

## Dependency Injection

The handler receives server.py functions as keyword arguments to avoid circular imports:
- `route_model_call` → `server._route_model_call`
- `log_llm_call` → `db._log_llm_call`
- `extract_json` → `server._extract_json`
- `safe_import` → `server._safe_import`

## Status

- **Web UI**: Supported (via `/api/llm` with `settings.scaffolding = "rlm"`)
- **CLI/Batch**: Not yet supported (no `play_game_rlm()` game loop)
