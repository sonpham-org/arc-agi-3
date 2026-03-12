# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-12 12:52
# PURPOSE: History condensation and post-game reflection for ARC-AGI-3. Summarizes
#   game history to save context tokens and asks reflector LLM to extract learnings
#   for future runs. Extracted from agent.py in Phase 11.
# SRP/DRY check: Pass — all history management logic consolidated; agent.py uses as handler
"""History condensation and post-game reflection for ARC-AGI-3.

Extracted from agent.py (Phase 11).

Provides:
- condense_history(): Summarize history entries via LLM when context gets large
- reflect_and_update_memory(): Extract post-game learnings for persistent memory
"""

from agent_llm import call_model_with_retry
from agent_response_parsing import _parse_json
from constants import ACTION_NAMES


def condense_history(history: list[dict], cfg: dict, 
                     effective_model_fn=None,
                     load_hard_memory_fn=None,
                     append_memory_fn=None) -> list[dict]:
    """Summarise all non-summary entries via LLM, replacing them with one summary entry.
    
    Args:
        history: List of history entries
        cfg: Configuration dict
        effective_model_fn: Function to get model for a role (imported to avoid circular deps)
        load_hard_memory_fn: Function to load memory (imported to avoid circular deps)
        append_memory_fn: Function to append memory (imported to avoid circular deps)
    """
    if effective_model_fn is None:
        # Import here to avoid circular dependency
        from agent import effective_model
        effective_model_fn = effective_model
    
    raw_entries = [h for h in history if not h.get("is_summary")]
    if not raw_entries:
        return history

    model_key = effective_model_fn(cfg, "condenser")
    reasoning_trace = cfg.get("context", {}).get("reasoning_trace", False)
    lines = []
    for h in raw_entries:
        aname = ACTION_NAMES.get(h["action"], f"ACTION{h['action']}")
        obs = (h.get("observation", "") or "")[:300]
        line = f"Step {h['step']}: {aname} -> levels={h.get('levels','?')}  | {obs}"
        if reasoning_trace and h.get("reasoning"):
            line += f" | reasoning: {h['reasoning'][:300]}"
        lines.append(line)

    prompt = (
        "You are summarising an ARC-AGI-3 game history for an AI agent.\n\n"
        "Raw history:\n" + "\n".join(lines) + "\n\n"
        "Write a compact tactical summary (≤ 8 bullet points, ≤ 120 chars each) "
        "capturing: what actions were tried, what each did, what level progress was made, "
        "and any rules/patterns discovered.\n"
        "Respond with ONLY a JSON object: {\"summary\": \"bullet1\\nbullet2\\n...\"}"
    )

    print(f"  [memory] condensing {len(raw_entries)} history entries...")
    raw = call_model_with_retry(model_key, prompt, cfg, role="condenser")
    summary_text = ""
    if raw:
        parsed = _parse_json(raw)
        if parsed:
            summary_text = parsed.get("summary", "")
    if not summary_text:
        summary_text = f"(condensed {len(raw_entries)} steps — summary unavailable)"

    summary_entry = {
        "is_summary": True,
        "step_range": f"{raw_entries[0]['step']}-{raw_entries[-1]['step']}",
        "summary": summary_text,
    }
    # Keep existing summary entries at the front, then the new one
    existing_summaries = [h for h in history if h.get("is_summary")]
    return existing_summaries + [summary_entry]


def reflect_and_update_memory(
    game_id: str,
    history: list[dict],
    result: str,
    steps_taken: int,
    levels_done: int,
    win_levels: int,
    cfg: dict,
    effective_model_fn=None,
    load_hard_memory_fn=None,
    append_memory_fn=None,
) -> None:
    """Ask the reflector LLM to extract learnings and append them to MEMORY.md.
    
    Args:
        game_id: Game identifier
        history: Game history entries
        result: Game result (WIN, GAME_OVER, etc.)
        steps_taken: Number of steps taken
        levels_done: Levels completed
        win_levels: Total win levels
        cfg: Configuration dict
        effective_model_fn: Function to get model for a role (imported to avoid circular deps)
        load_hard_memory_fn: Function to load memory (imported to avoid circular deps)
        append_memory_fn: Function to append memory (imported to avoid circular deps)
    """
    if effective_model_fn is None:
        # Import here to avoid circular dependency
        from agent import effective_model
        effective_model_fn = effective_model
    
    if load_hard_memory_fn is None:
        from agent import load_hard_memory
        load_hard_memory_fn = load_hard_memory
    
    if append_memory_fn is None:
        from agent import append_memory_bullet
        append_memory_fn = append_memory_bullet
    
    if not cfg["memory"]["reflect_after_game"]:
        return

    model_key = effective_model_fn(cfg, "reflector")
    raw_entries = [h for h in history if not h.get("is_summary")]

    history_text = "\n".join(
        f"Step {h['step']}: {ACTION_NAMES.get(h['action'], str(h['action']))} -> "
        f"levels={h.get('levels','?')} | {(h.get('observation','') or '')[:80]}"
        for h in raw_entries[-40:]  # last 40 entries is enough for reflection
    )

    existing_memory = load_hard_memory_fn(cfg)
    game_section_exists = f"## {game_id}" in existing_memory

    prompt = (
        f"You played ARC-AGI-3 game '{game_id}'.\n"
        f"Result: {result} | Steps: {steps_taken} | Levels: {levels_done}/{win_levels}\n\n"
        f"Game history (last 40 steps):\n{history_text}\n\n"
        f"Based on this run, extract 2-5 concise, NOVEL facts worth remembering for future runs.\n"
        f"Focus on: what each action does, how levels advance, obstacles, winning strategies.\n"
        f"{'Existing game-specific notes are already stored — only add NEW facts.' if game_section_exists else ''}\n\n"
        f"Respond with ONLY JSON: "
        f"{{\"learnings\": [\"fact1\", \"fact2\", ...]}}"
    )

    print(f"  [memory] running post-game reflection with {model_key}...")
    raw = call_model_with_retry(model_key, prompt, cfg, role="reflector")
    if not raw:
        return
    parsed = _parse_json(raw)
    if not parsed or "learnings" not in parsed:
        return

    for bullet in parsed["learnings"]:
        bullet = bullet.strip()
        if bullet:
            append_memory_fn(cfg, game_id, bullet)
            print(f"  [memory] stored: {bullet[:80]}")
