"""Shared memories — persistent knowledge store across agent lifetimes."""

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SharedMemories:
    """Thread-safe shared memory for orchestrator and subagents.

    Stores facts, hypotheses, observations, action log, and a stack of
    agent reports discovered during gameplay.
    All agents read/write through this single instance.
    """
    facts: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    observations: list[dict] = field(default_factory=list)
    action_log: list[dict] = field(default_factory=list)
    stack: list[dict] = field(default_factory=list)

    def add_fact(self, fact: str) -> None:
        if fact and fact not in self.facts:
            self.facts.append(fact)

    def add_hypothesis(self, hypothesis: str) -> None:
        if hypothesis and hypothesis not in self.hypotheses:
            self.hypotheses.append(hypothesis)

    def add_observation(self, step: int, action: int, observation: str,
                        grid_before: list | None = None, grid_after: list | None = None) -> None:
        self.observations.append({
            "step": step,
            "action": action,
            "observation": observation,
            "grid_before": grid_before,
            "grid_after": grid_after,
        })

    def log_action(self, step: int, action: int, data: dict | None,
                   agent: str, reasoning: str) -> None:
        self.action_log.append({
            "step": step,
            "action": action,
            "data": data or {},
            "agent": agent,
            "reasoning": reasoning,
        })

    def add_to_stack(self, summary: str, details: str, agent_type: str) -> None:
        """Push an agent report onto the memory stack."""
        self.stack.append({
            "summary": summary,
            "details": details,
            "agent_type": agent_type,
            "timestamp": time.time(),
        })

    def format_for_prompt(self, max_observations: int = 20) -> str:
        """Format memories as a text block for LLM prompts."""
        parts = []

        if self.facts:
            parts.append("## Confirmed Facts")
            for i, f in enumerate(self.facts[-5:], 1):
                parts.append(f"  {i}. {f}")
            if len(self.facts) > 5:
                parts.append(f"  (... {len(self.facts) - 5} earlier facts omitted)")

        if self.hypotheses:
            parts.append("## Hypotheses")
            for i, h in enumerate(self.hypotheses[-5:], 1):
                parts.append(f"  {i}. {h}")
            if len(self.hypotheses) > 5:
                parts.append(f"  (... {len(self.hypotheses) - 5} earlier hypotheses omitted)")

        if self.stack:
            recent_stack = self.stack[-8:]
            parts.append(f"## Agent Report Stack (last {len(recent_stack)})")
            for i, entry in enumerate(recent_stack, 1):
                parts.append(f"  [{i}] ({entry['agent_type']}) {entry['summary']}")
                if entry.get("details"):
                    # Indent details, truncate long ones
                    detail_lines = entry["details"][:200]
                    parts.append(f"      {detail_lines}")

        if self.observations:
            recent = self.observations[-max_observations:]
            parts.append(f"## Recent Observations (last {len(recent)})")
            for obs in recent:
                parts.append(f"  Step {obs['step']}: action={obs['action']} -> {obs['observation']}")

        return "\n".join(parts) if parts else "(no memories yet)"
