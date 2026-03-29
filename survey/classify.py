# Author: Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-29 13:15
# PURPOSE: Instinct classification logic for ARC-AGI-3 survey. Analyzes per-game
#   session data (action distribution, LLM reasoning text) to assign an instinct
#   category. Categories ranked by specificity (highest priority first):
#     partial_solver > hypothesis_driven > systematic_explorer >
#     directional_mover > action5_spammer > random_clicker > frozen
#   Also detects strategy phases by action shift points and computes change
#   awareness ratio from reasoning text.
#   Dependencies: None (pure functions, takes dicts as input).
# SRP/DRY check: Pass — classification only. DB reads in report_generator.py.
"""Instinct classification for ARC-AGI-3 survey games."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# ── Instinct categories, ordered by classification priority (highest first) ──
INSTINCT_PRIORITY = [
    "partial_solver",
    "hypothesis_driven",
    "systematic_explorer",
    "directional_mover",
    "action5_spammer",
    "random_clicker",
    "frozen",
]

# Hypothesis language patterns
_HYPOTHESIS_PATTERNS = [
    r"\bi think\b",
    r"\blet me (try|test|check|see)\b",
    r"\bthis suggests?\b",
    r"\bhypothes[ie]s\b",
    r"\bmaybe\b.*\bif\b",
    r"\bperhaps\b",
    r"\bmy theory\b",
    r"\bexperiment\b",
    r"\btest(ing)? whether\b",
    r"\bwhat happens (if|when)\b",
    r"\bto (verify|confirm|test)\b",
]
_HYPOTHESIS_RE = re.compile("|".join(_HYPOTHESIS_PATTERNS), re.IGNORECASE)

# Change awareness patterns
_CHANGE_PATTERNS = [
    r"\bchanged?\b",
    r"\bdifferen(t|ce)\b",
    r"\bafter (ACTION|action|clicking|moving)\b",
    r"\bnow (the|there|I see)\b",
    r"\bpreviously\b",
    r"\bbefore\b.*\bnow\b",
    r"\bnotice\b",
    r"\bgrid (is|has|looks|shows)\b",
    r"\bnew (color|cell|block|pattern)\b",
    r"\bappeared\b",
    r"\bdisappeared\b",
]
_CHANGE_RE = re.compile("|".join(_CHANGE_PATTERNS), re.IGNORECASE)


def compute_action_distribution(actions: list[dict]) -> dict[str, int]:
    """Count actions from session_actions rows. Returns {ACTION_NAME: count}."""
    counter = Counter()
    for a in actions:
        act_num = a.get("action", 0)
        name = f"ACTION{act_num}"
        counter[name] += 1
    return dict(counter.most_common())


def count_hypothesis_mentions(reasoning_texts: list[str]) -> int:
    """Count how many reasoning outputs contain hypothesis language."""
    count = 0
    for text in reasoning_texts:
        if text and _HYPOTHESIS_RE.search(text):
            count += 1
    return count


def compute_change_awareness(reasoning_texts: list[str]) -> dict:
    """Compute ratio of reasoning outputs that reference grid changes."""
    total = len(reasoning_texts)
    refs = sum(1 for t in reasoning_texts if t and _CHANGE_RE.search(t))
    return {
        "references_changes": refs,
        "total_steps": total,
        "ratio": round(refs / total, 3) if total > 0 else 0.0,
    }


def detect_strategy_phases(actions: list[dict], reasoning_texts: list[str]) -> list[dict]:
    """Detect strategy phase transitions based on dominant action shifts.

    A new phase starts when the most common action in a sliding window of 5
    steps changes from the previous window's dominant action.
    """
    if not actions:
        return []

    act_nums = [a.get("action", 0) for a in actions]
    n = len(act_nums)

    if n <= 5:
        dominant = Counter(act_nums).most_common(1)[0][0]
        label = _phase_label(dominant, reasoning_texts[:n])
        return [{"steps": f"0-{n - 1}", "label": label, "summary": _phase_summary(dominant, n)}]

    # Sliding window phase detection
    phases = []
    window = 5
    prev_dominant = None
    phase_start = 0

    for i in range(0, n, window):
        chunk = act_nums[i:i + window]
        dominant = Counter(chunk).most_common(1)[0][0]

        if dominant != prev_dominant and prev_dominant is not None:
            # Close previous phase
            chunk_reasoning = reasoning_texts[phase_start:i]
            label = _phase_label(prev_dominant, chunk_reasoning)
            phases.append({
                "steps": f"{phase_start}-{i - 1}",
                "label": label,
                "summary": _phase_summary(prev_dominant, i - phase_start),
            })
            phase_start = i

        prev_dominant = dominant

    # Close final phase
    chunk_reasoning = reasoning_texts[phase_start:n]
    label = _phase_label(prev_dominant, chunk_reasoning)
    phases.append({
        "steps": f"{phase_start}-{n - 1}",
        "label": label,
        "summary": _phase_summary(prev_dominant, n - phase_start),
    })

    return phases


def _phase_label(dominant_action: int, reasoning_texts: list[str]) -> str:
    """Generate a human-readable phase label from dominant action."""
    hyp_count = count_hypothesis_mentions(reasoning_texts)
    if hyp_count >= 2:
        return "hypothesis_testing"
    labels = {
        1: "moving_up", 2: "moving_down", 3: "moving_left", 4: "moving_right",
        5: "using_action5", 6: "clicking", 7: "undoing",
    }
    return labels.get(dominant_action, "exploration")


def _phase_summary(dominant_action: int, step_count: int) -> str:
    """Generate a short summary for a strategy phase."""
    descs = {
        1: "Moved up repeatedly",
        2: "Moved down repeatedly",
        3: "Moved left repeatedly",
        4: "Moved right repeatedly",
        5: "Used ACTION5 (perform action)",
        6: "Clicked on grid positions",
        7: "Used undo",
    }
    desc = descs.get(dominant_action, "Tried varied actions")
    return f"{desc} ({step_count} steps)"


def extract_first_impression(reasoning_texts: list[str]) -> str:
    """Extract the agent's first impression from the first reasoning output.

    Tries to parse JSON and extract the observation field. Falls back to raw text.
    """
    import json as _json
    for text in reasoning_texts[:3]:
        if not text or len(text.strip()) < 20:
            continue
        # Try to extract observation from JSON
        try:
            parsed = _json.loads(text)
            obs = parsed.get("observation", "")
            if obs and len(obs) > 20:
                return obs.strip()[:300]
        except (ValueError, TypeError, AttributeError):
            pass
        # Fall back to raw text
        return text.strip()[:300]
    return "(no first impression captured)"


def classify_instinct(
    levels_completed: int,
    action_dist: dict[str, int],
    reasoning_texts: list[str],
    total_steps: int,
) -> str:
    """Classify a game's agent behavior into an instinct category.

    Priority order (highest first):
        partial_solver > hypothesis_driven > systematic_explorer >
        directional_mover > action5_spammer > random_clicker > frozen

    Returns the instinct category string.
    """
    # 1. partial_solver — completed at least one level
    if levels_completed > 0:
        return "partial_solver"

    # 2. Count hypothesis mentions
    hyp_count = count_hypothesis_mentions(reasoning_texts)

    # 3. Compute action entropy (how varied are the actions?)
    total_actions = sum(action_dist.values())
    unique_actions = len(action_dist)
    top_action_count = max(action_dist.values()) if action_dist else 0
    top_action_ratio = top_action_count / total_actions if total_actions > 0 else 1.0

    # 4. frozen — one action > 90% of the time
    if top_action_ratio > 0.90 and total_steps >= 10:
        return "frozen"

    # 5. hypothesis_driven — 3+ hypothesis mentions in reasoning
    if hyp_count >= 3:
        return "hypothesis_driven"

    # 6. Compute directional bias (ACTION1-4)
    dir_actions = sum(action_dist.get(f"ACTION{i}", 0) for i in range(1, 5))
    dir_ratio = dir_actions / total_actions if total_actions > 0 else 0

    # 7. action5_spammer — ACTION5 > 60% of actions
    a5_ratio = action_dist.get("ACTION5", 0) / total_actions if total_actions > 0 else 0
    if a5_ratio > 0.60:
        return "action5_spammer"

    # 8. directional_mover — directional actions > 60%
    if dir_ratio > 0.60:
        return "directional_mover"

    # 9. systematic_explorer — uses 3+ different actions AND references changes
    change_awareness = compute_change_awareness(reasoning_texts)
    if unique_actions >= 3 and change_awareness["ratio"] > 0.2:
        return "systematic_explorer"

    # 10. hypothesis_driven (lower threshold if also change-aware)
    if hyp_count >= 2 and change_awareness["ratio"] > 0.1:
        return "hypothesis_driven"

    # 11. random_clicker — default fallback (ACTION6 dominant or no clear pattern)
    return "random_clicker"


def classify_game(
    session: dict,
    actions: list[dict],
    llm_calls: list[dict],
) -> dict:
    """Classify a single game session. Returns the full per-game survey result dict.

    Args:
        session: Row from sessions table (dict with id, game_id, result, steps, levels, etc.)
        actions: Rows from session_actions for this session
        llm_calls: Rows from llm_calls for this session
    """
    game_id = session.get("game_id", "unknown")
    levels = session.get("levels", 0) or 0
    steps = session.get("steps", 0) or 0
    total_cost = session.get("total_cost", 0) or 0

    # Extract reasoning texts from LLM calls
    reasoning_texts = []
    for call in llm_calls:
        output = call.get("output_json") or ""
        # output_json is the raw LLM text (first 1000 chars stored by agent.py)
        # Try to parse JSON to extract observation + reasoning
        text = ""
        try:
            parsed = __import__("json").loads(output)
            obs = parsed.get("observation", "")
            reas = parsed.get("reasoning", "")
            text = f"{obs} {reas}".strip()
        except (ValueError, TypeError):
            text = output
        reasoning_texts.append(text)

    # Action distribution
    action_dist = compute_action_distribution(actions)

    # Classification
    instinct = classify_instinct(levels, action_dist, reasoning_texts, steps)

    # Strategy phases
    phases = detect_strategy_phases(actions, reasoning_texts)

    # Change awareness
    change_awareness = compute_change_awareness(reasoning_texts)

    # Hypothesis count
    hyp_count = count_hypothesis_mentions(reasoning_texts)

    # First impression
    first_impression = extract_first_impression(reasoning_texts)

    return {
        "game_id": game_id,
        "model": session.get("model", "unknown"),
        "session_id": session.get("id", ""),
        "result": session.get("result", ""),
        "steps_taken": steps,
        "levels_completed": levels,
        "total_cost_usd": round(total_cost, 4) if total_cost else 0,
        "action_distribution": action_dist,
        "first_impression": first_impression,
        "strategy_phases": phases,
        "change_awareness": change_awareness,
        "hypothesis_count": hyp_count,
        "instinct_class": instinct,
    }
