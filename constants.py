# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 13:47
# PURPOSE: Shared constants for ARC-AGI-3 — color palette (COLOR_MAP, COLOR_NAMES),
#   action labels (ACTION_NAMES), and game description text (ARC_AGI3_DESCRIPTION).
#   Extracted from server.py in Phase 1 to eliminate duplication between server.py
#   and agent.py. Imported by server.py, agent.py, grid_analysis.py, prompt_builder.py.
# SRP/DRY check: Pass — single source of truth for palette/action constants
"""ARC-AGI-3 shared constants — palette, action labels, descriptions.

Import from here instead of defining locally in server.py or agent.py.
"""

from pathlib import Path

# ── Color palette ──────────────────────────────────────────────────────────

COLOR_MAP = {
    0: "#FFFFFF", 1: "#CCCCCC", 2: "#999999", 3: "#666666",
    4: "#333333", 5: "#000000", 6: "#E53AA3", 7: "#FF7BCC",
    8: "#F93C31", 9: "#1E93FF", 10: "#88D8F1", 11: "#FFDC00",
    12: "#FF851B", 13: "#921231", 14: "#4FCC30", 15: "#A356D6",
}

COLOR_NAMES = {
    0: "White", 1: "LightGray", 2: "Gray", 3: "DarkGray",
    4: "VeryDarkGray", 5: "Black", 6: "Magenta", 7: "LightMagenta",
    8: "Red", 9: "Blue", 10: "LightBlue", 11: "Yellow",
    12: "Orange", 13: "Maroon", 14: "Green", 15: "Purple",
}

# ── Action labels ──────────────────────────────────────────────────────────

ACTION_NAMES = {
    0: "RESET", 1: "ACTION1", 2: "ACTION2", 3: "ACTION3",
    4: "ACTION4", 5: "ACTION5", 6: "ACTION6", 7: "ACTION7",
}

# ── Game description (loaded once at import time) ──────────────────────────

ARC_AGI3_DESCRIPTION = (
    Path(__file__).parent / "prompts" / "shared" / "arc_description.txt"
).read_text().strip()

# ── System message (canonical — used by server.py via models.py and agent.py) ──
# NOTE: models.py still defines its own SYSTEM_MSG; in Phase 2, models.py
# should import this instead. For Phase 1 we only eliminate the agent.py copy.

SYSTEM_MSG = (
    "You are an expert puzzle-solving AI agent. Analyse game grids and output "
    "ONLY valid JSON — no markdown, no explanation outside JSON."
)
