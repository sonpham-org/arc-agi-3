# Three-System Scaffolding (Planner / Monitor / World Model)

## Overview

The Three-System scaffolding splits the agent into three specialized LLM-powered systems that collaborate to play games:

1. **Planner** — Decides what actions to take. Can simulate actions, analyze the grid, or commit an action plan.
2. **Monitor** — Checks each executed step against expectations. Can trigger replanning if results diverge.
3. **World Model** — Builds and maintains a rules document describing how the game works. Supports historical queries.

## Architecture

```
                    ┌─────────────────────────┐
                    │      Planner System      │
                    │  simulate / analyze /    │
                    │  commit action plans     │
                    └───────┬─────────────────┘
                            │ plan
                    ┌───────▼─────────────────┐
                    │      Executor            │
                    │  runs each plan step     │
                    └───────┬─────────────────┘
                            │ per step
                ┌───────────┴──────────────┐
                ▼                          ▼
    ┌───────────────────┐     ┌────────────────────┐
    │  Monitor System   │     │  World Model System │
    │  CONTINUE/REPLAN  │     │  rules document     │
    │  discovery notes  │     │  simulate()         │
    └───────────────────┘     └────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `prompts.py` | Unified prompt templates shared between CLI and web UI. Note: `ARC_AGI3_DESCRIPTION` is NOT imported here — callers prepend it to avoid circular imports. |
| `systems.py` | Core classes (`PlannerSystem`, `MonitorSystem`, `WorldModelSystem`) + dataclasses (`StepSnapshot`, `GameContext`) + utilities (`_recover_truncated_rules`, `_compact_grid`). Used by the CLI/batch path. Imports from `agent.py`. |
| `game_loop.py` | `play_game_scaffold()` — the CLI/batch game loop. Drop-in replacement for `agent.play_game()` with the same interface. |
| `handler.py` | Web UI handler functions: `handle_three_system_scaffolding()`, `ts_get_state()`, `ts_run_wm_update()`, `ts_simulate_actions()`, etc. Uses dependency injection for server.py functions. |

## Two Code Paths

### CLI/Batch Path (`systems.py` + `game_loop.py`)

Used by `batch_runner.py` and direct CLI invocation:
```python
from scaffoldings.three_system.game_loop import play_game_scaffold
result = play_game_scaffold(arcade, game_id, cfg, max_steps=200)
```

- Classes instantiate directly and call `agent.call_model_with_retry()`
- Uses `agent.py`'s `ARC_AGI3_DESCRIPTION` (baked in at import time)
- Self-contained game loop with plan-execute-monitor cycle

### Web UI Path (`handler.py`)

Used by `server.py` route handlers:
```python
result = handle_three_system_scaffolding(
    payload, settings,
    route_model_call=_route_model_call,
    log_llm_call=_log_llm_call,
    extract_json=_extract_json,
    action_names=ACTION_NAMES,
    ...
)
```

- Receives server.py dependencies via injection (no circular imports)
- Uses `server.py`'s `ARC_AGI3_DESCRIPTION` (passed as parameter)
- Stateful per-session (via `_three_system_state` dict)
- Separate routes for monitor (`/api/llm/monitor`) and observe (`/api/three_system/observe`)

## Dependency Injection (Web UI)

The web handlers need server.py functions but can't import them at module level (circular import). Instead, the thin wrappers in `server.py` pass them as keyword arguments:

| Dependency | Source |
|-----------|--------|
| `route_model_call` | `server._route_model_call` |
| `log_llm_call` | `db._log_llm_call` |
| `extract_json` | `server._extract_json` |
| `action_names` | `server.ACTION_NAMES` |
| `compress_row` | `server.compress_row` |
| `compute_change_map` | `server.compute_change_map` |
| `compute_color_histogram` | `server.compute_color_histogram` |
| `compute_region_map` | `server.compute_region_map` |
| `arc_agi3_description` | `server.ARC_AGI3_DESCRIPTION` |

## Config Keys

Under `cfg["scaffolding"]`:

| Key | Default | Description |
|-----|---------|-------------|
| `planner_max_turns` | 10 | Max REPL turns for the planner |
| `max_plan_length` | 15 | Max actions per committed plan |
| `min_plan_length` | 3 | Min actions (padded with exploratory if shorter) |
| `world_model_update_every` | 5 | Steps between WM rule updates |
| `world_model_max_turns` | 5 | Max REPL turns for WM updates |

## Status

- **Web UI**: Supported (via `/api/llm` with `settings.scaffolding = "three_system"`)
- **CLI/Batch**: Supported (via `batch_runner.py --scaffold three_system` or config)
