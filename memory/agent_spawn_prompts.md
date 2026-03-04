# Agent Spawn Prompt Architecture

## Orchestrator Inputs (per turn, stateless — rebuilt each time)

| Input | Variable | Source |
|-------|----------|--------|
| Game ID | `{game_id}` | `_cur.currentState.game_id` |
| Step number | `{step_num}` | `_cur.stepCount` |
| Level progress | `{levels_done} / {win_levels}` | `currentState.levels_completed/win_levels` |
| Game state | `{state_str}` | `PLAYING`, `WIN`, or `GAME_OVER` |
| Available actions | `{action_desc}` | e.g. `0=RESET, 1=MOVE_UP, 2=MOVE_DOWN` |
| Grid | `{grid_block}` | RLE-compressed rows with color names |
| Change map | `{change_map_block}` | Diff from previous grid |
| Shared memories | `{memories}` | Facts, hypotheses, agent report stack |
| Recent history | `{history_block}` | Last N steps with grid + change map per step |

Static prefix: `AS_ORCHESTRATOR_PREMISE` + `AS_GAME_REFERENCE`

### Orchestrator Commands
- `delegate`: reasoning, agent_type, task, budget
- `think`: reasoning, facts[], hypotheses[], next

## Subagent Inputs (multi-turn conversation, stateful)

**System message (sent once):** role-specific prompt (`AS_AGENT_SYSTEM[type]`) + `AS_GAME_REFERENCE`

**First user message (`AS_AGENT_TURN`):**

| Input | Variable | Source |
|-------|----------|--------|
| Task | `{task}` | From orchestrator's delegation |
| Step + budget | `{step_num}`, `{budget_remaining}/{budget_total}` | Current step, remaining action budget |
| Level progress | `{levels_done} / {win_levels}` | Same as orchestrator |
| Game state | `{state_str}` | Same |
| Available actions | `{action_desc}` | Same |
| Grid | `{grid_block}` | Current RLE grid |
| Change map | `{change_map_block}` | Diff from last action |
| Shared memories | `{memories}` | Same pool as orchestrator |
| Session history | `{session_history}` | This subagent's own actions so far |
| Tool results | `{tool_results}` | Last frame_tool output |

**Subsequent turns:** Action results, updated grid, budget status appended as user messages. LLM retains full reasoning chain.

### Subagent Commands
- `act`: action, data, reasoning
- `frame_tool`: tool name, args (FREE, no budget cost)
- `report`: findings[], hypotheses[], summary

## Agent Types
- **explorer**: tries all actions, reports what each does. Has game actions.
- **theorist**: analysis only, NO game actions. Uses frame_tool + report.
- **tester**: tests specific hypothesis with minimal actions (1-3).
- **solver**: executes a validated strategy efficiently.

## Key Settings
- `orchestrator_max_turns`: max think/delegate cycles per invocation (default 5)
- `max_subagent_budget`: cap on game actions per subagent (default 5)
- `orchestrator_history_length`: how many recent steps to include in history (default 15)
- Thinking budgets: orchestrator=high (8192), subagents=med (4096)
- Color palette: 16 colors (White, LightGray, Gray, DarkGray, VeryDarkGray, Black, Magenta, LightMagenta, Red, Blue, LightBlue, Yellow, Orange, Maroon, Green, Purple)

## Prompt Continuation
Subagents use multi-turn conversation (messages array grows). Orchestrator is stateless (fresh prompt each turn). RLM scaffolding also uses multi-turn for comparison.
