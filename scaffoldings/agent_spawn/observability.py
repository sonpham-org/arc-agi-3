"""Agent observability — live status file + JSONL event log for monitoring long runs."""

import json
import os
import time
from pathlib import Path

# Default output directory for observability files
OBS_DIR = Path(".agent_obs")


class AgentObserver:
    """Writes a live status JSON file and appends JSONL events for agent runs.

    Usage:
        obs = AgentObserver(game_id="ls20", max_steps=50)
        obs.event("game_start", model="gemini-2.5-flash")
        obs.update_status(step=1, turn=1, ...)
        obs.event("act", agent="explorer", action="MOVE_RIGHT", ...)
        obs.close("WIN")

    Files written:
        .agent_obs/status.json     — overwritten each update, `watch cat` friendly
        .agent_obs/events.jsonl    — append-only, one JSON line per event
        .agent_obs/memory.json     — periodic memory dump
    """

    def __init__(self, game_id: str, max_steps: int, session_id: str = ""):
        self.game_id = game_id
        self.max_steps = max_steps
        self.session_id = session_id
        self.start_time = time.time()

        # Ensure output directory exists
        OBS_DIR.mkdir(exist_ok=True)

        self.status_path = OBS_DIR / "status.json"
        self.events_path = OBS_DIR / "events.jsonl"
        self.memory_path = OBS_DIR / "memory.json"
        self.grid_path = OBS_DIR / "grid.json"

        # Clear previous events file for this run
        self.events_path.write_text("")

        # Write initial status
        self._status = {
            "game": game_id,
            "session_id": session_id,
            "step": 0,
            "max_steps": max_steps,
            "level": "0/?",
            "turn": 0,
            "state": "STARTING",
            "elapsed_min": 0.0,
            "total_llm_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "current_agent": None,
            "current_task": None,
            "memory_facts": 0,
            "memory_hypotheses": 0,
            "memory_observations": 0,
            "last_event": "game_start",
        }
        self._write_status()
        self.event("game_start")

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())

    def _elapsed_min(self) -> float:
        return round((time.time() - self.start_time) / 60, 1)

    def _write_status(self):
        """Overwrite status.json with current state."""
        self._status["elapsed_min"] = self._elapsed_min()
        try:
            self.status_path.write_text(json.dumps(self._status, indent=2) + "\n")
        except Exception:
            pass  # non-fatal

    def event(self, event_type: str, **kwargs):
        """Append a single event line to events.jsonl."""
        entry = {
            "t": self._now(),
            "elapsed_s": round(time.time() - self.start_time, 1),
            "event": event_type,
            **kwargs,
        }
        try:
            with open(self.events_path, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass  # non-fatal

        self._status["last_event"] = event_type
        self._write_status()

    def update_status(self, **kwargs):
        """Update status fields and rewrite status.json."""
        self._status.update(kwargs)
        self._write_status()

    def orchestrator_decide(self, turn: int, step: int, command: str,
                            agent_type: str = "", task: str = "",
                            input_tokens: int = 0, output_tokens: int = 0,
                            duration_ms: int = 0, response: str = ""):
        """Log an orchestrator decision."""
        self.update_status(
            turn=turn,
            step=step,
            current_agent="orchestrator",
            current_task=f"{command}: {task[:80]}" if task else command,
        )
        self.event(
            "orchestrator_decide",
            turn=turn, step=step, command=command,
            agent_type=agent_type, task=task[:120],
            input_tokens=input_tokens, output_tokens=output_tokens,
            duration_ms=duration_ms,
            response=response,
        )

    def subagent_start(self, agent_type: str, task: str, budget: int, step: int,
                       available_actions: str = "", level: str = "",
                       memory_summary: str = ""):
        """Log subagent spawn."""
        self.update_status(
            current_agent=agent_type,
            current_task=task[:80],
        )
        self.event(
            "subagent_start",
            agent_type=agent_type, task=task[:200], budget=budget, step=step,
            available_actions=available_actions,
            level=level,
            memory_summary=memory_summary[:500] if memory_summary else "",
        )

    def subagent_act(self, agent_type: str, step: int, action: str,
                     state: str, reasoning: str = "",
                     input_tokens: int = 0, output_tokens: int = 0,
                     duration_ms: int = 0, grid=None, response: str = ""):
        """Log a subagent game action."""
        self.update_status(step=step)
        extra = {}
        if grid is not None:
            extra["grid"] = grid
        self.event(
            "act",
            agent=agent_type, step=step, action=action, state=state,
            reasoning=reasoning,
            input_tokens=input_tokens, output_tokens=output_tokens,
            duration_ms=duration_ms,
            response=response,
            **extra,
        )

    def subagent_frame_tool(self, agent_type: str, tool_name: str):
        """Log a frame tool usage (free, no step cost)."""
        self.event("frame_tool", agent=agent_type, tool=tool_name)

    def subagent_report(self, agent_type: str, steps_used: int, llm_calls: int,
                        findings: int, hypotheses: int, summary: str = ""):
        """Log subagent completion."""
        self.update_status(current_agent=None, current_task=None)
        self.event(
            "subagent_report",
            agent_type=agent_type, steps_used=steps_used, llm_calls=llm_calls,
            findings=findings, hypotheses=hypotheses, summary=summary[:120],
        )

    def update_memory_stats(self, memories):
        """Update status with current memory sizes."""
        self.update_status(
            memory_facts=len(memories.facts),
            memory_hypotheses=len(memories.hypotheses),
            memory_observations=len(memories.observations),
        )

    def dump_memory(self, memories):
        """Write full memory state to memory.json for inspection."""
        try:
            dump = {
                "t": self._now(),
                "facts": memories.facts,
                "hypotheses": memories.hypotheses,
                "observations": [
                    {k: v for k, v in obs.items() if k not in ("grid_before", "grid_after")}
                    for obs in memories.observations
                ],
                "stack": memories.stack,
            }
            self.memory_path.write_text(json.dumps(dump, indent=2, default=str) + "\n")
        except Exception:
            pass

    def update_grid(self, grid: list):
        """Write current game grid to grid.json for dashboard visualization."""
        try:
            self.grid_path.write_text(json.dumps(grid))
        except Exception:
            pass

    def update_level(self, levels_done: int, win_levels: int):
        """Update level progress in status."""
        self.update_status(level=f"{levels_done}/{win_levels}")

    def update_totals(self, total_llm_calls: int,
                      total_input_tokens: int = 0, total_output_tokens: int = 0):
        """Update cumulative totals."""
        self.update_status(
            total_llm_calls=total_llm_calls,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
        )

    def close(self, result: str):
        """Final event — game over."""
        self.update_status(state=result, current_agent=None, current_task=None)
        self.event("game_end", result=result, elapsed_min=self._elapsed_min())
